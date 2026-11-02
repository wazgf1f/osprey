"""Local Qwen-VL vision client through Ollama, plus OCR-box annotation."""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ..capture.base import Frame
from ..errors import Aborted, OspreyError
from .deepseek import parse_json_reply
from .ocr import OcrItem

LOCAL_MODELS = {
    "3b": os.environ.get("OSPREY_QWEN_3B", "qwen2.5vl:3b"),
    "7b": os.environ.get("OSPREY_QWEN_7B", "qwen2.5vl:7b"),
}
MODEL_LABELS = {
    "3b": "Qwen-VL 3B（能用）",
    "7b": "Qwen-VL 7B（精准）",
}
OLLAMA_URL = "http://127.0.0.1:11434"


class QwenVisionError(OspreyError):
    """Local Qwen-VL/Ollama is unavailable or returned an invalid reply."""


def _startupinfo():
    if sys.platform != "win32":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


class OllamaManager:
    """Find/start Ollama and make sure the requested Qwen-VL tag exists."""

    def __init__(self, base_url: str = OLLAMA_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._process = None

    def executable(self) -> str:
        found = shutil.which("ollama")
        if found:
            return found
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Ollama" / "ollama.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        raise QwenVisionError(
            "Ollama is not installed. Install it from https://ollama.com/download "
            "and run: ollama pull qwen2.5vl:3b"
        )

    def is_running(self, timeout: float = 1.5) -> bool:
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=timeout) as response:
                return response.status == 200
        except Exception:
            return False

    def start(self, timeout: float = 20.0) -> None:
        if self.is_running():
            return
        exe = self.executable()
        try:
            self._process = subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=_startupinfo(),
            )
        except OSError as exc:
            raise QwenVisionError("could not start Ollama: %s" % exc) from exc
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_running():
                return
            time.sleep(0.25)
        raise QwenVisionError("Ollama did not start in time")

    def models(self) -> List[str]:
        if not self.is_running():
            return []
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=5) as response:
                data = json.load(response)
        except Exception as exc:
            raise QwenVisionError("could not read Ollama models: %s" % exc) from exc
        return [str(item.get("name", "")) for item in data.get("models", [])
                if isinstance(item, dict)]

    def ensure_model(self, model: str, timeout: float = 3600.0,
                     should_abort=None) -> None:
        if not self.is_running():
            self.start()
        names = self.models()
        if model in names:
            return
        exe = self.executable()
        try:
            process = subprocess.Popen(
                [exe, "pull", model],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=_startupinfo(),
            )
        except OSError as exc:
            raise QwenVisionError("could not start ollama pull: %s" % exc) from exc
        started = time.monotonic()
        while process.poll() is None:
            if should_abort is not None and should_abort():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise Aborted("local model download cancelled")
            if time.monotonic() - started > timeout:
                process.kill()
                raise QwenVisionError("timed out pulling Ollama model %s" % model)
            time.sleep(0.2)
        if process.returncode != 0:
            raise QwenVisionError("could not pull %s (exit %s)" % (model, process.returncode))


class QwenVisionClient:
    """Native Ollama vision chat (/api/chat), so image handling is deterministic."""

    def __init__(self, *, model: str = LOCAL_MODELS["3b"],
                 base_url: str = OLLAMA_URL,
                 timeout: float = 120.0,
                 manager: Optional[OllamaManager] = None) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.timeout = float(timeout)
        self.manager = manager or OllamaManager(self.base_url)

    def ensure_ready(self, should_abort=None) -> None:
        self.manager.ensure_model(self.model, should_abort=should_abort)

    def complete_json(self, system: str, user: str, image_data_url: str) -> Dict[str, Any]:
        encoded = image_data_url.split(",", 1)[-1]
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": [encoded]},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            self.base_url + "/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:800]
            raise QwenVisionError("Qwen-VL HTTP %d: %s" % (exc.code, detail)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise QwenVisionError(
                "Qwen-VL request failed; is Ollama running? %s" % exc) from exc
        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise QwenVisionError("unexpected Qwen-VL response: %r" % (data,)) from exc
        return parse_json_reply(content)


def annotate_frame(frame: Frame, items: List[OcrItem], *,
                   max_width: int = 1600) -> str:
    """Draw OCR ids on a downscaled screenshot and return a JPEG data URL."""
    from PIL import Image, ImageDraw

    rgb = np.ascontiguousarray(frame.bgr[..., ::-1])
    image = Image.fromarray(rgb)
    scale = min(1.0, max_width / float(max(1, image.width)))
    if scale < 1.0:
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.LANCZOS,
        )
    draw = ImageDraw.Draw(image)
    for index, item in enumerate(items):
        x, y, width, height = item.box
        left = int(round(x * scale))
        top = int(round(y * scale))
        right = int(round((x + width) * scale))
        bottom = int(round((y + height) * scale))
        draw.rectangle((left, top, right, bottom), outline=(255, 40, 40), width=2)
        draw.text((left + 2, max(0, top - 12)), str(index), fill=(255, 40, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + encoded
