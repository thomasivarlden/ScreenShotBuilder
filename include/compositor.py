"""Composite a single output image: warped screenshot + base + labels + stamps."""
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from .perspective import warp_to_quad
from .postprocess import apply_post_process

Point = Tuple[float, float]


def _to_point(v: Sequence) -> Point:
    return (float(v[0]), float(v[1]))


def _quad_from_corners(corners: Dict[str, Sequence]) -> List[Point]:
    return [
        _to_point(corners["top_left"]),
        _to_point(corners["top_right"]),
        _to_point(corners["bottom_right"]),
        _to_point(corners["bottom_left"]),
    ]


def _load_font(font_path: str | None, size: int, assets_dir: Path) -> ImageFont.FreeTypeFont:
    if font_path:
        candidate = Path(font_path)
        if not candidate.is_absolute():
            candidate = assets_dir / candidate
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    # Fallbacks: look for common system fonts, else default.
    for sys_font in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(sys_font).is_file():
            try:
                return ImageFont.truetype(sys_font, size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def _draw_label(
    canvas: Image.Image,
    label: Dict[str, Any],
    assets_dir: Path,
) -> None:
    text = str(label.get("text", ""))
    if not text:
        return
    pos = _to_point(label.get("position", [0, 0]))
    color = label.get("color", "#000000")
    shadow_color = label.get("shadow_color")
    shadow_offset = label.get("shadow_offset", [2, 2])
    font = _load_font(label.get("font"), int(label.get("font_size", 48)), assets_dir)
    anchor = label.get("anchor")  # e.g. "mm" for centered

    draw = ImageDraw.Draw(canvas)
    if shadow_color:
        sx, sy = float(shadow_offset[0]), float(shadow_offset[1])
        draw.text(
            (pos[0] + sx, pos[1] + sy),
            text,
            font=font,
            fill=shadow_color,
            anchor=anchor,
        )
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

    bg_color = brand_cfg.get("background_color", [0, 0, 0, 0])
    canvas = Image.new("RGBA", base.size, tuple(bg_color))

    shot_path = assets_dir / shot_cfg["source"]
    if not shot_path.is_file():
        raise FileNotFoundError(f"Screenshot source not found: {shot_path}")
    screenshot = Image.open(shot_path).convert("RGBA")

    quad = _quad_from_corners(brand_cfg["screen_corners"])
    warped = warp_to_quad(screenshot, base.size, quad)

    # Screenshot goes BEHIND the base (so transparent display reveals it).
    canvas.alpha_composite(warped)
    canvas.alpha_composite(base)

    for stamp_cfg in shot_cfg.get("stamps", []) or []:
        _apply_stamp(canvas, stamp_cfg, assets_dir)

    for label in shot_cfg.get("labels", []) or []:
        _draw_label(canvas, label, assets_dir)

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
