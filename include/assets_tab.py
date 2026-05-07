"""Assets tab — browse images under assets/ (backgrounds, stamps, etc.).

Categories are derived from the assets/ folder layout and the YAML:
  - Phones        : images referenced as a phone's base_image
  - Backgrounds   : images under phones/ NOT referenced by a phone (e.g. bg.jpg)
  - Logos/Stamps  : images under logos/
  - Screenshots   : images under screenshots/
  - Fonts         : files under fonts/ (listed, not thumbnailed)
"""
from __future__ import annotations

import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk


THUMB_MAX = (180, 240)
COLUMNS = 5
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
FONT_EXTS = {".ttf", ".otf"}


class AssetsTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, data: Any, assets_dir: Path) -> None:
        super().__init__(parent)
        self.data = data
        self.assets_dir = assets_dir
        self._thumb_refs: list[ImageTk.PhotoImage] = []
        self._build_ui()
        self.after(80, self.refresh)

    # ---------- UI ------------------------------------------------------

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 8))
        toolbar.pack(side="top", fill="x")
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="left")
        self.count_var = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self.count_var, foreground="#666")\
            .pack(side="left", padx=12)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Left: category list
        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text="Category", font=("", 10, "bold")).pack(anchor="w")
        self.cat_list = tk.Listbox(left, exportselection=False, height=14)
        self.cat_list.pack(fill="both", expand=True, pady=2)
        self.cat_list.bind("<<ListboxSelect>>", lambda _e: self._on_select_category())

        # Right: thumbnail grid (scrollable)
        right = ttk.Frame(paned)
        paned.add(right, weight=4)

        self.canvas = tk.Canvas(right, bg="#2a2a2e", highlightthickness=0)
        scroll = ttk.Scrollbar(right, orient="vertical", command=self.canvas.yview)
        self.canvas.config(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.grid_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

    # ---------- categories ---------------------------------------------

    def _gather(self) -> dict[str, list[Path]]:
        """Scan assets/ and return {category: [paths]}."""
        cats: dict[str, list[Path]] = {
            "Phones": [],
            "Backgrounds": [],
            "Logos / stamps": [],
            "Screenshots": [],
            "Fonts": [],
        }

        # Set of resolved paths referenced as phone base_images.
        phone_paths: set[Path] = set()
        for phone in (self.data.get("phones") or {}).values():
            base = phone.get("base_image")
            if base:
                phone_paths.add((self.assets_dir / str(base)).resolve())

        phones_dir = self.assets_dir / "phones"
        if phones_dir.is_dir():
            for p in sorted(phones_dir.rglob("*")):
                if p.is_file() and p.suffix.lower() in IMG_EXTS:
                    if p.resolve() in phone_paths:
                        cats["Phones"].append(p)
                    else:
                        cats["Backgrounds"].append(p)

        logos_dir = self.assets_dir / "logos"
        if logos_dir.is_dir():
            for p in sorted(logos_dir.rglob("*")):
                if p.is_file() and p.suffix.lower() in IMG_EXTS:
                    cats["Logos / stamps"].append(p)

        shots_dir = self.assets_dir / "screenshots"
        if shots_dir.is_dir():
            for p in sorted(shots_dir.rglob("*")):
                if p.is_file() and p.suffix.lower() in IMG_EXTS:
                    cats["Screenshots"].append(p)

        fonts_dir = self.assets_dir / "fonts"
        if fonts_dir.is_dir():
            for p in sorted(fonts_dir.rglob("*")):
                if p.is_file() and p.suffix.lower() in FONT_EXTS:
                    cats["Fonts"].append(p)

        return cats

    def refresh(self) -> None:
        self._cats = self._gather()
        self.cat_list.delete(0, "end")
        for name, paths in self._cats.items():
            self.cat_list.insert("end", f"{name}  ({len(paths)})")
        # Auto-select first non-empty category, else first.
        target = 0
        for i, paths in enumerate(self._cats.values()):
            if paths:
                target = i
                break
        self.cat_list.selection_clear(0, "end")
        self.cat_list.selection_set(target)
        self._on_select_category()

    def _on_select_category(self) -> None:
        sel = self.cat_list.curselection()
        if not sel:
            return
        idx = sel[0]
        name = list(self._cats.keys())[idx]
        paths = self._cats[name]
        self.count_var.set(f"{name}: {len(paths)} file(s)")
        self._render_grid(name, paths)

    # ---------- grid rendering -----------------------------------------

    def _render_grid(self, category: str, paths: list[Path]) -> None:
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self._thumb_refs.clear()

        if not paths:
            ttk.Label(self.grid_frame, text="(empty)", foreground="#888")\
                .grid(row=0, column=0, padx=8, pady=8, sticky="w")
            return

        if category == "Fonts":
            for i, path in enumerate(paths):
                self._add_font_row(path, row=i)
            return

        for i, path in enumerate(paths):
            r, c = divmod(i, COLUMNS)
            self._add_thumb(path, r, c)

    def _add_thumb(self, path: Path, row: int, col: int) -> None:
        cell = ttk.Frame(self.grid_frame, padding=4)
        cell.grid(row=row, column=col, padx=4, pady=4, sticky="n")
        try:
            img = Image.open(path)
            img.thumbnail(THUMB_MAX, Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._thumb_refs.append(photo)
            lbl = tk.Label(cell, image=photo, bg="#1f1f23", cursor="hand2")
            lbl.pack()
            lbl.bind("<Button-1>", lambda _e, p=path: self._open_path(p))
        except Exception as exc:  # noqa: BLE001
            tk.Label(cell, text=f"[error: {exc}]", fg="#a44", bg="#2a2a2e",
                     wraplength=THUMB_MAX[0]).pack()

        try:
            rel = path.relative_to(self.assets_dir)
        except ValueError:
            rel = path.name
        ttk.Label(cell, text=str(rel), foreground="#ccc",
                  wraplength=THUMB_MAX[0], justify="center")\
            .pack(pady=(2, 0))

    def _add_font_row(self, path: Path, row: int) -> None:
        try:
            rel = path.relative_to(self.assets_dir)
        except ValueError:
            rel = path.name
        cell = ttk.Frame(self.grid_frame, padding=(8, 4))
        cell.grid(row=row, column=0, sticky="w")
        link = tk.Label(cell, text=str(rel), fg="#4ea1ff", bg="#2a2a2e", cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda _e, p=path: self._open_path(p))

    # ---------- open ----------------------------------------------------

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
