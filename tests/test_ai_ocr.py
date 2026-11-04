"""Windows OCR output parsing without invoking PowerShell."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from osprey.ai.ocr import _WINDOWS_SCRIPT, OcrError, OcrItem, default_ocr_backend, ocr_frame

from .helpers import make_frame, sample_template


@unittest.skipUnless(sys.platform == "win32", "STARTUPINFO is Windows-only")
class TestWindowsTimeout(unittest.TestCase):
    def test_timeout_becomes_ocr_error(self) -> None:
        import numpy as np
        from PIL import Image

        from osprey.ai.ocr import _run_windows_ocr
        from osprey.capture.base import Frame

        image = Image.new("RGB", (20, 20), "white")
        frame = Frame(np.asarray(image.convert("RGBA"))[..., [2, 1, 0, 3]])
        with mock.patch("osprey.ai.ocr.sys.platform", "win32"):
            with mock.patch("osprey.ai.ocr.shutil.which", return_value=sys.executable):
                with mock.patch("osprey.ai.ocr.subprocess.run",
                                side_effect=__import__("subprocess").TimeoutExpired("x", 1)):
                    with self.assertRaises(OcrError):
                        _run_windows_ocr(image)


class TestDedupe(unittest.TestCase):
    def test_keeps_longer_overlapping_text(self) -> None:
        from osprey.ai.ocr import _dedupe

        items = [
            OcrItem("目标包含点击", (0, 0, 100, 20)),
            OcrItem("目标包含点击浏览器", (0, 0, 150, 20)),
        ]
        merged = _dedupe(items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].text, "目标包含点击浏览器")

    def test_keeps_separate_buttons(self) -> None:
        from osprey.ai.ocr import _dedupe

        items = [
            OcrItem("上一节", (0, 0, 64, 20)),
            OcrItem("下一节", (70, 0, 64, 20)),
        ]
        self.assertEqual(len(_dedupe(items)), 2)


class TestWindowsScript(unittest.TestCase):
    def test_falls_back_to_profile_language_without_chinese_pack(self) -> None:
        self.assertIn("TryCreateFromUserProfileLanguages", _WINDOWS_SCRIPT)


class TestBackendSelection(unittest.TestCase):
    def test_broken_rapidocr_falls_back_to_windows(self) -> None:
        with mock.patch("osprey.ai.ocr._rapid_engine", side_effect=RuntimeError("broken")):
            with mock.patch.dict(sys.modules, {"pytesseract": None}):
                with mock.patch("osprey.ai.ocr.sys.platform", "win32"):
                    with mock.patch("osprey.ai.ocr.shutil.which", return_value="powershell"):
                        self.assertEqual(default_ocr_backend(), "windows")


@unittest.skipUnless(sys.platform == "win32", "Windows OCR runs on Windows")
class TestWindowsOcr(unittest.TestCase):
    def test_aborts_before_backend(self) -> None:
        with self.assertRaises(OcrError):
            ocr_frame(make_frame(sample_template()), should_abort=lambda: True)

    def test_parses_utf8_json_and_boxes(self) -> None:
        payload = [{
            "text": "确定 取消",
            "words": [
                {"text": "确定", "x": 10, "y": 20, "w": 40, "h": 20},
                {"text": "取消", "x": 60, "y": 20, "w": 40, "h": 20},
            ],
        }]
        def fake_run(command, **kwargs):
            out_path = command[command.index("-Out") + 1]
            Path(out_path).write_text(json.dumps(payload, ensure_ascii=False),
                                      encoding="utf-8")
            return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

        frame = make_frame(sample_template())
        with mock.patch("osprey.ai.ocr._windows_script", return_value=Path("ocr.ps1")):
            with mock.patch("osprey.ai.ocr.subprocess.run", side_effect=fake_run) as run:
                items = ocr_frame(frame, backend="windows")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].text, "确定取消")
        self.assertEqual(items[0].box, (10, 20, 90, 20))
        self.assertIn("-Out", run.call_args.args[0])

    def test_empty_output_is_an_error(self) -> None:
        completed = SimpleNamespace(stdout=b"", stderr=b"no engine", returncode=1)
        frame = make_frame(sample_template())
        with mock.patch("osprey.ai.ocr._windows_script", return_value=Path("ocr.ps1")):
            with mock.patch("osprey.ai.ocr.subprocess.run", return_value=completed):
                with self.assertRaises(Exception):
                    ocr_frame(frame, backend="windows")


if __name__ == "__main__":
    unittest.main()
