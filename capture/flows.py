"""Recorded capture flows.

Each entry in SCREENS is a function that takes the puk and returns the list of
Steps to run. Coordinates are fractions of screen size (0.0 – 1.0); record them
once against the emulator you use for capture and adjust if it drifts.

The flow is responsible for: clear → launch → reach the target screen →
screenshot. Force-stop happens after each run from the orchestrator.
"""
from __future__ import annotations

from typing import Callable

from .flow import Step

FlowBuilder = Callable[[str | None], list[Step]]


def _login(puk: str | None) -> list[Step]:
    """PUK login from a fresh app start.

    The start screen has a single, auto-focused input field, so we type the
    PUK straight in and submit with Enter — no coordinate-tapping needed.
    """
    return [
        Step("clear"),
        Step("launch"),
        Step("wait_text", {"text": "PUK", "timeout": 20.0}),  # TODO: real PUK-screen text
        Step("type", {"text": "{puk}"}),
        Step("key", {"keycode": "KEYCODE_ENTER"}),
        Step("wait_text", {"text": "Home", "timeout": 20.0}),  # TODO: real landing-screen text
    ]


def home(puk: str | None) -> list[Step]:
    return _login(puk) + [
        Step("sleep", {"seconds": 1.0}),
        Step("screenshot"),
    ]


# Add more screens here as you record them. Example:
#
# def catch_detail(puk):
#     return _login(puk) + [
#         Step("tap", {"x": 0.20, "y": 0.78}),       # first catch in list
#         Step("wait_text", {"text": "Details"}),
#         Step("screenshot"),
#     ]


SCREENS: dict[str, FlowBuilder] = {
    "home": home,
    # "catch_detail": catch_detail,
}
