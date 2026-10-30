"""OCR text cleanup for Chinese screens."""

from __future__ import annotations

import unittest

from osprey.ai.ocr import normalize_text


class TestNormalizeText(unittest.TestCase):
    def test_removes_spaces_between_cjk_characters(self) -> None:
        self.assertEqual(normalize_text("下 一 页 1 2 3"), "下一页 1 2 3")
        self.assertEqual(normalize_text("下 一 节"), "下一节")

    def test_keeps_latin_spacing(self) -> None:
        self.assertEqual(normalize_text("Next page 1 2 3"), "Next page 1 2 3")

    def test_removes_spaces_around_chinese_punctuation(self) -> None:
        self.assertEqual(normalize_text("确定 ， 取消 。"), "确定，取消。")


if __name__ == "__main__":
    unittest.main()
