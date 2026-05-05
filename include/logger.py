import sys
import time


class Logger:
    """Simple progress-aware stdout logger."""

    LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

    def __init__(self, level: str = "INFO"):
        self.level = self.LEVELS.get(level.upper(), 20)
        self._t0 = time.time()

    def _emit(self, tag: str, msg: str) -> None:
        elapsed = time.time() - self._t0
        sys.stdout.write(f"[{elapsed:6.2f}s] {tag:5s} {msg}\n")
        sys.stdout.flush()

    def debug(self, msg: str) -> None:
        if self.level <= 10:
            self._emit("DEBUG", msg)

    def info(self, msg: str) -> None:
        if self.level <= 20:
            self._emit("INFO", msg)

    def warn(self, msg: str) -> None:
        if self.level <= 30:
            self._emit("WARN", msg)

    def error(self, msg: str) -> None:
        if self.level <= 40:
            self._emit("ERROR", msg)

    def step(self, current: int, total: int, msg: str) -> None:
        self._emit("STEP", f"[{current}/{total}] {msg}")
