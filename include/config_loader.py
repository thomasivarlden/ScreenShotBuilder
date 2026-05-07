from pathlib import Path
from typing import Any, Dict, List

import yaml


class ConfigError(Exception):
    pass


CORNER_KEYS = ("top_left", "top_right", "bottom_right", "bottom_left")


def load_config(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError("Top-level YAML must be a mapping")
    if "brands" not in data or not isinstance(data["brands"], dict):
        raise ConfigError("Config must contain a 'brands' mapping")
    if "phones" in data and not isinstance(data["phones"], dict):
        raise ConfigError("'phones' must be a mapping of phone-name -> phone-config")
    return data


def _validate_phone(name: str, phone: Dict[str, Any]) -> None:
    if not isinstance(phone, dict):
        raise ConfigError(f"Phone '{name}' must be a mapping")
    if "base_image" not in phone:
        raise ConfigError(f"Phone '{name}' missing 'base_image'")
    if "screen_corners" not in phone:
        raise ConfigError(f"Phone '{name}' missing 'screen_corners'")
    corners = phone["screen_corners"]
    for c in CORNER_KEYS:
        if c not in corners:
            raise ConfigError(f"Phone '{name}' screen_corners missing '{c}'")
        pt = corners[c]
        if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
            raise ConfigError(f"Phone '{name}' corner '{c}' must be [x, y]")


def validate_phones(phones: Dict[str, Any]) -> None:
    for name, cfg in phones.items():
        _validate_phone(name, cfg)


def resolve_shot_phone(
    brand_name: str,
    brand: Dict[str, Any],
    shot: Dict[str, Any],
    phones: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    """Return (phone_name, phone_cfg) for one output (screenshot entry).

    Resolution order:
      1. shot.phone — per-output override (preferred in the new model)
      2. brand.phone — brand-level default
      3. first entry of brand.phones — legacy matrix mode, fall back to first
      4. brand inline base_image+screen_corners
    """
    name = shot.get("phone") or brand.get("phone")
    if not name and isinstance(brand.get("phones"), list) and brand["phones"]:
        name = brand["phones"][0]
    if name:
        if name not in phones:
            raise ConfigError(
                f"Brand '{brand_name}' references unknown phone '{name}'"
            )
        return name, phones[name]

    if "base_image" in brand and "screen_corners" in brand:
        inline = {
            "base_image": brand["base_image"],
            "screen_corners": brand["screen_corners"],
        }
        _validate_phone(f"{brand_name} (inline)", inline)
        return "", inline

    raise ConfigError(
        f"Brand '{brand_name}' output {shot.get('output') or shot.get('source') or '?'}: "
        f"no 'phone' on the output and no brand-level fallback"
    )


def resolve_brand_phones(
    brand_name: str,
    brand: Dict[str, Any],
    phones: Dict[str, Any],
) -> List[tuple[str, Dict[str, Any]]]:
    """Return [(phone_name, phone_cfg)] to use for this brand.

    Resolution order:
      1. brand.phones: [name, name, ...]   -> matrix over those phones
      2. brand.phone:  name                -> single phone
      3. brand has its own base_image + screen_corners (legacy / inline)
    """
    if "phones" in brand:
        names = brand["phones"]
        if not isinstance(names, list) or not names:
            raise ConfigError(f"Brand '{brand_name}' 'phones' must be a non-empty list")
        result = []
        for n in names:
            if n not in phones:
                raise ConfigError(
                    f"Brand '{brand_name}' references unknown phone '{n}'"
                )
            result.append((n, phones[n]))
        return result

    if "phone" in brand:
        n = brand["phone"]
        if n not in phones:
            raise ConfigError(f"Brand '{brand_name}' references unknown phone '{n}'")
        return [(n, phones[n])]

    if "base_image" in brand and "screen_corners" in brand:
        # Inline phone: not in registry, treat brand itself as the phone.
        inline = {
            "base_image": brand["base_image"],
            "screen_corners": brand["screen_corners"],
        }
        _validate_phone(f"{brand_name} (inline)", inline)
        return [("", inline)]

    raise ConfigError(
        f"Brand '{brand_name}' must specify either 'phone', 'phones', "
        f"or inline 'base_image'+'screen_corners'"
    )


def validate_brand(name: str, brand: Dict[str, Any]) -> None:
    if "screenshots" not in brand:
        raise ConfigError(f"Brand '{name}' missing 'screenshots'")
    if not isinstance(brand["screenshots"], list) or not brand["screenshots"]:
        raise ConfigError(f"Brand '{name}' must list at least one screenshot")
