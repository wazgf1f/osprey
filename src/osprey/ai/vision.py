"""Local Qwen-VL vision client through Ollama, plus OCR-box annotation."""

from __future__ import annotations

import base64
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from ..capture.base import Frame
from ..errors import Aborted, OspreyError
from .deepseek import DeepSeekError, parse_json_reply
from .ocr import OcrItem

LOCAL_MODELS = {
    "3b": os.environ.get("OSPREY_QWEN_3B", "qwen2.5vl:3b"),
    "7b": os.environ.get("OSPREY_QWEN_7B", "qwen2.5vl:7b"),
}
MODEL_LABELS = {
    "3b": "Qwen-VL 3B（能用）",
    "7b": "Qwen-VL 7B（精准）",
}
MODEL_SIZES = {
    "3b": "约 3 GB",
    "7b": "约 6 GB",
}
LOCAL_PROFILES = {
    "3b": {"num_ctx": 16384, "num_batch": 128, "max_width": 1600, "max_items": 80},
    # 8 GB cards: smaller image, fewer OCR boxes and a shorter KV cache.
    "7b": {"num_ctx": 8192, "num_batch": 64, "max_width": 1024, "max_items": 50},
}
OLLAMA_URL = "http://127.0.0.1:11434"


class QwenVisionError(OspreyError):
    """Local Qwen-VL/Ollama is unavailable or returned an invalid reply."""


def _popen(cmd, **kwargs):
    """Start a child hidden; some frozen/windowed environments reject STARTUPINFO."""
    try:
        return subprocess.Popen(cmd, startupinfo=_startupinfo(), **kwargs)
    except OSError:
        kwargs.pop("startupinfo", None)
        return subprocess.Popen(cmd, startupinfo=None, **kwargs)


def _server_env():
    env = os.environ.copy()
    env.setdefault("OLLAMA_FLASH_ATTENTION", "1")
    env.setdefault("OLLAMA_KV_CACHE_TYPE", "q8_0")
    env.setdefault("OLLAMA_NUM_PARALLEL", "1")
    env.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
    return env


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
            self._process = _popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_server_env(),
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

    def has_model(self, model: str) -> bool:
        return model in self.models() if self.is_running() else False

    def ensure_model(self, model: str, timeout: float = 3600.0,
                     should_abort=None,
                     progress: Optional[Callable[[int, str], None]] = None) -> None:
        if not self.is_running():
            self.start()
        names = self.models()
        if model in names:
            return
        exe = self.executable()
        try:
            process = _popen(
                [exe, "pull", model],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise QwenVisionError("could not start ollama pull: %s" % exc) from exc
        lines: queue.Queue = queue.Queue()

        def read_output():
            try:
                if process.stdout is not None:
                    for line in process.stdout:
                        lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        started = time.monotonic()
        last_percent = 0
        while True:
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
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if line is None:
                break
            match = re.search(r"(\d{1,3})%", line)
            if match is not None:
                last_percent = min(100, int(match.group(1)))
                if progress is not None:
                    progress(last_percent, line.strip())
            elif progress is not None and line.strip():
                progress(last_percent, line.strip())
        process.wait()
        if process.returncode != 0:
            raise QwenVisionError("could not pull %s (exit %s)" % (model, process.returncode))
        if progress is not None:
            progress(100, "下载完成")


class QwenVisionClient:
    """Native Ollama vision chat (/api/chat), so image handling is deterministic."""

    def __init__(self, *, model: str = LOCAL_MODELS["3b"], profile: str = "3b",
                 base_url: str = OLLAMA_URL,
                 timeout: float = 120.0,
                 manager: Optional[OllamaManager] = None) -> None:
        self.model = model
        self.profile = profile if profile in LOCAL_PROFILES else "3b"
        settings = LOCAL_PROFILES[self.profile]
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.timeout = float(timeout)
        if self.profile == "7b":
            self.timeout = min(self.timeout, 45.0)
        self.max_width = int(settings["max_width"])
        self.max_items = int(settings["max_items"])
        self.num_batch = int(settings["num_batch"])
        self.num_ctx = int(os.environ.get(
            "OSPREY_QWEN_NUM_CTX", str(settings["num_ctx"])))
        self.manager = manager or OllamaManager(self.base_url)

    def ensure_ready(self, should_abort=None) -> None:
        """Verify the model exists; never download implicitly."""
        if not self.manager.is_running():
            self.manager.start()
        if not self.manager.has_model(self.model):
            raise QwenVisionError(
                "local model %s is not downloaded; open AI 指令 → 本地模型 "
                "and click 下载所选模型 first" % self.model)

    def complete_json(self, system: str, user: str, image_data_url: str) -> Dict[str, Any]:
        encoded = image_data_url.split(",", 1)[-1]
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": [encoded]},
            ],
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self.num_ctx,
                        "num_batch": self.num_batch, "num_predict": 80,
                        "repeat_penalty": 1.2, "repeat_last_n": 128},
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
        try:
            return parse_json_reply(content)
        except DeepSeekError:
            return parse_action_text(content)


def parse_action_text(content: str) -> Dict[str, Any]:
    """Parse a short local-model action line (CLICK 3, WAIT 1, ...)."""
    text = " ".join(str(content or "").strip().split())
    if not text:
        raise QwenVisionError("model returned an empty action")
    upper = text.upper()
    if upper in ("DONE", "FINISH", "TERMINATE", "COMPLETE"):
        return {"action": "done"}
    match = re.search(r"(?:LEFT_)?CLICK\s*[:(]?\s*(\d+)", upper)
    if match:
        return {"action": "click", "element_id": int(match.group(1))}
    match = re.search(r"WAIT\s*:?\s*(\d+(?:\.\d+)?)", upper)
    if match:
        return {"action": "wait", "seconds": float(match.group(1))}
    match = re.search(r"SCROLL\s*:?\s*(-?\d+)", upper)
    if match:
        return {"action": "scroll", "amount": int(match.group(1))}
    raise QwenVisionError("model did not return a recognized action: %r" % content)


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
