"""Round-trip YAML I/O for the GUI editor.

Uses ruamel.yaml so saves preserve comments, key order, and quoting style.
The process side (build pipeline) keeps using PyYAML safe_load — read only.
"""
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.scalarint import ScalarInt


def make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 120
    return y


_PATH_KEYS = frozenset({"base_image", "background_image", "source", "font"})


def _normalize_path_separators(node: Any) -> None:
    """Convert backslashes to forward slashes in path-valued keys, in place.

    Configs authored on Windows save with `\\`; on POSIX those don't resolve.
    """
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k in _PATH_KEYS and isinstance(v, str) and "\\" in v:
                node[k] = v.replace("\\", "/")
            else:
                _normalize_path_separators(v)
    elif isinstance(node, list):
        for item in node:
            _normalize_path_separators(item)


def load_round_trip(path: Path) -> Any:
    y = make_yaml()
    with path.open("r", encoding="utf-8") as fh:
        data = y.load(fh)
    _normalize_path_separators(data)
    return data


def save_round_trip(path: Path, data: Any) -> None:
    y = make_yaml()
    with path.open("w", encoding="utf-8") as fh:
        y.dump(data, fh)


def update_phone_corners(
    data: Any,
    phone_name: str,
    corners: dict[str, tuple[int, int]],
) -> None:
    """Replace screen_corners for the named phone, in-place on a round-trip doc."""
    if "phones" not in data or phone_name not in data["phones"]:
        raise KeyError(f"phone '{phone_name}' not found in YAML")
    phone = data["phones"][phone_name]
    sc = phone.setdefault("screen_corners", {})
    for key in ("top_left", "top_right", "bottom_right", "bottom_left"):
        x, y = corners[key]
        sc[key] = [int(x), int(y)]


def update_phone_corner_radius(data: Any, phone_name: str, radius: int | None) -> None:
    """Set or remove the corner_radius for the named phone."""
    if "phones" not in data or phone_name not in data["phones"]:
        raise KeyError(f"phone '{phone_name}' not found in YAML")
    phone = data["phones"][phone_name]
    if radius is None or radius <= 0:
        if "corner_radius" in phone:
            del phone["corner_radius"]
    else:
        phone["corner_radius"] = int(radius)
