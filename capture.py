#!/usr/bin/env python3
"""Capture orchestrator.

Loops (brand x screen), drives the running Android emulator over adb to log
into each brand's app and capture screenshots into assets/screenshots/<brand>/.

Assumes:
  - The Android emulator is already running (`adb devices` shows one device).
  - Each brand's APK is already installed on the emulator. Pass --rebuild to
    install/reinstall via `fvm flutter install --flavor <flavor>` first.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

from capture import adb, emulator
from capture.flow import Context, run_flow
from capture.flows import SCREENS

REPO_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = REPO_ROOT / "capture.yaml"
SECRETS_PATH = REPO_ROOT / "secrets.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def load_puks() -> dict[str, str]:
    if not SECRETS_PATH.exists():
        return {}
    with SECRETS_PATH.open() as f:
        data = yaml.safe_load(f) or {}
    return data.get("puks", {})


def rebuild(flutter_project: Path, flavor: str, dart_defines: dict[str, str]) -> None:
    cmd = ["fvm", "flutter", "install", "--flavor", flavor]
    for k, v in dart_defines.items():
        cmd.extend(["--dart-define", f"{k}={v}"])
    print(f"  rebuilding: {' '.join(cmd)} (cwd={flutter_project})")
    result = subprocess.run(cmd, cwd=flutter_project)
    if result.returncode != 0:
        raise SystemExit(f"flutter install failed for flavor {flavor}")


def capture_one(brand_id: str, brand_cfg: dict, screen: str, puk: str | None,
                output_root: Path) -> None:
    if screen not in SCREENS:
        raise SystemExit(f"Unknown screen {screen!r}. Known: {sorted(SCREENS)}")

    out_path = output_root / brand_id / f"{screen}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[{brand_id}] {screen} -> {out_path.relative_to(REPO_ROOT)}")
    ctx = Context(app_id=brand_cfg["app_id"], out_path=out_path, puk=puk)
    steps = SCREENS[screen](puk)
    try:
        run_flow(steps, ctx)
    finally:
        adb.force_stop(brand_cfg["app_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture screenshots across brands.")
    parser.add_argument("--brand", action="append", help="Limit to one or more brand IDs.")
    parser.add_argument("--screen", action="append", help="Limit to one or more screen names.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Run `fvm flutter install` for each brand before capturing.")
    parser.add_argument("--list", action="store_true", help="List configured brands and screens, then exit.")
    parser.add_argument("--start-emulator", nargs="?", const="", default=None, metavar="AVD",
                        help="Boot an emulator if none is running. Optional AVD name (default: first listed).")
    parser.add_argument("--list-avds", action="store_true", help="List installed AVDs and exit.")
    args = parser.parse_args()

    config = load_config()
    brands_cfg: dict[str, dict] = config["brands"]
    output_root = (REPO_ROOT / config.get("output_dir", "assets/screenshots")).resolve()
    flutter_project = Path(config.get("flutter_project", "")).expanduser()

    if args.list:
        print("Brands:", ", ".join(sorted(brands_cfg)))
        print("Screens:", ", ".join(sorted(SCREENS)))
        return 0

    if args.list_avds:
        print("\n".join(emulator.list_avds()))
        return 0

    selected_brands = args.brand or list(brands_cfg.keys())
    selected_screens = args.screen or list(SCREENS.keys())

    for b in selected_brands:
        if b not in brands_cfg:
            raise SystemExit(f"Unknown brand {b!r}. Known: {sorted(brands_cfg)}")
    for s in selected_screens:
        if s not in SCREENS:
            raise SystemExit(f"Unknown screen {s!r}. Known: {sorted(SCREENS)}")

    if args.start_emulator is not None:
        avd = args.start_emulator or None
        serial = emulator.start(avd)
    else:
        serial = adb.require_device()
    w, h = adb.screen_size()
    print(f"Using device {serial} ({w}x{h})")

    puks = load_puks()

    for brand_id in selected_brands:
        cfg = brands_cfg[brand_id]
        if args.rebuild:
            if not flutter_project or not flutter_project.exists():
                raise SystemExit(
                    f"--rebuild requires flutter_project in capture.yaml; got {flutter_project!r}"
                )
            rebuild(flutter_project, cfg["flavor"], cfg.get("dart_defines") or {})
        for screen in selected_screens:
            capture_one(brand_id, cfg, screen, puks.get(brand_id), output_root)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
