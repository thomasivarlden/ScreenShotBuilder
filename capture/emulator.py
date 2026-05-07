"""Helpers for booting an Android emulator before capture.

The Homebrew Android SDK on this machine is broken; the working SDK lives at
~/Library/Android/sdk. We override ANDROID_SDK_ROOT/ANDROID_HOME at launch
time so the emulator binary uses the right SDK regardless of shell env.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from . import adb

DEFAULT_SDK = Path.home() / "Library" / "Android" / "sdk"


def sdk_root() -> Path:
    return Path(os.environ.get("ANDROID_SDK_ROOT_OVERRIDE", str(DEFAULT_SDK)))


def emulator_bin() -> Path:
    return sdk_root() / "emulator" / "emulator"


def list_avds() -> list[str]:
    bin_path = emulator_bin()
    if not bin_path.exists():
        raise RuntimeError(f"Emulator binary not found at {bin_path}")
    out = subprocess.run(
        [str(bin_path), "-list-avds"],
        capture_output=True, text=True, env=_clean_env(),
    )
    if out.returncode != 0:
        raise RuntimeError(f"emulator -list-avds failed: {out.stderr}")
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def _clean_env() -> dict[str, str]:
    """Force ANDROID_SDK_ROOT / ANDROID_HOME to the working SDK."""
    env = os.environ.copy()
    env["ANDROID_SDK_ROOT"] = str(sdk_root())
    env["ANDROID_HOME"] = str(sdk_root())
    return env


def start(avd: str | None = None, *, wait_timeout: float = 90.0) -> str:
    """Boot an emulator (default = first AVD listed) and wait until adb sees it.

    Returns the device serial. If an emulator is already running, returns its
    serial without starting a new one.
    """
    existing = adb.devices()
    if existing:
        return existing[0]

    avds = list_avds()
    if not avds:
        raise RuntimeError(
            f"No AVDs found under {sdk_root()}. Create one in Android Studio first."
        )
    if avd is None:
        avd = avds[0]
    elif avd not in avds:
        raise RuntimeError(f"AVD {avd!r} not found. Available: {avds}")

    print(f"Starting emulator: {avd} (sdk={sdk_root()})")
    subprocess.Popen(
        [str(emulator_bin()), "-avd", avd],
        env=_clean_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        serials = adb.devices()
        if serials:
            serial = serials[0]
            # Wait for boot to complete (emulator visible != booted).
            boot = subprocess.run(
                ["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True,
            )
            if boot.stdout.strip() == "1":
                print(f"Emulator ready: {serial}")
                return serial
        time.sleep(2)
    raise RuntimeError(f"Emulator {avd!r} did not become ready within {wait_timeout}s")
