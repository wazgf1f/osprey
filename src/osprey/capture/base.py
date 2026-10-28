"""Frame container and the frame-source contract."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple

import numpy as np


class FrameSource(Protocol):
    """Anything that can produce a Frame (a real screen, a video, a test stub)."""

    def grab(self) -> "Frame":  # pragma: no cover - protocol definition
        ...

    def close(self) -> None:  # pragma: no cover - protocol definition
        ...


@dataclass
class Frame:
    """A BGRA image plus the desktop coordinate of its top-left pixel.

    Pixels are stored as BGRA uint8 with shape (height, width, 4). The alpha
    byte is unused for screen captures but keeping four channels makes the
    buffer directly compatible with the 32-bit DIB that GDI produces.

    Frame coordinates are local to the image. Add origin to translate a
    detection into a desktop coordinate, which is what the input layer wants.
    """

    bgra: np.ndarray
    origin: Tuple[int, int] = (0, 0)
    timestamp: float = field(default_factory=time.perf_counter)
    _gray: Optional[np.ndarray] = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bgra, np.ndarray):
            raise TypeError("bgra must be a numpy array")
        if self.bgra.ndim != 3 or self.bgra.shape[2] != 4:
            raise ValueError(
                "bgra must have shape (height, width, 4), got %r" % (self.bgra.shape,)
            )
        if self.bgra.dtype != np.uint8:
            raise ValueError("bgra must be uint8, got %s" % self.bgra.dtype)
        if self.bgra.shape[0] == 0 or self.bgra.shape[1] == 0:
            raise ValueError("frame is empty")

    @property
    def width(self) -> int:
        return int(self.bgra.shape[1])

    @property
    def height(self) -> int:
        return int(self.bgra.shape[0])

    @property
    def bgr(self) -> np.ndarray:
        """View of the frame with the alpha channel dropped."""
        return self.bgra[..., :3]

    def gray(self) -> np.ndarray:
        """Luma image (BT.601 weights), computed once per frame."""
        if self._gray is None:
            b = self.bgra[..., 0].astype(np.float32)
            g = self.bgra[..., 1].astype(np.float32)
            r = self.bgra[..., 2].astype(np.float32)
            self._gray = np.clip(0.114 * b + 0.587 * g + 0.299 * r, 0, 255).astype(np.uint8)
        return self._gray

    def crop(self, x: int, y: int, width: int, height: int) -> "Frame":
        """Return a sub-frame; the new origin is adjusted accordingly."""
        x, y, width, height = int(x), int(y), int(width), int(height)
        if width <= 0 or height <= 0:
            raise ValueError("crop width and height must be positive")
        if x < 0 or y < 0 or x + width > self.width or y + height > self.height:
            raise ValueError(
                "crop %r is outside the %dx%d frame" % ((x, y, width, height), self.width, self.height)
            )
        sub = self.bgra[y:y + height, x:x + width]
        return Frame(bgra=sub, origin=(self.origin[0] + x, self.origin[1] + y))

    def mean_brightness(self) -> float:
        """Average luma; handy for detecting a black or disconnected screen."""
        return float(self.gray().mean())
