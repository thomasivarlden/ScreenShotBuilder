"""Translation support: load/save translations.yaml, apply to label text."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List

import yaml


DEFAULT_SETTINGS: Dict[str, Any] = {
    "base_language": "en",
    "label_align": "center",
}


def default_data() -> Dict[str, Any]:
    return {
        "settings": dict(DEFAULT_SETTINGS),
        "languages": [
            {"code": "en", "name": "English", "enabled": True},
            {"code": "sv", "name": "Svenska", "enabled": True},
            {"code": "de", "name": "Deutsch", "enabled": True},
        ],
        "strings": {},
    }


def load_translations(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return default_data()
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        return default_data()
    data.setdefault("settings", dict(DEFAULT_SETTINGS))
    data.setdefault("languages", [{"code": "en", "name": "English", "enabled": True}])
    data.setdefault("strings", {})
    return data


def get_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(data.get("settings") or {})}


def save_translations(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)


def enabled_languages(data: Dict[str, Any]) -> List[Dict[str, str]]:
    return [lang for lang in data.get("languages", []) if lang.get("enabled", True)]


def collect_label_texts(config: Dict[str, Any]) -> List[str]:
    """Return unique label text values from config, in order of first appearance."""
    seen: set[str] = set()
    result: List[str] = []
    for brand_cfg in (config.get("brands") or {}).values():
        for shot in (brand_cfg.get("screenshots") or []):
            for label in (shot.get("labels") or []):
                t = str(label.get("text", "")).strip()
                if t and t not in seen:
                    seen.add(t)
                    result.append(t)
    return result


def apply_translations(
    shot_cfg: Dict[str, Any],
    lang_code: str,
    strings: Dict[str, Any],
    settings: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return a copy of shot_cfg with label texts (and optional overrides) applied.

    Each language value in strings can be:
      - a plain string  →  only the text is replaced
      - a dict          →  "text" is replaced + any extra keys (font_size, position, …)
                           are merged onto the label, allowing per-language nudges

    Falls back to the original English text/style when no translation exists.

    When settings["label_align"] is "center" or "right", private metadata keys
    (_fit_align, _source_*) are added so the compositor can measure the English
    text bounding box and align the translated text accordingly.
    """
    if lang_code == "en":
        return shot_cfg
    labels = shot_cfg.get("labels")
    if not labels:
        return shot_cfg

    align = (settings or {}).get("label_align", "center")
    needs_fit = align in ("center", "right")

    new_labels = []
    for label in labels:
        text = str(label.get("text", "")).strip()
        entry = (strings.get(text) or {}).get(lang_code)
        if entry is not None:
            if isinstance(entry, dict):
                label = {**label, **entry}
                if "text" not in entry:
                    label["text"] = text
            else:
                label = {**label, "text": str(entry)}

            # Attach source-label info so the compositor can measure the English
            # bounding box and re-anchor the translated text. Only when the label
            # was actually translated (entry is not None) and the dict form
            # didn't already supply an explicit position override.
            if needs_fit and not (isinstance(entry, dict) and "position" in entry):
                label = {
                    **label,
                    "_fit_align": align,
                    "_source_text": text,
                    "_source_position": list(label.get("position", [0, 0])),
                    "_source_font": label.get("font"),
                    "_source_font_size": int(label.get("font_size") or 48),
                    "_source_bold": bool(label.get("bold")),
                    "_source_anchor": label.get("anchor"),
                }

        new_labels.append(label)
    return {**shot_cfg, "labels": new_labels}
