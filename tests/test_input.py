"""Key parsing, struct layout and the dry-run input path."""

from __future__ import annotations

import ctypes
import sys
import time
import unittest

from osprey.errors import Aborted
from osprey.input.win32 import (
    INPUT,
    KEYBDINPUT,
    MOUSEINPUT,
    InputController,
    resolve_key,
)


class TestKeyResolution(unittest.TestCase):
    def test_letters_and_digits(self) -> None:
        self.assertEqual(resolve_key("a"), ord("A"))
        self.assertEqual(resolve_key("Z"), ord("Z"))
        self.assertEqual(resolve_key("7"), ord("7"))

    def test_named_keys(self) -> None:
        self.assertEqual(resolve_key("enter"), 0x0D)
        self.assertEqual(resolve_key("Space"), 0x20)
        self.assertEqual(resolve_key("esc"), 0x1B)
        self.assertEqual(resolve_key("F12"), 0x7B)
        self.assertEqual(resolve_key("f1"), 0x70)

    def test_integer_passthrough(self) -> None:
        self.assertEqual(resolve_key(0x41), 0x41)

    def test_rejects_nonsense(self) -> None:
        for bad in ("", "nope", "f25", True, None, 3.5, -5, 999):
            with self.subTest(bad=bad):
                with self.assertRaises((ValueError, TypeError)):
                    resolve_key(bad)


@unittest.skipUnless(sys.platform == "win32", "Win32 ABI layout")
class TestStructLayout(unittest.TestCase):
    def test_sizes_match_the_win32_abi(self) -> None:
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(MOUSEINPUT), 32)
            self.assertEqual(ctypes.sizeof(KEYBDINPUT), 24)
            self.assertEqual(ctypes.sizeof(INPUT), 40)


class TestDryRunInput(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = InputController(dry_run=True, seed=3)

    def test_click_records_history(self) -> None:
        self.controller.click(100, 200)
        self.assertTrue(any(entry.startswith("click left") for entry in self.controller.history))

    def test_keyboard_history(self) -> None:
        self.controller.press("enter")
        self.assertIn("key_down enter", self.controller.history)
        self.assertIn("key_up enter", self.controller.history)

    def test_write_surrogate_pairs(self) -> None:
        self.controller.write("a\U0001F600")
        typed = [entry for entry in self.controller.history if entry.startswith("type ")]
        self.assertEqual(len(typed), 3)  # 'a' plus two UTF-16 units

    def test_non_finite_sleep_is_rejected(self) -> None:
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.controller._sleep(value)

    def test_non_finite_speed_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            InputController(speed=float("nan"))

    def test_move_produces_a_path(self) -> None:
        self.controller.move_to(300, 240, duration=0.01)
        moves = [entry for entry in self.controller.history if entry.startswith("move ")]
        self.assertGreater(len(moves), 3)
        self.assertEqual(moves[-1], "move 300,240")

    def test_click_with_coords_and_no_humanize_moves(self) -> None:
        self.controller.click(120, 80, move=False)
        moves = [entry for entry in self.controller.history if entry.startswith("move ")]
        self.assertEqual(moves[-1], "move 120,80")
        self.assertTrue(any(entry.startswith("click left") for entry in self.controller.history))

    def test_abort_guard_prevents_everything(self) -> None:
        controller = InputController(dry_run=True, should_abort=lambda: True)
        with self.assertRaises(Aborted):
            controller.click(1, 2)
        self.assertEqual(controller.history, [])

    def test_hold_can_be_aborted(self) -> None:
        calls = {"count": 0}

        def guard() -> bool:
            calls["count"] += 1
            return calls["count"] > 2

        controller = InputController(dry_run=True, should_abort=guard)
        started = time.monotonic()
        with self.assertRaises(Aborted):
            controller.hold("a", 5.0)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_release_all_works_after_an_abort(self) -> None:
        controller = InputController(dry_run=True)
        controller.key_down("a")
        controller.should_abort = lambda: True
        controller.release_all()
        self.assertIn("key_up a", controller.history)

    def test_release_all_is_safe_when_nothing_is_held(self) -> None:
        self.controller.release_all()

    def test_invalid_button(self) -> None:
        with self.assertRaises(ValueError):
            self.controller.click(button="elbow")


if __name__ == "__main__":
    unittest.main()
