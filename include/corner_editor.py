"""Tk Canvas widget: draggable 4-corner editor with optional warp preview."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from PIL import Image, ImageTk

from .perspective import warp_to_quad

CORNER_KEYS: Tuple[str, str, str, str] = (
    "top_left",
    "top_right",
    "bottom_right",
    "bottom_left",
)
HANDLE_RADIUS = 9
HANDLE_FILL = "#ff3b30"
HANDLE_OUTLINE = "#ffffff"
LINE_COLOR = "#ff3b30"


class CornerEditor:
    """Encapsulates a Tk Canvas that displays a base image with four
    draggable corner handles. Optionally shows a screenshot warped behind."""

    def __init__(
        self,
        canvas: tk.Canvas,
        on_change: Callable[[Dict[str, Tuple[int, int]]], None] | None = None,
        on_zoom_change: Callable[[float], None] | None = None,
    ):
        self.canvas = canvas
        self.on_change = on_change
        self.on_zoom_change = on_zoom_change

        self._base_pil: Image.Image | None = None
        self._screenshot_pil: Image.Image | None = None
        self._composite_tk: ImageTk.PhotoImage | None = None

        # Zoom: when _fit_mode is True, the image auto-fits the canvas.
        # Otherwise _user_zoom is the absolute scale factor (1.0 = 100%).
        self._fit_mode: bool = True
        self._user_zoom: float = 1.0

        self._scale: float = 1.0
        self._image_id: int | None = None
        self._line_ids: List[int] = []
        self._handle_ids: Dict[str, int] = {}
        self._label_ids: Dict[str, int] = {}

        # Corners in IMAGE pixel coords (not canvas coords).
        self._corners: Dict[str, Tuple[int, int]] = {}
        self._dragging: str | None = None
        # Pan mode is toggled by the host (e.g. while spacebar is held);
        # in pan mode the left mouse button drags the viewport instead of
        # grabbing a corner handle.
        self.pan_mode: bool = False
        self._panning: bool = False

        canvas.bind("<Button-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Configure>", lambda _e: self._redraw())

    # ---------- public API ------------------------------------------------

    def load_base(self, path: Path, corners: Dict[str, Tuple[int, int]]) -> None:
        self._base_pil = Image.open(path).convert("RGBA")
        self._corners = {k: tuple(corners[k]) for k in CORNER_KEYS}
        self._redraw()

    def load_screenshot(self, path: Path | None) -> None:
        self._screenshot_pil = (
            Image.open(path).convert("RGBA") if path else None
        )
        self._redraw()

    def get_corners(self) -> Dict[str, Tuple[int, int]]:
        return {k: (int(v[0]), int(v[1])) for k, v in self._corners.items()}

    # ---------- zoom -----------------------------------------------------

    def get_zoom(self) -> float:
        """Effective scale factor (1.0 = 100%)."""
        return self._scale

    def zoom_in(self) -> None:
        self._set_zoom(self._scale * 1.25)

    def zoom_out(self) -> None:
        self._set_zoom(self._scale / 1.25)

    def zoom_reset(self) -> None:
        self._fit_mode = True
        self._redraw()
        self._fire_zoom()

    def _set_zoom(self, scale: float) -> None:
        scale = max(0.05, min(scale, 16.0))
        self._fit_mode = False
        self._user_zoom = scale
        self._redraw()
        self._fire_zoom()

    def _fire_zoom(self) -> None:
        if self.on_zoom_change is not None:
            self.on_zoom_change(self._scale)

    def zoom_at_cursor(self, factor: float, view_x: float, view_y: float) -> None:
        """Zoom by `factor` keeping the image point under the cursor stationary."""
        if self._base_pil is None:
            return
        # Image coord under cursor before zoom
        cx = self.canvas.canvasx(view_x)
        cy = self.canvas.canvasy(view_y)
        ix, iy = self._canvas_to_img(cx, cy)
        new_scale = max(0.05, min(self._scale * factor, 16.0))
        self._fit_mode = False
        self._user_zoom = new_scale
        self._redraw()
        # After redraw, scroll so (ix, iy) sits under the same view point.
        new_cx = ix * self._scale
        new_cy = iy * self._scale
        bw, bh = self._base_pil.size
        sw = max(1, int(bw * self._scale))
        sh = max(1, int(bh * self._scale))
        target_x = new_cx - view_x
        target_y = new_cy - view_y
        self.canvas.xview_moveto(max(0.0, min(1.0, target_x / sw)))
        self.canvas.yview_moveto(max(0.0, min(1.0, target_y / sh)))
        self._fire_zoom()

    def reset_corners_to_image_bounds(self) -> None:
        if self._base_pil is None:
            return
        w, h = self._base_pil.size
        m = int(min(w, h) * 0.15)
        self._corners = {
            "top_left":     (m, m),
            "top_right":    (w - m, m),
            "bottom_right": (w - m, h - m),
            "bottom_left":  (m, h - m),
        }
        self._redraw()
        self._notify()

    # ---------- coord conversion -----------------------------------------

    def _img_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        return x * self._scale, y * self._scale

    def _canvas_to_img(self, x: float, y: float) -> Tuple[int, int]:
        if self._scale == 0:
            return (0, 0)
        return int(round(x / self._scale)), int(round(y / self._scale))

    # ---------- drawing --------------------------------------------------

    def _compute_scale(self) -> float:
        if self._base_pil is None:
            return 1.0
        if self._fit_mode:
            cw = max(self.canvas.winfo_width(), 1)
            ch = max(self.canvas.winfo_height(), 1)
            bw, bh = self._base_pil.size
            return min(cw / bw, ch / bh, 1.0)  # fit, never upscale beyond 1:1
        return self._user_zoom

    def _build_composite(self) -> Image.Image | None:
        if self._base_pil is None:
            return None
        base = self._base_pil
        composed = Image.new("RGBA", base.size, (32, 32, 36, 255))
        if self._screenshot_pil is not None:
            quad = [self._corners[k] for k in CORNER_KEYS]
            try:
                warped = warp_to_quad(self._screenshot_pil, base.size, quad)
                composed.alpha_composite(warped)
            except Exception:
                # Degenerate quad — skip the warp this frame.
                pass
        composed.alpha_composite(base)
        return composed

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._image_id = None
        self._line_ids.clear()
        self._handle_ids.clear()
        self._label_ids.clear()
        if self._base_pil is None:
            return

        self._scale = self._compute_scale()
        composite = self._build_composite()
        if composite is None:
            return
        bw, bh = composite.size
        disp_w = max(1, int(bw * self._scale))
        disp_h = max(1, int(bh * self._scale))
        scaled = composite.resize((disp_w, disp_h), Image.LANCZOS)
        self._composite_tk = ImageTk.PhotoImage(scaled)
        self._image_id = self.canvas.create_image(
            0, 0, anchor="nw", image=self._composite_tk
        )
        # Allow the canvas to scroll the full scaled image when zoomed in.
        self.canvas.config(scrollregion=(0, 0, disp_w, disp_h))

        # Dashed quad
        pts = [self._img_to_canvas(*self._corners[k]) for k in CORNER_KEYS]
        for i in range(4):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 4]
            line = self.canvas.create_line(
                x1, y1, x2, y2, fill=LINE_COLOR, dash=(6, 4), width=2
            )
            self._line_ids.append(line)

        # Handles + coord labels
        for key in CORNER_KEYS:
            cx, cy = self._img_to_canvas(*self._corners[key])
            self._handle_ids[key] = self.canvas.create_oval(
                cx - HANDLE_RADIUS, cy - HANDLE_RADIUS,
                cx + HANDLE_RADIUS, cy + HANDLE_RADIUS,
                fill=HANDLE_FILL, outline=HANDLE_OUTLINE, width=2,
                tags=("handle", key),
            )
            ix, iy = self._corners[key]
            self._label_ids[key] = self.canvas.create_text(
                cx + 14, cy - 14,
                text=f"{key}\n{ix}, {iy}",
                fill="#ffffff", anchor="sw",
                font=("Helvetica", 10, "bold"),
            )

        # Notify listeners about the now-current effective zoom (for fit mode
        # this changes whenever the canvas is resized).
        self._fire_zoom()

    def _hit_test(self, x: float, y: float) -> str | None:
        for key, hid in self._handle_ids.items():
            x1, y1, x2, y2 = self.canvas.coords(hid)
            if x1 <= x <= x2 and y1 <= y <= y2:
                return key
        return None

    # ---------- mouse events --------------------------------------------

    def _on_press(self, event: tk.Event) -> None:
        if self.pan_mode:
            self.canvas.scan_mark(event.x, event.y)
            self._panning = True
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self._dragging = self._hit_test(cx, cy)

    def _on_drag(self, event: tk.Event) -> None:
        if self._panning:
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return
        if self._dragging is None or self._base_pil is None:
            return
        bw, bh = self._base_pil.size
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        ix, iy = self._canvas_to_img(cx, cy)
        ix = max(0, min(bw, ix))
        iy = max(0, min(bh, iy))
        self._corners[self._dragging] = (ix, iy)
        # Cheap update: move handle + redraw lines + label, skip warp.
        cx, cy = self._img_to_canvas(ix, iy)
        self.canvas.coords(
            self._handle_ids[self._dragging],
            cx - HANDLE_RADIUS, cy - HANDLE_RADIUS,
            cx + HANDLE_RADIUS, cy + HANDLE_RADIUS,
        )
        self.canvas.coords(self._label_ids[self._dragging], cx + 14, cy - 14)
        self.canvas.itemconfig(
            self._label_ids[self._dragging],
            text=f"{self._dragging}\n{ix}, {iy}",
        )
        # Redraw the dashed quad
        for i, line_id in enumerate(self._line_ids):
            a = CORNER_KEYS[i]
            b = CORNER_KEYS[(i + 1) % 4]
            ax, ay = self._img_to_canvas(*self._corners[a])
            bx, by = self._img_to_canvas(*self._corners[b])
            self.canvas.coords(line_id, ax, ay, bx, by)
        self._notify()

    def _on_release(self, _event: tk.Event) -> None:
        if self._panning:
            self._panning = False
            return
        if self._dragging is not None:
            self._dragging = None
            # Full redraw: re-warps screenshot preview if loaded.
            self._redraw()
            self._notify()

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change(self.get_corners())
