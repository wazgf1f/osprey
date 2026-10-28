"""Stop conditions."""

from __future__ import annotations

import os
import time
import unittest

from osprey.core.safety import Safety
from osprey.errors import Aborted

from .helpers import temp_dir


class TestSafety(unittest.TestCase):
    def test_no_guards_passes(self) -> None:
        safety = Safety(abort_keys=())
        safety.start()
        safety.check()

    def test_stop_file(self) -> None:
        with temp_dir() as folder:
            path = os.path.join(folder, "STOP")
            safety = Safety(abort_keys=(), stop_file=path)
            safety.start()
            safety.check()
            open(path, "w").close()
            self.assertTrue(safety.should_abort())
            with self.assertRaises(Aborted):
                safety.check()

    def test_max_runtime(self) -> None:
        safety = Safety(abort_keys=(), max_runtime=0.05)
        safety.start()
        time.sleep(0.07)
        with self.assertRaises(Aborted):
            safety.check()

    def test_reset_clears_state(self) -> None:
        safety = Safety(abort_keys=())
        safety.request_stop("because")
        self.assertTrue(safety.should_abort())
        safety.reset()
        self.assertFalse(safety.aborted)
        safety.check()

    def test_invalid_runtime(self) -> None:
        with self.assertRaises(ValueError):
            Safety(max_runtime=0)

    def test_non_finite_runtime_is_rejected(self) -> None:
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Safety(max_runtime=value)

    def test_invalid_abort_key_is_rejected_early(self) -> None:
        with self.assertRaises(ValueError):
            Safety(abort_keys=("not-a-real-key",))

    def test_string_abort_key_is_not_split(self) -> None:
        self.assertEqual(Safety(abort_keys="f12").abort_keys, ("f12",))

    def test_valid_abort_keys_are_kept(self) -> None:
        safety = Safety(abort_keys=("f12", "ctrl"))
        self.assertEqual(safety.abort_keys, ("f12", "ctrl"))


if __name__ == "__main__":
    unittest.main()
