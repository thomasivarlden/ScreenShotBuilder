#!/usr/bin/env python3
"""Screenshot Builder — main CLI entrypoint.

(C) Thomas F Abrahamsson at Alvega & Co AB <Thomas@alvega.company>
"""
import argparse
import sys
from pathlib import Path

from include.builder import print_summary, run_build
from include.config_loader import ConfigError, load_config
from include.logger import Logger
from include.translations import load_translations
from include.version import APP_NAME, APP_VERSION, banner

DEFAULT_CONFIG = "screenshots.yaml"
DEFAULT_ASSETS = "assets"
DEFAULT_DIST = "dist"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="screenshot_builder",
        description=f"{APP_NAME} v{APP_VERSION} — batch composite app store screenshots",
    )
    p.add_argument(
        "-c", "--config",
        default=DEFAULT_CONFIG,
        help=f"YAML config file (default: {DEFAULT_CONFIG})",
    )
    p.add_argument(
        "-a", "--assets",
        default=DEFAULT_ASSETS,
        help=f"Assets folder (default: {DEFAULT_ASSETS})",
    )
    p.add_argument(
        "-o", "--out",
        default=DEFAULT_DIST,
        help=f"Output dist folder (default: {DEFAULT_DIST})",
    )
    p.add_argument(
        "-t", "--translations",
        default=None,
        help="Translations YAML file (default: translations.yaml alongside --config, if present)",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose (DEBUG) logging",
    )
    p.add_argument(
        "--version",
        action="version",
        version=banner(),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    log = Logger(level="DEBUG" if args.verbose else "INFO")
    log.info(banner())

    root = Path.cwd()
    config_path = (root / args.config).resolve()
    assets_dir = (root / args.assets).resolve()
    dist_dir = (root / args.out).resolve()

    # Translations: explicit path or auto-discover alongside config.
    if args.translations:
        translations_path = (root / args.translations).resolve()
    else:
        translations_path = config_path.with_name("translations.yaml")

    log.info(f"Config       : {config_path}")
    log.info(f"Assets       : {assets_dir}")
    log.info(f"Dist         : {dist_dir}")
    log.info(f"Translations : {translations_path}" + ("" if translations_path.is_file() else " (not found, English only)"))

    if not assets_dir.is_dir():
        log.error(f"Assets folder missing: {assets_dir}")
        return 2

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        log.error(f"Config error: {exc}")
        return 2

    translations = load_translations(translations_path) if translations_path.is_file() else None

    dist_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = run_build(config, assets_dir, dist_dir, log, translations=translations)
    except Exception as exc:  # noqa: BLE001
        log.error(f"Fatal: {exc}")
        return 1

    print_summary(report)
    log.info(
        f"Done. Wrote {len(report.succeeded)} image(s) "
        f"({len(report.failed)} failed) in {report.elapsed:.2f}s"
    )
    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
