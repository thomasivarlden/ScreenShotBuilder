"""Top-level batch driver: iterate brands x phones x screenshots, write PNGs."""
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .compositor import build_composite
from .gallery import write_gallery
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


_VALID_OS = frozenset({"ios", "android"})
_VALID_FORM = frozenset({"phone", "tablet"})

# Leading platform/order tokens the author may have baked into `output:` names
# (e.g. "android_03_login"). They are now expressed as folders, so strip them.
_PLATFORM_PREFIX = re.compile(r"^(android|ios|iphone|ipad|tablet)[_-]", re.I)
_ORDER_PREFIX = re.compile(r"^(\d+)[_-](.*)$")


def _device_bucket(phone_name: str, phone_cfg: Dict[str, Any]) -> tuple[str, str]:
    """Return (os, form) folders for a phone.

    Prefers the phone's declared `platform`/`form` (config intent); falls back
    to sniffing the phone name so undeclared/legacy phones still route somewhere.
    """
    os_ = str(phone_cfg.get("platform", "")).lower()
    form = str(phone_cfg.get("form", "")).lower()
    n = (phone_name or "").lower()
    if os_ not in _VALID_OS:
        if "iphone" in n or "ipad" in n:
            os_ = "ios"
        elif "android" in n or "samsung" in n:
            os_ = "android"
        else:
            os_ = "other"
    if form not in _VALID_FORM:
        form = "tablet" if ("ipad" in n or "tablet" in n) else "phone"
    return os_, form


def _output_filename(shot_cfg: Dict[str, Any], suffix: str = "") -> str:
    """Clean, ordered filename for the leaf folder.

    Language and device are now folders, so the name carries only the order
    prefix (from `output:`) and a descriptive slug. Order/wording come from the
    config (author intent); the code just strips now-redundant platform tokens.
    `suffix` is appended before the extension (e.g. "_Clean").
    """
    raw = shot_cfg.get("output") or (Path(shot_cfg["source"]).stem + ".png")
    stem = raw[:-4] if raw.lower().endswith(".png") else raw
    stem = _PLATFORM_PREFIX.sub("", stem)
    order, rest = "", stem
    m = _ORDER_PREFIX.match(stem)
    if m:
        order, rest = m.group(1), m.group(2)

    slug = _labels_slug(shot_cfg)
    name = slug or rest or Path(shot_cfg["source"]).stem
    stem = f"{order}_{name}" if order else name
    return f"{stem}{suffix}.png"


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


def _emit(
    *,
    merged_brand: Dict[str, Any],
    shot: Dict[str, Any],
    assets_dir: Path,
    out_path: Path,
    brand_out: Path,
    brand_name: str,
    phone_name: str,
    lang_code: str,
    clean: bool,
    report: BuildReport,
    log: Logger,
    step_no: int,
    total: int,
) -> None:
    """Render one variant (decorated or clean) to out_path and record the result."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rel = str(out_path.relative_to(brand_out))
    tag = f"[{lang_code}] {brand_name} [{phone_name}] :: {rel}" if phone_name \
        else f"[{lang_code}] {brand_name} :: {rel}"
    log.step(step_no, total, tag)
    t0 = time.time()
    try:
        image = build_composite(merged_brand, shot, assets_dir, clean=clean)
        image.save(out_path, format="PNG", optimize=True)
        report.succeeded.append(
            ShotResult(
                brand=brand_name, phone=phone_name, name=rel,
                path=out_path, width=image.size[0], height=image.size[1],
                bytes=out_path.stat().st_size, seconds=time.time() - t0,
            )
        )
        log.debug(f"  wrote {out_path} ({image.size[0]}x{image.size[1]})")
    except Exception as exc:  # noqa: BLE001
        log.error(f"Failed: [{lang_code}] {brand_name} / {rel}: {exc}")
        report.failed.append({"brand": brand_name, "name": rel, "error": str(exc)})


def _emit_shot(
    *,
    merged_brand: Dict[str, Any],
    shot: Dict[str, Any],
    assets_dir: Path,
    brand_out: Path,
    brand_name: str,
    phone_name: str,
    phone_cfg: Dict[str, Any],
    lang_code: str,
    clean: bool,
    report: BuildReport,
    log: Logger,
    counter: int,
    total: int,
) -> int:
    """Emit the decorated output plus (optionally) its clean twin. Returns new counter."""
    os_, form = _device_bucket(phone_name, phone_cfg)
    counter += 1
    _emit(
        merged_brand=merged_brand, shot=shot, assets_dir=assets_dir,
        out_path=brand_out / os_ / form / lang_code / _output_filename(shot),
        brand_out=brand_out, brand_name=brand_name, phone_name=phone_name,
        lang_code=lang_code, clean=False, report=report, log=log,
        step_no=counter, total=total,
    )
    if clean:
        counter += 1
        _emit(
            merged_brand=merged_brand, shot=shot, assets_dir=assets_dir,
            out_path=brand_out / "Clean" / os_ / form / lang_code
            / _output_filename(shot, suffix="_Clean"),
            brand_out=brand_out, brand_name=brand_name, phone_name=phone_name,
            lang_code=lang_code, clean=True, report=report, log=log,
            step_no=counter, total=total,
        )
    return counter


def run_build(
    config: Dict[str, Any],
    assets_dir: Path,
    dist_dir: Path,
    log: Logger,
    translations: Optional[Dict[str, Any]] = None,
    clean: bool = True,
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

    variants = 2 if clean else 1
    total_shots = sum(shots_per_brand.values()) * len(langs) * variants
    log.info(
        f"Planning {total_shots} image(s) across {len(brands)} brand(s), "
        f"{len(phones)} registered phone(s), {len(langs)} language(s)"
        + (" — incl. Clean variants" if clean else "")
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
                    phone_name, phone_cfg = resolve_shot_phone(
                        brand_name, brand_cfg, shot_cfg, phones,
                    )
                    merged_brand = {**brand_cfg, **phone_cfg}
                    translated_shot = apply_translations(shot_cfg, lang_code, strings, settings)
                    counter = _emit_shot(
                        merged_brand=merged_brand, shot=translated_shot, assets_dir=assets_dir,
                        brand_out=brand_out, brand_name=brand_name, phone_name=phone_name,
                        phone_cfg=phone_cfg, lang_code=lang_code, clean=clean,
                        report=report, log=log, counter=counter, total=total_shots,
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
                    translated_shot = apply_translations(shot_cfg, lang_code, strings, settings)
                    counter = _emit_shot(
                        merged_brand=merged_brand, shot=translated_shot, assets_dir=assets_dir,
                        brand_out=brand_out, brand_name=brand_name, phone_name=phone_name,
                        phone_cfg=phone_cfg, lang_code=lang_code, clean=clean,
                        report=report, log=log, counter=counter, total=total_shots,
                    )

    report.finished = time.time()
    write_gallery(dist_dir, report)
    return report
