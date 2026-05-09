"""Round-trip helpers for editing the `brands:` section of screenshots.yaml.

Mirrors yaml_io.update_phone_corners but for brand-level fields. All mutations
operate in place on the ruamel CommentedMap loaded by load_round_trip, so
comments, ordering, and quoting are preserved.
"""
from __future__ import annotations

from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq


def ensure_brands(data: Any) -> CommentedMap:
    if "brands" not in data or data["brands"] is None:
        data["brands"] = CommentedMap()
    return data["brands"]


def list_brand_names(data: Any) -> list[str]:
    brands = data.get("brands") or {}
    return list(brands.keys())


def add_brand(data: Any, name: str, phone: str | None = None) -> CommentedMap:
    brands = ensure_brands(data)
    if name in brands:
        raise ValueError(f"brand {name!r} already exists")
    new_brand = CommentedMap()
    if phone:
        new_brand["phone"] = phone
    new_brand["screenshots"] = CommentedSeq()
    brands[name] = new_brand
    return new_brand


def delete_brand(data: Any, name: str) -> None:
    brands = ensure_brands(data)
    if name in brands:
        del brands[name]


def _set_or_remove(brand: CommentedMap, key: str, value: Any) -> None:
    """Write `key=value`, or remove the key entirely if value is None."""
    if value is None:
        if key in brand:
            del brand[key]
    else:
        brand[key] = value


def update_brand(
    data: Any,
    name: str,
    *,
    phone: str | None = None,
    background_color: list[int] | None = None,
    background_image: str | None = None,
    background_scale: float | None = None,
    phone_padding: dict | None = None,
    output_size: list[int] | None = None,
) -> None:
    """Update one brand's top-level fields. Pass None to remove a key."""
    brands = ensure_brands(data)
    if name not in brands:
        raise KeyError(f"brand {name!r} not found")
    brand = brands[name]
    if phone is not None:
        brand["phone"] = phone
    _set_or_remove(brand, "background_color", background_color)
    _set_or_remove(brand, "background_image", background_image)
    _set_or_remove(brand, "background_scale", background_scale)
    _set_or_remove(brand, "phone_padding", phone_padding)
    _set_or_remove(brand, "output_size", output_size)


def get_screenshots(data: Any, name: str) -> CommentedSeq:
    brand = data["brands"][name]
    if "screenshots" not in brand or brand["screenshots"] is None:
        brand["screenshots"] = CommentedSeq()
    return brand["screenshots"]


def add_screenshot(data: Any, name: str, *, source: str = "", output: str = "") -> CommentedMap:
    shots = get_screenshots(data, name)
    shot = CommentedMap()
    shot["source"] = source
    shot["output"] = output
    shots.append(shot)
    return shot


def delete_screenshot(data: Any, name: str, index: int) -> None:
    shots = get_screenshots(data, name)
    if 0 <= index < len(shots):
        del shots[index]


def update_screenshot(
    data: Any,
    name: str,
    index: int,
    *,
    source: str | None = None,
    output: str | None = None,
    phone: str | None | object = ...,
) -> None:
    """Update an output entry. Pass `phone=None` to remove the field;
    omit it (sentinel) to leave it untouched."""
    shots = get_screenshots(data, name)
    if not (0 <= index < len(shots)):
        raise IndexError(f"screenshot index {index} out of range for brand {name!r}")
    shot = shots[index]
    if source is not None:
        shot["source"] = source
    if output is not None:
        shot["output"] = output
    if phone is not ...:
        if phone is None or phone == "":
            if "phone" in shot:
                del shot["phone"]
        else:
            shot["phone"] = phone


# ---------- labels (per output) -------------------------------------

def _shot(data: Any, brand: str, index: int) -> CommentedMap:
    shots = get_screenshots(data, brand)
    if not (0 <= index < len(shots)):
        raise IndexError(f"output index {index} out of range")
    return shots[index]


def get_labels(data: Any, brand: str, shot_index: int) -> CommentedSeq:
    shot = _shot(data, brand, shot_index)
    if "labels" not in shot or shot["labels"] is None:
        shot["labels"] = CommentedSeq()
    return shot["labels"]


def add_label(data: Any, brand: str, shot_index: int) -> CommentedMap:
    labels = get_labels(data, brand, shot_index)
    label = CommentedMap()
    label["text"] = "New label"
    label["position"] = [100, 100]
    label["font_size"] = 64
    label["color"] = "#000000"
    labels.append(label)
    return label


def delete_label(data: Any, brand: str, shot_index: int, label_index: int) -> None:
    labels = get_labels(data, brand, shot_index)
    if 0 <= label_index < len(labels):
        del labels[label_index]


def update_label(
    data: Any, brand: str, shot_index: int, label_index: int, **fields: Any,
) -> None:
    """Update fields on a label. Pass None to remove a key (except `text`)."""
    labels = get_labels(data, brand, shot_index)
    if not (0 <= label_index < len(labels)):
        raise IndexError(f"label index {label_index} out of range")
    label = labels[label_index]
    for k, v in fields.items():
        if v is None and k != "text":
            if k in label:
                del label[k]
        else:
            label[k] = v


# ---------- stamps (per output) -------------------------------------

def get_stamps(data: Any, brand: str, shot_index: int) -> CommentedSeq:
    shot = _shot(data, brand, shot_index)
    if "stamps" not in shot or shot["stamps"] is None:
        shot["stamps"] = CommentedSeq()
    return shot["stamps"]


def add_stamp(data: Any, brand: str, shot_index: int, *, source: str = "") -> CommentedMap:
    stamps = get_stamps(data, brand, shot_index)
    stamp = CommentedMap()
    stamp["source"] = source
    stamp["position"] = [40, 40]
    stamp["scale"] = 1.0
    stamps.append(stamp)
    return stamp


def delete_stamp(data: Any, brand: str, shot_index: int, stamp_index: int) -> None:
    stamps = get_stamps(data, brand, shot_index)
    if 0 <= stamp_index < len(stamps):
        del stamps[stamp_index]


def update_bg_offset(
    data: Any, brand: str, shot_index: int, *,
    top: int | None = None, left: int | None = None,
) -> None:
    """Set the per-output `background_offset: {top, left}` block.

    Each value is in source-pixel coordinates of the brand's background
    image. The compositor uses (left, top) as the upper-left of the
    canvas-sized window cropped from the bg. Pass 0 to clear that side;
    if both end up empty the whole block is removed.
    """
    shot = _shot(data, brand, shot_index)
    bg = shot.get("background_offset")
    if not isinstance(bg, dict):
        bg = CommentedMap()
    # Drop any legacy 'bottom' key from earlier iterations of this feature.
    bg.pop("bottom", None)

    if top is not None:
        if top > 0:
            bg["top"] = int(top)
        else:
            bg.pop("top", None)
    if left is not None:
        if left > 0:
            bg["left"] = int(left)
        else:
            bg.pop("left", None)

    if bg:
        shot["background_offset"] = bg
    elif "background_offset" in shot:
        del shot["background_offset"]


def update_post_process(
    data: Any, brand: str, shot_index: int, *,
    crop_mode: str | None = None,
    crop_values: list[int] | None = None,
    resize_width: int | None = None,
    resize_height: int | None = None,
) -> None:
    """Update an output's `post_process` block.

    crop_mode: "none" | "margins" | "box" | "center" | None (no change)
    crop_values: 4 ints for margins/box, 2 ints for center. None means clear.
    resize_width / resize_height: integer or None (None = remove that dim).

    Empty post_process is removed entirely so YAML stays clean.
    """
    shot = _shot(data, brand, shot_index)
    pp = shot.get("post_process")
    if pp is None or not isinstance(pp, dict):
        pp = CommentedMap()

    if crop_mode is not None:
        if crop_mode == "none" or not crop_values:
            if "crop" in pp:
                del pp["crop"]
        else:
            crop = CommentedMap()
            crop[crop_mode] = list(crop_values)
            pp["crop"] = crop

    # Resize: only touch if either dim was passed.
    rz = pp.get("resize")
    if resize_width is not None or resize_height is not None:
        if not isinstance(rz, dict):
            rz = CommentedMap()
        if resize_width is not None and resize_width > 0:
            rz["width"] = int(resize_width)
        else:
            rz.pop("width", None)
        if resize_height is not None and resize_height > 0:
            rz["height"] = int(resize_height)
        else:
            rz.pop("height", None)
        if rz:
            pp["resize"] = rz
        elif "resize" in pp:
            del pp["resize"]

    # Persist or strip.
    if pp:
        shot["post_process"] = pp
    elif "post_process" in shot:
        del shot["post_process"]


def update_stamp(
    data: Any, brand: str, shot_index: int, stamp_index: int, **fields: Any,
) -> None:
    stamps = get_stamps(data, brand, shot_index)
    if not (0 <= stamp_index < len(stamps)):
        raise IndexError(f"stamp index {stamp_index} out of range")
    stamp = stamps[stamp_index]
    for k, v in fields.items():
        if v is None:
            if k in stamp:
                del stamp[k]
        else:
            stamp[k] = v
