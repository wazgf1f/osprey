"""Normalised cross-correlation template matching.

Two backends implement the same maths:

* numpy - a pure FFT implementation. It is exact (validated against brute
  force in the test suite) and needs nothing beyond NumPy.
* opencv - matchTemplate with TM_CCOEFF_NORMED. Around 5-10x faster, used
  automatically when opencv-python is installed.

Both return scores in [-1, 1] where 1.0 means a pixel-perfect match.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from ..errors import VisionError

try:  # optional acceleration
    import cv2 as _cv2  # type: ignore
except Exception:  # pragma: no cover - depends on the environment
    _cv2 = None

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    """A matched rectangle in image coordinates."""

    x: int
    y: int
    w: int
    h: int
    score: float
    scale: float = 1.0

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    @property
    def box(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def iou(self, other: "Detection") -> float:
        ax2, ay2 = self.x + self.w, self.y + self.h
        bx2, by2 = other.x + other.w, other.y + other.h
        ix = max(0, min(ax2, bx2) - max(self.x, other.x))
        iy = max(0, min(ay2, by2) - max(self.y, other.y))
        inter = ix * iy
        union = self.w * self.h + other.w * other.h - inter
        return float(inter) / float(union) if union > 0 else 0.0

    def shifted(self, dx: int, dy: int) -> "Detection":
        return Detection(self.x + dx, self.y + dy, self.w, self.h, self.score, self.scale)


# ---------------------------------------------------------------------------
# image helpers
# ---------------------------------------------------------------------------
def ensure_gray(image: np.ndarray) -> np.ndarray:
    """Return a 2-D view of an image, treating 3-channel input as BGR."""
    array = np.asarray(image)
    if array.ndim == 2:
        return array
    if array.ndim == 3 and array.shape[2] >= 3:
        b = array[..., 0].astype(np.float32)
        g = array[..., 1].astype(np.float32)
        r = array[..., 2].astype(np.float32)
        return np.clip(0.114 * b + 0.587 * g + 0.299 * r, 0, 255).astype(np.uint8)
    raise VisionError("expected a 2-D grayscale or HxWx3 BGR image, got shape %r" % (array.shape,))


def to_uint8(image: np.ndarray) -> np.ndarray:
    """Normalise an image to uint8 without silently clipping 0..1 floats."""
    array = np.asarray(image)
    if array.dtype == np.uint8:
        return array
    if np.issubdtype(array.dtype, np.floating):
        finite = array[np.isfinite(array)]
        peak = float(finite.max()) if finite.size else 0.0
        if peak <= 1.0 + 1e-6:
            array = array * 255.0
    return np.clip(array, 0, 255).astype(np.uint8)


def _smooth_size(n: int) -> int:
    """Smallest even 5-smooth number >= n (fast FFT length)."""
    n = max(2, int(n))
    while True:
        m = n
        for prime in (2, 3, 5):
            while m % prime == 0:
                m //= prime
        if m == 1 and n % 2 == 0:
            return n
        n += 1


def _integral(array: np.ndarray) -> np.ndarray:
    out = np.empty((array.shape[0] + 1, array.shape[1] + 1), dtype=np.float64)
    out[0, :] = 0.0
    out[:, 0] = 0.0
    np.cumsum(array, axis=0, out=out[1:, 1:])
    np.cumsum(out[1:, 1:], axis=1, out=out[1:, 1:])
    return out


def _window_sums(integral: np.ndarray, height: int, width: int) -> np.ndarray:
    """Sum over every height x width window, shape (H-h+1, W-w+1)."""
    return (
        integral[height:, width:]
        - integral[:-height, width:]
        - integral[height:, :-width]
        + integral[:-height, :-width]
    )


def ncc_map(image: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Full normalised cross-correlation map for a single template size."""
    img = ensure_gray(image).astype(np.float64, copy=False)
    tpl = ensure_gray(template).astype(np.float64, copy=False)
    th, tw = tpl.shape
    if th > img.shape[0] or tw > img.shape[1]:
        raise VisionError(
            "template %dx%d is larger than the %dx%d image" % (tw, th, img.shape[1], img.shape[0])
        )
    return _ncc_map(img, tpl)


def _ncc_map(img: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    th, tw = tpl.shape
    centred = tpl - tpl.mean()
    tpl_norm = float(np.sqrt((centred * centred).sum()))
    if tpl_norm < 1e-9:
        raise VisionError("template is flat (no contrast); matching is undefined")

    fh = _smooth_size(img.shape[0] + th - 1)
    fw = _smooth_size(img.shape[1] + tw - 1)
    spectrum = np.fft.rfft2(img, (fh, fw))
    flipped = np.fft.rfft2(centred[::-1, ::-1], (fh, fw))
    correlation = np.fft.irfft2(spectrum * flipped, (fh, fw))

    height = img.shape[0] - th + 1
    width = img.shape[1] - tw + 1
    numerator = correlation[th - 1: th - 1 + height, tw - 1: tw - 1 + width]

    integral = _integral(img)
    integral_sq = _integral(img * img)
    area = float(th * tw)
    sums = _window_sums(integral, th, tw)
    sums_sq = _window_sums(integral_sq, th, tw)
    variance = sums_sq - (sums * sums) / area
    denominator = np.sqrt(np.maximum(variance, 0.0)) * tpl_norm

    result = np.zeros_like(numerator)
    np.divide(numerator, denominator, out=result, where=denominator > 1e-9)
    return np.clip(result, -1.0, 1.0)


def _ncc_maps(image: np.ndarray, templates: Sequence[np.ndarray]) -> List[np.ndarray]:
    """One shared image FFT for several template sizes."""
    img = image.astype(np.float64, copy=False)
    tallest = max(t.shape[0] for t in templates)
    widest = max(t.shape[1] for t in templates)
    fh = _smooth_size(img.shape[0] + tallest - 1)
    fw = _smooth_size(img.shape[1] + widest - 1)
    spectrum = np.fft.rfft2(img, (fh, fw))

    integral = _integral(img)
    integral_sq = _integral(img * img)

    maps: List[np.ndarray] = []
    for tpl in templates:
        th, tw = tpl.shape
        centred = tpl - tpl.mean()
        tpl_norm = float(np.sqrt((centred * centred).sum()))
        if tpl_norm < 1e-9:
            raise VisionError("template is flat (no contrast); matching is undefined")
        flipped = np.fft.rfft2(centred[::-1, ::-1], (fh, fw))
        correlation = np.fft.irfft2(spectrum * flipped, (fh, fw))

        height = img.shape[0] - th + 1
        width = img.shape[1] - tw + 1
        numerator = correlation[th - 1: th - 1 + height, tw - 1: tw - 1 + width]

        area = float(th * tw)
        sums = _window_sums(integral, th, tw)
        sums_sq = _window_sums(integral_sq, th, tw)
        variance = sums_sq - (sums * sums) / area
        denominator = np.sqrt(np.maximum(variance, 0.0)) * tpl_norm

        result = np.zeros_like(numerator)
        np.divide(numerator, denominator, out=result, where=denominator > 1e-9)
        maps.append(np.clip(result, -1.0, 1.0))
    return maps


def _cv_match(image: np.ndarray, template: np.ndarray) -> np.ndarray:
    result = _cv2.matchTemplate(image.astype(np.float32), template.astype(np.float32),
                                _cv2.TM_CCOEFF_NORMED)
    return np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)


def _resize(gray: np.ndarray, size: Tuple[int, int], box: bool = False) -> np.ndarray:
    from PIL import Image

    filter_ = Image.BOX if box else Image.BILINEAR
    return np.asarray(Image.fromarray(gray).resize(size, filter_))


def _auto_downscale(image_shape: Tuple[int, int], template_shape: Tuple[int, int]) -> int:
    """Pick a coarse-search factor from the screen area and template size.

    Searching a 4K frame at full resolution costs ~0.5 s per template with the
    numpy backend. Halving each axis cuts the FFT work by ~4x; the peak is then
    refined at full resolution, so accuracy is unchanged. Very small templates
    are excluded because half-resolution detail would be lost.
    """
    height, width = image_shape
    th, tw = template_shape
    smallest = min(th, tw)
    area = height * width
    if smallest < 16:
        return 1
    if area >= 8_000_000 and smallest >= 24:
        return 4
    if area >= 1_000_000:
        return 2
    return 1


def _score_maps(image: np.ndarray, templates: Sequence[np.ndarray], backend: str) -> List[np.ndarray]:
    if backend == "opencv":
        return [_cv_match(image, tpl) for tpl in templates]
    return _ncc_maps(image, templates)


def _refine(
    image: np.ndarray,
    template: np.ndarray,
    x: int,
    y: int,
    scale: float,
    margin: int,
) -> Optional[Detection]:
    """Re-score one coarse candidate on the full-resolution image."""
    height, width = template.shape
    x0 = max(0, x - margin)
    y0 = max(0, y - margin)
    x1 = min(image.shape[1], x + width + margin)
    y1 = min(image.shape[0], y + height + margin)
    window = image[y0:y1, x0:x1]
    if window.shape[0] < height or window.shape[1] < width:
        return None
    scores = _ncc_map(window.astype(np.float64, copy=False), template.astype(np.float64, copy=False))
    index = int(np.argmax(scores))
    iy, ix = divmod(index, scores.shape[1])
    return Detection(x0 + ix, y0 + iy, width, height, float(scores[iy, ix]), scale)


def _candidate_peaks(score_map: np.ndarray, threshold: float, limit: int) -> List[Tuple[int, int, float]]:
    flat = score_map.ravel()
    if limit <= 0 or flat.size == 0:
        return []
    if limit < flat.size:
        indices = np.argpartition(flat, -limit)[-limit:]
    else:
        indices = np.arange(flat.size)
    indices = indices[flat[indices] >= threshold]
    if indices.size == 0:
        return []
    order = indices[np.argsort(-flat[indices], kind="stable")]
    width = score_map.shape[1]
    peaks = []
    for index in order:
        y, x = divmod(int(index), width)
        peaks.append((x, y, float(flat[index])))
    return peaks


def _nms(detections: List[Detection], iou_threshold: float) -> List[Detection]:
    kept: List[Detection] = []
    for candidate in sorted(detections, key=lambda d: d.score, reverse=True):
        if all(candidate.iou(other) <= iou_threshold for other in kept):
            kept.append(candidate)
    return kept


def _resolve_backend(backend: str) -> str:
    if backend not in ("auto", "numpy", "opencv"):
        raise ValueError("backend must be 'auto', 'numpy' or 'opencv', got %r" % (backend,))
    if backend in ("auto", "opencv"):
        if _cv2 is not None:
            return "opencv"
        if backend == "opencv":
            logger.warning("opencv backend requested but cv2 is not installed; using numpy")
    return "numpy"


def match_template(
    image: np.ndarray,
    template: np.ndarray,
    *,
    threshold: float = 0.8,
    scales: Sequence[float] = (1.0,),
    max_results: int = 10,
    nms_iou: float = 0.3,
    backend: str = "auto",
    downscale: Optional[int] = None,
) -> List[Detection]:
    """Find every occurrence of template in image above threshold.

    Args:
        image: 2-D grayscale or HxWx3 BGR array.
        template: the same, smaller than image.
        threshold: minimum NCC score, normally 0.75-0.9.
        scales: template scales to try, e.g. (1.0, 0.9, 1.1) for DPI changes.
        max_results: cap on returned detections.
        nms_iou: detections overlapping more than this are merged.
        backend: 'auto', 'numpy' or 'opencv'.
        downscale: coarse-search factor. None picks automatically (1 disables).

    Returns:
        Detections sorted by score, best first. Coordinates are relative to
        image; add the capture origin to obtain desktop coordinates.
    """
    if max_results <= 0:
        return []
    if not -1.0 <= threshold <= 1.0:
        raise ValueError("threshold must be within [-1, 1]")
    if not 0.0 <= nms_iou <= 1.0:
        raise ValueError("nms_iou must be within [0, 1]")

    gray_image = to_uint8(ensure_gray(image))
    gray_template = to_uint8(ensure_gray(template))
    if gray_image.ndim != 2 or gray_template.ndim != 2:
        raise VisionError("image and template must be two-dimensional after conversion")

    requested: List[float] = []
    for scale in scales:
        value = float(scale)
        if not np.isfinite(value) or value <= 0:
            raise ValueError("scales must be positive finite numbers, got %r" % (scale,))
        requested.append(value)
    if not requested:
        raise ValueError("scales must not be empty")

    base_h, base_w = gray_template.shape
    image_h, image_w = gray_image.shape

    prepared: List[Tuple[float, np.ndarray]] = []
    seen: set = set()
    for scale in requested:
        width = max(1, int(round(base_w * scale)))
        height = max(1, int(round(base_h * scale)))
        if width > image_w or height > image_h:
            logger.debug("skipping scale %.3f: template %dx%d exceeds image", scale, width, height)
            continue
        if (height, width) in seen:
            continue
        seen.add((height, width))
        scaled = gray_template if (height, width) == (base_h, base_w) else _resize(
            gray_template, (width, height)
        )
        prepared.append((scale, scaled))
    if not prepared:
        raise VisionError(
            "no scale fits: template is %dx%d, image is %dx%d"
            % (base_w, base_h, image_w, image_h)
        )

    if downscale is not None and (isinstance(downscale, bool) or int(downscale) < 1):
        raise ValueError("downscale must be a positive integer or None")

    resolved = _resolve_backend(backend)
    factor = int(downscale) if downscale is not None else _auto_downscale(
        gray_image.shape, gray_template.shape
    )
    if factor > 1 and min(min(t.shape) for _, t in prepared) // factor < 6:
        factor = 1

    found: List[Detection] = []
    if factor > 1:
        small_image = _resize(
            gray_image,
            (max(1, image_w // factor), max(1, image_h // factor)),
            box=True,
        )
        coarse: List[Tuple[float, np.ndarray, np.ndarray]] = []
        for scale, tpl in prepared:
            th, tw = tpl.shape
            small = _resize(tpl, (max(1, tw // factor), max(1, th // factor)), box=True)
            coarse.append((scale, tpl, small))
        maps = _score_maps(small_image, [small for _, _, small in coarse], resolved)
        # The coarse pass is only a proposal generator. Fine textures can drop
        # to ~0.3 at half resolution even at the true location, so every peak is
        # kept and the full-resolution refinement decides with the real score.
        per_scale = max(8, max_results * 4)
        for (scale, tpl, _), score_map in zip(coarse, maps):
            for x, y, _score in _candidate_peaks(score_map, -1.0, per_scale):
                refined = _refine(gray_image, tpl, x * factor, y * factor, scale, factor + 2)
                if refined is not None and refined.score >= threshold:
                    found.append(refined)
    else:
        maps = _score_maps(gray_image, [tpl for _, tpl in prepared], resolved)
        per_scale = max(4, max_results * 3)
        for (scale, tpl), score_map in zip(prepared, maps):
            height, width = tpl.shape
            for x, y, score in _candidate_peaks(score_map, threshold, per_scale):
                found.append(Detection(x, y, width, height, score, scale))

    return _nms(found, nms_iou)[:max_results]
