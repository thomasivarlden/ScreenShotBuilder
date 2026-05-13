"""Composite a single output image: warped screenshot + base + labels + stamps."""
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .perspective import warp_to_quad
from .postprocess import apply_post_process

Point = Tuple[float, float]


def _to_point(v: Sequence) -> Point:
    return (float(v[0]), float(v[1]))


def _norm_color(color: Any) -> str | None:
    """Return a PIL-compatible color string, or None if input is empty/None."""
    if not color:
        return None
    s = str(color).strip()
    if not s:
        return None
    # Bare hex digits without '#' — 3 or 6 char forms.
    if s[0] != "#" and all(c in "0123456789abcdefABCDEF" for c in s) and len(s) in (3, 6):
        s = "#" + s
    return s


def _round_corners(image: Image.Image, radius_base_px: float, quad: List[Point]) -> Image.Image:
    """Apply a rounded-rect alpha mask to `image` (the screenshot).

    `radius_base_px` is given in *base-image* pixels (i.e. matches the units
    of `screen_corners`). It's scaled into screenshot space using the average
    width of the quad, so the curve looks consistent regardless of screenshot
    resolution.
    """
    import math
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = quad
    top_w = math.hypot(trx - tlx, try_ - tly)
    bottom_w = math.hypot(brx - blx, bry - bly)
    avg_quad_w = max(1.0, (top_w + bottom_w) / 2.0)
    scale = image.width / avg_quad_w
    r = max(0, int(round(radius_base_px * scale)))
    if r <= 0:
        return image
    # Clamp to half the shorter side to avoid invalid radii.
    r = min(r, image.width // 2, image.height // 2)
    if r <= 0:
        return image

    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1), radius=r, fill=255,
    )
    out = image.copy()
    # Combine the rounded mask with whatever alpha the screenshot already had.
    combined_alpha = ImageChops.multiply(out.getchannel("A"), mask)
    out.putalpha(combined_alpha)
    return out


def _quad_from_corners(corners: Dict[str, Sequence]) -> List[Point]:
    return [
        _to_point(corners["top_left"]),
        _to_point(corners["top_right"]),
        _to_point(corners["bottom_right"]),
        _to_point(corners["bottom_left"]),
    ]


_BOLD_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",          # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",        # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",                                # Windows
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/tahomabd.ttf",
)
_REGULAR_FONTS = (
    "/System/Library/Fonts/Helvetica.ttc",                         # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",             # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/Arial.ttf",                                  # Windows
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
)


def _load_font(font_path: str | None, size: int, assets_dir: Path,
               bold: bool = False) -> ImageFont.FreeTypeFont:
    if font_path:
        candidate = Path(font_path)
        if not candidate.is_absolute():
            candidate = assets_dir / candidate
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    # Try bold variants first when bold is requested, then fall back to regular.
    candidates = (_BOLD_FONTS + _REGULAR_FONTS) if bold else (_REGULAR_FONTS + _BOLD_FONTS)
    for sys_font in candidates:
        if Path(sys_font).is_file():
            try:
                return ImageFont.truetype(sys_font, size=size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _measure_text_bbox(
    text: str,
    pos: Point,
    font: ImageFont.FreeTypeFont,
    anchor: str | None,
) -> tuple[float, float, float, float]:
    """Return (left, top, right, bottom) of `text` rendered at `pos` with `anchor`."""
    dummy = Image.new("L", (1, 1))
    bbox = ImageDraw.Draw(dummy).textbbox(pos, text, font=font, anchor=anchor)
    return bbox


def _fit_anchor(fit_align: str, source_anchor: str | None) -> str:
    """Build a PIL anchor string with the horizontal component replaced by fit_align.

    When source_anchor is None, PIL defaults to 'la' (left, ascender-top), so
    we preserve 'a' as the vertical component — not 's' (baseline), which would
    shift text up significantly at large font sizes.
    """
    v = source_anchor[1] if source_anchor and len(source_anchor) >= 2 else "a"
    h = {"center": "m", "right": "r"}.get(fit_align, "l")
    return h + v


def _draw_label(
    canvas: Image.Image,
    label: Dict[str, Any],
    assets_dir: Path,
) -> None:
    text = str(label.get("text", ""))
    if not text:
        return
    pos = _to_point(label.get("position", [0, 0]))
    color = _norm_color(label.get("color")) or "#000000"
    shadow_color = _norm_color(label.get("shadow_color"))
    shadow_offset = label.get("shadow_offset", [4, 4])
    shadow_blur = max(0, int(label.get("shadow_blur") or 0))
    font = _load_font(label.get("font"), int(label.get("font_size") or 48), assets_dir,
                      bold=bool(label.get("bold")))
    anchor = label.get("anchor") or None

    # Fit-align: adjust pos/anchor so the translated text aligns with the
    # spatial center or right edge of the source (English) text.
    fit_align = label.get("_fit_align")
    if fit_align in ("center", "right"):
        src_text = str(label.get("_source_text", ""))
        src_pos = _to_point(label.get("_source_position", list(pos)))
        src_anchor = label.get("_source_anchor") or None
        src_font = _load_font(
            label.get("_source_font"),
            int(label.get("_source_font_size") or 48),
            assets_dir,
            bold=bool(label.get("_source_bold")),
        )
        if src_text:
            l, _t, r, _b = _measure_text_bbox(src_text, src_pos, src_font, src_anchor)
            if fit_align == "center":
                target_x = (l + r) / 2.0
            else:  # right
                target_x = r
            pos = (target_x, pos[1])
            anchor = _fit_anchor(fit_align, src_anchor)

    draw = ImageDraw.Draw(canvas)
    if shadow_color:
        sx, sy = float(shadow_offset[0]), float(shadow_offset[1])
        if shadow_blur > 0:
            shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow_layer).text(
                (pos[0] + sx, pos[1] + sy), text,
                font=font, fill=shadow_color, anchor=anchor,
            )
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
            canvas.alpha_composite(shadow_layer)
        else:
            draw.text((pos[0] + sx, pos[1] + sy), text,
                      font=font, fill=shadow_color, anchor=anchor)
    draw.text(pos, text, font=font, fill=color, anchor=anchor)


def _apply_stamp(
    canvas: Image.Image,
    stamp_cfg: Dict[str, Any],
    assets_dir: Path,
) -> None:
    src_path = assets_dir / stamp_cfg["source"]
    if not src_path.is_file():
        raise FileNotFoundError(f"Stamp source not found: {src_path}")
    stamp = Image.open(src_path).convert("RGBA")
    scale = float(stamp_cfg.get("scale", 1.0))
    if scale != 1.0:
        new_size = (max(1, int(stamp.width * scale)), max(1, int(stamp.height * scale)))
        stamp = stamp.resize(new_size, Image.LANCZOS)
    opacity = max(0.0, min(1.0, float(stamp_cfg.get("opacity", 1.0))))
    if opacity < 1.0:
        r, g, b, a = stamp.split()
        a = a.point(lambda v: int(v * opacity))
        stamp = Image.merge("RGBA", (r, g, b, a))
    pos = _to_point(stamp_cfg.get("position", [0, 0]))
    canvas.alpha_composite(stamp, dest=(int(pos[0]), int(pos[1])))


def build_composite(
    brand_cfg: Dict[str, Any],
    shot_cfg: Dict[str, Any],
    assets_dir: Path,
) -> Image.Image:
    """Compose a single screenshot output and return an RGBA image."""
    base_path = assets_dir / brand_cfg["base_image"]
    if not base_path.is_file():
        raise FileNotFoundError(f"Base image not found: {base_path}")
    base = Image.open(base_path).convert("RGBA")

    pad = brand_cfg.get("phone_padding") or {}
    pad_t = max(0, int(pad.get("top") or 0)) if isinstance(pad, dict) else 0
    pad_r = max(0, int(pad.get("right") or 0)) if isinstance(pad, dict) else 0
    pad_b = max(0, int(pad.get("bottom") or 0)) if isinstance(pad, dict) else 0
    pad_l = max(0, int(pad.get("left") or 0)) if isinstance(pad, dict) else 0
    canvas_w = base.width + pad_l + pad_r
    canvas_h = base.height + pad_t + pad_b

    bg_color = brand_cfg.get("background_color", [0, 0, 0, 0])
    canvas = Image.new("RGBA", (canvas_w, canvas_h), tuple(bg_color))

    bg_image_rel = brand_cfg.get("background_image")
    if bg_image_rel:
        bg_path = assets_dir / bg_image_rel
        if not bg_path.is_file():
            raise FileNotFoundError(f"Background image not found: {bg_path}")
        bg = Image.open(bg_path).convert("RGBA")
        tw, th = canvas_w, canvas_h

        bg_off = shot_cfg.get("background_offset")
        off_left = int(bg_off.get("left") or 0) if isinstance(bg_off, dict) else 0
        off_top = int(bg_off.get("top") or 0) if isinstance(bg_off, dict) else 0

        # Skip `off_left` source columns and `off_top` source rows from the
        # bg image, then cover-fit the remainder to the canvas. This keeps
        # the bg filling the canvas at all offsets, just panned into the
        # source image.
        l = max(0, off_left)
        t = max(0, off_top)
        rem_w = bg.width - l
        rem_h = bg.height - t
        # If the offset eats too much of the source, the cover-fit would
        # blow up the remaining sliver to a huge image and freeze the UI.
        # Require at least 16 px on each axis; otherwise skip the bg and
        # let `background_color` show through.
        if rem_w >= 16 and rem_h >= 16:
            if l > 0 or t > 0:
                bg = bg.crop((l, t, bg.width, bg.height))

            bg_scale = float(brand_cfg.get("background_scale") or 1.0)
            scale = max(tw / bg.width, th / bg.height) * bg_scale
            new_size = (max(1, int(round(bg.width * scale))),
                        max(1, int(round(bg.height * scale))))
            bg = bg.resize(new_size, Image.LANCZOS)
            cl = (bg.width - tw) // 2
            ct = (bg.height - th) // 2
            bg = bg.crop((cl, ct, cl + tw, ct + th))
            canvas.alpha_composite(bg)

    shot_path = assets_dir / shot_cfg["source"]
    if not shot_path.is_file():
        raise FileNotFoundError(f"Screenshot source not found: {shot_path}")
    screenshot = Image.open(shot_path).convert("RGBA")

    quad = _quad_from_corners(brand_cfg["screen_corners"])

    # Optional rounded corners. The radius is given in base-image pixels; we
    # convert it to screenshot pixels so the curve is applied before warping.
    radius_base = brand_cfg.get("corner_radius")
    if radius_base and float(radius_base) > 0:
        screenshot = _round_corners(screenshot, float(radius_base), quad)

    warped = warp_to_quad(screenshot, base.size, quad)

    # Composite warp + phone frame onto the padded canvas.
    phone_canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
    phone_canvas.alpha_composite(warped)
    phone_canvas.alpha_composite(base)
    canvas.alpha_composite(phone_canvas, dest=(pad_l, pad_t))

    # Labels and stamps are drawn on the full padded canvas so that their
    # x/y coordinates match what the preview coordinate readout shows.
    for label in shot_cfg.get("labels", []) or []:
        _draw_label(canvas, label, assets_dir)

    for stamp_cfg in shot_cfg.get("stamps", []) or []:
        _apply_stamp(canvas, stamp_cfg, assets_dir)

    # Post-process: shot-level overrides brand-level entirely if present.
    pp_cfg = shot_cfg.get("post_process", brand_cfg.get("post_process"))
    canvas = apply_post_process(canvas, pp_cfg)

    final_size = brand_cfg.get("output_size")
    if final_size:
        canvas = canvas.resize(
            (int(final_size[0]), int(final_size[1])),
            Image.LANCZOS,
        )
    return canvas
