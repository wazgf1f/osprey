"""Context detection, coordinate mapping and abortable sleeping."""

from __future__ import annotations

import os
import unittest

import numpy as np

from osprey.core.context import Context
from osprey.core.safety import Safety
from osprey.core.stats import Stats
from osprey.errors import Aborted
from osprey.input.win32 import InputController

from .helpers import FakeScreen, make_frame, sample_template, temp_dir


def build_context(template, position, origin=(0, 0), size=(200, 160)) -> Context:
    frame = make_frame(template, position=position, origin=origin, size=size)
    return Context(
        frame=frame,
        screen=FakeScreen(lambda: frame),
        input=InputController(dry_run=True, seed=1),
        safety=Safety(abort_keys=()),
        config={"threshold": 0.9, "scales": [1.0], "nms_iou": 0.3},
        stats=Stats(),
    )


class TestLocate(unittest.TestCase):
    def setUp(self) -> None:
        self.template = sample_template()
        self.ctx = build_context(self.template, (70, 44))

    def test_finds_template_in_frame(self) -> None:
        det = self.ctx.locate(self.template)
        self.assertIsNotNone(det)
        self.assertEqual((det.x, det.y), (70, 44))
        self.assertGreater(det.score, 0.99)

    def test_missing_template_returns_none(self) -> None:
        self.assertIsNone(self.ctx.locate(sample_template(seed=99)))

    def test_roi_translates_back_to_frame_space(self) -> None:
        det = self.ctx.locate(self.template, roi=(60, 34, 90, 70))
        self.assertEqual((det.x, det.y), (70, 44))

    def test_roi_outside_frame_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.ctx.locate(self.template, roi=(190, 10, 50, 10))

    def test_stats_count_detections(self) -> None:
        self.ctx.locate(self.template)
        self.assertGreaterEqual(self.ctx.stats.detections, 1)

    def test_point_adds_frame_origin(self) -> None:
        frame = make_frame(self.template, (10, 12), origin=(100, 50))
        ctx = Context(
            frame=frame,
            screen=FakeScreen(lambda: frame),
            input=InputController(dry_run=True),
            safety=Safety(abort_keys=()),
            config={"threshold": 0.9},
        )
        det = ctx.locate(self.template)
        x, y = ctx.point(det)
        self.assertAlmostEqual(x, 100 + 10 + det.w / 2)
        self.assertAlmostEqual(y, 50 + 12 + det.h / 2)

    def test_point_accepts_tuple(self) -> None:
        x, y = self.ctx.point((1.5, 2.5))
        self.assertEqual((x, y), (1.5, 2.5))

    def test_click_records_action(self) -> None:
        det = self.ctx.locate(self.template)
        self.ctx.click(det)
        self.assertEqual(self.ctx.stats.actions, 1)
        self.assertTrue(any(entry.startswith("click") for entry in self.ctx.input.history))

    def test_sleep_aborts(self) -> None:
        self.ctx.safety.request_stop("unit test")
        with self.assertRaises(Aborted):
            self.ctx.sleep(1.0)

    def test_wait_for_times_out(self) -> None:
        self.assertIsNone(self.ctx.wait_for(sample_template(seed=42), timeout=0.05, interval=0.01))

    def test_snapshot_writes_png(self) -> None:
        with temp_dir() as folder:
            path = os.path.join(folder, "frame.png")
            self.ctx.snapshot(path)
            self.assertTrue(os.path.getsize(path) > 0)

    def test_snapshot_with_boxes(self) -> None:
        det = self.ctx.locate(self.template)
        with temp_dir() as folder:
            path = os.path.join(folder, "frame.png")
            self.ctx.snapshot(path, [det])
            self.assertTrue(os.path.getsize(path) > 0)


if __name__ == "__main__":
    unittest.main()
