"""End-to-end check against the real desktop.

Captures the screen, cuts a random high-contrast patch out of it, then asks the
matcher to find that patch again. This exercises GDI capture, luma conversion,
the correlator and coordinate mapping in one go, without sending any input.

    python tools/selftest.py
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

import numpy as np

from osprey.capture.gdi import GdiGrabber
from osprey.vision.match import match_template


def pick_patch(gray: np.ndarray, size: int, seed: int) -> tuple:
    """Find a patch with enough contrast that matching is meaningful."""
    rng = np.random.default_rng(seed)
    height, width = gray.shape
    best = None
    for _ in range(400):
        x = int(rng.integers(0, max(1, width - size)))
        y = int(rng.integers(0, max(1, height - size)))
        patch = gray[y:y + size, x:x + size]
        contrast = float(patch.std())
        if best is None or contrast > best[0]:
            best = (contrast, x, y)
        if contrast > 18:
            break
    contrast, x, y = best
    return gray[y:y + size, x:x + size].copy(), x, y, contrast


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=56)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args()

    with GdiGrabber() as grabber:
        frame = grabber.grab()
        print("screen: %dx%d, brightness %.1f" % (frame.width, frame.height, frame.mean_brightness()))
        gray = frame.gray()
        template, x, y, contrast = pick_patch(gray, args.size, seed=1)
        print("patch : %dx%d at (%d, %d), contrast %.1f" % (
            args.size, args.size, x, y, contrast))

        timings = []
        result = None
        for _ in range(args.runs):
            start = time.perf_counter()
            found = match_template(gray, template, threshold=args.threshold, max_results=8)
            timings.append((time.perf_counter() - start) * 1000.0)
            result = found

        if not result:
            print("FAIL: patch was not found on its own screen")
            return 1

        # The same pixels can legitimately appear more than once (repeated list
        # rows, duplicated icons). The patch must be among the matches, not
        # necessarily the first one.
        target = next(
            (det for det in result if abs(det.x - x) <= 1 and abs(det.y - y) <= 1), None
        )
        if target is None:
            top = result[0]
            print("FAIL: patch at (%d, %d) not found; best was (%d, %d) score %.4f"
                  % (x, y, top.x, top.y, top.score))
            return 1

        print("match : (%d, %d) score %.4f, %d candidate(s)" % (
            target.x, target.y, target.score, len(result)))
        print("timing: min %.1f ms, median %.1f ms, max %.1f ms" % (
            min(timings), statistics.median(timings), max(timings)))

        ok = target.score >= 0.99
        print("status:", "OK" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
