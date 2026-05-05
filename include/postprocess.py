"""Post-processing: final cropping and color adjustments.

Configured via the optional `post_process` block in YAML, either at brand
level (applies to every screenshot in the brand) or at screenshot level
(overrides the brand-level block entirely).

Pipeline order:
    1. crop      (absolute box | center | margins)
    2. adjust    (brightness, contrast, saturation, sharpness, grayscale)

Runs *before* the optional `output_size` final resize, so cropped/adjusted
images still get scaled to the brand's target output dimensions.
"""
from typing import Any, Dict, Tuple

from PIL import Image, ImageEnhance


def _resolve_crop_box(image: Image.Image, crop: Any) -> Tuple[int, int, int, int] | None:
    """Resolve a YAML `crop` value into a (left, top, right, bottom) box."""
    if crop is None:
        return None
    w, h = image.size

    # Plain list/tuple => absolute box [l, t, r, b]
    if isinstance(crop, (list, tuple)):
        if len(crop) != 4:
            raise ValueError("crop list must be [left, top, right, bottom]")
        l, t, r, b = (int(v) for v in crop)
        return l, t, r, b

    if isinstance(crop, dict):
        if "box" in crop:
            l, t, r, b = (int(v) for v in crop["box"])
            return l, t, r, b
        if "center" in crop:
            cw, ch = (int(v) for v in crop["center"])
            l = max(0, (w - cw) // 2)
            t = max(0, (h - ch) // 2)
            return l, t, l + cw, t + ch
        if "margins" in crop:
            ml, mt, mr, mb = (int(v) for v in crop["margins"])
            return ml, mt, w - mr, h - mb
        raise ValueError("crop dict must contain 'box', 'center', or 'margins'")

    raise ValueError(f"Unsupported crop value: {crop!r}")


def _apply_crop(image: Image.Image, crop: Any) -> Image.Image:
    box = _resolve_crop_box(image, crop)
    if box is None:
        return image
    l, t, r, b = box
    w, h = image.size
    # Clamp to image bounds; PIL would fill with black otherwise.
    l = max(0, min(l, w))
    t = max(0, min(t, h))
    r = max(l + 1, min(r, w))
    b = max(t + 1, min(b, h))
    return image.crop((l, t, r, b))


def _enhance(image: Image.Image, factory, factor: float) -> Image.Image:
    if factor is None or float(factor) == 1.0:
        return image
    return factory(image).enhance(float(factor))


def _apply_adjust(image: Image.Image, adjust: Dict[str, Any] | None) -> Image.Image:
    if not adjust:
        return image

    if adjust.get("grayscale"):
        # Preserve alpha while desaturating RGB.
        if image.mode == "RGBA":
            r, g, b, a = image.split()
            gray = Image.merge("RGB", (r, g, b)).convert("L").convert("RGB")
            r2, g2, b2 = gray.split()
            image = Image.merge("RGBA", (r2, g2, b2, a))
        else:
            image = image.convert("L").convert(image.mode)

    image = _enhance(image, ImageEnhance.Brightness, adjust.get("brightness", 1.0))
    image = _enhance(image, ImageEnhance.Contrast,   adjust.get("contrast",   1.0))
    image = _enhance(image, ImageEnhance.Color,      adjust.get("saturation", 1.0))
    image = _enhance(image, ImageEnhance.Sharpness,  adjust.get("sharpness",  1.0))
    return image


def apply_post_process(image: Image.Image, cfg: Dict[str, Any] | None) -> Image.Image:
    if not cfg:
        return image
    image = _apply_crop(image, cfg.get("crop"))
    image = _apply_adjust(image, cfg.get("adjust"))
    return image
