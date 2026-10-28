"""Everything a task can touch during a tick."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from ..capture.base import Frame, FrameSource
from ..input.win32 import InputController
from ..vision.io import draw_detections, load_gray, save_image
from ..vision.match import Detection, match_template
from .config import resolve_asset
from .safety import Safety
from .stats import Stats

Target = Union[Detection, Tuple[float, float]]


@dataclass
class Context:
    """Per-run state handed to every task callback."""

    frame: Frame
    screen: FrameSource
    input: InputController
    safety: Safety
    config: Mapping[str, Any]
    stats: Stats = field(default_factory=Stats)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("osprey.task"))

    # -- vision ------------------------------------------------------------
    @property
    def gray(self) -> np.ndarray:
        return self.frame.gray()

    @property
    def origin(self) -> Tuple[int, int]:
        return self.frame.origin

    def _load_template(self, template: Union[str, np.ndarray]) -> np.ndarray:
        if isinstance(template, np.ndarray):
            return template
        if not isinstance(template, (str, os.PathLike)):
            raise TypeError("template must be a path or a numpy array, got %r" % (type(template),))
        return load_gray(resolve_asset(self.config, os.fspath(template)))

    def locate_all(
        self,
        template: Union[str, np.ndarray],
        *,
        threshold: Optional[float] = None,
        scales: Optional[Sequence[float]] = None,
        roi: Optional[Tuple[int, int, int, int]] = None,
        max_results: int = 1,
    ) -> List[Detection]:
        """Find template occurrences in frame coordinates.

        roi is (x, y, width, height) in frame coordinates and limits both the
        search area and the cost. Returned detections are always translated
        back to full-frame coordinates.
        """
        gray = self.gray
        offset_x = offset_y = 0
        if roi is not None:
            x, y, width, height = (int(v) for v in roi)
            if width <= 0 or height <= 0:
                raise ValueError("roi width and height must be positive")
            if x < 0 or y < 0 or x + width > gray.shape[1] or y + height > gray.shape[0]:
                raise ValueError("roi %r is outside the %dx%d frame"
                                 % ((x, y, width, height), gray.shape[1], gray.shape[0]))
            gray = gray[y:y + height, x:x + width]
            offset_x, offset_y = x, y

        detections = match_template(
            gray,
            self._load_template(template),
            threshold=float(threshold if threshold is not None else self.config.get("threshold", 0.82)),
            scales=tuple(scales if scales is not None else self.config.get("scales", [1.0])),
            max_results=max_results,
            nms_iou=float(self.config.get("nms_iou", 0.3)),
        )
        self.stats.detections += len(detections)
        if offset_x or offset_y:
            detections = [d.shifted(offset_x, offset_y) for d in detections]
        return detections

    def locate(
        self,
        template: Union[str, np.ndarray],
        **kwargs,
    ) -> Optional[Detection]:
        """Best match for template, or None."""
        kwargs.setdefault("max_results", 1)
        found = self.locate_all(template, **kwargs)
        return found[0] if found else None

    def wait_for(self, template: Union[str, np.ndarray], *, timeout: float = 10.0,
                 interval: float = 0.15, grab: bool = True, **kwargs) -> Optional[Detection]:
        """Poll the screen until template appears or timeout expires."""
        if interval <= 0:
            raise ValueError("interval must be positive")
        if timeout < 0:
            raise ValueError("timeout must not be negative")
        deadline = time.monotonic() + timeout
        while True:
            found = self.locate(template, **kwargs)
            if found is not None:
                return found
            if time.monotonic() >= deadline:
                return None
            self.sleep(interval)
            if grab:
                self.frame = self.screen.grab()

    # -- actions -----------------------------------------------------------
    def point(self, target: Target) -> Tuple[float, float]:
        """Convert a frame-relative target into a desktop coordinate."""
        if isinstance(target, Detection):
            x, y = target.center
        elif isinstance(target, (tuple, list)) and len(target) == 2:
            x, y = float(target[0]), float(target[1])
        else:
            raise TypeError("target must be a Detection or an (x, y) pair")
        return x + self.frame.origin[0], y + self.frame.origin[1]

    def click(self, target: Optional[Target] = None, *, button: str = "left",
              offset: Tuple[float, float] = (0.0, 0.0), move: bool = True) -> None:
        """Click a detection, a frame-relative point, or the current position."""
        if target is None:
            self.input.click(button=button)
        else:
            x, y = self.point(target)
            self.input.click(x + offset[0], y + offset[1], button=button, move=move)
        self.stats.actions += 1

    def move(self, target: Target, *, duration: Optional[float] = None) -> None:
        x, y = self.point(target)
        self.input.move_to(x, y, duration=duration)
        self.stats.actions += 1

    def sleep(self, seconds: float) -> None:
        """Abortable sleep; the panic key is checked every 20 ms."""
        end = time.monotonic() + max(0.0, float(seconds))
        while True:
            self.safety.check()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.02, remaining))

    # -- debugging ---------------------------------------------------------
    def snapshot(self, path: str, detections: Optional[Sequence[Detection]] = None) -> str:
        """Save the current frame, optionally with detection boxes."""
        rgb = np.ascontiguousarray(self.frame.bgr[..., ::-1])
        if detections:
            rgb = draw_detections(rgb, detections)
        save_image(path, rgb)
        return path
