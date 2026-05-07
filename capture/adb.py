"""Thin wrappers around `adb` for the capture orchestrator.

Coordinates passed in are *fractions* of screen size (0.0 – 1.0). They get
resolved against `wm size` once per session and cached.
"""
from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path


class AdbError(RuntimeError):
    pass


def _run(cmd: list[str], *, capture: bool = False, check: bool = True) -> str:
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
    )
    if check and result.returncode != 0:
        stderr = result.stderr if capture else ""
        raise AdbError(f"adb command failed ({result.returncode}): {' '.join(cmd)}\n{stderr}")
    return result.stdout if capture else ""


def devices() -> list[str]:
    out = _run(["adb", "devices"], capture=True)
    serials = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        serial, state = line.split("\t", 1)
        if state.strip() == "device":
            serials.append(serial)
    return serials


def require_device() -> str:
    serials = devices()
    if not serials:
        raise AdbError(
            "No emulator/device found. Either start the emulator yourself, "
            "or re-run capture with --start-emulator (optionally followed by "
            "an AVD name; see --list-avds)."
        )
    if len(serials) > 1:
        raise AdbError(
            f"Multiple devices attached: {serials}. Set ANDROID_SERIAL or detach extras."
        )
    return serials[0]


_size_cache: tuple[int, int] | None = None


def screen_size() -> tuple[int, int]:
    global _size_cache
    if _size_cache is not None:
        return _size_cache
    out = _run(["adb", "shell", "wm", "size"], capture=True)
    m = re.search(r"(\d+)x(\d+)", out)
    if not m:
        raise AdbError(f"Could not parse `wm size` output: {out!r}")
    _size_cache = (int(m.group(1)), int(m.group(2)))
    return _size_cache


def _resolve(x: float, y: float) -> tuple[int, int]:
    w, h = screen_size()
    return int(round(x * w)), int(round(y * h))


def tap(x: float, y: float) -> None:
    px, py = _resolve(x, y)
    _run(["adb", "shell", "input", "tap", str(px), str(py)])


def swipe(x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
    px1, py1 = _resolve(x1, y1)
    px2, py2 = _resolve(x2, y2)
    _run(["adb", "shell", "input", "swipe", str(px1), str(py1), str(px2), str(py2), str(duration_ms)])


def type_text(text: str) -> None:
    # `input text` doesn't accept spaces literally — they need to be %s.
    escaped = text.replace(" ", "%s")
    _run(["adb", "shell", "input", "text", shlex.quote(escaped)])


def key(keycode: str) -> None:
    _run(["adb", "shell", "input", "keyevent", keycode])


def screencap(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        result = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"],
            stdout=f,
        )
    if result.returncode != 0:
        raise AdbError(f"screencap failed for {out_path}")


def pm_clear(app_id: str) -> None:
    _run(["adb", "shell", "pm", "clear", app_id])


def launch(app_id: str) -> None:
    _run([
        "adb", "shell", "monkey",
        "-p", app_id,
        "-c", "android.intent.category.LAUNCHER", "1",
    ])


def force_stop(app_id: str) -> None:
    _run(["adb", "shell", "am", "force-stop", app_id])


def ui_dump_text() -> str:
    """Return the concatenated text content of the current UI, for `wait_text`.

    Flutter renders to a canvas, but text widgets still surface through the
    accessibility tree, so `uiautomator dump` picks them up.
    """
    _run(["adb", "shell", "uiautomator", "dump", "/sdcard/ui.xml"])
    out = _run(["adb", "shell", "cat", "/sdcard/ui.xml"], capture=True)
    return out


def wait_text(needle: str, timeout: float = 15.0, interval: float = 0.5) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            last = ui_dump_text()
        except AdbError:
            last = ""
        if needle in last:
            return
        time.sleep(interval)
    raise AdbError(f"Timed out waiting for text {needle!r} (last dump {len(last)} chars)")
