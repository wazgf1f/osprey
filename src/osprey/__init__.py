"""Osprey - a screen-vision automation engine for Windows.

The pipeline is small and explicit:

    capture -> vision -> decision -> input

Everything is plain Python on top of NumPy, Pillow and the Win32 API, so the
whole stack can be read in an afternoon and extended without a framework.
"""

from .errors import Aborted, CaptureError, ConfigError, OspreyError, VisionError

__version__ = "0.1.2"

__all__ = [
    "Aborted",
    "CaptureError",
    "ConfigError",
    "OspreyError",
    "VisionError",
    "__version__",
]
