"""Brands tab — three-pane editor (sidebar tree | preview | inspector).

Phase 1 layout:
  - Left: hierarchical Treeview of  Brand → Output → (Labels/Stamps)
  - Center: preview area (static placeholder for now; live render is Phase 2)
  - Right: context-sensitive inspector — only shows controls for the selected
           object (brand, output, label or stamp)

Keyboard shortcuts:
  Delete / Backspace : delete the selected tree node
  ⌘D / Ctrl-D        : duplicate the selected label/stamp
  Arrow keys         : nudge label/stamp position by 5 px (Shift = 25)

Underlying YAML schema is unchanged from the previous iteration.
"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from PIL import Image, ImageTk

from . import brand_io
from .compositor import build_composite
from .config_loader import resolve_shot_phone


# ----- dark-ish palette ---------------------------------------------------

C_BG          = "#1e1e22"
C_PANEL       = "#26262b"
C_PANEL_ALT   = "#2c2c32"
C_BORDER      = "#3a3a42"
C_TEXT        = "#e6e6ea"
C_TEXT_DIM    = "#9a9aa3"
C_ACCENT      = "#4ea1ff"
C_ACCENT_DIM  = "#274a73"
C_PREVIEW_BG  = "#15151a"


def install_dark_theme(root: tk.Misc) -> None:
    """Apply a dark ttk theme. Idempotent — safe to call multiple times."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=C_PANEL, foreground=C_TEXT, bordercolor=C_BORDER)
    style.configure("TFrame", background=C_PANEL)
    style.configure("TLabel", background=C_PANEL, foreground=C_TEXT)
    style.configure("Dim.TLabel", background=C_PANEL, foreground=C_TEXT_DIM)
    style.configure("Heading.TLabel", background=C_PANEL, foreground=C_TEXT,
                    font=("", 12, "bold"))
    style.configure("Section.TLabel", background=C_PANEL, foreground=C_TEXT_DIM,
                    font=("", 10, "bold"))
    style.configure("TLabelframe", background=C_PANEL, foreground=C_TEXT_DIM,
                    bordercolor=C_BORDER)
    style.configure("TLabelframe.Label", background=C_PANEL, foreground=C_TEXT_DIM)
    style.configure("TButton", background=C_PANEL_ALT, foreground=C_TEXT,
                    padding=4, borderwidth=1)
    style.map("TButton",
              background=[("active", C_ACCENT_DIM), ("pressed", C_ACCENT_DIM)],
              foreground=[("active", C_TEXT)])
    style.configure("Accent.TButton", background=C_ACCENT, foreground="#0b1726",
                    padding=4)
    style.map("Accent.TButton",
              background=[("active", "#6cb3ff"), ("pressed", "#6cb3ff")])
    style.configure("Icon.TButton", padding=(2, 0), font=("", 12))
    style.configure("TEntry", fieldbackground=C_PANEL_ALT, foreground=C_TEXT,
                    insertcolor=C_TEXT, bordercolor=C_BORDER)
    style.configure("TSpinbox", fieldbackground=C_PANEL_ALT, foreground=C_TEXT,
                    insertcolor=C_TEXT, bordercolor=C_BORDER, arrowcolor=C_TEXT)
    style.configure("TCombobox", fieldbackground=C_PANEL_ALT, foreground=C_TEXT,
                    background=C_PANEL_ALT, bordercolor=C_BORDER, arrowcolor=C_TEXT)
    style.map("TCombobox",
              fieldbackground=[("readonly", C_PANEL_ALT)],
              foreground=[("readonly", C_TEXT)])
    style.configure("TPanedwindow", background=C_BG)
    style.configure("TSeparator", background=C_BORDER)
    style.configure("Treeview", background=C_PANEL_ALT, foreground=C_TEXT,
                    fieldbackground=C_PANEL_ALT, bordercolor=C_BORDER,
                    rowheight=22)
    style.map("Treeview",
              background=[("selected", C_ACCENT_DIM)],
              foreground=[("selected", C_TEXT)])
    style.configure("Treeview.Heading", background=C_PANEL, foreground=C_TEXT_DIM)
    style.configure("TNotebook", background=C_BG, bordercolor=C_BORDER)
    style.configure("TNotebook.Tab", background=C_PANEL, foreground=C_TEXT_DIM,
                    padding=(12, 6))
    style.map("TNotebook.Tab",
              background=[("selected", C_PANEL_ALT)],
              foreground=[("selected", C_TEXT)])


# ----- node id helpers ----------------------------------------------------
# Tree IIDs: "brand:Foo", "shot:Foo:0", "label:Foo:0:1", "stamp:Foo:0:2"

def nid_brand(b: str) -> str:                       return f"brand:{b}"
def nid_shot(b: str, i: int) -> str:                return f"shot:{b}:{i}"
def nid_labels(b: str, i: int) -> str:              return f"labels:{b}:{i}"
def nid_stamps(b: str, i: int) -> str:              return f"stamps:{b}:{i}"
def nid_label(b: str, i: int, j: int) -> str:       return f"label:{b}:{i}:{j}"
def nid_stamp(b: str, i: int, j: int) -> str:       return f"stamp:{b}:{i}:{j}"


def parse_nid(nid: str) -> tuple[str, list[str]]:
    parts = nid.split(":")
    return parts[0], parts[1:]


def attach_tooltip(widget: tk.Widget, text: str) -> None:
    """Show a small tooltip after hovering over `widget`."""
    state: dict[str, Any] = {"tip": None, "after": None}

    def show() -> None:
        state["after"] = None
        if state["tip"] is not None:
            return
        try:
            x = widget.winfo_rootx() + 12
            y = widget.winfo_rooty() + widget.winfo_height() + 4
        except tk.TclError:
            return
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip, text=text, bg="#000000", fg=C_TEXT,
            relief="solid", borderwidth=1, padx=6, pady=2,
        ).pack()
        state["tip"] = tip

    def hide(_e: object = None) -> None:
        if state["after"] is not None:
            try:
                widget.after_cancel(state["after"])
            except tk.TclError:
                pass
            state["after"] = None
        if state["tip"] is not None:
            try:
                state["tip"].destroy()
            except tk.TclError:
                pass
            state["tip"] = None

    def enter(_e: object) -> None:
        hide()
        state["after"] = widget.after(450, show)

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", hide, add="+")
    widget.bind("<ButtonPress>", hide, add="+")


# ==========================================================================
# BrandsTab
# ==========================================================================

class BrandsTab(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        data: Any,
        assets_dir: Path,
        on_dirty: Callable[[], None],
    ) -> None:
        install_dark_theme(parent)
        super().__init__(parent)
        self.data = data
        self.assets_dir = assets_dir
        self.on_dirty = on_dirty

        # The currently-selected node's logical address.
        self._sel_kind: str = ""        # "brand"|"shot"|"label"|"stamp"|""
        self._sel_brand: str | None = None
        self._sel_shot: int | None = None
        self._sel_label: int | None = None
        self._sel_stamp: int | None = None

        self._loading = False           # suppress on-change while populating

        # Preview state.
        self._preview_image: Image.Image | None = None       # rendered composite (full-res)
        self._preview_tk: ImageTk.PhotoImage | None = None
        self._preview_scale: float = 1.0                     # current display scale
        self._preview_fit: bool = True                       # auto-fit to canvas
        self._preview_user_zoom: float = 1.0
        self._render_after_id: str | None = None             # debounce token
        self._render_token: int = 0                          # cancel-stale-renders
        self._cur_preview_key: tuple[str, int] | None = None  # (brand, shot_idx)
        self._last_render_sig: str | None = None  # skip rebuilds when inputs unchanged
        self._preview_origin: tuple[int, int] = (0, 0)
        self._drag_handle: str | None = None  # "tl"|"tr"|"br"|"bl" or None
        # Crop-rect move state: (start_ix, start_iy, l0, t0, r0, b0) or None
        self._drag_move: tuple[int, int, int, int, int, int] | None = None

        self._build_ui()
        self._refresh_tree()

    # ===================================================================
    # UI construction
    # ===================================================================

    def _build_ui(self) -> None:
        self.configure(style="TFrame")

        # Top toolbar inside the tab.
        topbar = ttk.Frame(self, padding=(8, 6))
        topbar.pack(side="top", fill="x")
        ttk.Label(topbar, text="Configuration", style="Heading.TLabel").pack(side="left")
        ttk.Label(topbar,
                  text="  ·  Brand → Output → Labels/Stamps",
                  style="Dim.TLabel").pack(side="left")

        # Three-pane horizontal split.
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._paned = paned

        # ---- Left: tree sidebar (slim) ----
        sidebar = ttk.Frame(paned, padding=4)
        paned.add(sidebar, weight=1)
        self._build_sidebar(sidebar)

        # ---- Center: preview (largest) ----
        center = ttk.Frame(paned, padding=4)
        paned.add(center, weight=4)
        self._build_preview(center)

        # ---- Right: inspector ----
        right_outer = ttk.Frame(paned, padding=4)
        paned.add(right_outer, weight=3)
        self._inspector_root = right_outer
        self._inspector_body: ttk.Frame | None = None
        self._render_inspector()

        # Set initial sash positions once the paned widget has a real width.
        self.after_idle(self._set_initial_sashes)

        # Keyboard shortcuts (active when this tab has focus).
        self.bind_all("<Delete>", self._on_key_delete)
        self.bind_all("<BackSpace>", self._on_key_delete)
        self.bind_all("<Command-d>", self._on_key_duplicate)
        self.bind_all("<Control-d>", self._on_key_duplicate)
        for seq, dx, dy in (
            ("<Left>", -5, 0), ("<Right>", 5, 0),
            ("<Up>", 0, -5), ("<Down>", 0, 5),
            ("<Shift-Left>", -25, 0), ("<Shift-Right>", 25, 0),
            ("<Shift-Up>", 0, -25), ("<Shift-Down>", 0, 25),
        ):
            self.bind_all(seq, lambda e, dx=dx, dy=dy: self._on_key_nudge(e, dx, dy))

    # -------- sidebar --------

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="＋ Brand", command=self._add_brand,
                   style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="＋ Output", command=self._add_output)\
            .pack(side="left", padx=4)
        ttk.Button(bar, text="🗑", style="Icon.TButton",
                   command=self._delete_selected).pack(side="right")

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        vbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_tree_select())
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        # Right-click context menu (Button-2 is right-click on macOS trackpads,
        # Button-3 on Linux/Windows; Control-Button-1 is the mac fallback).
        for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.tree.bind(seq, self._on_tree_right_click)

        # Visual indent for nested levels (Tk default is OK; nothing needed).

    # -------- preview --------

    def _build_preview(self, parent: ttk.Frame) -> None:
        # Toolbar above the canvas.
        bar = ttk.Frame(parent); bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="−", width=3, command=self._preview_zoom_out)\
            .pack(side="left")
        ttk.Button(bar, text="＋", width=3, command=self._preview_zoom_in)\
            .pack(side="left", padx=2)
        ttk.Button(bar, text="Fit", command=self._preview_zoom_fit)\
            .pack(side="left", padx=4)
        ttk.Button(bar, text="↻", width=3, command=self._force_render_preview)\
            .pack(side="left")
        self.preview_status_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.preview_status_var,
                  style="Dim.TLabel").pack(side="left", padx=12)

        # Scrollable canvas.
        canvas_wrap = ttk.Frame(parent); canvas_wrap.pack(fill="both", expand=True)
        canvas_wrap.rowconfigure(0, weight=1); canvas_wrap.columnconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(
            canvas_wrap, bg=C_PREVIEW_BG, highlightthickness=0,
            xscrollincrement=1, yscrollincrement=1,
        )
        vbar = ttk.Scrollbar(canvas_wrap, orient="vertical",
                             command=self.preview_canvas.yview)
        hbar = ttk.Scrollbar(canvas_wrap, orient="horizontal",
                             command=self.preview_canvas.xview)
        self.preview_canvas.config(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        # Hint text shown until something is selected.
        self._preview_hint_id = self.preview_canvas.create_text(
            300, 200, text="Select an output in the sidebar to preview it.",
            fill=C_TEXT_DIM, font=("", 14), tags=("preview_text",),
        )
        self.preview_canvas.bind("<Configure>", self._on_preview_resize)

        # Mousewheel zoom + pan.
        self.preview_canvas.bind("<MouseWheel>", self._on_preview_wheel)
        self.preview_canvas.bind("<Button-4>", lambda e: self._preview_wheel(1, e))
        self.preview_canvas.bind("<Button-5>", lambda e: self._preview_wheel(-1, e))
        # B1 either drags a crop handle (if one is under the cursor) or pans.
        self.preview_canvas.bind("<ButtonPress-1>", self._on_preview_press)
        self.preview_canvas.bind("<B1-Motion>", self._on_preview_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_preview_release)
        self.preview_canvas.bind("<Motion>", self._on_preview_motion)
        self.preview_canvas.bind("<Leave>", self._on_preview_leave)

        # Default cursor + floating coordinate label (child of canvas so
        # place() coords match event.x/y and canvas.delete("all") leaves it untouched).
        self.preview_canvas.config(cursor="crosshair")
        self._coord_label = tk.Label(
            self.preview_canvas,
            text="",
            bg="#1a1a1a",
            fg="#e8e8e8",
            font=("Courier", 10),
            padx=6,
            pady=3,
            bd=0,
            relief="flat",
        )

    def _set_initial_sashes(self) -> None:
        """Pin the panes to ~12.5% / 50% / 37.5% (sidebar / preview / inspector).

        That makes the sidebar 25% slimmer than the previous 1:3:2 weights
        gave it, freeing space for the preview and inspector.
        """
        try:
            self.update_idletasks()
            w = self._paned.winfo_width()
        except tk.TclError:
            return
        if w <= 50:
            self.after(50, self._set_initial_sashes)
            return
        try:
            self._paned.sashpos(0, int(w * 0.125))
            self._paned.sashpos(1, int(w * 0.625))
        except tk.TclError:
            pass

    def _on_preview_resize(self, event: tk.Event) -> None:
        # Recenter the hint text and re-fit if in fit mode.
        self.preview_canvas.coords("preview_text", event.width // 2, event.height // 2)
        if self._preview_image is not None and self._preview_fit:
            self._blit_preview()

    # -------- inspector swap --------

    def _render_inspector(self) -> None:
        if self._inspector_body is not None:
            self._inspector_body.destroy()
        self._inspector_body = ttk.Frame(self._inspector_root)
        self._inspector_body.pack(fill="both", expand=True)
        body = self._inspector_body

        kind = self._sel_kind
        if kind == "brand":
            self._render_brand_inspector(body)
        elif kind == "shot":
            self._render_output_inspector(body)
        elif kind == "label":
            self._render_output_inspector(body)
        elif kind == "stamp":
            self._render_output_inspector(body)
        else:
            ttk.Label(body, text="Select a brand or output in the sidebar to edit.",
                      style="Dim.TLabel", wraplength=240, justify="left")\
                .pack(padx=12, pady=12, anchor="nw")

    # ===================================================================
    # Inspector — Brand
    # ===================================================================

    def _render_brand_inspector(self, body: ttk.Frame) -> None:
        b = self._sel_brand
        if not b:
            return
        ttk.Label(body, text=f"Brand · {b}", style="Heading.TLabel")\
            .pack(anchor="w", padx=8, pady=(8, 4))

        brand = self.data["brands"][b]

        # --- Background card ---
        card = self._card(body, "Background")
        # color
        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Color (RGBA)", width=12).pack(side="left")
        self.bg_vars = [tk.StringVar() for _ in range(4)]
        bg = (list(brand.get("background_color") or [0, 0, 0, 0]) + [0, 0, 0, 0])[:4]
        for var, val in zip(self.bg_vars, bg):
            var.set(str(int(val)))
            sb = ttk.Spinbox(row, from_=0, to=255, width=4, textvariable=var,
                             command=self._on_brand_field_change)
            sb.pack(side="left", padx=1)
            var.trace_add("write", lambda *_a: self._on_brand_field_change())
        # image
        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Image", width=12).pack(side="left")
        self.bg_image_var = tk.StringVar(value=str(brand.get("background_image") or ""))
        self.bg_image_var.trace_add("write", lambda *_a: self._on_brand_field_change())
        ttk.Entry(row, textvariable=self.bg_image_var)\
            .pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(row, text="…", style="Icon.TButton", width=2,
                   command=self._browse_bg_image).pack(side="left")
        ttk.Button(row, text="✕", style="Icon.TButton", width=2,
                   command=lambda: self.bg_image_var.set("")).pack(side="left", padx=(2, 0))
        # scale
        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Scale", width=12).pack(side="left")
        bg_scale_raw = brand.get("background_scale")
        self.bg_scale_var = tk.StringVar(
            value=str(float(bg_scale_raw)) if bg_scale_raw is not None else "")
        self.bg_scale_var.trace_add("write", lambda *_a: self._on_brand_field_change())
        ttk.Entry(row, textvariable=self.bg_scale_var, width=8).pack(side="left")
        ttk.Label(row, text=" (1.0 = default, >1 zooms in)", style="Dim.TLabel")\
            .pack(side="left", padx=4)

        # --- Phone padding card ---
        card = self._card(body, "Phone padding")
        pad = brand.get("phone_padding") or {}
        self.pad_vars = {}
        for key in ("top", "right", "bottom", "left"):
            row = ttk.Frame(card); row.pack(fill="x", pady=2)
            ttk.Label(row, text=key.capitalize(), width=12).pack(side="left")
            val = pad.get(key) if isinstance(pad, dict) else None
            var = tk.StringVar(value=str(int(val)) if val else "")
            var.trace_add("write", lambda *_a: self._on_brand_field_change())
            ttk.Entry(row, textvariable=var, width=8).pack(side="left")
            self.pad_vars[key] = var
        ttk.Label(card, text="px added around the phone (canvas grows)",
                  style="Dim.TLabel").pack(anchor="w", padx=4, pady=(0, 2))

        # --- Output size card ---
        card = self._card(body, "Output size")
        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="W × H", width=12).pack(side="left")
        out = brand.get("output_size")
        self.out_w_var = tk.StringVar(value=str(int(out[0])) if out else "")
        self.out_h_var = tk.StringVar(value=str(int(out[1])) if out else "")
        for var in (self.out_w_var, self.out_h_var):
            var.trace_add("write", lambda *_a: self._on_brand_field_change())
        ttk.Entry(row, textvariable=self.out_w_var, width=8).pack(side="left")
        ttk.Label(row, text="×").pack(side="left", padx=2)
        ttk.Entry(row, textvariable=self.out_h_var, width=8).pack(side="left")
        ttk.Label(row, text=" (blank = no resize)", style="Dim.TLabel")\
            .pack(side="left", padx=4)

        # --- Quick action ---
        ttk.Button(body, text="＋ Add output", style="Accent.TButton",
                   command=self._add_output).pack(fill="x", padx=8, pady=(8, 4))

    def _on_brand_field_change(self) -> None:
        if self._loading or not self._sel_brand:
            return
        try:
            bg_color = [int(v.get() or "0") for v in self.bg_vars]
        except ValueError:
            bg_color = None
        if bg_color and bg_color == [0, 0, 0, 0]:
            bg_color = None

        bg_image = self.bg_image_var.get().strip() or None

        try:
            bg_scale = float(self.bg_scale_var.get().strip()) if self.bg_scale_var.get().strip() else None
            if bg_scale == 1.0:
                bg_scale = None
        except ValueError:
            bg_scale = None

        phone_padding = {}
        for key, var in self.pad_vars.items():
            try:
                v = int(var.get().strip()) if var.get().strip() else 0
            except ValueError:
                v = 0
            if v > 0:
                phone_padding[key] = v
        if not phone_padding:
            phone_padding = None

        out_w = self.out_w_var.get().strip()
        out_h = self.out_h_var.get().strip()
        try:
            output_size = [int(out_w), int(out_h)] if (out_w and out_h) else None
        except ValueError:
            output_size = None

        try:
            brand_io.update_brand(
                self.data, self._sel_brand,
                background_color=bg_color,
                background_image=bg_image,
                background_scale=bg_scale,
                phone_padding=phone_padding,
                output_size=output_size,
            )
        except KeyError:
            return
        self.on_dirty()
        self._schedule_preview_render()

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
    # Inspector — Output
    # ===================================================================

    def _render_output_inspector(self, body: ttk.Frame) -> None:
        b, i = self._sel_brand, self._sel_shot
        if b is None or i is None:
            return
        shot = brand_io.get_screenshots(self.data, b)[i]

        header = ttk.Frame(body)
        header.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(header, text=f"Output · {shot.get('output') or '(unnamed)'}",
                  style="Heading.TLabel").pack(side="left")
        ttk.Button(header, text="Duplicate",
                   command=lambda: self._duplicate_shot(b, i))\
            .pack(side="right")
        ttk.Label(body, text=f"in brand · {b}", style="Dim.TLabel")\
            .pack(anchor="w", padx=8)

        # --- Identity card ---
        card = self._card(body, "Identity")

        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Phone", width=8).pack(side="left")
        self.phone_var = tk.StringVar(value=str(shot.get("phone") or ""))
        self.phone_combo = ttk.Combobox(row, textvariable=self.phone_var,
                                        values=self._phone_names(), state="readonly",
                                        width=22)
        self.phone_combo.pack(side="left", fill="x", expand=True)
        self.phone_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self._on_output_field_change())

        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="File", width=8).pack(side="left")
        self.shot_output_var = tk.StringVar(value=str(shot.get("output") or ""))
        self.shot_output_var.trace_add(
            "write", lambda *_a: self._on_output_field_change())
        ttk.Entry(row, textvariable=self.shot_output_var)\
            .pack(side="left", fill="x", expand=True)

        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Source", width=8).pack(side="left")
        self.shot_source_var = tk.StringVar(value=str(shot.get("source") or ""))
        self.shot_source_var.trace_add(
            "write", lambda *_a: self._on_output_field_change())
        ttk.Entry(row, textvariable=self.shot_source_var)\
            .pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(row, text="…", style="Icon.TButton", width=2,
                   command=self._browse_shot_source).pack(side="left")

        # --- BG transform card ---
        self._build_bg_transform_card(body, shot)

        # --- Output transform card ---
        self._build_transform_card(body, shot)

        # --- Quick add buttons ---
        actions = ttk.Frame(body); actions.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(actions, text="＋ Label", command=self._add_label).pack(side="left")
        self.label_paste_btn = ttk.Button(
            actions, text="📥", width=2, command=self._paste_label_into_current,
        )
        self.label_paste_btn.pack(side="left", padx=(2, 4))
        attach_tooltip(self.label_paste_btn, "Paste label from clipboard")
        ttk.Button(actions, text="＋ Stamp", command=self._add_stamp)\
            .pack(side="left")
        self.stamp_paste_btn = ttk.Button(
            actions, text="📥", width=2, command=self._paste_stamp_into_current,
        )
        self.stamp_paste_btn.pack(side="left", padx=(2, 4))
        attach_tooltip(self.stamp_paste_btn, "Paste stamp from clipboard")
        self._refresh_paste_state()

        # --- Compact lists with counts (selecting jumps to that node) ---
        labels = brand_io.get_labels(self.data, b, i)
        stamps = brand_io.get_stamps(self.data, b, i)

        ttk.Label(body, text=f"Labels · {len(labels)}", style="Section.TLabel")\
            .pack(anchor="w", padx=8, pady=(8, 0))
        if not labels:
            ttk.Label(body, text="  (none)", style="Dim.TLabel")\
                .pack(anchor="w", padx=8)
        for j, lbl in enumerate(labels):
            row = ttk.Frame(body); row.pack(fill="x", padx=8, pady=1)
            txt = (str(lbl.get("text") or "")[:28]) or "—"
            btn = ttk.Button(row, text=f"  {j+1}. {txt}",
                             command=lambda j=j: self._open_label_dialog(b, i, j))
            btn.pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="🗑", style="Icon.TButton", width=2,
                       command=lambda j=j: self._delete_label_at(j))\
                .pack(side="left", padx=(2, 0))

        ttk.Label(body, text=f"Stamps · {len(stamps)}", style="Section.TLabel")\
            .pack(anchor="w", padx=8, pady=(8, 0))
        if not stamps:
            ttk.Label(body, text="  (none)", style="Dim.TLabel")\
                .pack(anchor="w", padx=8)
        for j, st in enumerate(stamps):
            row = ttk.Frame(body); row.pack(fill="x", padx=8, pady=1)
            src = Path(str(st.get("source") or "")).name or "—"
            btn = ttk.Button(row, text=f"  {j+1}. {src}",
                             command=lambda j=j: self._open_stamp_dialog(b, i, j))
            btn.pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="🗑", style="Icon.TButton", width=2,
                       command=lambda j=j: self._delete_stamp_at(j))\
                .pack(side="left", padx=(2, 0))

    # -------- Output transform (crop + resize) --------

    # -------- BG transform (per-output background-image vertical crop) --------

    def _brand_bg_dimensions(self) -> tuple[int, int] | None:
        """Read the current brand's background_image file size (w, h), or None."""
        if not self._sel_brand:
            return None
        brand = (self.data.get("brands") or {}).get(self._sel_brand)
        if not brand:
            return None
        bg_rel = brand.get("background_image")
        if not bg_rel:
            return None
        bg_path = self.assets_dir / str(bg_rel)
        if not bg_path.is_file():
            return None
        try:
            with Image.open(bg_path) as im:
                return (im.width, im.height)
        except Exception:
            return None


    def _build_bg_transform_card(self, body: ttk.Frame, shot: Any) -> None:
        bg_dims = self._brand_bg_dimensions()
        if bg_dims:
            title = f"BG transform · offset into the {bg_dims[0]}×{bg_dims[1]} background"
        else:
            title = "BG transform · (no background image set on brand)"
        card = self._card(body, title)

        bg_off = shot.get("background_offset") or {}
        top = int(bg_off.get("top") or 0) if isinstance(bg_off, dict) else 0
        left = int(bg_off.get("left") or 0) if isinstance(bg_off, dict) else 0

        prev_loading, self._loading = self._loading, True
        try:
            self.bg_top_var = tk.StringVar(value=str(top) if top else "")
            self.bg_left_var = tk.StringVar(value=str(left) if left else "")
        finally:
            self._loading = prev_loading

        grid = ttk.Frame(card); grid.pack(anchor="w", pady=2)
        ttk.Label(grid, text="From top:", width=10, anchor="w")\
            .grid(row=0, column=0, sticky="w", pady=1)
        ttk.Entry(grid, textvariable=self.bg_top_var, width=8)\
            .grid(row=0, column=1, sticky="w", padx=(2, 14), pady=1)
        ttk.Label(grid, text="From left:", width=10, anchor="w")\
            .grid(row=0, column=2, sticky="w", pady=1)
        ttk.Entry(grid, textvariable=self.bg_left_var, width=8)\
            .grid(row=0, column=3, sticky="w", padx=(2, 14), pady=1)

        ttk.Label(card,
                  text="(left, top) point of the bg that lands at the canvas "
                       "top-left. No scaling. Blank = use the full image.",
                  style="Dim.TLabel", wraplength=420)\
            .pack(anchor="w", pady=(2, 0))

        for var in (self.bg_top_var, self.bg_left_var):
            var.trace_add("write", lambda *_a: self._on_bg_offset_change())

    def _on_bg_offset_change(self) -> None:
        if self._loading or self._sel_brand is None or self._sel_shot is None:
            return

        def parse(s: str) -> int:
            s = s.strip()
            if not s:
                return 0
            try:
                return max(0, int(s))
            except ValueError:
                return 0

        top = parse(self.bg_top_var.get())
        left = parse(self.bg_left_var.get())
        try:
            brand_io.update_bg_offset(
                self.data, self._sel_brand, self._sel_shot,
                top=top, left=left,
            )
        except Exception:
            return
        self.on_dirty()
        # BG transform DOES affect the rendered composite, so re-render.
        self._schedule_preview_render()

    def _build_transform_card(self, body: ttk.Frame, shot: Any) -> None:
        card = self._card(body, "Output transform (applied at Generate)")

        pp = shot.get("post_process") or {}
        crop = pp.get("crop") if isinstance(pp, dict) else None
        crop_mode = "none"
        crop_values: list[int] = []
        if isinstance(crop, dict):
            for key in ("margins", "box", "center"):
                if key in crop:
                    crop_mode = key
                    crop_values = [int(v) for v in (crop[key] or [])]
                    break
        elif isinstance(crop, (list, tuple)):
            crop_mode = "box"
            crop_values = [int(v) for v in crop]

        rz = pp.get("resize") if isinstance(pp, dict) else None
        rz_w = ""
        rz_h = ""
        if isinstance(rz, dict):
            rz_w = str(int(rz["width"])) if rz.get("width") else ""
            rz_h = str(int(rz["height"])) if rz.get("height") else ""
        elif isinstance(rz, (list, tuple)) and len(rz) == 2:
            rz_w, rz_h = str(int(rz[0])), str(int(rz[1]))

        # Suppress trace-fires while we wire StringVars and set initial values.
        prev_loading, self._loading = self._loading, True
        try:
            self.crop_mode_var = tk.StringVar(value=crop_mode)
            # 7 crop fields. l/t/r/b are canonical for box+margins; w/h are
            # canonical for center; aspect is always derived/editable.
            self.crop_l_var = tk.StringVar()
            self.crop_t_var = tk.StringVar()
            self.crop_r_var = tk.StringVar()
            self.crop_b_var = tk.StringVar()
            self.crop_w_var = tk.StringVar()
            self.crop_h_var = tk.StringVar()
            self.crop_a_var = tk.StringVar()
            if not hasattr(self, "aspect_locked_var"):
                self.aspect_locked_var = tk.BooleanVar(value=False)
            self.resize_w_var = tk.StringVar(value=rz_w)
            self.resize_h_var = tk.StringVar(value=rz_h)
            self._populate_crop_vars_from_saved(crop_mode, crop_values)
        finally:
            self._loading = prev_loading
        self._suppress_crop_sync = False

        # ---- Crop ----
        # Header row: [Crop ▾]  <hint text>
        header = ttk.Frame(card); header.pack(fill="x", pady=2)
        ttk.Label(header, text="Crop", width=6).pack(side="left")
        self.crop_combo = ttk.Combobox(
            header, textvariable=self.crop_mode_var, state="readonly",
            values=["none", "margins", "box", "center"], width=10,
        )
        self.crop_combo.pack(side="left", padx=(2, 6))
        self.crop_combo.bind("<<ComboboxSelected>>",
                             lambda _e: self._on_crop_mode_change())
        self.crop_hint_var = tk.StringVar()
        ttk.Label(header, textvariable=self.crop_hint_var, style="Dim.TLabel")\
            .pack(side="left")
        # Copy/Paste of all numbers in this card (box mode only).
        self.crop_copy_btn = ttk.Button(
            header, text="📋", width=2, command=self._copy_transform,
        )
        self.crop_paste_btn = ttk.Button(
            header, text="📥", width=2, command=self._paste_transform,
        )
        self.crop_copy_btn.pack(side="right", padx=(2, 0))
        self.crop_paste_btn.pack(side="right", padx=(2, 0))
        attach_tooltip(self.crop_copy_btn, "Copy transform")
        attach_tooltip(self.crop_paste_btn, "Paste transform")
        self._refresh_paste_state()

        # Fields grid — 2 columns, left-aligned, name-keyed for show/hide.
        fields = ttk.Frame(card); fields.pack(anchor="w", pady=(2, 0))
        self.crop_field_rows: dict[str, tuple[ttk.Label, ttk.Entry]] = {}

        def add_field(name: str, label: str, var: tk.StringVar,
                      row: int, col: int, width: int = 8) -> None:
            lbl = ttk.Label(fields, text=label, width=8, anchor="w")
            ent = ttk.Entry(fields, textvariable=var, width=width)
            lbl.grid(row=row, column=col * 2, sticky="w", pady=1)
            ent.grid(row=row, column=col * 2 + 1, sticky="w", padx=(2, 14), pady=1)
            self.crop_field_rows[name] = (lbl, ent)

        add_field("l", "Left:",   self.crop_l_var, 0, 0)
        add_field("t", "Top:",    self.crop_t_var, 0, 1)
        add_field("r", "Right:",  self.crop_r_var, 1, 0)
        add_field("b", "Bottom:", self.crop_b_var, 1, 1)
        add_field("w", "Width:",  self.crop_w_var, 2, 0)
        add_field("h", "Height:", self.crop_h_var, 2, 1)
        add_field("a", "Aspect:", self.crop_a_var, 3, 0, width=10)
        self.aspect_lock_btn = ttk.Checkbutton(
            fields, text="Lock", variable=self.aspect_locked_var,
        )
        self.aspect_lock_btn.grid(row=3, column=2, sticky="w", padx=(2, 0))

        self._apply_crop_mode_layout()

        # Resize row, also a grid: [Resize] W:[__] H:[__]
        rgrid = ttk.Frame(card); rgrid.pack(fill="x", pady=2)
        ttk.Label(rgrid, text="Resize", width=6).grid(row=0, column=0, sticky="w")
        ttk.Label(rgrid, text="W").grid(row=0, column=1, padx=(2, 0))
        ttk.Entry(rgrid, textvariable=self.resize_w_var, width=6)\
            .grid(row=0, column=2, padx=(2, 8))
        ttk.Label(rgrid, text="H").grid(row=0, column=3)
        ttk.Entry(rgrid, textvariable=self.resize_h_var, width=6)\
            .grid(row=0, column=4, padx=2)
        ttk.Label(rgrid, text="(blank = no resize)", style="Dim.TLabel")\
            .grid(row=0, column=5, padx=6, sticky="w")

        # Wire change traces. Mode change has its own handler. Each crop
        # field routes through _on_crop_field_changed so we can keep all
        # seven fields in sync. Resize fields just write directly.
        self.crop_mode_var.trace_add("write",
                                     lambda *_a: self._on_transform_field_change())
        for name, var in (
            ("l", self.crop_l_var), ("t", self.crop_t_var),
            ("r", self.crop_r_var), ("b", self.crop_b_var),
            ("w", self.crop_w_var), ("h", self.crop_h_var),
            ("a", self.crop_a_var),
        ):
            var.trace_add("write",
                          lambda *_a, n=name: self._on_crop_field_changed(n))
        for v in (self.resize_w_var, self.resize_h_var):
            v.trace_add("write", lambda *_a: self._on_transform_field_change())

    # ---- crop layout / sync ----

    _CROP_VISIBLE = {
        "none":    set(),
        "margins": {"l", "t", "r", "b", "w", "h", "a"},
        "box":     {"l", "t", "r", "b", "w", "h", "a"},
        "center":  {"w", "h", "a"},
    }
    _CROP_HINT = {
        "none":    "",
        "margins": "px to trim from each edge",
        "box":     "rectangle to keep",
        "center":  "size of the centered crop",
    }

    def _apply_crop_mode_layout(self) -> None:
        """Show/hide each named field row based on the current crop mode."""
        mode = self.crop_mode_var.get()
        visible = self._CROP_VISIBLE.get(mode, set())
        for name, (lbl, ent) in self.crop_field_rows.items():
            if name in visible:
                lbl.grid(); ent.grid()
            else:
                lbl.grid_remove(); ent.grid_remove()
        if hasattr(self, "aspect_lock_btn"):
            if "a" in visible:
                self.aspect_lock_btn.grid()
            else:
                self.aspect_lock_btn.grid_remove()
        # Re-pack in fixed order: Copy on the far right, Paste to its left.
        for btn_attr in ("crop_copy_btn", "crop_paste_btn"):
            btn = getattr(self, btn_attr, None)
            if btn is not None:
                btn.pack_forget()
                if mode == "box":
                    btn.pack(side="right", padx=(2, 0))
        if hasattr(self, "crop_hint_var"):
            hint = self._CROP_HINT.get(mode, "")
            self.crop_hint_var.set(f"  · {hint}" if hint else "")

    def _populate_crop_vars_from_saved(self, mode: str, saved: list[int]) -> None:
        """Initialize the 7 crop StringVars from YAML-loaded values + mode."""
        # Default canonical state.
        if self._preview_image is not None:
            iw, ih = self._preview_image.size
        else:
            iw, ih = 1920, 1080
        if mode in ("margins", "box") and len(saved) == 4:
            if mode == "margins":
                ml, mt, mr, mb = saved
                l, t, r, b = ml, mt, max(ml + 1, iw - mr), max(mt + 1, ih - mb)
                self.crop_l_var.set(str(ml))
                self.crop_t_var.set(str(mt))
                self.crop_r_var.set(str(mr))
                self.crop_b_var.set(str(mb))
            else:
                l, t, r, b = saved
                self.crop_l_var.set(str(l))
                self.crop_t_var.set(str(t))
                self.crop_r_var.set(str(r))
                self.crop_b_var.set(str(b))
            w, h = max(1, r - l), max(1, b - t)
            self.crop_w_var.set(str(w))
            self.crop_h_var.set(str(h))
            self.crop_a_var.set(self._format_aspect(w, h))
        elif mode == "center" and len(saved) == 2:
            w, h = saved
            self.crop_w_var.set(str(w))
            self.crop_h_var.set(str(h))
            self.crop_a_var.set(self._format_aspect(w, h))

    def _on_crop_field_changed(self, source: str) -> None:
        if self._loading or self._suppress_crop_sync:
            return
        if self._sel_brand is None or self._sel_shot is None:
            return
        self._suppress_crop_sync = True
        try:
            self._sync_crop_fields(source)
        finally:
            self._suppress_crop_sync = False
        # After all fields are in sync, write the new values to YAML.
        self._on_transform_field_change()

    def _sync_crop_fields(self, source: str) -> None:
        """Recompute every crop field from the user-edited one (`source`)."""
        mode = self.crop_mode_var.get()
        if mode == "none":
            return

        if self._preview_image is not None:
            iw, ih = self._preview_image.size
        else:
            iw, ih = 1920, 1080

        def read(var: tk.StringVar, default: int = 0) -> int:
            s = var.get().strip()
            if not s:
                return default
            try:
                return int(s)
            except ValueError:
                return default

        # Compute canonical (l, t, r, b) absolute pixel rect.
        if mode == "margins":
            ml = read(self.crop_l_var, 0)
            mt = read(self.crop_t_var, 0)
            mr = read(self.crop_r_var, 0)
            mb = read(self.crop_b_var, 0)
            l, t, r, b = ml, mt, iw - mr, ih - mb
        elif mode == "box":
            l = read(self.crop_l_var, 0)
            t = read(self.crop_t_var, 0)
            r = read(self.crop_r_var, iw)
            b = read(self.crop_b_var, ih)
        else:  # center
            w0 = read(self.crop_w_var, iw)
            h0 = read(self.crop_h_var, ih)
            l = (iw - w0) // 2; r = l + max(1, w0)
            t = (ih - h0) // 2; b = t + max(1, h0)

        # Apply the user's edit (l/t/r/b are already reflected for margins/box).
        if source == "w":
            new_w = max(1, read(self.crop_w_var, max(1, r - l)))
            if mode == "center":
                cx = (l + r) // 2
                l = cx - new_w // 2; r = l + new_w
            else:
                r = l + new_w
        elif source == "h":
            new_h = max(1, read(self.crop_h_var, max(1, b - t)))
            if mode == "center":
                cy = (t + b) // 2
                t = cy - new_h // 2; b = t + new_h
            else:
                b = t + new_h
        elif source == "a":
            ratio = self._parse_aspect(self.crop_a_var.get())
            if ratio is not None and ratio > 0:
                # Width-led: keep current width and derive height.
                new_w = max(1, r - l)
                new_h = max(1, int(round(new_w / ratio)))
                # If height overflows the image, constrain by height instead.
                if new_h > ih:
                    new_h = ih
                    new_w = max(1, int(round(ih * ratio)))
                # If width now overflows too, constrain by width.
                if new_w > iw:
                    new_w = iw
                    new_h = max(1, int(round(iw / ratio)))
                if mode == "center":
                    cx = (l + r) // 2
                    cy = (t + b) // 2
                    l = cx - new_w // 2; r = l + new_w
                    t = cy - new_h // 2; b = t + new_h
                else:
                    r = l + new_w
                    b = t + new_h

        # Clamp to image bounds.
        l = max(0, min(iw - 1, l))
        t = max(0, min(ih - 1, t))
        r = max(l + 1, min(iw, r))
        b = max(t + 1, min(ih, b))
        new_w = r - l
        new_h = b - t

        # Aspect lock: if engaged, force the box to match the locked ratio.
        # Width leads when the user touched a width-affecting field; height
        # leads otherwise. When the user edits 'a' itself, that becomes the
        # new locked ratio.
        if (getattr(self, "aspect_locked_var", None) is not None
                and self.aspect_locked_var.get()):
            ratio = self._parse_aspect(self.crop_a_var.get())
            if ratio and ratio > 0:
                width_leads = source in ("w", "l", "r", "a")
                if width_leads:
                    forced_h = max(1, int(round(new_w / ratio)))
                    if mode == "center":
                        cy = (t + b) // 2
                        t = max(0, cy - forced_h // 2)
                        b = min(ih, t + forced_h); t = max(0, b - forced_h)
                    else:
                        b = min(ih, t + forced_h)
                        t = max(0, b - forced_h)
                else:
                    forced_w = max(1, int(round(new_h * ratio)))
                    if mode == "center":
                        cx = (l + r) // 2
                        l = max(0, cx - forced_w // 2)
                        r = min(iw, l + forced_w); l = max(0, r - forced_w)
                    else:
                        r = min(iw, l + forced_w)
                        l = max(0, r - forced_w)
                new_w = r - l
                new_h = b - t

        # Build the desired writeback values, then push to every field
        # except the one the user is actively editing — that one leads.
        if mode == "margins":
            to_write: dict[str, str] = {
                "l": str(l), "t": str(t),
                "r": str(iw - r), "b": str(ih - b),
            }
        elif mode == "box":
            to_write = {"l": str(l), "t": str(t), "r": str(r), "b": str(b)}
        else:
            to_write = {}
        to_write["w"] = str(new_w)
        to_write["h"] = str(new_h)
        to_write["a"] = self._format_aspect(new_w, new_h)

        vars_by_name = {
            "l": self.crop_l_var, "t": self.crop_t_var,
            "r": self.crop_r_var, "b": self.crop_b_var,
            "w": self.crop_w_var, "h": self.crop_h_var,
            "a": self.crop_a_var,
        }
        for name, value in to_write.items():
            if name == source:
                continue  # leave the field with the cursor alone
            var = vars_by_name[name]
            if var.get() != value:
                var.set(value)

    @staticmethod
    def _parse_aspect(s: str) -> float | None:
        """Parse '16:9', '1.778', etc. Returns w/h ratio, or None if invalid."""
        s = s.strip()
        if not s:
            return None
        if ":" in s:
            parts = s.split(":")
            if len(parts) != 2:
                return None
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                return None
            return (x / y) if y > 0 else None
        try:
            v = float(s)
        except ValueError:
            return None
        return v if v > 0 else None

    @staticmethod
    def _format_aspect(w: int, h: int) -> str:
        if w <= 0 or h <= 0:
            return ""
        from math import gcd
        g = gcd(int(w), int(h))
        a, b = int(w) // g, int(h) // g
        # Prefer a clean ratio when it's compact; otherwise fall back to
        # the decimal so we don't show "1921:1080".
        if a <= 99 and b <= 99:
            return f"{a}:{b}"
        return f"{w / h:.3f}"

    def _on_crop_mode_change(self) -> None:
        self._apply_crop_mode_layout()
        # If switching to a real crop mode and the user has no values yet,
        # populate sensible defaults derived from the preview image size.
        new_mode = self.crop_mode_var.get()
        if new_mode != "none":
            self._populate_default_crop_values(new_mode)
        self._on_transform_field_change()

    def _populate_default_crop_values(self, mode: str) -> None:
        """Fill crop fields with sensible defaults if they're empty/zero."""
        def read(var: tk.StringVar) -> int:
            try:
                return int(var.get().strip() or "0")
            except ValueError:
                return 0
        if mode in ("margins", "box"):
            existing = [read(v) for v in
                        (self.crop_l_var, self.crop_t_var,
                         self.crop_r_var, self.crop_b_var)]
        else:  # center
            existing = [read(self.crop_w_var), read(self.crop_h_var)]
        if any(v != 0 for v in existing):
            return  # user already has something — leave it alone

        if self._preview_image is not None:
            iw, ih = self._preview_image.size
        else:
            iw, ih = 1920, 1080

        prev_loading, self._loading = self._loading, True
        try:
            if mode == "margins":
                m = max(20, min(iw, ih) // 20)
                self.crop_l_var.set(str(m))
                self.crop_t_var.set(str(m))
                self.crop_r_var.set(str(m))
                self.crop_b_var.set(str(m))
                w, h = iw - 2 * m, ih - 2 * m
            elif mode == "box":
                l, t = iw // 10, ih // 10
                r, b = iw - l, ih - t
                self.crop_l_var.set(str(l))
                self.crop_t_var.set(str(t))
                self.crop_r_var.set(str(r))
                self.crop_b_var.set(str(b))
                w, h = r - l, b - t
            elif mode == "center":
                w, h = int(iw * 0.8), int(ih * 0.8)
                self.crop_w_var.set(str(w))
                self.crop_h_var.set(str(h))
            else:
                return
            # Always populate derived fields so they're never blank.
            if mode in ("margins", "box"):
                self.crop_w_var.set(str(w))
                self.crop_h_var.set(str(h))
            self.crop_a_var.set(self._format_aspect(w, h))
        finally:
            self._loading = prev_loading

    def _clipboard_has_transform(self) -> bool:
        """Return True if the clipboard looks like something paste can use."""
        try:
            raw = (self.clipboard_get() or "").strip()
        except tk.TclError:
            return False
        if not raw:
            return False
        import json
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and ("box" in data or "resize" in data):
                return True
        except (ValueError, TypeError):
            pass
        # Bare CSV fallback: needs at least 4 ints.
        head = raw.split("|", 1)[0]
        try:
            nums = [int(x.strip()) for x in head.split(",")]
            return len(nums) == 4
        except ValueError:
            return False

    def _refresh_paste_state(self) -> None:
        """Enable/disable known paste buttons based on clipboard contents.
        Re-runs every ~700ms while at least one paste button still exists."""
        alive = False
        # Transform paste button.
        btn = getattr(self, "crop_paste_btn", None)
        if btn is not None:
            try:
                if btn.winfo_exists():
                    btn.state(["!disabled"] if self._clipboard_has_transform()
                              else ["disabled"])
                    alive = True
                else:
                    self.crop_paste_btn = None  # type: ignore[assignment]
            except tk.TclError:
                self.crop_paste_btn = None  # type: ignore[assignment]
        # Label/stamp paste buttons.
        kind = self._clipboard_kind()
        for attr, want in (("label_paste_btn", "ssb-label"),
                           ("stamp_paste_btn", "ssb-stamp")):
            pb = getattr(self, attr, None)
            if pb is None:
                continue
            try:
                if pb.winfo_exists():
                    pb.state(["!disabled"] if kind == want else ["disabled"])
                    alive = True
                else:
                    setattr(self, attr, None)
            except tk.TclError:
                setattr(self, attr, None)
        if alive:
            self.after(700, self._refresh_paste_state)

    def _copy_transform(self) -> None:
        """Copy box-mode crop + resize values to the clipboard as JSON."""
        def read(var: tk.StringVar) -> int | None:
            s = var.get().strip()
            if not s:
                return None
            try:
                return int(s)
            except ValueError:
                return None
        payload: dict[str, Any] = {}
        box = [read(v) for v in (self.crop_l_var, self.crop_t_var,
                                 self.crop_r_var, self.crop_b_var)]
        if all(v is not None for v in box):
            payload["box"] = box
        rw, rh = read(self.resize_w_var), read(self.resize_h_var)
        if rw is not None or rh is not None:
            payload["resize"] = [rw, rh]
        if not payload:
            return
        import json
        text = json.dumps(payload, separators=(",", ":"))
        self.clipboard_clear()
        self.clipboard_append(text)
        self._refresh_paste_state()

    def _paste_transform(self) -> None:
        """Read clipboard, parse, and populate box-mode + resize fields."""
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            return
        raw = (raw or "").strip()
        if not raw:
            return
        import json
        box: list[int] | None = None
        resize: list[int | None] | None = None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            b = data.get("box")
            if isinstance(b, (list, tuple)) and len(b) == 4:
                try:
                    box = [int(x) for x in b]
                except (TypeError, ValueError):
                    box = None
            r = data.get("resize")
            if isinstance(r, (list, tuple)) and len(r) == 2:
                resize = [int(x) if x not in (None, "", "null") else None
                          for x in r]
        else:
            # Fallback: bare CSV "l,t,r,b" or "l,t,r,b|w,h"
            parts = raw.split("|", 1)
            try:
                nums = [int(x.strip()) for x in parts[0].split(",")]
                if len(nums) == 4:
                    box = nums
            except ValueError:
                box = None
            if len(parts) == 2:
                try:
                    rn = [int(x.strip()) for x in parts[1].split(",")]
                    if len(rn) == 2:
                        resize = [rn[0] or None, rn[1] or None]
                except ValueError:
                    resize = None
        if box is None and resize is None:
            return

        prev_loading, self._loading = self._loading, True
        try:
            if box is not None:
                self.crop_mode_var.set("box")
                self._apply_crop_mode_layout()
                l, t, r, b_ = box
                self.crop_l_var.set(str(l))
                self.crop_t_var.set(str(t))
                self.crop_r_var.set(str(r))
                self.crop_b_var.set(str(b_))
                w, h = max(1, r - l), max(1, b_ - t)
                self.crop_w_var.set(str(w))
                self.crop_h_var.set(str(h))
                self.crop_a_var.set(self._format_aspect(w, h))
            if resize is not None:
                self.resize_w_var.set(str(resize[0]) if resize[0] else "")
                self.resize_h_var.set(str(resize[1]) if resize[1] else "")
        finally:
            self._loading = prev_loading
        # Now persist.
        self._on_transform_field_change()
        self._draw_crop_overlay()

    # ---------- label / stamp clipboard ----------------------------------

    @staticmethod
    def _to_plain(obj: Any) -> Any:
        """Convert ruamel CommentedMap/Seq (and nested) to plain dict/list."""
        if isinstance(obj, dict):
            return {str(k): BrandsTab._to_plain(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [BrandsTab._to_plain(v) for v in obj]
        return obj

    @staticmethod
    def _to_commented(obj: Any) -> Any:
        """Convert plain JSON dict/list into ruamel CommentedMap/Seq for YAML."""
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
        if isinstance(obj, dict):
            m = CommentedMap()
            for k, v in obj.items():
                m[k] = BrandsTab._to_commented(v)
            return m
        if isinstance(obj, list):
            s = CommentedSeq()
            for v in obj:
                s.append(BrandsTab._to_commented(v))
            return s
        return obj

    def _clipboard_kind(self) -> str | None:
        """Return the 'kind' marker from a JSON clipboard payload, or None."""
        import json
        try:
            raw = (self.clipboard_get() or "").strip()
        except tk.TclError:
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if (isinstance(data, dict)
                and isinstance(data.get("kind"), str)
                and isinstance(data.get("data"), dict)):
            return data["kind"]
        return None

    def _read_clipboard_payload(self, want_kind: str) -> dict | None:
        import json
        try:
            raw = (self.clipboard_get() or "").strip()
        except tk.TclError:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if (isinstance(data, dict) and data.get("kind") == want_kind
                and isinstance(data.get("data"), dict)):
            return data["data"]
        return None

    def _put_on_clipboard(self, kind: str, obj: Any) -> None:
        import json
        payload = {"kind": kind, "data": self._to_plain(obj)}
        self.clipboard_clear()
        self.clipboard_append(json.dumps(payload, separators=(",", ":")))
        self._refresh_paste_state()

    def _copy_label(self) -> None:
        if (self._sel_brand is None or self._sel_shot is None
                or self._sel_label is None):
            return
        labels = brand_io.get_labels(self.data, self._sel_brand, self._sel_shot)
        if 0 <= self._sel_label < len(labels):
            self._put_on_clipboard("ssb-label", labels[self._sel_label])

    def _copy_stamp(self) -> None:
        if (self._sel_brand is None or self._sel_shot is None
                or self._sel_stamp is None):
            return
        stamps = brand_io.get_stamps(self.data, self._sel_brand, self._sel_shot)
        if 0 <= self._sel_stamp < len(stamps):
            self._put_on_clipboard("ssb-stamp", stamps[self._sel_stamp])

    def _paste_label_into_current(self) -> None:
        if self._sel_brand is None or self._sel_shot is None:
            return
        payload = self._read_clipboard_payload("ssb-label")
        if payload is None:
            return
        labels = brand_io.get_labels(self.data, self._sel_brand, self._sel_shot)
        labels.append(self._to_commented(payload))
        self.on_dirty()
        self._refresh_tree()
        self._select(nid_label(self._sel_brand, self._sel_shot, len(labels) - 1))

    def _paste_stamp_into_current(self) -> None:
        if self._sel_brand is None or self._sel_shot is None:
            return
        payload = self._read_clipboard_payload("ssb-stamp")
        if payload is None:
            return
        stamps = brand_io.get_stamps(self.data, self._sel_brand, self._sel_shot)
        stamps.append(self._to_commented(payload))
        self.on_dirty()
        self._refresh_tree()
        self._select(nid_stamp(self._sel_brand, self._sel_shot, len(stamps) - 1))

    def _on_transform_field_change(self) -> None:
        if self._loading or self._sel_brand is None or self._sel_shot is None:
            return
        # Crop — read canonical fields based on mode.
        mode = self.crop_mode_var.get()
        crop_values: list[int] | None
        if mode == "none":
            crop_values = None
        elif mode in ("margins", "box"):
            try:
                crop_values = [
                    int(self.crop_l_var.get() or "0"),
                    int(self.crop_t_var.get() or "0"),
                    int(self.crop_r_var.get() or "0"),
                    int(self.crop_b_var.get() or "0"),
                ]
            except ValueError:
                crop_values = None
        elif mode == "center":
            try:
                crop_values = [
                    int(self.crop_w_var.get() or "0"),
                    int(self.crop_h_var.get() or "0"),
                ]
            except ValueError:
                crop_values = None
        else:
            crop_values = None
        # Resize
        try:
            rw = int(self.resize_w_var.get()) if self.resize_w_var.get().strip() else None
        except ValueError:
            rw = None
        try:
            rh = int(self.resize_h_var.get()) if self.resize_h_var.get().strip() else None
        except ValueError:
            rh = None

        try:
            brand_io.update_post_process(
                self.data, self._sel_brand, self._sel_shot,
                crop_mode=mode,
                crop_values=crop_values,
                resize_width=rw if rw is not None else 0,
                resize_height=rh if rh is not None else 0,
            )
        except Exception:
            return
        self.on_dirty()
        # Crop/resize don't drive a live composite re-render — just refresh
        # the dotted overlay so the user sees where the crop will land.
        self._draw_crop_overlay()

    def _on_output_field_change(self) -> None:
        if self._loading or self._sel_brand is None or self._sel_shot is None:
            return
        brand_io.update_screenshot(
            self.data, self._sel_brand, self._sel_shot,
            source=self.shot_source_var.get().strip(),
            output=self.shot_output_var.get().strip(),
            phone=self.phone_var.get().strip() or None,
        )
        self.on_dirty()
        self._refresh_tree(restore=True)
        self._schedule_preview_render()

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
    # Inspector — Label
    # ===================================================================

    def _render_label_inspector(self, body: ttk.Frame) -> None:
        b, i, j = self._sel_brand, self._sel_shot, self._sel_label
        labels = brand_io.get_labels(self.data, b, i)
        if not (0 <= j < len(labels)):
            return
        lbl = labels[j]
        header = ttk.Frame(body)
        header.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(header, text="Label", style="Heading.TLabel").pack(side="left")
        copy_btn = ttk.Button(header, text="📋", width=2, command=self._copy_label)
        copy_btn.pack(side="right", padx=(2, 0))
        attach_tooltip(copy_btn, "Copy label to clipboard")
        dup_btn = ttk.Button(header, text="⎘", width=2,
                             command=self._duplicate_selected)
        dup_btn.pack(side="right", padx=(2, 0))
        attach_tooltip(dup_btn, "Duplicate label in this output")
        ttk.Label(body, text=f"in {b} / {brand_io.get_screenshots(self.data, b)[i].get('output') or 'output'}",
                  style="Dim.TLabel").pack(anchor="w", padx=8, pady=(0, 4))

        # Text card
        card = self._card(body, "Text")
        self.label_text_var = tk.StringVar(value=str(lbl.get("text") or ""))
        self.label_text_var.trace_add("write", lambda *_a: self._on_label_field_change())
        ttk.Entry(card, textvariable=self.label_text_var).pack(fill="x", pady=2)

        # Position + size + color card
        card = self._card(body, "Layout & Style")

        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="X, Y", width=8).pack(side="left")
        pos = lbl.get("position") or [0, 0]
        self.label_x_var = tk.StringVar(value=str(int(pos[0])))
        self.label_y_var = tk.StringVar(value=str(int(pos[1])))
        for v in (self.label_x_var, self.label_y_var):
            v.trace_add("write", lambda *_a: self._on_label_field_change())
        ttk.Entry(row, textvariable=self.label_x_var, width=8).pack(side="left", padx=1)
        ttk.Entry(row, textvariable=self.label_y_var, width=8).pack(side="left", padx=1)

        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Size", width=8).pack(side="left")
        self.label_size_var = tk.StringVar(value=str(int(lbl.get("font_size") or 48)))
        self.label_size_var.trace_add("write",
                                      lambda *_a: self._on_label_field_change())
        ttk.Entry(row, textvariable=self.label_size_var, width=8).pack(side="left", padx=1)
        ttk.Label(row, text="Color", width=6).pack(side="left", padx=(8, 0))
        self.label_color_var = tk.StringVar(value=str(lbl.get("color") or ""))
        self.label_color_var.trace_add("write",
                                       lambda *_a: self._on_label_field_change())
        ttk.Entry(row, textvariable=self.label_color_var, width=10).pack(side="left", padx=1)

        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Anchor", width=8).pack(side="left")
        self.label_anchor_var = tk.StringVar(value=str(lbl.get("anchor") or ""))
        self.label_anchor_combo = ttk.Combobox(
            row, textvariable=self.label_anchor_var, state="readonly",
            values=["", "lt", "lm", "lb", "mt", "mm", "mb", "rt", "rm", "rb"],
            width=6,
        )
        self.label_anchor_combo.pack(side="left", padx=1)
        self.label_anchor_combo.bind("<<ComboboxSelected>>",
                                     lambda _e: self._on_label_field_change())
        ttk.Label(row, text="(blank = top-left)", style="Dim.TLabel")\
            .pack(side="left", padx=4)

        # Row of actions
        actions = ttk.Frame(body); actions.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(actions, text="Delete", command=self._delete_selected)\
            .pack(side="left")

    def _on_label_field_change(self) -> None:
        if (self._loading or self._sel_brand is None
                or self._sel_shot is None or self._sel_label is None):
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
            self.data, self._sel_brand, self._sel_shot, self._sel_label,
            text=self.label_text_var.get(),
            position=[x, y],
            font_size=size,
            color=color,
            anchor=anchor,
        )
        self.on_dirty()
        self._refresh_tree(restore=True)
        # Labels typically get edited character-by-character; a long debounce
        # avoids re-rendering the composite on every keystroke.
        self._schedule_preview_render(debounce_ms=700)

    def _open_label_dialog(self, b: str, i: int, j: int, is_new: bool = False) -> None:
        labels = brand_io.get_labels(self.data, b, i)
        if not (0 <= j < len(labels)):
            return
        lbl = labels[j]

        dlg = tk.Toplevel(self.winfo_toplevel())
        dlg.title("Edit Label")
        dlg.resizable(False, False)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(3, weight=1)

        # ---- Text ----
        ttk.Label(outer, text="Text").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        text_var = tk.StringVar(value=str(lbl.get("text") or ""))
        text_entry = ttk.Entry(outer, textvariable=text_var, width=36)
        text_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

        # ---- Position ----
        pos = lbl.get("position") or [0, 0]
        ttk.Label(outer, text="X").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        x_var = tk.StringVar(value=str(int(pos[0])))
        ttk.Entry(outer, textvariable=x_var, width=8).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(outer, text="Y").grid(row=1, column=2, sticky="w", pady=4, padx=(8, 4))
        y_var = tk.StringVar(value=str(int(pos[1])))
        ttk.Entry(outer, textvariable=y_var, width=8).grid(row=1, column=3, sticky="w", pady=4)

        # ---- Size + Color ----
        ttk.Label(outer, text="Size").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        size_var = tk.StringVar(value=str(int(lbl.get("font_size") or 48)))
        ttk.Entry(outer, textvariable=size_var, width=8).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(outer, text="Color").grid(row=2, column=2, sticky="w", pady=4, padx=(8, 4))
        color_var = tk.StringVar(value=str(lbl.get("color") or ""))
        ttk.Entry(outer, textvariable=color_var, width=12).grid(row=2, column=3, sticky="w", pady=4)

        # ---- Anchor ----
        ttk.Label(outer, text="Anchor").grid(row=3, column=0, sticky="w", pady=4, padx=(0, 8))
        anchor_var = tk.StringVar(value=str(lbl.get("anchor") or ""))
        ttk.Combobox(
            outer, textvariable=anchor_var, state="readonly",
            values=["", "lt", "lm", "lb", "mt", "mm", "mb", "rt", "rm", "rb"], width=8,
        ).grid(row=3, column=1, sticky="w", pady=4)
        bold_var = tk.BooleanVar(value=bool(lbl.get("bold")))
        ttk.Checkbutton(outer, text="Bold", variable=bold_var).grid(
            row=3, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=4)

        # ---- Font ----
        ttk.Label(outer, text="Font").grid(row=4, column=0, sticky="w", pady=4, padx=(0, 8))
        font_var = tk.StringVar(value=str(lbl.get("font") or ""))
        font_row = ttk.Frame(outer)
        font_row.grid(row=4, column=1, columnspan=3, sticky="ew", pady=4)
        font_entry = ttk.Entry(font_row, textvariable=font_var)
        font_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))

        def _browse_font() -> None:
            path = filedialog.askopenfilename(
                title="Select font file",
                initialdir=str(self.assets_dir),
                filetypes=[("Font files", "*.ttf *.otf *.TTF *.OTF"), ("All files", "*.*")],
                parent=dlg,
            )
            if path:
                font_var.set(self._relative_to_assets(Path(path)))

        ttk.Button(font_row, text="…", style="Icon.TButton", width=2,
                   command=_browse_font).pack(side="left")
        ttk.Label(font_row, text="  blank = system default", style="Dim.TLabel")\
            .pack(side="left", padx=(4, 0))

        # ---- Shadow section ----
        ttk.Separator(outer, orient="horizontal").grid(
            row=5, column=0, columnspan=4, sticky="ew", pady=(6, 4))
        ttk.Label(outer, text="Shadow", style="Section.TLabel").grid(
            row=6, column=0, columnspan=4, sticky="w", pady=(0, 4))

        shadow_off = lbl.get("shadow_offset") or [4, 4]
        ttk.Label(outer, text="Color").grid(row=7, column=0, sticky="w", pady=4, padx=(0, 8))
        shadow_color_var = tk.StringVar(value=str(lbl.get("shadow_color") or ""))
        ttk.Entry(outer, textvariable=shadow_color_var, width=12).grid(
            row=7, column=1, sticky="w", pady=4)
        ttk.Label(outer, text="(blank = no shadow)", style="Dim.TLabel").grid(
            row=7, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=4)

        ttk.Label(outer, text="Offset X").grid(row=8, column=0, sticky="w", pady=4, padx=(0, 8))
        shadow_x_var = tk.StringVar(value=str(int(shadow_off[0])))
        ttk.Entry(outer, textvariable=shadow_x_var, width=8).grid(
            row=8, column=1, sticky="w", pady=4)
        ttk.Label(outer, text="Offset Y").grid(row=8, column=2, sticky="w", pady=4, padx=(8, 4))
        shadow_y_var = tk.StringVar(value=str(int(shadow_off[1])))
        ttk.Entry(outer, textvariable=shadow_y_var, width=8).grid(
            row=8, column=3, sticky="w", pady=4)

        ttk.Label(outer, text="Blur").grid(row=9, column=0, sticky="w", pady=4, padx=(0, 8))
        shadow_blur_var = tk.StringVar(value=str(int(lbl.get("shadow_blur") or 0)))
        ttk.Entry(outer, textvariable=shadow_blur_var, width=8).grid(
            row=9, column=1, sticky="w", pady=4)
        ttk.Label(outer, text="px radius  (0 = hard edge)", style="Dim.TLabel").grid(
            row=9, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=4)

        # ---- Buttons ----
        ttk.Separator(outer, orient="horizontal").grid(
            row=10, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        btn_row = ttk.Frame(outer)
        btn_row.grid(row=11, column=0, columnspan=4, pady=(8, 0), sticky="e")

        def _commit() -> None:
            try:
                x = int(x_var.get() or "0")
                y = int(y_var.get() or "0")
            except ValueError:
                x, y = 0, 0
            size_s = size_var.get().strip()
            try:
                size = int(size_s) if size_s else 48
            except ValueError:
                size = 48
            sc = shadow_color_var.get().strip() or None
            try:
                sx = int(shadow_x_var.get() or "4")
                sy = int(shadow_y_var.get() or "4")
            except ValueError:
                sx, sy = 4, 4
            try:
                sblur = int(shadow_blur_var.get() or "0")
            except ValueError:
                sblur = 0
            brand_io.update_label(
                self.data, b, i, j,
                text=text_var.get(),
                position=[x, y],
                font_size=size,
                color=color_var.get().strip() or None,
                anchor=anchor_var.get().strip() or None,
                font=font_var.get().strip() or None,
                bold=True if bold_var.get() else None,
                shadow_color=sc,
                shadow_offset=[sx, sy] if sc else None,
                shadow_blur=sblur if sc and sblur > 0 else None,
            )
            self.on_dirty()
            self._refresh_tree()
            self._select(nid_shot(b, i))
            dlg.destroy()

        def _discard() -> None:
            if is_new:
                brand_io.delete_label(self.data, b, i, j)
                self.on_dirty()
                self._refresh_tree()
            self._select(nid_shot(b, i))
            dlg.destroy()

        def _collect() -> dict:
            """Build a label dict from current dialog values."""
            try:
                x = int(x_var.get() or "0")
                y = int(y_var.get() or "0")
            except ValueError:
                x, y = 0, 0
            try:
                size = int(size_var.get() or "48")
            except ValueError:
                size = 48
            try:
                sx = int(shadow_x_var.get() or "4")
                sy = int(shadow_y_var.get() or "4")
            except ValueError:
                sx, sy = 4, 4
            try:
                sblur = int(shadow_blur_var.get() or "0")
            except ValueError:
                sblur = 0
            sc = shadow_color_var.get().strip()
            d: dict[str, Any] = {
                "text": text_var.get(),
                "position": [x, y],
                "font_size": size,
            }
            color = color_var.get().strip()
            if color: d["color"] = color
            anchor = anchor_var.get().strip()
            if anchor: d["anchor"] = anchor
            font = font_var.get().strip()
            if font: d["font"] = font
            if bold_var.get(): d["bold"] = True
            if sc:
                d["shadow_color"] = sc
                d["shadow_offset"] = [sx, sy]
                if sblur > 0:
                    d["shadow_blur"] = sblur
            return d

        def _copy() -> None:
            self._put_on_clipboard("ssb-label", _collect())

        def _duplicate() -> None:
            _commit()  # closes the dialog
            labels_now = brand_io.get_labels(self.data, b, i)
            labels_now.append(self._to_commented(_collect()))
            self.on_dirty()
            self._refresh_tree()
            new_j = len(labels_now) - 1
            self._select(nid_label(b, i, new_j))
            self._open_label_dialog(b, i, new_j)

        ttk.Button(btn_row, text="Copy", command=_copy).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="Duplicate", command=_duplicate)\
            .pack(side="left", padx=(0, 12))
        ttk.Button(btn_row, text="Cancel", command=_discard).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="Save", command=_commit).pack(side="left")

        dlg.bind("<Return>", lambda _e: _commit())
        dlg.bind("<Escape>", lambda _e: _discard())
        dlg.protocol("WM_DELETE_WINDOW", _discard)

        dlg.update_idletasks()
        pw = self.winfo_toplevel()
        cx = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_reqwidth()) // 2
        cy = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry(f"+{cx}+{cy}")
        text_entry.focus_set()
        text_entry.select_range(0, "end")

    def _open_stamp_dialog(self, b: str, i: int, j: int, is_new: bool = False) -> None:
        stamps = brand_io.get_stamps(self.data, b, i)
        if not (0 <= j < len(stamps)):
            return
        st = stamps[j]

        dlg = tk.Toplevel(self.winfo_toplevel())
        dlg.title("Edit Stamp")
        dlg.resizable(False, False)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(3, weight=1)

        # ---- Source ----
        ttk.Label(outer, text="Source").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        source_var = tk.StringVar(value=str(st.get("source") or ""))
        src_row = ttk.Frame(outer)
        src_row.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Entry(src_row, textvariable=source_var).pack(
            side="left", fill="x", expand=True, padx=(0, 4))

        def _browse_source() -> None:
            start = self.assets_dir / "logos"
            if b:
                sp = start / b
                if sp.is_dir():
                    start = sp
            path = filedialog.askopenfilename(
                title="Select stamp image",
                initialdir=str(start if start.is_dir() else self.assets_dir),
                filetypes=[("Images", "*.png *.PNG *.jpg *.jpeg *.JPG"), ("All files", "*.*")],
                parent=dlg,
            )
            if path:
                source_var.set(self._relative_to_assets(Path(path)))

        ttk.Button(src_row, text="…", style="Icon.TButton", width=2,
                   command=_browse_source).pack(side="left")

        # ---- Position ----
        pos = st.get("position") or [0, 0]
        ttk.Label(outer, text="X").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        x_var = tk.StringVar(value=str(int(pos[0])))
        ttk.Entry(outer, textvariable=x_var, width=8).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(outer, text="Y").grid(row=1, column=2, sticky="w", pady=4, padx=(8, 4))
        y_var = tk.StringVar(value=str(int(pos[1])))
        ttk.Entry(outer, textvariable=y_var, width=8).grid(row=1, column=3, sticky="w", pady=4)

        # ---- Scale + Opacity ----
        ttk.Label(outer, text="Scale").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        scale_var = tk.StringVar(value=str(float(st.get("scale") or 1.0)))
        ttk.Entry(outer, textvariable=scale_var, width=8).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(outer, text="Opacity").grid(row=2, column=2, sticky="w", pady=4, padx=(8, 4))
        opacity_var = tk.StringVar(value=str(float(st.get("opacity", 1.0))))
        ttk.Entry(outer, textvariable=opacity_var, width=8).grid(row=2, column=3, sticky="w", pady=4)
        ttk.Label(outer, text="1.0 = original size   |   opacity: 0.0–1.0", style="Dim.TLabel").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(0, 4))

        # ---- Buttons ----
        ttk.Separator(outer, orient="horizontal").grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        btn_row = ttk.Frame(outer)
        btn_row.grid(row=5, column=0, columnspan=4, pady=(8, 0), sticky="e")

        def _commit() -> None:
            try:
                x = int(x_var.get() or "0")
                y = int(y_var.get() or "0")
            except ValueError:
                x, y = 0, 0
            try:
                scale = float(scale_var.get() or "1.0")
            except ValueError:
                scale = 1.0
            try:
                opacity = max(0.0, min(1.0, float(opacity_var.get() or "1.0")))
            except ValueError:
                opacity = 1.0
            brand_io.update_stamp(
                self.data, b, i, j,
                source=source_var.get().strip(),
                position=[x, y],
                scale=scale,
                opacity=opacity if opacity < 1.0 else None,
            )
            self.on_dirty()
            self._refresh_tree()
            self._select(nid_shot(b, i))
            dlg.destroy()

        def _discard() -> None:
            if is_new:
                brand_io.delete_stamp(self.data, b, i, j)
                self.on_dirty()
                self._refresh_tree()
            self._select(nid_shot(b, i))
            dlg.destroy()

        def _collect() -> dict:
            try:
                x = int(x_var.get() or "0")
                y = int(y_var.get() or "0")
            except ValueError:
                x, y = 0, 0
            try:
                scale = float(scale_var.get() or "1.0")
            except ValueError:
                scale = 1.0
            try:
                opacity = max(0.0, min(1.0, float(opacity_var.get() or "1.0")))
            except ValueError:
                opacity = 1.0
            d: dict[str, Any] = {
                "source": source_var.get().strip(),
                "position": [x, y],
                "scale": scale,
            }
            if opacity < 1.0:
                d["opacity"] = opacity
            return d

        def _copy() -> None:
            self._put_on_clipboard("ssb-stamp", _collect())

        def _duplicate() -> None:
            _commit()
            stamps_now = brand_io.get_stamps(self.data, b, i)
            stamps_now.append(self._to_commented(_collect()))
            self.on_dirty()
            self._refresh_tree()
            new_j = len(stamps_now) - 1
            self._select(nid_stamp(b, i, new_j))
            self._open_stamp_dialog(b, i, new_j)

        ttk.Button(btn_row, text="Copy", command=_copy).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="Duplicate", command=_duplicate)\
            .pack(side="left", padx=(0, 12))
        ttk.Button(btn_row, text="Cancel", command=_discard).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="Save", command=_commit).pack(side="left")

        dlg.bind("<Return>", lambda _e: _commit())
        dlg.bind("<Escape>", lambda _e: _discard())
        dlg.protocol("WM_DELETE_WINDOW", _discard)

        dlg.update_idletasks()
        pw = self.winfo_toplevel()
        cx = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_reqwidth()) // 2
        cy = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry(f"+{cx}+{cy}")
        source_var.get() or _browse_source()

    # ===================================================================
    # Inspector — Stamp
    # ===================================================================

    def _render_stamp_inspector(self, body: ttk.Frame) -> None:
        b, i, j = self._sel_brand, self._sel_shot, self._sel_stamp
        stamps = brand_io.get_stamps(self.data, b, i)
        if not (0 <= j < len(stamps)):
            return
        st = stamps[j]
        header = ttk.Frame(body)
        header.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(header, text="Stamp", style="Heading.TLabel").pack(side="left")
        copy_btn = ttk.Button(header, text="📋", width=2, command=self._copy_stamp)
        copy_btn.pack(side="right", padx=(2, 0))
        attach_tooltip(copy_btn, "Copy stamp to clipboard")
        dup_btn = ttk.Button(header, text="⎘", width=2,
                             command=self._duplicate_selected)
        dup_btn.pack(side="right", padx=(2, 0))
        attach_tooltip(dup_btn, "Duplicate stamp in this output")
        ttk.Label(body, text=f"in {b} / {brand_io.get_screenshots(self.data, b)[i].get('output') or 'output'}",
                  style="Dim.TLabel").pack(anchor="w", padx=8, pady=(0, 4))

        card = self._card(body, "Source")
        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        self.stamp_source_var = tk.StringVar(value=str(st.get("source") or ""))
        self.stamp_source_var.trace_add(
            "write", lambda *_a: self._on_stamp_field_change())
        ttk.Entry(row, textvariable=self.stamp_source_var)\
            .pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(row, text="…", style="Icon.TButton", width=2,
                   command=self._browse_stamp_source).pack(side="left")

        card = self._card(body, "Layout")
        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="X, Y", width=8).pack(side="left")
        pos = st.get("position") or [0, 0]
        self.stamp_x_var = tk.StringVar(value=str(int(pos[0])))
        self.stamp_y_var = tk.StringVar(value=str(int(pos[1])))
        for v in (self.stamp_x_var, self.stamp_y_var):
            v.trace_add("write", lambda *_a: self._on_stamp_field_change())
        ttk.Entry(row, textvariable=self.stamp_x_var, width=8).pack(side="left", padx=1)
        ttk.Entry(row, textvariable=self.stamp_y_var, width=8).pack(side="left", padx=1)

        row = ttk.Frame(card); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Scale", width=8).pack(side="left")
        self.stamp_scale_var = tk.StringVar(value=str(float(st.get("scale") or 1.0)))
        self.stamp_scale_var.trace_add(
            "write", lambda *_a: self._on_stamp_field_change())
        ttk.Entry(row, textvariable=self.stamp_scale_var, width=8).pack(side="left", padx=1)
        ttk.Label(row, text="(1.0 = original size)", style="Dim.TLabel")\
            .pack(side="left", padx=4)

        actions = ttk.Frame(body); actions.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(actions, text="Delete", command=self._delete_selected)\
            .pack(side="left")

    def _on_stamp_field_change(self) -> None:
        if (self._loading or self._sel_brand is None
                or self._sel_shot is None or self._sel_stamp is None):
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
            self.data, self._sel_brand, self._sel_shot, self._sel_stamp,
            source=self.stamp_source_var.get().strip(),
            position=[x, y],
            scale=scale,
        )
        self.on_dirty()
        self._refresh_tree(restore=True)
        self._schedule_preview_render()

    def _browse_stamp_source(self) -> None:
        start = self.assets_dir / "logos"
        if self._sel_brand:
            specific = start / self._sel_brand
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

    # ===================================================================
    # Tree population & navigation
    # ===================================================================

    def _refresh_tree(self, *, restore: bool = False) -> None:
        # Remember selected nid + open state to restore.
        prev_nid = self._current_nid()
        open_state: dict[str, bool] = {}
        for iid in self.tree.get_children(""):
            self._collect_open_state(iid, open_state)

        for iid in self.tree.get_children(""):
            self.tree.delete(iid)

        for brand_name in brand_io.list_brand_names(self.data):
            b_iid = nid_brand(brand_name)
            self.tree.insert("", "end", iid=b_iid, text=f"📁 {brand_name}", open=True)
            shots = brand_io.get_screenshots(self.data, brand_name)
            for i, shot in enumerate(shots):
                phone = shot.get("phone") or "?"
                out = shot.get("output") or "(unnamed)"
                s_iid = nid_shot(brand_name, i)
                self.tree.insert(b_iid, "end", iid=s_iid,
                                 text=f"🖼 {out}  · [{phone}]", open=False)
                labels = brand_io.get_labels(self.data, brand_name, i)
                if labels:
                    grp = nid_labels(brand_name, i)
                    self.tree.insert(s_iid, "end", iid=grp,
                                     text=f"  Labels ({len(labels)})", open=False)
                    for j, lbl in enumerate(labels):
                        text = (str(lbl.get("text") or "")[:28]) or "—"
                        self.tree.insert(grp, "end", iid=nid_label(brand_name, i, j),
                                         text=f"   T  {text}")
                stamps = brand_io.get_stamps(self.data, brand_name, i)
                if stamps:
                    grp = nid_stamps(brand_name, i)
                    self.tree.insert(s_iid, "end", iid=grp,
                                     text=f"  Stamps ({len(stamps)})", open=False)
                    for j, st in enumerate(stamps):
                        src = Path(str(st.get("source") or "")).name or "—"
                        self.tree.insert(grp, "end", iid=nid_stamp(brand_name, i, j),
                                         text=f"   *  {src}")

        # Restore open state (best effort).
        for iid, opened in open_state.items():
            try:
                self.tree.item(iid, open=opened)
            except tk.TclError:
                pass

        # Restore selection if requested + still valid.
        target = prev_nid if restore else None
        if target and self.tree.exists(target):
            self.tree.selection_set(target)
            self.tree.see(target)

    def _collect_open_state(self, iid: str, out: dict[str, bool]) -> None:
        out[iid] = bool(self.tree.item(iid, "open"))
        for child in self.tree.get_children(iid):
            self._collect_open_state(child, out)

    def _current_nid(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_tree_select(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self._set_selection("", None, None, None, None)
            return
        kind, parts = parse_nid(sel[0])
        if kind == "brand":
            self._set_selection("brand", parts[0], None, None, None)
        elif kind == "shot":
            self._set_selection("shot", parts[0], int(parts[1]), None, None)
        elif kind == "labels":
            # Group node: select the parent shot.
            self._select(nid_shot(parts[0], int(parts[1])))
            return
        elif kind == "stamps":
            self._select(nid_shot(parts[0], int(parts[1])))
            return
        elif kind == "label":
            b, i, j = parts[0], int(parts[1]), int(parts[2])
            self._set_selection("shot", b, i, None, None)
            self.after(0, lambda b=b, i=i, j=j: self._open_label_dialog(b, i, j))
            return
        elif kind == "stamp":
            b, i, j = parts[0], int(parts[1]), int(parts[2])
            self._set_selection("shot", b, i, None, None)
            self.after(0, lambda b=b, i=i, j=j: self._open_stamp_dialog(b, i, j))
            return

    def _on_tree_double_click(self, event: tk.Event) -> None:
        # Toggle open state on double-click for any expandable node.
        iid = self.tree.identify_row(event.y)
        if iid and self.tree.get_children(iid):
            self.tree.item(iid, open=not self.tree.item(iid, "open"))

    def _on_tree_right_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        # Select the row under the cursor so following actions act on it.
        self.tree.selection_set(iid)
        self._on_tree_select()
        kind = self._sel_kind
        menu = tk.Menu(self, tearoff=0)
        if kind == "shot":
            menu.add_command(label="Duplicate output",
                             command=self._duplicate_selected)
            menu.add_separator()
            menu.add_command(label="Add label", command=self._add_label)
            menu.add_command(label="Add stamp", command=self._add_stamp)
            paste_kind = self._clipboard_kind()
            menu.add_command(label="Paste label",
                             command=self._paste_label_into_current,
                             state=("normal" if paste_kind == "ssb-label"
                                    else "disabled"))
            menu.add_command(label="Paste stamp",
                             command=self._paste_stamp_into_current,
                             state=("normal" if paste_kind == "ssb-stamp"
                                    else "disabled"))
            menu.add_separator()
            menu.add_command(label="Delete output",
                             command=self._delete_selected)
        elif kind == "label":
            menu.add_command(label="Copy label", command=self._copy_label)
            menu.add_command(label="Duplicate", command=self._duplicate_selected)
            menu.add_separator()
            menu.add_command(label="Delete", command=self._delete_selected)
        elif kind == "stamp":
            menu.add_command(label="Copy stamp", command=self._copy_stamp)
            menu.add_command(label="Duplicate", command=self._duplicate_selected)
            menu.add_separator()
            menu.add_command(label="Delete", command=self._delete_selected)
        elif kind == "brand":
            menu.add_command(label="Delete brand",
                             command=self._delete_selected)
        else:
            return
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _set_selection(self, kind: str, b: str | None, i: int | None,
                       lj: int | None, sj: int | None) -> None:
        self._sel_kind = kind
        self._sel_brand = b
        self._sel_shot = i
        self._sel_label = lj
        self._sel_stamp = sj
        self._render_inspector()
        self._schedule_preview_render()

    def _select(self, nid: str) -> None:
        if self.tree.exists(nid):
            self.tree.selection_set(nid)
            self.tree.see(nid)

    # ===================================================================
    # Add / Delete / Duplicate operations
    # ===================================================================

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
        self._refresh_tree()
        self._select(nid_brand(name.strip()))

    def _add_output(self) -> None:
        b = self._sel_brand or self._first_brand()
        if b is None:
            messagebox.showinfo("Add output", "Add a brand first.", parent=self)
            return
        start = self.assets_dir / "screenshots" / b
        if not start.is_dir():
            start = self.assets_dir / "screenshots"
        if not start.is_dir():
            start = self.assets_dir
        self.winfo_toplevel().lift()
        path = filedialog.askopenfilename(
            title=f"Pick screenshot source for {b}",
            initialdir=str(start),
            filetypes=[("Images", "*.png *.PNG *.jpg *.jpeg *.JPG"), ("All files", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if not path:
            return
        source_rel = self._relative_to_assets(Path(path))
        brand = self.data["brands"][b]
        existing = brand_io.get_screenshots(self.data, b)
        out_name = f"{len(existing) + 1:02d}_{Path(path).stem}.png"
        phones = self._phone_names()
        default_phone = str(brand.get("phone") or (phones[0] if phones else ""))
        shot = brand_io.add_screenshot(self.data, b, source=source_rel, output=out_name)
        if default_phone:
            shot["phone"] = default_phone
        self.on_dirty()
        self._refresh_tree()
        self._select(nid_shot(b, len(existing)))

    def _add_label(self) -> None:
        if self._sel_brand is None or self._sel_shot is None:
            return
        b, i = self._sel_brand, self._sel_shot
        brand_io.add_label(self.data, b, i)
        self.on_dirty()
        self._refresh_tree()
        labels = brand_io.get_labels(self.data, b, i)
        self._open_label_dialog(b, i, len(labels) - 1, is_new=True)

    def _add_stamp(self) -> None:
        if self._sel_brand is None or self._sel_shot is None:
            return
        b, i = self._sel_brand, self._sel_shot
        brand_io.add_stamp(self.data, b, i)
        self.on_dirty()
        self._refresh_tree()
        stamps = brand_io.get_stamps(self.data, b, i)
        self._open_stamp_dialog(b, i, len(stamps) - 1, is_new=True)

    def _delete_selected(self) -> None:
        kind = self._sel_kind
        if kind == "brand" and self._sel_brand:
            if not messagebox.askyesno("Delete brand",
                                       f"Delete brand {self._sel_brand!r}?",
                                       parent=self):
                return
            brand_io.delete_brand(self.data, self._sel_brand)
            self._set_selection("", None, None, None, None)
        elif kind == "shot" and self._sel_brand is not None and self._sel_shot is not None:
            if not messagebox.askyesno("Delete output",
                                       f"Delete output #{self._sel_shot + 1}?",
                                       parent=self):
                return
            brand_io.delete_screenshot(self.data, self._sel_brand, self._sel_shot)
            self._set_selection("brand", self._sel_brand, None, None, None)
        elif kind == "label" and self._sel_label is not None:
            self._delete_label_at(self._sel_label)
            return
        elif kind == "stamp" and self._sel_stamp is not None:
            self._delete_stamp_at(self._sel_stamp)
            return
        else:
            return
        self.on_dirty()
        self._refresh_tree()

    def _delete_label_at(self, j: int) -> None:
        if self._sel_brand is None or self._sel_shot is None:
            return
        brand_io.delete_label(self.data, self._sel_brand, self._sel_shot, j)
        self._set_selection("shot", self._sel_brand, self._sel_shot, None, None)
        self.on_dirty()
        self._refresh_tree()

    def _delete_stamp_at(self, j: int) -> None:
        if self._sel_brand is None or self._sel_shot is None:
            return
        brand_io.delete_stamp(self.data, self._sel_brand, self._sel_shot, j)
        self._set_selection("shot", self._sel_brand, self._sel_shot, None, None)
        self.on_dirty()
        self._refresh_tree()

    def _duplicate_selected(self) -> None:
        from copy import deepcopy
        kind = self._sel_kind
        if kind == "label" and self._sel_label is not None:
            labels = brand_io.get_labels(self.data, self._sel_brand, self._sel_shot)
            labels.append(deepcopy(labels[self._sel_label]))
            self.on_dirty()
            self._refresh_tree()
            self._select(nid_label(self._sel_brand, self._sel_shot, len(labels) - 1))
        elif kind == "stamp" and self._sel_stamp is not None:
            stamps = brand_io.get_stamps(self.data, self._sel_brand, self._sel_shot)
            stamps.append(deepcopy(stamps[self._sel_stamp]))
            self.on_dirty()
            self._refresh_tree()
            self._select(nid_stamp(self._sel_brand, self._sel_shot, len(stamps) - 1))
        elif (kind == "shot" and self._sel_brand is not None
                and self._sel_shot is not None):
            self._duplicate_shot(self._sel_brand, self._sel_shot)

    def _duplicate_shot(self, b: str, i: int) -> None:
        """Duplicate an output (with its labels & stamps) and select the copy."""
        from copy import deepcopy
        shots = brand_io.get_screenshots(self.data, b)
        if not (0 <= i < len(shots)):
            return
        new_shot = deepcopy(shots[i])
        # Derive a non-colliding output filename.
        existing = {str(s.get("output") or "") for s in shots}
        original = str(new_shot.get("output") or "")
        if original:
            stem, _, ext = original.rpartition(".")
            if not stem:
                stem, ext = original, ""
            suffix = f".{ext}" if ext else ""
            candidate = f"{stem}_copy{suffix}"
            n = 2
            while candidate in existing:
                candidate = f"{stem}_copy{n}{suffix}"
                n += 1
            new_shot["output"] = candidate
        shots.append(new_shot)
        self.on_dirty()
        self._refresh_tree()
        self._select(nid_shot(b, len(shots) - 1))

    # ===================================================================
    # Keyboard handlers
    # ===================================================================

    def _is_active(self) -> bool:
        """Are we the currently-shown notebook tab and is focus not in a text widget?"""
        try:
            nb = self.master  # The notebook.
            if hasattr(nb, "select"):
                if nb.nametowidget(nb.select()) is not self:
                    return False
        except Exception:
            pass
        focus = self.focus_get()
        if isinstance(focus, (tk.Entry, tk.Text, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
            return False
        return True

    def _on_key_delete(self, _event: tk.Event) -> None:
        if not self._is_active():
            return
        self._delete_selected()

    def _on_key_duplicate(self, _event: tk.Event) -> None:
        if not self._is_active():
            return
        self._duplicate_selected()

    def _on_key_nudge(self, _event: tk.Event, dx: int, dy: int) -> None:
        if not self._is_active():
            return
        if (self._sel_brand is None or self._sel_shot is None):
            return
        if self._sel_kind == "label" and self._sel_label is not None:
            labels = brand_io.get_labels(self.data, self._sel_brand, self._sel_shot)
            pos = list(labels[self._sel_label].get("position") or [0, 0])
            labels[self._sel_label]["position"] = [int(pos[0]) + dx, int(pos[1]) + dy]
            self.on_dirty()
            self._render_inspector()
            self._schedule_preview_render()
        elif self._sel_kind == "stamp" and self._sel_stamp is not None:
            stamps = brand_io.get_stamps(self.data, self._sel_brand, self._sel_shot)
            pos = list(stamps[self._sel_stamp].get("position") or [0, 0])
            stamps[self._sel_stamp]["position"] = [int(pos[0]) + dx, int(pos[1]) + dy]
            self.on_dirty()
            self._render_inspector()
            self._schedule_preview_render()

    # ===================================================================
    # Preview render
    # ===================================================================

    def _preview_target(self) -> tuple[str, int] | None:
        """Which (brand, shot_idx) should the preview show right now?"""
        if self._sel_brand is None:
            return None
        if self._sel_kind in ("shot", "label", "stamp") and self._sel_shot is not None:
            return (self._sel_brand, self._sel_shot)
        if self._sel_kind == "brand":
            shots = brand_io.get_screenshots(self.data, self._sel_brand)
            if shots:
                return (self._sel_brand, 0)
        return None

    def _schedule_preview_render(self, debounce_ms: int = 250) -> None:
        if self._render_after_id is not None:
            try:
                self.after_cancel(self._render_after_id)
            except Exception:
                pass
            self._render_after_id = None
        target = self._preview_target()
        if target is None:
            self._clear_preview("Select an output in the sidebar to preview it.")
            return
        # If we're switching to a different output, render immediately so the
        # user gets visual feedback for the navigation; otherwise debounce edits.
        delay = 0 if target != self._cur_preview_key else debounce_ms
        self._render_after_id = self.after(delay, self._render_preview_now)

    def _force_render_preview(self) -> None:
        """Manual reload — bypass the input-signature cache (e.g. for on-disk
        asset changes that don't show in the YAML)."""
        self._last_render_sig = None
        self._render_preview_now()

    def _render_preview_now(self) -> None:
        self._render_after_id = None
        target = self._preview_target()
        if target is None:
            self._clear_preview("Select an output in the sidebar to preview it.")
            return
        brand_name, shot_idx = target
        self._cur_preview_key = target

        try:
            brand_cfg = self.data["brands"][brand_name]
            shots = brand_io.get_screenshots(self.data, brand_name)
            if not (0 <= shot_idx < len(shots)):
                self._clear_preview("(no output)"); return
            shot = shots[shot_idx]
            phones = self.data.get("phones") or {}
            phone_name, phone_cfg = resolve_shot_phone(
                brand_name, dict(brand_cfg), dict(shot), dict(phones),
            )
            merged = {**dict(brand_cfg), **dict(phone_cfg)}
            # Don't apply output sizing/cropping/resizing to the preview —
            # crop is shown as a dotted overlay; resize doesn't need a preview.
            merged.pop("output_size", None)
            merged.pop("post_process", None)
            shot = dict(shot)
            shot.pop("post_process", None)
        except Exception as exc:
            self._clear_preview(f"⚠ {exc}")
            return

        # Skip the expensive composite if the inputs haven't changed since the
        # last successful render. Many field-change traces fire even when the
        # underlying value is identical (re-typed, same value reapplied).
        import json
        try:
            sig = json.dumps(
                {"k": [brand_name, shot_idx, phone_name],
                 "m": self._to_plain(merged),
                 "s": self._to_plain(shot)},
                sort_keys=True, default=str, separators=(",", ":"),
            )
        except Exception:
            sig = None
        if (sig is not None and sig == self._last_render_sig
                and self._preview_image is not None):
            self.preview_status_var.set(
                f"{self._preview_image.width}×{self._preview_image.height}  ·  "
                f"{brand_name} / {shot.get('output') or '?'} [{phone_name or '?'}]"
            )
            return

        token = self._render_token = self._render_token + 1
        self.preview_status_var.set("Rendering…")
        self.update_idletasks()

        try:
            image = build_composite(merged, shot, self.assets_dir)
        except Exception as exc:
            if token != self._render_token:
                return
            self._clear_preview(f"⚠ Render failed: {exc}")
            return
        if token != self._render_token:
            return  # a newer render started while we were working

        self._preview_image = image
        self._last_render_sig = sig
        self._blit_preview()
        self.preview_status_var.set(
            f"{image.width}×{image.height}  ·  {brand_name} / {shot.get('output') or '?'} [{phone_name or '?'}]"
        )

    def _blit_preview(self) -> None:
        img = self._preview_image
        if img is None:
            return
        cw = max(self.preview_canvas.winfo_width(), 1)
        ch = max(self.preview_canvas.winfo_height(), 1)
        if self._preview_fit:
            scale = min(cw / img.width, ch / img.height, 1.0)
        else:
            scale = self._preview_user_zoom
        scale = max(0.05, min(scale, 8.0))
        self._preview_scale = scale
        disp_w = max(1, int(img.width * scale))
        disp_h = max(1, int(img.height * scale))
        scaled = img.resize((disp_w, disp_h), Image.LANCZOS)
        self._preview_tk = ImageTk.PhotoImage(scaled)
        self.preview_canvas.delete("all")
        # Center the image within the visible viewport.
        x = max(0, (cw - disp_w) // 2)
        y = max(0, (ch - disp_h) // 2)
        self._preview_origin = (x, y)
        self.preview_canvas.create_image(x, y, anchor="nw", image=self._preview_tk)
        self.preview_canvas.config(scrollregion=(0, 0, max(cw, disp_w), max(ch, disp_h)))
        # Dotted crop overlay (driven by the inspector form; no live re-render).
        self._draw_crop_overlay()

    def _draw_crop_overlay(self) -> None:
        # Always remove any prior overlay first (rect + handles).
        self.preview_canvas.delete("crop_overlay")
        self.preview_canvas.delete("crop_handle")
        if self._preview_image is None:
            return
        if self._sel_brand is None or self._sel_shot is None:
            return
        try:
            shots = brand_io.get_screenshots(self.data, self._sel_brand)
            shot = shots[self._sel_shot]
        except Exception:
            return
        pp = shot.get("post_process") or {}
        crop = pp.get("crop") if isinstance(pp, dict) else None
        if not crop:
            return

        iw, ih = self._preview_image.size
        try:
            box = self._resolve_crop_for_overlay(crop, iw, ih)
        except Exception:
            return
        if box is None:
            return
        l, t, r, b = box
        ox, oy = self._preview_origin
        s = self._preview_scale
        cl = ox + l * s
        ct = oy + t * s
        cr = ox + r * s
        cb = oy + b * s
        self.preview_canvas.create_rectangle(
            cl, ct, cr, cb,
            outline="#ffd60a", dash=(6, 4), width=2,
            tags=("crop_overlay",),
        )
        # Four draggable handles, one at each corner.
        hr = 6  # handle radius (canvas px)
        for name, (hx, hy) in (
            ("tl", (cl, ct)),
            ("tr", (cr, ct)),
            ("br", (cr, cb)),
            ("bl", (cl, cb)),
        ):
            self.preview_canvas.create_rectangle(
                hx - hr, hy - hr, hx + hr, hy + hr,
                fill="#ffd60a", outline="#000000", width=1,
                tags=("crop_handle", f"crop_handle:{name}"),
            )

    # -------- handle hit-test + drag --------

    def _hit_handle(self, vx: int, vy: int) -> str | None:
        """Return the corner tag ('tl'/'tr'/'br'/'bl') under viewport (vx, vy), or None."""
        cx = self.preview_canvas.canvasx(vx)
        cy = self.preview_canvas.canvasy(vy)
        for item in self.preview_canvas.find_overlapping(cx - 2, cy - 2, cx + 2, cy + 2):
            for tag in self.preview_canvas.gettags(item):
                if tag.startswith("crop_handle:"):
                    return tag.split(":", 1)[1]
        return None

    def _current_crop_box(self) -> tuple[int, int, int, int] | None:
        """Return the active crop box in image-pixel coords, or None."""
        if (self._sel_brand is None or self._sel_shot is None
                or self._preview_image is None):
            return None
        try:
            shots = brand_io.get_screenshots(self.data, self._sel_brand)
            shot = shots[self._sel_shot]
        except Exception:
            return None
        pp = shot.get("post_process") or {}
        crop = pp.get("crop") if isinstance(pp, dict) else None
        if not crop:
            return None
        iw, ih = self._preview_image.size
        try:
            return self._resolve_crop_for_overlay(crop, iw, ih)
        except Exception:
            return None

    def _hit_crop_interior(self, vx: int, vy: int) -> bool:
        """True if (vx, vy) is inside the dotted rect but not on a corner handle.

        Only meaningful in 'box' / 'margins' modes; 'center' is symmetric and
        not draggable.
        """
        if self._hit_handle(vx, vy) is not None:
            return False
        mode = getattr(self, "crop_mode_var", None)
        if mode is None or mode.get() not in ("box", "margins"):
            return False
        box = self._current_crop_box()
        if box is None:
            return False
        l, t, r, b = box
        ox, oy = self._preview_origin
        s = self._preview_scale or 1.0
        cx = self.preview_canvas.canvasx(vx)
        cy = self.preview_canvas.canvasy(vy)
        return (ox + l * s) <= cx <= (ox + r * s) and (oy + t * s) <= cy <= (oy + b * s)

    def _on_preview_press(self, event: tk.Event) -> None:
        h = self._hit_handle(event.x, event.y)
        if h is not None:
            self._drag_handle = h
            self._drag_move = None
            self.preview_canvas.config(cursor="crosshair")
            return
        if self._hit_crop_interior(event.x, event.y):
            box = self._current_crop_box()
            if box is not None and self._preview_image is not None:
                ox, oy = self._preview_origin
                s = self._preview_scale or 1.0
                ix0 = int(round((self.preview_canvas.canvasx(event.x) - ox) / s))
                iy0 = int(round((self.preview_canvas.canvasy(event.y) - oy) / s))
                self._drag_move = (ix0, iy0, *box)
                self._drag_handle = None
                self.preview_canvas.config(cursor="fleur")
                return
        self._drag_handle = None
        self._drag_move = None
        self.preview_canvas.scan_mark(event.x, event.y)
        self.preview_canvas.config(cursor="fleur")

    def _on_preview_drag(self, event: tk.Event) -> None:
        if self._drag_handle:
            self._drag_crop_handle(event.x, event.y)
        elif self._drag_move is not None:
            self._drag_crop_move(event.x, event.y)
        else:
            self.preview_canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_preview_release(self, _event: tk.Event) -> None:
        if self._drag_handle is not None:
            self._drag_handle = None
        if self._drag_move is not None:
            self._drag_move = None
        self.preview_canvas.config(cursor="")

    def _on_preview_motion(self, event: tk.Event) -> None:
        if self._drag_handle is None and self._drag_move is None:
            if self._hit_crop_interior(event.x, event.y):
                self.preview_canvas.config(cursor="fleur")
            else:
                self.preview_canvas.config(cursor="crosshair")

        # Floating coordinate overlay.
        if self._preview_image is None:
            self._coord_label.place_forget()
            return
        ox, oy = self._preview_origin
        s = self._preview_scale or 1.0
        cx = self.preview_canvas.canvasx(event.x)
        cy = self.preview_canvas.canvasy(event.y)
        ix = int(round((cx - ox) / s))
        iy = int(round((cy - oy) / s))
        iw, ih = self._preview_image.size
        if 0 <= ix <= iw and 0 <= iy <= ih:
            self._coord_label.config(text=f"x {ix}   y {iy}")
            cw = self.preview_canvas.winfo_width()
            ch = self.preview_canvas.winfo_height()
            lw = self._coord_label.winfo_reqwidth()
            lh = self._coord_label.winfo_reqheight()
            lx = min(event.x + 14, cw - lw - 4)
            ly = min(event.y + 14, ch - lh - 4)
            self._coord_label.place(x=lx, y=ly)
            self._coord_label.lift()
        else:
            self._coord_label.place_forget()

    def _on_preview_leave(self, _event: tk.Event) -> None:
        self._coord_label.place_forget()

    def _drag_crop_handle(self, vx: int, vy: int) -> None:
        if (self._sel_brand is None or self._sel_shot is None
                or self._preview_image is None or self._drag_handle is None):
            return
        iw, ih = self._preview_image.size
        ox, oy = self._preview_origin
        s = self._preview_scale or 1.0
        cx = self.preview_canvas.canvasx(vx)
        cy = self.preview_canvas.canvasy(vy)
        ix = max(0, min(iw, int(round((cx - ox) / s))))
        iy = max(0, min(ih, int(round((cy - oy) / s))))

        # Read the current box from YAML.
        shots = brand_io.get_screenshots(self.data, self._sel_brand)
        shot = shots[self._sel_shot]
        pp = shot.get("post_process") or {}
        crop = pp.get("crop") if isinstance(pp, dict) else None
        box = self._resolve_crop_for_overlay(crop, iw, ih) if crop else (0, 0, iw, ih)
        if box is None:
            return
        l, t, r, b = box
        h = self._drag_handle

        mode = self.crop_mode_var.get()
        locked = (getattr(self, "aspect_locked_var", None) is not None
                  and self.aspect_locked_var.get())
        ratio = self._parse_aspect(self.crop_a_var.get()) if locked else None
        if mode == "center":
            # Resize symmetrically around the image center.
            cx_img, cy_img = iw // 2, ih // 2
            new_w = max(2, min(iw, 2 * abs(ix - cx_img)))
            new_h = max(2, min(ih, 2 * abs(iy - cy_img)))
            if ratio and ratio > 0:
                # Width leads, then clamp to image and recompute h from ratio.
                new_h = max(2, int(round(new_w / ratio)))
                if new_h > ih:
                    new_h = ih; new_w = max(2, int(round(new_h * ratio)))
                if new_w > iw:
                    new_w = iw; new_h = max(2, int(round(new_w / ratio)))
            new_values = [new_w, new_h]
        else:
            if "t" in h: t = max(0, min(b - 1, iy))
            if "b" in h: b = max(t + 1, min(ih, iy))
            if "l" in h: l = max(0, min(r - 1, ix))
            if "r" in h: r = max(l + 1, min(iw, ix))
            if ratio and ratio > 0:
                cur_w = r - l
                cur_h = b - t
                # Width leads. Anchor to the side opposite the dragged edge so
                # the dragged corner stays under the cursor on its leading axis.
                forced_h = max(1, int(round(cur_w / ratio)))
                if "t" in h:
                    t = max(0, b - forced_h)
                else:
                    b = min(ih, t + forced_h)
                # If we ran out of room vertically, pin height and re-derive
                # width so the box stays inside the image.
                if b - t != forced_h:
                    forced_h = b - t
                    forced_w = max(1, int(round(forced_h * ratio)))
                    if "l" in h:
                        l = max(0, r - forced_w)
                    else:
                        r = min(iw, l + forced_w)
            if mode == "margins":
                new_values = [l, t, iw - r, ih - b]
            else:  # box (or fallback)
                if mode != "box":
                    mode = "box"  # safety
                new_values = [l, t, r, b]

        # Push to YAML (without retriggering resize), update inspector vars
        # without firing the sync handler, then redraw the overlay.
        brand_io.update_post_process(
            self.data, self._sel_brand, self._sel_shot,
            crop_mode=mode, crop_values=new_values,
        )
        prev_loading, self._loading = self._loading, True
        prev_suppress, self._suppress_crop_sync = self._suppress_crop_sync, True
        try:
            self.crop_mode_var.set(mode)
            if mode == "margins":
                self.crop_l_var.set(str(new_values[0]))
                self.crop_t_var.set(str(new_values[1]))
                self.crop_r_var.set(str(new_values[2]))
                self.crop_b_var.set(str(new_values[3]))
                w_disp = iw - new_values[0] - new_values[2]
                h_disp = ih - new_values[1] - new_values[3]
            elif mode == "box":
                self.crop_l_var.set(str(new_values[0]))
                self.crop_t_var.set(str(new_values[1]))
                self.crop_r_var.set(str(new_values[2]))
                self.crop_b_var.set(str(new_values[3]))
                w_disp = new_values[2] - new_values[0]
                h_disp = new_values[3] - new_values[1]
            else:  # center
                self.crop_w_var.set(str(new_values[0]))
                self.crop_h_var.set(str(new_values[1]))
                w_disp, h_disp = new_values[0], new_values[1]
            if mode in ("margins", "box"):
                self.crop_w_var.set(str(max(1, w_disp)))
                self.crop_h_var.set(str(max(1, h_disp)))
            self.crop_a_var.set(self._format_aspect(w_disp, h_disp))
        finally:
            self._loading = prev_loading
            self._suppress_crop_sync = prev_suppress
        self.on_dirty()
        self._draw_crop_overlay()

    def _drag_crop_move(self, vx: int, vy: int) -> None:
        """Translate the crop box by the cursor delta, clamped to image bounds."""
        if (self._drag_move is None or self._sel_brand is None
                or self._sel_shot is None or self._preview_image is None):
            return
        ix0, iy0, l0, t0, r0, b0 = self._drag_move
        iw, ih = self._preview_image.size
        ox, oy = self._preview_origin
        s = self._preview_scale or 1.0
        ix = int(round((self.preview_canvas.canvasx(vx) - ox) / s))
        iy = int(round((self.preview_canvas.canvasy(vy) - oy) / s))
        dx = ix - ix0
        dy = iy - iy0
        w = r0 - l0
        h = b0 - t0
        new_l = max(0, min(iw - w, l0 + dx))
        new_t = max(0, min(ih - h, t0 + dy))
        new_r = new_l + w
        new_b = new_t + h

        mode = self.crop_mode_var.get()
        if mode == "margins":
            new_values = [new_l, new_t, iw - new_r, ih - new_b]
        else:
            mode = "box"
            new_values = [new_l, new_t, new_r, new_b]

        brand_io.update_post_process(
            self.data, self._sel_brand, self._sel_shot,
            crop_mode=mode, crop_values=new_values,
        )
        prev_loading, self._loading = self._loading, True
        prev_suppress, self._suppress_crop_sync = self._suppress_crop_sync, True
        try:
            self.crop_mode_var.set(mode)
            if mode == "margins":
                self.crop_l_var.set(str(new_values[0]))
                self.crop_t_var.set(str(new_values[1]))
                self.crop_r_var.set(str(new_values[2]))
                self.crop_b_var.set(str(new_values[3]))
            else:
                self.crop_l_var.set(str(new_l))
                self.crop_t_var.set(str(new_t))
                self.crop_r_var.set(str(new_r))
                self.crop_b_var.set(str(new_b))
            self.crop_w_var.set(str(max(1, w)))
            self.crop_h_var.set(str(max(1, h)))
            self.crop_a_var.set(self._format_aspect(w, h))
        finally:
            self._loading = prev_loading
            self._suppress_crop_sync = prev_suppress
        self.on_dirty()
        self._draw_crop_overlay()

    @staticmethod
    def _resolve_crop_for_overlay(crop: Any, iw: int, ih: int) -> tuple[int, int, int, int] | None:
        if isinstance(crop, (list, tuple)) and len(crop) == 4:
            return tuple(int(v) for v in crop)  # type: ignore[return-value]
        if isinstance(crop, dict):
            if "box" in crop and crop["box"]:
                v = crop["box"]
                return (int(v[0]), int(v[1]), int(v[2]), int(v[3]))
            if "margins" in crop and crop["margins"]:
                ml, mt, mr, mb = (int(v) for v in crop["margins"])
                return (ml, mt, max(ml + 1, iw - mr), max(mt + 1, ih - mb))
            if "center" in crop and crop["center"]:
                cw, ch = (int(v) for v in crop["center"])
                if cw <= 0 or ch <= 0:
                    return None
                l = max(0, (iw - cw) // 2)
                t = max(0, (ih - ch) // 2)
                return (l, t, l + cw, t + ch)
        return None

    def _clear_preview(self, hint: str) -> None:
        self._preview_image = None
        self._preview_tk = None
        self._cur_preview_key = None
        self._last_render_sig = None
        self.preview_canvas.delete("all")
        cw = max(self.preview_canvas.winfo_width(), 1)
        ch = max(self.preview_canvas.winfo_height(), 1)
        self.preview_canvas.create_text(
            cw // 2, ch // 2, text=hint,
            fill=C_TEXT_DIM, font=("", 14), tags=("preview_text",),
        )
        self.preview_status_var.set("")

    # -------- zoom/pan helpers --------

    def _preview_zoom_in(self) -> None:
        self._preview_fit = False
        self._preview_user_zoom = min(self._preview_scale * 1.25, 8.0)
        self._blit_preview()

    def _preview_zoom_out(self) -> None:
        self._preview_fit = False
        self._preview_user_zoom = max(self._preview_scale / 1.25, 0.05)
        self._blit_preview()

    def _preview_zoom_fit(self) -> None:
        self._preview_fit = True
        self._blit_preview()

    def _on_preview_wheel(self, event: tk.Event) -> None:
        direction = 1 if event.delta > 0 else -1
        self._preview_wheel(direction, event)

    def _preview_wheel(self, direction: int, _event: tk.Event) -> None:
        if direction > 0:
            self._preview_zoom_in()
        else:
            self._preview_zoom_out()

    # ===================================================================
    # Helpers
    # ===================================================================

    def _phone_names(self) -> list[str]:
        return list((self.data.get("phones") or {}).keys())

    def refresh_phone_choices(self) -> None:
        # Inspector is rebuilt on next selection change; nothing to update live.
        pass

    def _first_brand(self) -> str | None:
        names = brand_io.list_brand_names(self.data)
        return names[0] if names else None

    def _card(self, parent: tk.Widget, title: str) -> ttk.Frame:
        wrap = ttk.LabelFrame(parent, text=title, padding=6)
        wrap.pack(fill="x", padx=8, pady=4)
        return wrap

    def _relative_to_assets(self, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(self.assets_dir.resolve())
            return rel.as_posix()
        except ValueError:
            return path.resolve().as_posix()
