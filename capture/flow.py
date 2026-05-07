"""Step primitives for recorded capture flows."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import adb


@dataclass
class Step:
    kind: str  # tap | swipe | type | key | wait_text | sleep | screenshot | clear | launch
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    app_id: str
    out_path: Path
    puk: str | None = None


def run_flow(steps: list[Step], ctx: Context) -> None:
    for step in steps:
        _run_step(step, ctx)


def _run_step(step: Step, ctx: Context) -> None:
    a = step.args
    match step.kind:
        case "clear":
            adb.pm_clear(ctx.app_id)
        case "launch":
            adb.launch(ctx.app_id)
        case "force_stop":
            adb.force_stop(ctx.app_id)
        case "tap":
            adb.tap(a["x"], a["y"])
        case "swipe":
            adb.swipe(a["x1"], a["y1"], a["x2"], a["y2"], a.get("duration_ms", 300))
        case "type":
            text = a["text"]
            if text == "{puk}":
                if not ctx.puk:
                    raise RuntimeError(f"Step needs PUK but none configured for {ctx.app_id}")
                text = ctx.puk
            adb.type_text(text)
        case "key":
            adb.key(a["keycode"])
        case "wait_text":
            adb.wait_text(a["text"], timeout=a.get("timeout", 15.0))
        case "sleep":
            time.sleep(a["seconds"])
        case "screenshot":
            adb.screencap(ctx.out_path)
        case _:
            raise ValueError(f"Unknown step kind: {step.kind}")
