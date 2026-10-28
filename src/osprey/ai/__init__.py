"""OCR + DeepSeek decision layer.

The engine still owns capture, timing and input. These helpers turn the current
frame into text boxes, ask a text model to choose one, and let the task execute
the choice through the normal Context API.
"""

from .agent import OcrAgentTask
from .deepseek import DeepSeekClient, DeepSeekError
from .ocr import OcrError, OcrItem, default_ocr_backend, ocr_frame

__all__ = [
    "DeepSeekClient",
    "DeepSeekError",
    "OcrAgentTask",
    "OcrError",
    "OcrItem",
    "default_ocr_backend",
    "ocr_frame",
]
