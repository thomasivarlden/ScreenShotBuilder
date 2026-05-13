"""Top-level batch driver: iterate brands x phones x screenshots, write PNGs."""
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .compositor import build_composite
from .config_loader import (
    resolve_brand_phones,
    resolve_shot_phone,
    validate_brand,
    validate_phones,
)
from .logger import Logger
from .translations import apply_translations, enabled_languages, get_settings


@dataclass
class ShotResult:
    brand: str
    phone: str
    name: str
    path: Path
    width: int
    height: int
    bytes: int
    seconds: float


@dataclass
class BuildReport:
    dist_dir: Path
    started: float
    finished: float = 0.0
    succeeded: List[ShotResult] = field(default_factory=list)
    failed: List[Dict[str, str]] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return self.finished - self.started

    @property
    def total_bytes(self) -> int:
        return sum(s.bytes for s in self.succeeded)


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for",
    "of", "with", "your", "my", "our", "their", "its", "is", "are",
    "was", "were", "be", "been", "by", "from", "when", "where",
})


def _labels_slug(shot_cfg: Dict[str, Any], max_len: int = 32) -> str:
    """Build a CamelCase slug from label texts, skipping common stop words.

    Returns an empty string when there are no usable labels (caller falls back
    to the source filename stem).
    """
    words: List[str] = []
    for label in (shot_cfg.get("labels") or []):
        for word in str(label.get("text", "")).split():
            clean = re.sub(r"[^a-zA-Z0-9]", "", word)
            if clean and clean.lower() not in _STOP_WORDS:
                words.append(clean.capitalize())
    slug = "".join(words)
    return slug[:max_len]


def _platform_tag(phone_name: str) -> str:
    """Derive a short platform label from a phone name."""
    n = phone_name.lower()
    if "iphone" in n:
        return "iOS"
    if "android" in n or "samsung" in n:
        return "Android"
    return phone_name  # pass-through for generic/custom phone names


def _output_filename(
    shot_cfg: Dict[str, Any],
    phone_name: str,
    lang_code: str,
    multilingual: bool,
) -> str:
    slug = _labels_slug(shot_cfg)
    if slug:
        stem = slug
    else:
        raw = shot_cfg.get("output") or Path(shot_cfg["source"]).stem + ".png"
        if not raw.lower().endswith(".png"):
            raw += ".png"
        stem = raw[:-4]
    prefix = f"{lang_code}__" if multilingual else ""
    platform = f"__{_platform_tag(phone_name)}" if phone_name else ""
    return f"{prefix}{stem}{platform}.png" if (prefix or platform) else f"{stem}.png"


def print_summary(report: BuildReport) -> None:
    sys.stdout.write("\n")
    sys.stdout.write("=" * 78 + "\n")
    sys.stdout.write(" Screenshot Builder — summary report\n")
    sys.stdout.write("=" * 78 + "\n")
    sys.stdout.write(f" Output folder : {report.dist_dir}\n")
    sys.stdout.write(f" Open in browser: {report.dist_dir.as_uri()}\n")
    sys.stdout.write(
        f" Built {len(report.succeeded)} image(s)"
        f"  ·  {len(report.failed)} failed"
        f"  ·  {_human_bytes(report.total_bytes)} total"
        f"  ·  {report.elapsed:.2f}s\n"
    )

    by_brand: Dict[str, List[ShotResult]] = {}
    for shot in report.succeeded:
        by_brand.setdefault(shot.brand, []).append(shot)

    for brand, shots in by_brand.items():
        sys.stdout.write("\n")
        sys.stdout.write(f" {brand}  ({len(shots)} image{'s' if len(shots) != 1 else ''})\n")
        sys.stdout.write(" " + "-" * 76 + "\n")
        for s in shots:
            dim = f"{s.width}x{s.height}"
            size = _human_bytes(s.bytes)
            phone_tag = f"[{s.phone}] " if s.phone else ""
            sys.stdout.write(f"   • {phone_tag}{s.name:<28}  {dim:>11}  {size:>9}  {s.seconds:5.2f}s\n")
            sys.stdout.write(f"     {s.path.as_uri()}\n")

    if report.failed:
        sys.stdout.write("\n")
        sys.stdout.write(" Failures\n")
        sys.stdout.write(" " + "-" * 76 + "\n")
        for f in report.failed:
            sys.stdout.write(f"   ✗ {f['brand']} / {f['name']}\n")
            sys.stdout.write(f"     {f['error']}\n")

    sys.stdout.write("=" * 78 + "\n")
    sys.stdout.flush()


def run_build(
    config: Dict[str, Any],
    assets_dir: Path,
    dist_dir: Path,
    log: Logger,
    translations: Optional[Dict[str, Any]] = None,
) -> BuildReport:
    """Build every screenshot for every brand × phone × language. Returns a BuildReport."""
    brands = config["brands"]
    phones = config.get("phones", {}) or {}
    validate_phones(phones)

    # Determine which languages to build.
    if translations:
        langs = enabled_languages(translations)
        strings = translations.get("strings", {})
        settings = get_settings(translations)
    else:
        langs = [{"code": "en", "name": "English", "enabled": True}]
        strings = {}
        settings = {}
    multilingual = len(langs) > 1

    # Pre-resolve so we can show an accurate plan and fail fast on bad refs.
    resolved: Dict[str, List[tuple[str, Dict[str, Any]]]] = {}
    per_output_mode: Dict[str, bool] = {}
    shots_per_brand: Dict[str, int] = {}
    for brand_name, brand_cfg in brands.items():
        validate_brand(brand_name, brand_cfg)
        shots = brand_cfg.get("screenshots", []) or []
        any_shot_phone = any(s.get("phone") for s in shots)
        per_output_mode[brand_name] = any_shot_phone
        if any_shot_phone:
            for s in shots:
                resolve_shot_phone(brand_name, brand_cfg, s, phones)
            resolved[brand_name] = []
            shots_per_brand[brand_name] = len(shots)
        else:
            phone_list = resolve_brand_phones(brand_name, brand_cfg, phones)
            resolved[brand_name] = phone_list
            shots_per_brand[brand_name] = len(phone_list) * len(shots)

    total_shots = sum(shots_per_brand.values()) * len(langs)
    log.info(
        f"Planning {total_shots} image(s) across {len(brands)} brand(s), "
        f"{len(phones)} registered phone(s), {len(langs)} language(s)"
    )

    report = BuildReport(dist_dir=dist_dir, started=time.time())
    counter = 0

    for lang in langs:
        lang_code = lang["code"]
        for brand_name, brand_cfg in brands.items():
            brand_out = dist_dir / brand_name
            brand_out.mkdir(parents=True, exist_ok=True)
            shots = brand_cfg.get("screenshots", []) or []

            if per_output_mode[brand_name]:
                log.info(f"[{lang_code}] Brand: {brand_name}  ->  {brand_out}  ({len(shots)} output(s))")
                for shot_cfg in shots:
                    counter += 1
                    phone_name, phone_cfg = resolve_shot_phone(
                        brand_name, brand_cfg, shot_cfg, phones,
                    )
                    merged_brand = {**brand_cfg, **phone_cfg}
                    translated_shot = apply_translations(shot_cfg, lang_code, strings, settings)
                    out_name = _output_filename(shot_cfg, phone_name, lang_code, multilingual)
                    out_path = brand_out / out_name
                    tag = f"[{lang_code}] {brand_name} [{phone_name}] :: {out_name}" if phone_name \
                        else f"[{lang_code}] {brand_name} :: {out_name}"
                    log.step(counter, total_shots, tag)
                    t0 = time.time()
                    try:
                        image = build_composite(merged_brand, translated_shot, assets_dir)
                        image.save(out_path, format="PNG", optimize=True)
                        report.succeeded.append(
                            ShotResult(
                                brand=brand_name, phone=phone_name, name=out_name,
                                path=out_path, width=image.size[0], height=image.size[1],
                                bytes=out_path.stat().st_size, seconds=time.time() - t0,
                            )
                        )
                        log.debug(f"  wrote {out_path} ({image.size[0]}x{image.size[1]})")
                    except Exception as exc:  # noqa: BLE001
                        log.error(f"Failed: [{lang_code}] {brand_name} / {out_name}: {exc}")
                        report.failed.append(
                            {"brand": brand_name, "name": out_name, "error": str(exc)}
                        )
                continue

            # Legacy: brand × phone-list matrix.
            phone_list = resolved[brand_name]
            multi_phone = len(phone_list) > 1
            log.info(
                f"[{lang_code}] Brand: {brand_name}  ->  {brand_out}  "
                f"({len(phone_list)} phone{'s' if multi_phone else ''})"
            )
            for phone_name, phone_cfg in phone_list:
                merged_brand = {**brand_cfg, **phone_cfg}
                for shot_cfg in shots:
                    counter += 1
                    translated_shot = apply_translations(shot_cfg, lang_code, strings, settings)
                    out_name = _output_filename(shot_cfg, phone_name, lang_code, multilingual)
                    out_path = brand_out / out_name
                    tag = f"[{lang_code}] {brand_name} [{phone_name}] :: {out_name}" if phone_name \
                        else f"[{lang_code}] {brand_name} :: {out_name}"
                    log.step(counter, total_shots, tag)
                    t0 = time.time()
                    try:
                        image = build_composite(merged_brand, translated_shot, assets_dir)
                        image.save(out_path, format="PNG", optimize=True)
                        report.succeeded.append(
                            ShotResult(
                                brand=brand_name, phone=phone_name, name=out_name,
                                path=out_path, width=image.size[0], height=image.size[1],
                                bytes=out_path.stat().st_size, seconds=time.time() - t0,
                            )
                        )
                        log.debug(f"  wrote {out_path} ({image.size[0]}x{image.size[1]})")
                    except Exception as exc:  # noqa: BLE001
                        log.error(f"Failed: [{lang_code}] {brand_name} / {out_name}: {exc}")
                        report.failed.append(
                            {"brand": brand_name, "name": out_name, "error": str(exc)}
                        )

    report.finished = time.time()
    return report
