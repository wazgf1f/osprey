"""Repeated left clicks on a timer, with no capture or template matching."""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Optional

from .input.win32 import InputController, is_key_pressed


class IntervalClicker:
    """Click the current cursor position every interval seconds.

    The caller owns the thread. run() blocks and returns the click count.
    F12, stop() and an optional should_abort callback all interrupt it.
    """

    def __init__(self, interval: float, *, count: int = 0,
                 dry_run: bool = True, should_abort=None,
                 on_click: Optional[Callable[[int], None]] = None) -> None:
        interval = float(interval)
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("interval must be a positive finite number")
        count = int(count)
        if count < 0:
            raise ValueError("count must be zero or positive")
        self.interval = interval
        self.count = count
        self.dry_run = bool(dry_run)
        self.should_abort = should_abort
        self.on_click = on_click
        self.clicks = 0
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _aborted(self) -> bool:
        if self._stop.is_set() or is_key_pressed("f12"):
            return True
        if self.should_abort is not None and self.should_abort():
            return True
        return False

    def run(self) -> int:
        controller = InputController(
            dry_run=self.dry_run, should_abort=self._aborted)
        try:
            next_at = time.monotonic()
            while not self._aborted():
                next_at += self.interval
                delay = next_at - time.monotonic()
                if delay > 0 and self._stop.wait(delay):
                    break
                if self._aborted():
                    break
                controller.click()
                self.clicks += 1
                if self.on_click is not None:
                    self.on_click(self.clicks)
                if self.count and self.clicks >= self.count:
                    break
        finally:
            controller.release_all()
        return self.clicks
