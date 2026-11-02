"""Local Qwen-VL client, annotation and Ollama management."""

from __future__ import annotations

import base64
import io
import json
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from osprey.ai.ocr import OcrItem
from osprey.ai.vision import (LOCAL_MODELS, OllamaManager, QwenVisionClient,
                              QwenVisionError, annotate_frame)
from osprey.capture.base import Frame


def make_frame(width=40, height=30):
    image = Image.new("RGB", (width, height), (30, 30, 30))
    data = np.asarray(image.convert("RGBA"))
    return Frame(data[..., [2, 1, 0, 3]])


class TestAnnotate(unittest.TestCase):
    def test_returns_jpeg_data_url_with_ids(self) -> None:
        frame = make_frame()
        url = annotate_frame(frame, [OcrItem("OK", (5, 5, 10, 8)), OcrItem("Cancel", (20, 5, 10, 8))])
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        raw = base64.b64decode(url.split(",", 1)[1])
        image = Image.open(io.BytesIO(raw))
        self.assertEqual(image.format, "JPEG")
        self.assertLessEqual(image.width, 1600)


class TestQwenClient(unittest.TestCase):
    def test_posts_image_and_parses_json(self) -> None:
        response = io.BytesIO(json.dumps({
            "message": {"content": '{"action": "done"}'},
        }).encode("utf-8"))
        client = QwenVisionClient(model=LOCAL_MODELS["3b"])
        with mock.patch("osprey.ai.vision.urllib.request.urlopen", return_value=response) as opened:
            reply = client.complete_json("system", "user", "data:image/jpeg;base64,AAAA")
        self.assertEqual(reply["action"], "done")
        request = opened.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], LOCAL_MODELS["3b"])
        self.assertEqual(body["messages"][1]["images"], ["AAAA"])

    def test_http_error_is_qwen_error(self) -> None:
        import urllib.error

        error = urllib.error.HTTPError(
            "http://localhost", 500, "boom", {}, io.BytesIO(b"bad model"))
        client = QwenVisionClient()
        with mock.patch("osprey.ai.vision.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(QwenVisionError):
                client.complete_json("s", "u", "data:image/jpeg;base64,AAAA")


class TestOllamaManager(unittest.TestCase):
    def test_ensure_model_pulls_missing_tag(self) -> None:
        manager = OllamaManager()
        manager.is_running = lambda: True
        manager.models = lambda: ["qwen2.5vl:7b"]
        manager.executable = lambda: "ollama"
        completed = mock.Mock(returncode=0, stderr=b"")
        with mock.patch("osprey.ai.vision.subprocess.run", return_value=completed) as run:
            manager.ensure_model("qwen2.5vl:3b")
        run.assert_called_once()
        self.assertIn("qwen2.5vl:3b", run.call_args.args[0])

    def test_existing_model_is_not_pulled(self) -> None:
        manager = OllamaManager()
        manager.is_running = lambda: True
        manager.models = lambda: ["qwen2.5vl:7b"]
        with mock.patch("osprey.ai.vision.subprocess.run") as run:
            manager.ensure_model("qwen2.5vl:7b")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
