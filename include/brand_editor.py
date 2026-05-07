"""Brands tab — output-centric editor.

Model: each Brand has 0..N Outputs. An Output is the unit that maps to one
generated PNG. It bundles:
  - phone        (which phone template, picked from `phones:` registry)
  - source       (input screenshot)
  - output       (output filename)
  - labels[]     (text overlays — text, position, color, font_size, anchor)
  - stamps[]     (image overlays — source, position, scale)

Brand-level fields apply to every output of the brand: background_color,
background_image, output_size.

The YAML key for outputs is still `screenshots:` (preserved for backward
compatibility); per-output `phone:` is new and overrides the brand-level
`phone:` if present.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from . import brand_io


SECTION_BG = ""  # default ttk styling


class BrandsTab(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        data: Any,
        assets_dir: Path,
        on_dirty: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.data = data
        self.assets_dir = assets_dir
        self.on_dirty = on_dirty

        self._loading = False
        self._current_brand: str | None = None
        self._current_shot_index: int | None = None
        self._current_label_index: int | None = None
        self._current_stamp_index: int | None = None

        self._build_ui()
        self._refresh_brand_list()

    # ===================================================================
    # UI construction
    # ===================================================================

    def _build_ui(self) -> None:
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # ----- Left: brand list -----
        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text="Brands", font=("", 11, "bold")).pack(anchor="w")
        self.brand_list = tk.Listbox(left, exportselection=False, height=24)
        self.brand_list.pack(fill="both", expand=True, pady=(2, 4))
        self.brand_list.bind("<<ListboxSelect>>", lambda _e: self._on_select_brand())
        brand_btns = ttk.Frame(left)
        brand_btns.pack(fill="x")
        ttk.Button(brand_btns, text="Add brand…", command=self._add_brand)\
            .pack(side="left", padx=2)
        ttk.Button(brand_btns, text="Delete", command=self._delete_brand)\
            .pack(side="left", padx=2)

        # ----- Right: dense form (no scroll) -----
        right = ttk.Frame(paned, padding=4)
        paned.add(right, weight=5)

        self._build_brand_section(right)
        self._build_outputs_section(right)

    # -------- brand-level fields --------

    def _build_brand_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Brand settings (apply to every output)",
                                 padding=6)
        section.pack(fill="x", pady=(0, 4))
        self.brand_section = section

        # Single horizontal row: [BG color] | [BG image] | [Output W×H]
        ttk.Label(section, text="BG (RGBA):").pack(side="left")
        self.bg_vars = [tk.StringVar() for _ in range(4)]
        for var in self.bg_vars:
            sb = ttk.Spinbox(section, from_=0, to=255, width=4, textvariable=var,
                             command=self._on_brand_field_change)
            sb.pack(side="left", padx=(2, 0))
            var.trace_add("write", lambda *_a: self._on_brand_field_change())

        ttk.Separator(section, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(section, text="BG image:").pack(side="left")
        self.bg_image_var = tk.StringVar()
        self.bg_image_var.trace_add("write", lambda *_a: self._on_brand_field_change())
        ttk.Entry(section, textvariable=self.bg_image_var, width=24)\
            .pack(side="left", padx=(2, 2), fill="x", expand=False)
        ttk.Button(section, text="…", width=2, command=self._browse_bg_image)\
            .pack(side="left")
        ttk.Button(section, text="✕", width=2,
                   command=lambda: self.bg_image_var.set(""))\
            .pack(side="left", padx=(2, 0))

        ttk.Separator(section, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(section, text="Out W×H:").pack(side="left")
        self.out_w_var = tk.StringVar()
        self.out_h_var = tk.StringVar()
        for var in (self.out_w_var, self.out_h_var):
            var.trace_add("write", lambda *_a: self._on_brand_field_change())
        ttk.Entry(section, textvariable=self.out_w_var, width=6)\
            .pack(side="left", padx=(2, 0))
        ttk.Label(section, text="×").pack(side="left", padx=2)
        ttk.Entry(section, textvariable=self.out_h_var, width=6).pack(side="left")

    # -------- outputs --------

    def _build_outputs_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Outputs", padding=6)
        section.pack(fill="both", expand=True)
        self.outputs_section = section

        # ---- Outputs list (left) | Selected-output area (right) ----
        body = ttk.Panedwindow(section, orient="horizontal")
        body.pack(fill="both", expand=True)

        list_pane = ttk.Frame(body)
        body.add(list_pane, weight=1)

        list_btns = ttk.Frame(list_pane)
        list_btns.pack(fill="x", pady=(0, 2))
        ttk.Button(list_btns, text="Add output…", command=self._add_output)\
            .pack(side="left", padx=(0, 2))
        ttk.Button(list_btns, text="Delete", command=self._delete_output)\
            .pack(side="left")

        self.shot_list = tk.Listbox(list_pane, exportselection=False, height=10)
        self.shot_list.pack(fill="both", expand=True)
        self.shot_list.bind("<<ListboxSelect>>", lambda _e: self._on_select_output())

        detail_pane = ttk.Frame(body)
        body.add(detail_pane, weight=3)
        self.output_form = detail_pane

        # Per-output identity: one horizontal row.
        identity = ttk.Frame(detail_pane)
        identity.pack(fill="x", pady=(0, 4))

        ttk.Label(identity, text="Phone:").pack(side="left")
        self.phone_var = tk.StringVar()
        self.phone_combo = ttk.Combobox(identity, textvariable=self.phone_var,
                                        values=self._phone_names(), state="readonly",
                                        width=18)
        self.phone_combo.pack(side="left", padx=(2, 8))
        self.phone_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self._on_output_field_change())

        ttk.Label(identity, text="Output:").pack(side="left")
        self.shot_output_var = tk.StringVar()
        self.shot_output_var.trace_add("write",
                                       lambda *_a: self._on_output_field_change())
        ttk.Entry(identity, textvariable=self.shot_output_var, width=22)\
            .pack(side="left", padx=(2, 8))

        ttk.Label(identity, text="Source:").pack(side="left")
        self.shot_source_var = tk.StringVar()
        self.shot_source_var.trace_add("write",
                                       lambda *_a: self._on_output_field_change())
        ttk.Entry(identity, textvariable=self.shot_source_var)\
            .pack(side="left", padx=(2, 2), fill="x", expand=True)
        ttk.Button(identity, text="…", width=2, command=self._browse_shot_source)\
            .pack(side="left")

        # Labels & Stamps side-by-side.
        sub = ttk.Panedwindow(detail_pane, orient="horizontal")
        sub.pack(fill="both", expand=True)

        labels_frame = ttk.Frame(sub)
        sub.add(labels_frame, weight=1)
        self._build_labels_section(labels_frame)

        stamps_frame = ttk.Frame(sub)
        sub.add(stamps_frame, weight=1)
        self._build_stamps_section(stamps_frame)

        # Disable everything until a brand is selected.
        self._set_form_state("disabled")

    # -------- labels --------

    def _build_labels_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Labels (text overlays)", padding=6)
        section.pack(fill="both", expand=True)
        self.labels_section = section

        btns = ttk.Frame(section)
        btns.pack(fill="x", pady=(0, 2))
        ttk.Button(btns, text="Add", command=self._add_label).pack(side="left")
        ttk.Button(btns, text="Delete", command=self._delete_label).pack(side="left", padx=2)

        self.label_list = tk.Listbox(section, exportselection=False, height=5)
        self.label_list.pack(fill="x")
        self.label_list.bind("<<ListboxSelect>>", lambda _e: self._on_select_label())

        form = ttk.Frame(section)
        form.pack(fill="x", pady=(6, 0))

        r = 0
        ttk.Label(form, text="Text:").grid(row=r, column=0, sticky="w", pady=2)
        self.label_text_var = tk.StringVar()
        self.label_text_var.trace_add("write", lambda *_a: self._on_label_field_change())
        ttk.Entry(form, textvariable=self.label_text_var, width=44)\
            .grid(row=r, column=1, columnspan=3, sticky="we", pady=2)
        r += 1

        ttk.Label(form, text="Position (x, y):").grid(row=r, column=0, sticky="w", pady=2)
        self.label_x_var = tk.StringVar()
        self.label_y_var = tk.StringVar()
        for var in (self.label_x_var, self.label_y_var):
            var.trace_add("write", lambda *_a: self._on_label_field_change())
        ttk.Entry(form, textvariable=self.label_x_var, width=8)\
            .grid(row=r, column=1, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.label_y_var, width=8)\
            .grid(row=r, column=2, sticky="w", pady=2)
        r += 1

        ttk.Label(form, text="Font size:").grid(row=r, column=0, sticky="w", pady=2)
        self.label_size_var = tk.StringVar()
        self.label_size_var.trace_add("write",
                                      lambda *_a: self._on_label_field_change())
        ttk.Entry(form, textvariable=self.label_size_var, width=8)\
            .grid(row=r, column=1, sticky="w", pady=2)

        ttk.Label(form, text="Color:").grid(row=r, column=2, sticky="e", pady=2)
        self.label_color_var = tk.StringVar()
        self.label_color_var.trace_add("write",
                                       lambda *_a: self._on_label_field_change())
        ttk.Entry(form, textvariable=self.label_color_var, width=10)\
            .grid(row=r, column=3, sticky="w", pady=2)
        r += 1

        ttk.Label(form, text="Anchor:").grid(row=r, column=0, sticky="w", pady=2)
        self.label_anchor_var = tk.StringVar()
        self.label_anchor_combo = ttk.Combobox(
            form, textvariable=self.label_anchor_var, state="readonly",
            values=["", "lt", "lm", "lb", "mt", "mm", "mb", "rt", "rm", "rb"],
            width=6,
        )
        self.label_anchor_combo.grid(row=r, column=1, sticky="w", pady=2)
        self.label_anchor_combo.bind("<<ComboboxSelected>>",
                                     lambda _e: self._on_label_field_change())
        ttk.Label(form, text="(blank = top-left)", foreground="#888")\
            .grid(row=r, column=2, columnspan=2, sticky="w", pady=2)
        r += 1

        form.columnconfigure(1, weight=0)
        form.columnconfigure(3, weight=1)

    # -------- stamps --------

    def _build_stamps_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Stamps (image overlays)", padding=6)
        section.pack(fill="both", expand=True)
        self.stamps_section = section

        btns = ttk.Frame(section)
        btns.pack(fill="x", pady=(0, 2))
        ttk.Button(btns, text="Add…", command=self._add_stamp).pack(side="left")
        ttk.Button(btns, text="Delete", command=self._delete_stamp).pack(side="left", padx=2)

        self.stamp_list = tk.Listbox(section, exportselection=False, height=5)
        self.stamp_list.pack(fill="x")
        self.stamp_list.bind("<<ListboxSelect>>", lambda _e: self._on_select_stamp())

        form = ttk.Frame(section)
        form.pack(fill="x", pady=(6, 0))

        r = 0
        ttk.Label(form, text="Source:").grid(row=r, column=0, sticky="w", pady=2)
        src_frame = ttk.Frame(form)
        src_frame.grid(row=r, column=1, columnspan=3, sticky="we", pady=2)
        self.stamp_source_var = tk.StringVar()
        self.stamp_source_var.trace_add("write",
                                        lambda *_a: self._on_stamp_field_change())
        ttk.Entry(src_frame, textvariable=self.stamp_source_var, width=40)\
            .pack(side="left", fill="x", expand=True)
        ttk.Button(src_frame, text="Browse…", command=self._browse_stamp_source)\
            .pack(side="left", padx=4)
        r += 1

        ttk.Label(form, text="Position (x, y):").grid(row=r, column=0, sticky="w", pady=2)
        self.stamp_x_var = tk.StringVar()
        self.stamp_y_var = tk.StringVar()
        for var in (self.stamp_x_var, self.stamp_y_var):
            var.trace_add("write", lambda *_a: self._on_stamp_field_change())
        ttk.Entry(form, textvariable=self.stamp_x_var, width=8)\
            .grid(row=r, column=1, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.stamp_y_var, width=8)\
            .grid(row=r, column=2, sticky="w", pady=2)
        r += 1

        ttk.Label(form, text="Scale:").grid(row=r, column=0, sticky="w", pady=2)
        self.stamp_scale_var = tk.StringVar()
        self.stamp_scale_var.trace_add("write",
                                       lambda *_a: self._on_stamp_field_change())
        ttk.Entry(form, textvariable=self.stamp_scale_var, width=8)\
            .grid(row=r, column=1, sticky="w", pady=2)
        ttk.Label(form, text="(1.0 = original size)", foreground="#888")\
            .grid(row=r, column=2, columnspan=2, sticky="w", pady=2)

        form.columnconfigure(3, weight=1)

    # ===================================================================
    # State helpers
    # ===================================================================

    def _phone_names(self) -> list[str]:
        return list((self.data.get("phones") or {}).keys())

    def refresh_phone_choices(self) -> None:
        self.phone_combo["values"] = self._phone_names()

    def _set_form_state(self, state: str) -> None:
        for section in (self.brand_section, self.outputs_section):
            self._walk_state(section, state)

    def _walk_state(self, root: tk.Widget, state: str) -> None:
        for child in root.winfo_children():
            cls = child.winfo_class()
            if cls in ("TEntry", "TSpinbox", "TButton", "Listbox"):
                try:
                    child.configure(state=state)
                except tk.TclError:
                    pass
            elif cls == "TCombobox":
                try:
                    child.configure(state="readonly" if state == "normal" else "disabled")
                except tk.TclError:
                    pass
            self._walk_state(child, state)

    # ===================================================================
    # Brand list
    # ===================================================================

    def _refresh_brand_list(self, *, select: str | None = None) -> None:
        names = brand_io.list_brand_names(self.data)
        self.brand_list.delete(0, "end")
        for n in names:
            self.brand_list.insert("end", n)
        if select and select in names:
            idx = names.index(select)
            self.brand_list.selection_set(idx)
            self.brand_list.see(idx)
            self._on_select_brand()
        elif names and self._current_brand in names:
            idx = names.index(self._current_brand)
            self.brand_list.selection_set(idx)
        else:
            self._current_brand = None
            self._clear_form()

    def _on_select_brand(self) -> None:
        sel = self.brand_list.curselection()
        if not sel:
            return
        name = self.brand_list.get(sel[0])
        self._current_brand = name
        self._load_brand(name)

    def _add_brand(self) -> None:
        name = simpledialog.askstring("New brand", "Brand name:", parent=self)
        if not name or not name.strip():
            return
        try:
            brand_io.add_brand(self.data, name.strip())
        except ValueError as exc:
            messagebox.showerror("Add brand", str(exc), parent=self)
            return
        self.on_dirty()
        self._refresh_brand_list(select=name.strip())

    def _delete_brand(self) -> None:
        if not self._current_brand:
            return
        name = self._current_brand
        if not messagebox.askyesno("Delete brand", f"Delete brand {name!r}?", parent=self):
            return
        brand_io.delete_brand(self.data, name)
        self._current_brand = None
        self.on_dirty()
        self._refresh_brand_list()

    # ===================================================================
    # Brand-level form
    # ===================================================================

    def _load_brand(self, name: str) -> None:
        brand = self.data["brands"][name]
        self._loading = True
        try:
            bg = list(brand.get("background_color") or [0, 0, 0, 0])
            bg = (bg + [0, 0, 0, 0])[:4]
            for var, val in zip(self.bg_vars, bg):
                var.set(str(int(val)))
            self.bg_image_var.set(str(brand.get("background_image") or ""))
            out = brand.get("output_size")
            if out:
                self.out_w_var.set(str(int(out[0])))
                self.out_h_var.set(str(int(out[1])))
            else:
                self.out_w_var.set("")
                self.out_h_var.set("")
        finally:
            self._loading = False
        self._set_form_state("normal")
        self._refresh_output_list()

    def _clear_form(self) -> None:
        self._loading = True
        try:
            for var in self.bg_vars:
                var.set("")
            self.bg_image_var.set("")
            self.out_w_var.set("")
            self.out_h_var.set("")
            self.shot_list.delete(0, "end")
            self._clear_output_form()
        finally:
            self._loading = False
        self._set_form_state("disabled")

    def _on_brand_field_change(self) -> None:
        if self._loading or not self._current_brand:
            return

        try:
            bg_color = [int(v.get() or "0") for v in self.bg_vars]
        except ValueError:
            bg_color = None
        if bg_color and bg_color == [0, 0, 0, 0]:
            bg_color = None

        bg_image = self.bg_image_var.get().strip() or None

        out_w = self.out_w_var.get().strip()
        out_h = self.out_h_var.get().strip()
        output_size: list[int] | None
        if out_w and out_h:
            try:
                output_size = [int(out_w), int(out_h)]
            except ValueError:
                output_size = None
        else:
            output_size = None

        # phone is no longer edited at brand level via the UI; preserve whatever
        # the YAML has by passing nothing (update_brand only writes fields it
        # sees keyword args for).
        try:
            brand_io.update_brand(
                self.data, self._current_brand,
                background_color=bg_color,
                background_image=bg_image,
                output_size=output_size,
            )
        except KeyError:
            return
        self.on_dirty()

    def _browse_bg_image(self) -> None:
        start = self.assets_dir / "phones"
        self.winfo_toplevel().lift()
        path = filedialog.askopenfilename(
            title="Select background image",
            initialdir=str(start if start.is_dir() else self.assets_dir),
            filetypes=[("Images", "*.png *.PNG *.jpg *.jpeg *.JPG"), ("All files", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if path:
            self.bg_image_var.set(self._relative_to_assets(Path(path)))

    # ===================================================================
    # Outputs
    # ===================================================================

    def _refresh_output_list(self, *, select_index: int | None = None) -> None:
        self.shot_list.delete(0, "end")
        if not self._current_brand:
            return
        shots = brand_io.get_screenshots(self.data, self._current_brand)
        if not shots:
            self.shot_list.insert("end", "  (no outputs — click Add output… to start)")
            self.shot_list.itemconfig(0, foreground="#888")
        for i, s in enumerate(shots):
            phone = s.get("phone") or "—"
            src = s.get("source") or ""
            out = s.get("output") or ""
            label = f"{i+1:>2}.  [{phone}]  {out or '—'}    ←  {Path(src).name if src else '—'}"
            self.shot_list.insert("end", label)
        if select_index is not None and 0 <= select_index < len(shots):
            self.shot_list.selection_set(select_index)
            self.shot_list.see(select_index)
            self._on_select_output()
        else:
            self._current_shot_index = None
            self._clear_output_form()

    def _on_select_output(self) -> None:
        sel = self.shot_list.curselection()
        if not sel or not self._current_brand:
            return
        shots = brand_io.get_screenshots(self.data, self._current_brand)
        if not shots:
            self.shot_list.selection_clear(0, "end")
            return
        idx = sel[0]
        self._current_shot_index = idx
        self._load_output(idx)

    def _add_output(self) -> None:
        if not self._current_brand:
            messagebox.showinfo("Pick a brand first",
                                "Select a brand on the left before adding an output.",
                                parent=self)
            return
        start = self.assets_dir / "screenshots" / self._current_brand
        if not start.is_dir():
            start = self.assets_dir / "screenshots"
        if not start.is_dir():
            start = self.assets_dir
        self.winfo_toplevel().lift()
        path = filedialog.askopenfilename(
            title=f"Pick screenshot source for {self._current_brand}",
            initialdir=str(start),
            filetypes=[("Images", "*.png *.PNG *.jpg *.jpeg *.JPG"), ("All files", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if not path:
            return
        source_rel = self._relative_to_assets(Path(path))
        output_name = self._suggest_output_name(Path(path))
        # Default phone: brand-level phone if set, else first phone in registry.
        brand = self.data["brands"][self._current_brand]
        phones = self._phone_names()
        default_phone = str(brand.get("phone") or (phones[0] if phones else ""))

        shot = brand_io.add_screenshot(self.data, self._current_brand,
                                       source=source_rel, output=output_name)
        if default_phone:
            shot["phone"] = default_phone

        shots = brand_io.get_screenshots(self.data, self._current_brand)
        self.on_dirty()
        self._refresh_output_list(select_index=len(shots) - 1)

    def _delete_output(self) -> None:
        if not self._current_brand or self._current_shot_index is None:
            return
        idx = self._current_shot_index
        if not messagebox.askyesno("Delete output", f"Delete output #{idx + 1}?",
                                   parent=self):
            return
        brand_io.delete_screenshot(self.data, self._current_brand, idx)
        self._current_shot_index = None
        self.on_dirty()
        self._refresh_output_list()

    def _suggest_output_name(self, src: Path) -> str:
        if not self._current_brand:
            return src.stem + ".png"
        existing = brand_io.get_screenshots(self.data, self._current_brand)
        next_idx = len(existing) + 1
        return f"{next_idx:02d}_{src.stem}.png"

    # -------- per-output form --------

    def _load_output(self, idx: int) -> None:
        shots = brand_io.get_screenshots(self.data, self._current_brand)
        shot = shots[idx]
        self._loading = True
        try:
            self.phone_var.set(str(shot.get("phone") or ""))
            self.shot_source_var.set(str(shot.get("source") or ""))
            self.shot_output_var.set(str(shot.get("output") or ""))
        finally:
            self._loading = False
        self._refresh_label_list()
        self._refresh_stamp_list()

    def _clear_output_form(self) -> None:
        self._loading = True
        try:
            self.phone_var.set("")
            self.shot_source_var.set("")
            self.shot_output_var.set("")
            self.label_list.delete(0, "end")
            self.stamp_list.delete(0, "end")
            self._clear_label_form()
            self._clear_stamp_form()
        finally:
            self._loading = False

    def _on_output_field_change(self) -> None:
        if self._loading or not self._current_brand or self._current_shot_index is None:
            return
        brand_io.update_screenshot(
            self.data, self._current_brand, self._current_shot_index,
            source=self.shot_source_var.get().strip(),
            output=self.shot_output_var.get().strip(),
            phone=self.phone_var.get().strip() or None,
        )
        self.on_dirty()
        idx = self._current_shot_index
        self._refresh_output_list(select_index=idx)

    def _browse_shot_source(self) -> None:
        start = self.assets_dir / "screenshots"
        self.winfo_toplevel().lift()
        path = filedialog.askopenfilename(
            title="Select screenshot source",
            initialdir=str(start if start.is_dir() else self.assets_dir),
            filetypes=[("Images", "*.png *.PNG *.jpg *.jpeg *.JPG"), ("All files", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if path:
            self.shot_source_var.set(self._relative_to_assets(Path(path)))

    # ===================================================================
    # Labels
    # ===================================================================

    def _refresh_label_list(self, *, select_index: int | None = None) -> None:
        self.label_list.delete(0, "end")
        if (not self._current_brand) or self._current_shot_index is None:
            self._clear_label_form()
            return
        labels = brand_io.get_labels(self.data, self._current_brand,
                                     self._current_shot_index)
        if not labels:
            self.label_list.insert("end", "  (no labels)")
            self.label_list.itemconfig(0, foreground="#888")
        for i, lbl in enumerate(labels):
            text = str(lbl.get("text") or "")
            pos = lbl.get("position") or [0, 0]
            self.label_list.insert("end",
                                   f"{i+1}.  {text[:30]}    @ {pos[0]},{pos[1]}")
        if select_index is not None and 0 <= select_index < len(labels):
            self.label_list.selection_set(select_index)
            self.label_list.see(select_index)
            self._on_select_label()
        else:
            self._current_label_index = None
            self._clear_label_form()

    def _on_select_label(self) -> None:
        sel = self.label_list.curselection()
        if not sel or self._current_shot_index is None:
            return
        labels = brand_io.get_labels(self.data, self._current_brand,
                                     self._current_shot_index)
        if not labels:
            self.label_list.selection_clear(0, "end")
            return
        idx = sel[0]
        self._current_label_index = idx
        lbl = labels[idx]
        self._loading = True
        try:
            self.label_text_var.set(str(lbl.get("text") or ""))
            pos = lbl.get("position") or [0, 0]
            self.label_x_var.set(str(int(pos[0])))
            self.label_y_var.set(str(int(pos[1])))
            self.label_size_var.set(str(int(lbl.get("font_size") or 48)))
            self.label_color_var.set(str(lbl.get("color") or ""))
            self.label_anchor_var.set(str(lbl.get("anchor") or ""))
        finally:
            self._loading = False

    def _add_label(self) -> None:
        if self._current_shot_index is None:
            return
        brand_io.add_label(self.data, self._current_brand, self._current_shot_index)
        self.on_dirty()
        labels = brand_io.get_labels(self.data, self._current_brand,
                                     self._current_shot_index)
        self._refresh_label_list(select_index=len(labels) - 1)

    def _delete_label(self) -> None:
        if (self._current_shot_index is None or self._current_label_index is None):
            return
        idx = self._current_label_index
        if not messagebox.askyesno("Delete label", f"Delete label #{idx + 1}?",
                                   parent=self):
            return
        brand_io.delete_label(self.data, self._current_brand,
                              self._current_shot_index, idx)
        self._current_label_index = None
        self.on_dirty()
        self._refresh_label_list()

    def _on_label_field_change(self) -> None:
        if (self._loading or self._current_shot_index is None
                or self._current_label_index is None):
            return
        try:
            x = int(self.label_x_var.get() or "0")
            y = int(self.label_y_var.get() or "0")
        except ValueError:
            return
        size_str = self.label_size_var.get().strip()
        try:
            size = int(size_str) if size_str else 48
        except ValueError:
            size = 48
        color = self.label_color_var.get().strip() or None
        anchor = self.label_anchor_var.get().strip() or None
        brand_io.update_label(
            self.data, self._current_brand,
            self._current_shot_index, self._current_label_index,
            text=self.label_text_var.get(),
            position=[x, y],
            font_size=size,
            color=color,
            anchor=anchor,
        )
        self.on_dirty()
        idx = self._current_label_index
        self._refresh_label_list(select_index=idx)

    def _clear_label_form(self) -> None:
        self._loading = True
        try:
            self.label_text_var.set("")
            self.label_x_var.set("")
            self.label_y_var.set("")
            self.label_size_var.set("")
            self.label_color_var.set("")
            self.label_anchor_var.set("")
        finally:
            self._loading = False

    # ===================================================================
    # Stamps
    # ===================================================================

    def _refresh_stamp_list(self, *, select_index: int | None = None) -> None:
        self.stamp_list.delete(0, "end")
        if (not self._current_brand) or self._current_shot_index is None:
            self._clear_stamp_form()
            return
        stamps = brand_io.get_stamps(self.data, self._current_brand,
                                     self._current_shot_index)
        if not stamps:
            self.stamp_list.insert("end", "  (no stamps)")
            self.stamp_list.itemconfig(0, foreground="#888")
        for i, st in enumerate(stamps):
            src = str(st.get("source") or "")
            pos = st.get("position") or [0, 0]
            scale = st.get("scale") or 1.0
            self.stamp_list.insert("end",
                                   f"{i+1}.  {Path(src).name or '—'}    "
                                   f"@ {pos[0]},{pos[1]}  ×{scale}")
        if select_index is not None and 0 <= select_index < len(stamps):
            self.stamp_list.selection_set(select_index)
            self.stamp_list.see(select_index)
            self._on_select_stamp()
        else:
            self._current_stamp_index = None
            self._clear_stamp_form()

    def _on_select_stamp(self) -> None:
        sel = self.stamp_list.curselection()
        if not sel or self._current_shot_index is None:
            return
        stamps = brand_io.get_stamps(self.data, self._current_brand,
                                     self._current_shot_index)
        if not stamps:
            self.stamp_list.selection_clear(0, "end")
            return
        idx = sel[0]
        self._current_stamp_index = idx
        st = stamps[idx]
        self._loading = True
        try:
            self.stamp_source_var.set(str(st.get("source") or ""))
            pos = st.get("position") or [0, 0]
            self.stamp_x_var.set(str(int(pos[0])))
            self.stamp_y_var.set(str(int(pos[1])))
            self.stamp_scale_var.set(str(float(st.get("scale") or 1.0)))
        finally:
            self._loading = False

    def _add_stamp(self) -> None:
        if self._current_shot_index is None:
            return
        start = self.assets_dir / "logos"
        if self._current_brand:
            specific = start / self._current_brand
            if specific.is_dir():
                start = specific
        if not start.is_dir():
            start = self.assets_dir
        self.winfo_toplevel().lift()
        path = filedialog.askopenfilename(
            title="Pick stamp image",
            initialdir=str(start),
            filetypes=[("Images", "*.png *.PNG *.jpg *.jpeg *.JPG"), ("All files", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if not path:
            return
        rel = self._relative_to_assets(Path(path))
        brand_io.add_stamp(self.data, self._current_brand,
                           self._current_shot_index, source=rel)
        self.on_dirty()
        stamps = brand_io.get_stamps(self.data, self._current_brand,
                                     self._current_shot_index)
        self._refresh_stamp_list(select_index=len(stamps) - 1)

    def _delete_stamp(self) -> None:
        if (self._current_shot_index is None or self._current_stamp_index is None):
            return
        idx = self._current_stamp_index
        if not messagebox.askyesno("Delete stamp", f"Delete stamp #{idx + 1}?",
                                   parent=self):
            return
        brand_io.delete_stamp(self.data, self._current_brand,
                              self._current_shot_index, idx)
        self._current_stamp_index = None
        self.on_dirty()
        self._refresh_stamp_list()

    def _on_stamp_field_change(self) -> None:
        if (self._loading or self._current_shot_index is None
                or self._current_stamp_index is None):
            return
        try:
            x = int(self.stamp_x_var.get() or "0")
            y = int(self.stamp_y_var.get() or "0")
        except ValueError:
            return
        try:
            scale = float(self.stamp_scale_var.get() or "1.0")
        except ValueError:
            scale = 1.0
        brand_io.update_stamp(
            self.data, self._current_brand,
            self._current_shot_index, self._current_stamp_index,
            source=self.stamp_source_var.get().strip(),
            position=[x, y],
            scale=scale,
        )
        self.on_dirty()
        idx = self._current_stamp_index
        self._refresh_stamp_list(select_index=idx)

    def _browse_stamp_source(self) -> None:
        start = self.assets_dir / "logos"
        if self._current_brand:
            specific = start / self._current_brand
            if specific.is_dir():
                start = specific
        self.winfo_toplevel().lift()
        path = filedialog.askopenfilename(
            title="Select stamp image",
            initialdir=str(start if start.is_dir() else self.assets_dir),
            filetypes=[("Images", "*.png *.PNG *.jpg *.jpeg *.JPG"), ("All files", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if path:
            self.stamp_source_var.set(self._relative_to_assets(Path(path)))

    def _clear_stamp_form(self) -> None:
        self._loading = True
        try:
            self.stamp_source_var.set("")
            self.stamp_x_var.set("")
            self.stamp_y_var.set("")
            self.stamp_scale_var.set("")
        finally:
            self._loading = False

    # ===================================================================
    # Path helpers
    # ===================================================================

    def _relative_to_assets(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.assets_dir.resolve()))
        except ValueError:
            return str(path.resolve())
