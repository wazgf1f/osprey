"""Run statistics."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Stats:
    ticks: int = 0
    detections: int = 0
    actions: int = 0
    errors: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    stop_reason: Optional[str] = None

    @property
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.time()
        return max(0.0, end - self.started_at)

    @property
    def fps(self) -> float:
        elapsed = self.elapsed
        return self.ticks / elapsed if elapsed > 0 else 0.0

    def finish(self, reason: Optional[str] = None) -> "Stats":
        self.finished_at = time.time()
        if reason:
            self.stop_reason = reason
        return self

    def summary(self) -> dict:
        data = asdict(self)
        data["elapsed"] = round(self.elapsed, 3)
        data["fps"] = round(self.fps, 2)
        return data
