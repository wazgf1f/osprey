"""Timer clicker without touching the real mouse."""

from __future__ import annotations

import unittest
from unittest import mock

from osprey.clicker import IntervalClicker


class TestIntervalClicker(unittest.TestCase):
    def test_runs_requested_number_of_clicks(self) -> None:
        seen = []
        clicker = IntervalClicker(0.001, count=3, dry_run=True,
                                  on_click=seen.append)
        self.assertEqual(clicker.run(), 3)
        self.assertEqual(seen, [1, 2, 3])

    def test_stop_interrupts_between_clicks(self) -> None:
        clicker = IntervalClicker(10, count=0, dry_run=True)
        with mock.patch.object(clicker._stop, "wait", return_value=True):
            self.assertEqual(clicker.run(), 0)

    def test_validation(self) -> None:
        with self.assertRaises(ValueError):
            IntervalClicker(0)
        with self.assertRaises(ValueError):
            IntervalClicker(1, count=-1)

    def test_f12_stops_before_click(self) -> None:
        with mock.patch("osprey.clicker.is_key_pressed", return_value=True):
            clicker = IntervalClicker(0.001, count=0)
            self.assertEqual(clicker.run(), 0)


if __name__ == "__main__":
    unittest.main()
