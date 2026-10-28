"""Shared test helpers: synthetic frames and a fake screen."""

from __future__ import annotations

import contextlib
import pathlib
import shutil
import uuid

import numpy as np

from osprey.capture.base import Frame

_TMP_ROOT = pathlib.Path(__file__).resolve().parent / ".tmp"


@contextlib.contextmanager
def temp_dir():
    """Temporary directory inside the repo.

    Not tempfile.mkdtemp: some Windows sandboxes give 0o700 directories an ACL
    that denies writes to the creating process. A default-mode folder works.
    """
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = _TMP_ROOT / ("t" + uuid.uuid4().hex[:12])
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def make_frame(
    template: np.ndarray,
    position=(40, 30),
    size=(200, 160),
    origin=(0, 0),
    background: int = 0,
) -> Frame:
    width, height = size
    canvas = np.full((height, width, 4), background, dtype=np.uint8)
    canvas[..., 3] = 255
    x, y = position
    th, tw = template.shape
    for channel in range(3):
        canvas[y:y + th, x:x + tw, channel] = template
    return Frame(bgra=canvas, origin=origin)


class FakeScreen:
    """A frame source that rebuilds its frame on every grab."""

    def __init__(self, factory) -> None:
        self.factory = factory
        self.grabs = 0
        self.closed = False

    def grab(self) -> Frame:
        self.grabs += 1
        return self.factory()

    def close(self) -> None:
        self.closed = True


def sample_template(seed: int = 11, height: int = 18, width: int = 22) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(40, 240, size=(height, width), dtype=np.uint8)
