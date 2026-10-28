"""Image loading, saving and debugging overlays."""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

from ..errors import VisionError
from .match import Detection, ensure_gray


@lru_cache(maxsize=32)
def load_gray(path: str) -> np.ndarray:
    """Load an image as grayscale, cached by path.

    Templates are usually matched on every tick, so decoding them once is a
    meaningful saving. Call load_gray.cache_clear() after editing a file.
    """
    try:
        with Image.open(path) as img:
            return np.asarray(img.convert("L"))
    except (OSError, ValueError) as exc:
        raise VisionError("could not load image %r: %s" % (path, exc)) from exc


def load_rgb(path: str) -> np.ndarray:
    try:
        with Image.open(path) as img:
            return np.asarray(img.convert("RGB"))
    except (OSError, ValueError) as exc:
        raise VisionError("could not load image %r: %s" % (path, exc)) from exc


def save_image(path: str, image: np.ndarray) -> None:
    """Save a gray, RGB or BGR array as PNG, creating parent folders as needed."""
    from pathlib import Path

    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    array = np.ascontiguousarray(image)
    if array.ndim == 2:
        mode_array = array.astype(np.uint8)
        Image.fromarray(mode_array, mode="L").save(path)
    elif array.ndim == 3 and array.shape[2] == 3:
        Image.fromarray(array.astype(np.uint8), mode="RGB").save(path)
    elif array.ndim == 3 and array.shape[2] == 4:
        Image.fromarray(array[..., :3].astype(np.uint8), mode="RGB").save(path)
    else:
        raise VisionError("cannot save an array with shape %r" % (array.shape,))


def draw_detections(
    image_rgb: np.ndarray,
    detections: Sequence[Detection],
    offset: Tuple[int, int] = (0, 0),
    color: Tuple[int, int, int] = (255, 64, 64),
    width: int = 2,
    label: bool = True,
) -> np.ndarray:
    """Return a copy of image_rgb with detection boxes drawn on it."""
    canvas = Image.fromarray(np.ascontiguousarray(image_rgb).astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(canvas)
    for det in detections:
        x0 = det.x + offset[0]
        y0 = det.y + offset[1]
        x1 = x0 + det.w - 1
        y1 = y0 + det.h - 1
        draw.rectangle([x0, y0, x1, y1], outline=color, width=width)
        if label:
            text = "%.3f" % det.score
            draw.text((x0 + 2, max(0, y0 - 12)), text, fill=color)
    return np.asarray(canvas)


def crop_gray(image: np.ndarray, box: Tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    gray = ensure_gray(image)
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > gray.shape[1] or y + h > gray.shape[0]:
        raise VisionError("crop %r is outside the %dx%d image" % (box, gray.shape[1], gray.shape[0]))
    return gray[y:y + h, x:x + w]
