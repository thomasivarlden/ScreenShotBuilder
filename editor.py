#!/usr/bin/env python3
"""Screenshot Builder — GUI editor for placing the four screen-corner points.

(C) Thomas F Abrahamsson at Alvega & Co AB <Thomas@alvega.company>
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from include.assets_tab import AssetsTab
from include.brand_editor import BrandsTab
from include.compositor import build_composite
from include.corner_editor import CORNER_KEYS, CornerEditor
from include.generate_tab import GenerateTab
from include.version import APP_NAME, APP_VERSION, banner
from include.yaml_io import (
    load_round_trip,
    save_round_trip,
    update_phone_corner_radius,
    update_phone_corners,
)

DEFAULT_CONFIG = "screenshots.yaml"
DEFAULT_ASSETS = "assets"


class EditorApp:
    def __init__(self, root: tk.Tk, config_path: Path, assets_dir: Path):
        self.root = root
        self.config_path = config_path
        self.assets_dir = assets_dir
        self.dist_dir = (config_path.parent / "dist").resolve()
        self._dirty = False
        self._screenshot_path: Path | None = None

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

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self._save)
        file_menu.add_separator()
        file_menu.add_command(label="Load screenshot…", command=self._load_screenshot)
        file_menu.add_command(label="Clear screenshot", command=self._clear_screenshot)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Reset corners", command=self._reset_corners)
        edit_menu.add_command(label="Render preview", command=self._render_preview)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Zoom in", accelerator="Ctrl++", command=self._zoom_in)
        view_menu.add_command(label="Zoom out", accelerator="Ctrl+-", command=self._zoom_out)
        view_menu.add_command(label="Fit", accelerator="Ctrl+0", command=self._zoom_reset)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(
            label=f"About {APP_NAME}",
            command=lambda: messagebox.showinfo(
                f"About {APP_NAME}", f"{APP_NAME} v{APP_VERSION}\n© Thomas F Abrahamsson / Alvega & Co AB"
            ),
        )
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-s>", lambda _e: self._save())

    def _build_ui(self) -> None:
        self._build_menu()

        # Status bar (declared early so tabs can use it via self.status_var).
        self.status_var = tk.StringVar(value="Load a phone to begin.")
        status = ttk.Label(self.root, textvariable=self.status_var, padding=6, anchor="w")
        status.pack(side="bottom", fill="x")

        # Notebook with four tabs.
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(side="top", fill="both", expand=True)

        # Save button overlaid on the notebook's tab row (right-aligned),
        # so it shares the vertical space with the tab strip.
        self.save_btn = ttk.Button(self.notebook, text="Save", command=self._save)
        self.save_btn.place(relx=1.0, x=-6, y=2, anchor="ne")

        corner_tab = ttk.Frame(self.notebook)
        self.notebook.add(corner_tab, text="Phone corners")

        brands_tab = BrandsTab(
            self.notebook, self.data, self.assets_dir,
            on_dirty=lambda: self._set_dirty(True),
        )
        self.notebook.add(brands_tab, text="Configuration")
        self.brands_tab = brands_tab

        generate_tab = GenerateTab(
            self.notebook,
            repo_root=self.config_path.parent,
            config_path=self.config_path,
            assets_dir=self.assets_dir,
            on_request_save=self._save_for_generate,
        )
        self.notebook.add(generate_tab, text="Generate")
        self.generate_tab = generate_tab

        assets_tab = AssetsTab(self.notebook, self.data, self.assets_dir)
        self.notebook.add(assets_tab, text="Assets")
        self.assets_tab = assets_tab

        toolbar = ttk.Frame(corner_tab, padding=8)
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
        ttk.Label(toolbar, text="Corner radius:").pack(side="left")
        self.radius_var = tk.StringVar(value="")
        radius_entry = ttk.Entry(toolbar, textvariable=self.radius_var, width=6)
        radius_entry.pack(side="left", padx=(2, 0))
        ttk.Label(toolbar, text="px").pack(side="left", padx=(1, 6))
        self.radius_var.trace_add("write", lambda *_a: self._on_radius_change())

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.preview_btn = ttk.Button(
            toolbar, text="Render preview", command=self._render_preview, state="disabled",
        )
        self.preview_btn.pack(side="left", padx=4)

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
        self.coord_var = tk.StringVar(value="—")
        ttk.Label(toolbar, textvariable=self.coord_var, width=14, anchor="center")\
            .pack(side="left", padx=4)

        # Canvas (wrapped with scrollbars for when the user zooms past viewport)
        canvas_frame = ttk.Frame(corner_tab)
        canvas_frame.pack(side="top", fill="both", expand=True)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_frame, bg="#1f1f23", highlightthickness=0,
            xscrollincrement=1, yscrollincrement=1,  # 1 unit = 1 pixel
        )
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
        # Shift + wheel = horizontal scroll (standard convention)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        for seq in ("<Command-equal>", "<Command-plus>", "<Control-equal>", "<Control-plus>"):
            self.root.bind(seq, lambda _e: self._zoom_in())
        for seq in ("<Command-minus>", "<Control-minus>"):
            self.root.bind(seq, lambda _e: self._zoom_out())
        for seq in ("<Command-0>", "<Control-0>"):
            self.root.bind(seq, lambda _e: self._zoom_reset())

        # Panning:
        #   space + drag (Photoshop/Figma convention),
        #   middle-mouse drag,
        #   arrow keys (40 px, or 5 px with Shift)
        self.root.bind("<KeyPress-space>", self._space_press)
        self.root.bind("<KeyRelease-space>", self._space_release)
        self.canvas.bind("<ButtonPress-2>", self._mid_press)
        self.canvas.bind("<B2-Motion>", self._mid_drag)
        self.canvas.bind("<ButtonRelease-2>", self._mid_release)
        self.canvas.bind("<ButtonPress-3>", self._mid_press)   # macOS sometimes maps wheel-click here
        self.canvas.bind("<B3-Motion>", self._mid_drag)
        self.canvas.bind("<ButtonRelease-3>", self._mid_release)

        # Live cursor coordinates (image-pixel space)
        self.canvas.bind("<Motion>", self._on_canvas_motion, add="+")
        self.canvas.bind("<Leave>", lambda _e: self.coord_var.set("—"), add="+")
        for seq, dx, dy in (
            ("<Left>",  -40, 0), ("<Right>",  40, 0),
            ("<Up>",    0, -40), ("<Down>",   0, 40),
            ("<Shift-Left>",  -5, 0), ("<Shift-Right>",  5, 0),
            ("<Shift-Up>",    0, -5), ("<Shift-Down>",   0, 5),
        ):
            self.root.bind(seq, lambda _e, dx=dx, dy=dy: self._pan_pixels(dx, dy))

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
        # Populate the corner radius field from YAML (suppress dirty during load).
        self._loading_radius = True
        try:
            self.radius_var.set(str(int(phone.get("corner_radius") or 0) or ""))
        finally:
            self._loading_radius = False
        self._set_dirty(False)
        self._update_status()
        self._update_preview_button_state()

    def _on_radius_change(self) -> None:
        # Push the radius into the canvas overlay regardless of dirty state,
        # so the preview updates while typing.
        self.editor.set_corner_radius(self._parse_radius() or 0)
        if getattr(self, "_loading_radius", False):
            return
        self._set_dirty(True)

    def _parse_radius(self) -> int | None:
        s = self.radius_var.get().strip()
        if not s:
            return None
        try:
            v = int(s)
        except ValueError:
            return None
        return v if v > 0 else None

    def _load_screenshot(self) -> None:
        start = self.assets_dir / "screenshots"
        path = filedialog.askopenfilename(
            title="Select screenshot to preview",
            initialdir=str(start if start.is_dir() else self.assets_dir),
            filetypes=[("PNG / JPEG", "*.png *.PNG *.jpg *.jpeg"), ("All files", "*.*")],
        )
        if path:
            self._screenshot_path = Path(path)
            self.editor.load_screenshot(self._screenshot_path)
            self._update_preview_button_state()

    def _clear_screenshot(self) -> None:
        self._screenshot_path = None
        self.editor.load_screenshot(None)
        self._update_preview_button_state()

    def _update_preview_button_state(self) -> None:
        ok = self._screenshot_path is not None and bool(self.phone_var.get())
        self.preview_btn.config(state="normal" if ok else "disabled")

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

    def _on_canvas_motion(self, event: tk.Event) -> None:
        pt = self.editor.view_to_image(event.x, event.y)
        self.coord_var.set(f"{pt[0]}, {pt[1]}" if pt else "—")

    # ---------- panning --------------------------------------------------

    def _space_press(self, _event: tk.Event) -> None:
        # Don't hijack space if a text widget has focus.
        focus = self.root.focus_get()
        if isinstance(focus, (tk.Entry, tk.Text)):
            return
        if not self.editor.pan_mode:
            self.editor.pan_mode = True
            self.canvas.config(cursor="fleur")

    def _space_release(self, _event: tk.Event) -> None:
        if self.editor.pan_mode:
            self.editor.pan_mode = False
            self.canvas.config(cursor="")

    def _mid_press(self, event: tk.Event) -> None:
        self.canvas.scan_mark(event.x, event.y)
        self.canvas.config(cursor="fleur")

    def _mid_drag(self, event: tk.Event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _mid_release(self, _event: tk.Event) -> None:
        # Restore cursor only if spacebar isn't currently held.
        if not self.editor.pan_mode:
            self.canvas.config(cursor="")

    def _on_shift_wheel(self, event: tk.Event) -> None:
        direction = 1 if event.delta > 0 else -1
        self.canvas.xview_scroll(-direction * 3, "units")

    def _pan_pixels(self, dx: int, dy: int) -> None:
        # Don't intercept arrow keys when a text/entry has focus.
        focus = self.root.focus_get()
        if isinstance(focus, (tk.Entry, tk.Text)):
            return
        if dx:
            self.canvas.xview_scroll(dx, "units")
        if dy:
            self.canvas.yview_scroll(dy, "units")

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

    def _render_preview(self) -> None:
        """Build a one-off composite using the current phone + screenshot,
        save it under dist/_preview/, and open it. Bypasses the brand
        pipeline so the user can verify a calibration immediately."""
        phone_name = self.phone_var.get()
        if not phone_name or self._screenshot_path is None:
            return
        phone_cfg = self.data["phones"].get(phone_name)
        if phone_cfg is None:
            return

        # Use the editor's live (possibly-unsaved) corners, not the YAML's.
        live_corners = self.editor.get_corners()
        synthetic_brand = {
            "base_image": str(phone_cfg["base_image"]),
            "screen_corners": {k: list(live_corners[k]) for k in CORNER_KEYS},
        }
        live_radius = self._parse_radius()
        if live_radius:
            synthetic_brand["corner_radius"] = live_radius
        # Pass the screenshot as an absolute path so build_composite finds
        # it regardless of whether it lives under assets/.
        synthetic_shot = {"source": str(self._screenshot_path.resolve())}

        out_dir = self.dist_dir / "_preview"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{phone_name}.png"

        try:
            image = build_composite(synthetic_brand, synthetic_shot, self.assets_dir)
            image.save(out_path, format="PNG", optimize=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Render failed", str(exc))
            return

        self.status_var.set(f"Rendered preview: {out_path.as_uri()}")
        self._open_path(out_path)

    @staticmethod
    def _open_path(path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(path)])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(path)])
            else:
                webbrowser.open(path.as_uri())
        except Exception:
            webbrowser.open(path.as_uri())

    def _save(self) -> None:
        # Commit live corner values for the currently-selected phone (if any)
        # before writing — brand-tab edits already sync into self.data on the
        # fly, so this is the only thing we need to flush manually.
        name = self.phone_var.get()
        try:
            if name and self.editor.has_image():
                update_phone_corners(self.data, name, self.editor.get_corners())
                update_phone_corner_radius(self.data, name, self._parse_radius())
            save_round_trip(self.config_path, self.data)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save failed", str(exc))
            return
        self._set_dirty(False)
        self.status_var.set(f"Saved changes to {self.config_path.name}.")

    def _save_for_generate(self) -> bool:
        """Called by the Generate tab before launching a build.

        If there are unsaved changes, ask whether to save first. Returns True
        if the build should proceed, False if the user cancelled.
        """
        if not self._dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            "You have unsaved changes. Save before generating?",
        )
        if answer is None:        # Cancel
            return False
        if answer is False:       # No — proceed without saving
            return True
        # Yes — save and proceed only if the save succeeds.
        self._save()
        return not self._dirty

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
    _set_app_name(root, APP_NAME)
    EditorApp(root, config_path, assets_dir)
    root.mainloop()
    return 0


def _set_app_name(root: tk.Tk, name: str) -> None:
    """Make the OS taskbar/dock/menu show `name` instead of 'Python'."""
    try:
        root.tk.call("tk", "appname", name)
    except tk.TclError:
        pass
    if sys.platform == "darwin":
        # macOS menu bar shows CFBundleName for non-bundled apps. Patch it
        # via Foundation if pyobjc is available; silently skip otherwise.
        try:
            from Foundation import NSBundle  # type: ignore
            bundle = NSBundle.mainBundle()
            info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
            if info is not None:
                info["CFBundleName"] = name
                info["CFBundleDisplayName"] = name
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
