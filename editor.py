#!/usr/bin/env python3
"""Screenshot Builder — GUI editor for placing the four screen-corner points.

(C) Thomas F Abrahamsson at Alvega & Co AB <Thomas@alvega.company>
"""
from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from include.corner_editor import CORNER_KEYS, CornerEditor
from include.version import APP_NAME, APP_VERSION, banner
from include.yaml_io import load_round_trip, save_round_trip, update_phone_corners

DEFAULT_CONFIG = "screenshots.yaml"
DEFAULT_ASSETS = "assets"


class EditorApp:
    def __init__(self, root: tk.Tk, config_path: Path, assets_dir: Path):
        self.root = root
        self.config_path = config_path
        self.assets_dir = assets_dir
        self._dirty = False

        root.title(f"{APP_NAME} — Corner Editor v{APP_VERSION}")
        root.geometry("1280x900")
        root.minsize(900, 600)

        self.data = load_round_trip(config_path)
        if "phones" not in self.data or not self.data["phones"]:
            messagebox.showerror(
                "No phones",
                f"{config_path.name} has no 'phones:' section to edit.",
            )
            root.destroy()
            return

        self._build_ui()
        # Prefer the first phone whose base_image exists locally,
        # otherwise fall back to the first defined phone.
        first = next(iter(self.data["phones"]))
        for name, cfg in self.data["phones"].items():
            base = (self.assets_dir / str(cfg.get("base_image", ""))).resolve()
            if base.is_file():
                first = name
                break
        self.phone_var.set(first)
        self._on_phone_change()

    # ---------- UI construction ------------------------------------------

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(side="top", fill="x")

        ttk.Label(toolbar, text="Phone:").pack(side="left")
        self.phone_var = tk.StringVar()
        phone_names = list(self.data["phones"].keys())
        self.phone_combo = ttk.Combobox(
            toolbar,
            textvariable=self.phone_var,
            values=phone_names,
            state="readonly",
            width=22,
        )
        self.phone_combo.pack(side="left", padx=(4, 12))
        self.phone_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_phone_change())

        ttk.Button(toolbar, text="Load screenshot…", command=self._load_screenshot)\
            .pack(side="left", padx=4)
        ttk.Button(toolbar, text="Clear screenshot", command=self._clear_screenshot)\
            .pack(side="left", padx=4)
        ttk.Button(toolbar, text="Reset corners", command=self._reset_corners)\
            .pack(side="left", padx=4)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="−", width=3, command=self._zoom_out)\
            .pack(side="left", padx=2)
        ttk.Button(toolbar, text="+", width=3, command=self._zoom_in)\
            .pack(side="left", padx=2)
        ttk.Button(toolbar, text="Fit", command=self._zoom_reset)\
            .pack(side="left", padx=4)
        self.zoom_var = tk.StringVar(value="—")
        ttk.Label(toolbar, textvariable=self.zoom_var, width=8, anchor="center")\
            .pack(side="left", padx=4)

        ttk.Button(toolbar, text="Save", command=self._save).pack(side="right", padx=4)

        # Status bar with live coordinates
        self.status_var = tk.StringVar(value="Load a phone to begin.")
        status = ttk.Label(self.root, textvariable=self.status_var, padding=6, anchor="w")
        status.pack(side="bottom", fill="x")

        # Canvas (wrapped with scrollbars for when the user zooms past viewport)
        canvas_frame = ttk.Frame(self.root)
        canvas_frame.pack(side="top", fill="both", expand=True)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, bg="#1f1f23", highlightthickness=0)
        vbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        hbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.config(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        self.editor = CornerEditor(
            self.canvas,
            on_change=self._on_corner_change,
            on_zoom_change=self._on_zoom_change,
        )

        # Zoom shortcuts and mouse wheel
        self.canvas.bind("<MouseWheel>", self._on_wheel)            # macOS / Windows
        self.canvas.bind("<Button-4>", lambda e: self._wheel_zoom(1, e))   # Linux up
        self.canvas.bind("<Button-5>", lambda e: self._wheel_zoom(-1, e))  # Linux down
        for seq in ("<Command-equal>", "<Command-plus>", "<Control-equal>", "<Control-plus>"):
            self.root.bind(seq, lambda _e: self._zoom_in())
        for seq in ("<Command-minus>", "<Control-minus>"):
            self.root.bind(seq, lambda _e: self._zoom_out())
        for seq in ("<Command-0>", "<Control-0>"):
            self.root.bind(seq, lambda _e: self._zoom_reset())

        # Title bar dirty indicator
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- actions --------------------------------------------------

    def _on_phone_change(self) -> None:
        if self._dirty and not self._confirm_discard():
            # revert combo selection
            return
        name = self.phone_var.get()
        if not name:
            return
        phone = self.data["phones"][name]
        base_rel = str(phone["base_image"])
        base_path = (self.assets_dir / base_rel).resolve()
        if not base_path.is_file():
            self.canvas.delete("all")
            self.status_var.set(
                f"⚠  Base image not found for '{name}': {base_path}"
            )
            return
        sc = phone.get("screen_corners", {}) or {}
        try:
            corners = {k: (int(sc[k][0]), int(sc[k][1])) for k in CORNER_KEYS}
        except (KeyError, TypeError, IndexError):
            # Fallback: place a sensible inset quad
            corners = {k: (0, 0) for k in CORNER_KEYS}
        self.editor.load_base(base_path, corners)
        if all(v == (0, 0) for v in corners.values()):
            self.editor.reset_corners_to_image_bounds()
        self._set_dirty(False)
        self._update_status()

    def _load_screenshot(self) -> None:
        start = self.assets_dir / "screenshots"
        path = filedialog.askopenfilename(
            title="Select screenshot to preview",
            initialdir=str(start if start.is_dir() else self.assets_dir),
            filetypes=[("PNG / JPEG", "*.png *.PNG *.jpg *.jpeg"), ("All files", "*.*")],
        )
        if path:
            self.editor.load_screenshot(Path(path))

    def _clear_screenshot(self) -> None:
        self.editor.load_screenshot(None)

    def _reset_corners(self) -> None:
        self.editor.reset_corners_to_image_bounds()
        self._set_dirty(True)

    def _zoom_in(self) -> None:
        self.editor.zoom_in()

    def _zoom_out(self) -> None:
        self.editor.zoom_out()

    def _zoom_reset(self) -> None:
        self.editor.zoom_reset()

    def _on_wheel(self, event: tk.Event) -> None:
        # macOS reports small deltas (e.g. ±1..±5); Windows reports ±120 per notch.
        direction = 1 if event.delta > 0 else -1
        self._wheel_zoom(direction, event)

    def _wheel_zoom(self, direction: int, event: tk.Event) -> None:
        factor = 1.15 if direction > 0 else 1 / 1.15
        self.editor.zoom_at_cursor(factor, event.x, event.y)

    def _on_zoom_change(self, scale: float) -> None:
        self.zoom_var.set(f"{scale * 100:.0f}%")

    def _on_corner_change(self, corners) -> None:
        self._set_dirty(True)
        self._update_status(corners)

    def _update_status(self, corners=None) -> None:
        if corners is None:
            corners = self.editor.get_corners()
        if not corners:
            self.status_var.set("Load a phone to begin.")
            return
        bits = "  ".join(
            f"{k}=({corners[k][0]},{corners[k][1]})" for k in CORNER_KEYS
        )
        self.status_var.set(bits)

    def _save(self) -> None:
        name = self.phone_var.get()
        if not name:
            return
        try:
            update_phone_corners(self.data, name, self.editor.get_corners())
            save_round_trip(self.config_path, self.data)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save failed", str(exc))
            return
        self._set_dirty(False)
        self.status_var.set(f"Saved {name} corners to {self.config_path.name}.")

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        marker = " •" if dirty else ""
        self.root.title(f"{APP_NAME} — Corner Editor v{APP_VERSION}{marker}")

    def _confirm_discard(self) -> bool:
        return messagebox.askyesno(
            "Unsaved changes",
            "You have unsaved corner changes. Discard them?",
        )

    def _on_close(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        self.root.destroy()


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="editor",
        description=f"{APP_NAME} v{APP_VERSION} — GUI corner editor",
    )
    p.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    p.add_argument("-a", "--assets", default=DEFAULT_ASSETS)
    p.add_argument("--version", action="version", version=banner())
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root_dir = Path.cwd()
    config_path = (root_dir / args.config).resolve()
    assets_dir = (root_dir / args.assets).resolve()

    if not config_path.is_file():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 2
    if not assets_dir.is_dir():
        print(f"Assets folder missing: {assets_dir}", file=sys.stderr)
        return 2

    root = tk.Tk()
    EditorApp(root, config_path, assets_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
