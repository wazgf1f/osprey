"""OCR + DeepSeek decision layer.

The engine still owns capture, timing and input. These helpers turn the current
frame into text boxes, ask a text model to choose one, and let the task execute
the choice through the normal Context API.
"""

from .agent import OcrAgentTask, VisionAgentTask
from .deepseek import DeepSeekClient, DeepSeekError
from .ocr import OcrError, OcrItem, default_ocr_backend, ocr_frame
from .vision import (LOCAL_MODELS, MODEL_LABELS, OllamaManager, QwenVisionClient,
                     QwenVisionError, annotate_frame)

__all__ = [
    "DeepSeekClient",
    "LOCAL_MODELS",
    "MODEL_LABELS",
    "OllamaManager",
    "QwenVisionClient",
    "QwenVisionError",
    "annotate_frame",
    "DeepSeekError",
    "OcrAgentTask",
    "VisionAgentTask",
    "OcrError",
    "OcrItem",
    "default_ocr_backend",
    "ocr_frame",
]
