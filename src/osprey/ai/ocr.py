"""OCR backends that return text boxes in frame coordinates."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

from ..capture.base import Frame
from ..errors import OspreyError


class OcrError(OspreyError):
    """OCR is unavailable or failed."""


@dataclass(frozen=True)
class OcrItem:
    text: str
    box: Tuple[int, int, int, int]      # x, y, width, height in frame pixels
    confidence: float = 1.0

    @property
    def center(self) -> Tuple[float, float]:
        x, y, width, height = self.box
        return (x + width / 2.0, y + height / 2.0)


_RAPID = None
_SCRIPT_PATH: Optional[Path] = None

_WINDOWS_SCRIPT = r'''param([string]$Path, [string]$Out)
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -like 'IAsyncOperation*'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime] | Out-Null

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = $null
[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime] | Out-Null
foreach ($tag in @('zh-Hans-CN', 'zh-Hans', 'en-US', 'en-GB')) {
    try {
        $language = New-Object Windows.Globalization.Language $tag
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    } catch {
        $engine = $null
    }
    if ($null -ne $engine) { break }
}
if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if ($null -eq $engine) {
    [System.IO.File]::WriteAllText($Out, '[]', (New-Object System.Text.UTF8Encoding($false)))
    exit 1
}
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = @()
foreach ($line in $result.Lines) {
    $words = @()
    foreach ($word in $line.Words) {
        $words += @{
            text = $word.Text
            x = [int]$word.BoundingRect.X
            y = [int]$word.BoundingRect.Y
            w = [int]$word.BoundingRect.Width
            h = [int]$word.BoundingRect.Height
        }
    }
    $lines += @{ text = $line.Text; words = $words }
}
$json = ConvertTo-Json -InputObject @($lines) -Depth 6 -Compress
[System.IO.File]::WriteAllText($Out, $json, (New-Object System.Text.UTF8Encoding($false)))
'''


def _rapid_engine():
    global _RAPID
    if _RAPID is not None:
        return _RAPID
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise OcrError(
                "RapidOCR is not installed; run: pip install -e \".[ai]\""
            ) from exc
    _RAPID = RapidOCR()
    return _RAPID


def _nested_points(points: Sequence) -> Tuple[int, int, int, int]:
    if points and isinstance(points[0], (list, tuple)):
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    elif len(points) >= 8:
        xs = [float(points[index]) for index in range(0, 8, 2)]
        ys = [float(points[index]) for index in range(1, 8, 2)]
    else:
        raise ValueError("unexpected OCR box: %r" % (points,))
    left, top = int(round(min(xs))), int(round(min(ys)))
    return (left, top,
            max(1, int(round(max(xs))) - left),
            max(1, int(round(max(ys))) - top))


def _rapid_items(frame: Frame) -> List[OcrItem]:
    engine = _rapid_engine()
    result = engine(frame.bgr)
    if isinstance(result, tuple):
        result = result[0]
    items: List[OcrItem] = []
    for row in result or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        box, text, score = row[0], row[1], row[2]
        text = " ".join(str(text or "").split())
        if not text:
            continue
        try:
            left, top, width, height = _nested_points(box)
        except (TypeError, ValueError, IndexError):
            continue
        items.append(OcrItem(text=text, box=(left, top, width, height),
                             confidence=float(score)))
    return items


def _tesseract_items(frame: Frame) -> List[OcrItem]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OcrError("pytesseract is not installed") from exc
    rgb = np.ascontiguousarray(frame.bgr[..., ::-1])
    try:
        data = pytesseract.image_to_data(
            Image.fromarray(rgb), output_type=pytesseract.Output.DICT)
    except Exception as exc:
        raise OcrError("pytesseract failed: %s" % exc) from exc
    items: List[OcrItem] = []
    for index, text in enumerate(data.get("text", [])):
        text = " ".join(str(text or "").split())
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, TypeError, ValueError):
            confidence = 1.0
        if confidence < 0:
            continue
        left = int(data["left"][index])
        top = int(data["top"][index])
        width = int(data["width"][index])
        height = int(data["height"][index])
        if width <= 0 or height <= 0:
            continue
        items.append(OcrItem(text=text, box=(left, top, width, height),
                             confidence=confidence / 100.0))
    return items


def _windows_script() -> Path:
    global _SCRIPT_PATH
    if _SCRIPT_PATH is None:
        _SCRIPT_PATH = Path(tempfile.gettempdir()) / "osprey_windows_ocr.ps1"
    if not _SCRIPT_PATH.exists() or _SCRIPT_PATH.read_text(
            encoding="utf-8-sig", errors="replace") != _WINDOWS_SCRIPT:
        _SCRIPT_PATH.write_text(_WINDOWS_SCRIPT, encoding="utf-8-sig")
    return _SCRIPT_PATH


def _windows_items(frame: Frame) -> List[OcrItem]:
    """Windows 10/11 built-in OCR through PowerShell + WinRT."""
    if sys.platform != "win32":
        raise OcrError("Windows OCR is only available on Windows")
    powershell = shutil.which("powershell") or str(
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    if not Path(powershell).exists():
        raise OcrError("powershell.exe was not found")

    script = _windows_script()
    fd, image_path = tempfile.mkstemp(prefix="osprey_ocr_", suffix=".png")
    os.close(fd)
    fd, json_path = tempfile.mkstemp(prefix="osprey_ocr_", suffix=".json")
    os.close(fd)
    try:
        from PIL import Image
        rgb = np.ascontiguousarray(frame.bgr[..., ::-1])
        Image.fromarray(rgb).save(image_path, format="PNG")
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        result = subprocess.run(
            [powershell, "-STA", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-Path", image_path, "-Out", json_path],
            capture_output=True, timeout=30, creationflags=flags,
        )
        output = Path(json_path).read_text(encoding="utf-8", errors="replace").strip()
        detail = (result.stderr or b"").decode("utf-8", "replace")[:500]
    finally:
        for path in (image_path, json_path):
            try:
                os.unlink(path)
            except OSError:
                pass

    if not output:
        raise OcrError("Windows OCR returned nothing: %s" % detail)
    start = min([index for index in (output.find("["), output.find("{")) if index >= 0] or [0])
    try:
        data = json.loads(output[start:])
    except json.JSONDecodeError as exc:
        raise OcrError("Windows OCR returned invalid JSON: %s" % exc) from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []

    items: List[OcrItem] = []
    for line in data:
        if not isinstance(line, dict):
            continue
        words = line.get("words") or []
        if not words:
            continue
        left = min(int(word["x"]) for word in words)
        top = min(int(word["y"]) for word in words)
        right = max(int(word["x"]) + int(word["w"]) for word in words)
        bottom = max(int(word["y"]) + int(word["h"]) for word in words)
        text = " ".join(str(line.get("text") or "").split())
        if not text:
            text = " ".join(str(word.get("text") or "") for word in words).strip()
        if text and right > left and bottom > top:
            items.append(OcrItem(text=text, box=(left, top, right - left, bottom - top)))
    return items


def default_ocr_backend() -> str:
    """Name of the first available backend, or raise a helpful error."""
    try:
        _rapid_engine()
        return "rapidocr"
    except OcrError:
        pass
    try:
        import pytesseract  # noqa: F401
        return "pytesseract"
    except ImportError:
        pass
    if sys.platform == "win32" and shutil.which("powershell"):
        return "windows"
    raise OcrError(
        "No OCR backend found. On Windows the built-in OCR is used; "
        "elsewhere install RapidOCR with: pip install -e \".[ai]\""
    )


def ocr_frame(frame: Frame, *, backend: str = "auto",
              min_confidence: float = 0.4, max_items: int = 80) -> List[OcrItem]:
    """OCR the frame and return text boxes sorted top-to-bottom, left-to-right."""
    if max_items <= 0:
        return []
    if backend not in ("auto", "rapidocr", "pytesseract", "windows"):
        raise OcrError("unknown OCR backend: %r" % (backend,))

    errors: List[str] = []
    names = [backend] if backend != "auto" else ["rapidocr", "pytesseract", "windows"]
    items: List[OcrItem] = []
    for name in names:
        try:
            if name == "rapidocr":
                items = _rapid_items(frame)
            elif name == "pytesseract":
                items = _tesseract_items(frame)
            else:
                items = _windows_items(frame)
        except Exception as exc:
            errors.append("%s: %s" % (name, exc))
            continue
        break
    else:
        raise OcrError("OCR failed: " + "; ".join(errors))

    cleaned = [
        OcrItem(text=item.text[:120], box=item.box, confidence=item.confidence)
        for item in items if item.confidence >= min_confidence
    ]
    cleaned.sort(key=lambda item: (item.box[1] // 10, item.box[0]))
    return cleaned[:max_items]
