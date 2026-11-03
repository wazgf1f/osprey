"""Per-run log file creation."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from osprey import logging_setup


class TestRunLog(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.patch = mock.patch.object(
            logging_setup, "log_directory",
            return_value=Path(self.folder.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        handler = logging_setup._ACTIVE_HANDLER
        if handler is not None:
            logging.getLogger("osprey").removeHandler(handler)
            handler.close()
        logging_setup._ACTIVE_PATH = None
        logging_setup._ACTIVE_HANDLER = None

    def test_creates_one_utf8_log_per_process(self) -> None:
        path = logging_setup.start_run_log("test", ["osprey", "doctor"])
        logging.getLogger("osprey").info("hello 日志")
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("hello 日志", text)
        self.assertIn("component=test", text)
        self.assertIn("argv=['osprey', 'doctor']", text)
        self.assertEqual(logging_setup.start_run_log("test", []), path)

    def test_falls_back_when_directory_is_not_writable(self) -> None:
        with mock.patch.object(logging_setup, "log_directory",
                               side_effect=OSError("denied")):
            self.assertIsNone(logging_setup.start_run_log("test", []))


if __name__ == "__main__":
    unittest.main()
