"""Top-level batch driver: iterate brands x phones x screenshots, write PNGs."""
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .compositor import build_composite
from .config_loader import (
    resolve_brand_phones,
    resolve_shot_phone,
    validate_brand,
    validate_phones,
)
from .logger import Logger


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


def _output_filename(shot_cfg: Dict[str, Any], phone_name: str, multi_phone: bool) -> str:
    raw = shot_cfg.get("output") or Path(shot_cfg["source"]).stem + ".png"
    if not raw.lower().endswith(".png"):
        raw += ".png"
    if multi_phone and phone_name:
        stem = raw[:-4]
        raw = f"{stem}__{phone_name}.png"
    return raw


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
) -> BuildReport:
    """Build every screenshot for every brand × phone. Returns a BuildReport."""
    brands = config["brands"]
    phones = config.get("phones", {}) or {}
    validate_phones(phones)

    # Pre-resolve so we can show an accurate plan and fail fast on bad refs.
    # Per-output mode: any shot with its own `phone:` triggers the new
    # one-shot-per-output iteration. Otherwise we fall back to the legacy
    # brand × phone-list matrix.
    resolved: Dict[str, List[tuple[str, Dict[str, Any]]]] = {}
    per_output_mode: Dict[str, bool] = {}
    total_shots = 0
    for brand_name, brand_cfg in brands.items():
        validate_brand(brand_name, brand_cfg)
        shots = brand_cfg.get("screenshots", []) or []
        any_shot_phone = any(s.get("phone") for s in shots)
        per_output_mode[brand_name] = any_shot_phone
        if any_shot_phone:
            # Each shot resolves its own phone — count once per shot.
            for s in shots:
                resolve_shot_phone(brand_name, brand_cfg, s, phones)  # validate
            resolved[brand_name] = []  # not used in this mode
            total_shots += len(shots)
        else:
            phone_list = resolve_brand_phones(brand_name, brand_cfg, phones)
            resolved[brand_name] = phone_list
            total_shots += len(phone_list) * len(shots)

    log.info(
        f"Planning {total_shots} image(s) across {len(brands)} brand(s) "
        f"and {len(phones)} registered phone(s)"
    )

    report = BuildReport(dist_dir=dist_dir, started=time.time())
    counter = 0

    for brand_name, brand_cfg in brands.items():
        brand_out = dist_dir / brand_name
        brand_out.mkdir(parents=True, exist_ok=True)
        shots = brand_cfg.get("screenshots", []) or []

        if per_output_mode[brand_name]:
            log.info(f"Brand: {brand_name}  ->  {brand_out}  ({len(shots)} output(s))")
            for shot_cfg in shots:
                counter += 1
                phone_name, phone_cfg = resolve_shot_phone(
                    brand_name, brand_cfg, shot_cfg, phones,
                )
                merged_brand = {**brand_cfg, **phone_cfg}
                out_name = _output_filename(shot_cfg, phone_name, multi_phone=False)
                out_path = brand_out / out_name
                tag = f"{brand_name} [{phone_name}] :: {out_name}" if phone_name \
                    else f"{brand_name} :: {out_name}"
                log.step(counter, total_shots, tag)
                t0 = time.time()
                try:
                    image = build_composite(merged_brand, shot_cfg, assets_dir)
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
                    log.error(f"Failed: {brand_name} / {out_name}: {exc}")
                    report.failed.append(
                        {"brand": brand_name, "name": out_name, "error": str(exc)}
                    )
            continue

        # Legacy: brand × phone-list matrix.
        phone_list = resolved[brand_name]
        multi_phone = len(phone_list) > 1
        log.info(
            f"Brand: {brand_name}  ->  {brand_out}  "
            f"({len(phone_list)} phone{'s' if multi_phone else ''})"
        )
        for phone_name, phone_cfg in phone_list:
            merged_brand = {**brand_cfg, **phone_cfg}
            for shot_cfg in shots:
                counter += 1
                out_name = _output_filename(shot_cfg, phone_name, multi_phone)
                out_path = brand_out / out_name
                tag = f"{brand_name} [{phone_name}] :: {out_name}" if phone_name \
                    else f"{brand_name} :: {out_name}"
                log.step(counter, total_shots, tag)
                t0 = time.time()
                try:
                    image = build_composite(merged_brand, shot_cfg, assets_dir)
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
                    log.error(f"Failed: {brand_name} / {out_name}: {exc}")
                    report.failed.append(
                        {"brand": brand_name, "name": out_name, "error": str(exc)}
                    )

    report.finished = time.time()
    return report
