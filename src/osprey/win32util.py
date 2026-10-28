"""Small Win32 helpers shared by the capture and input layers."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as wt

_IS_WINDOWS = sys.platform == "win32"
_dpi_aware = False

if _IS_WINDOWS:  # pragma: no branch - platform guard
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
else:  # pragma: no cover - non-Windows CI
    _user32 = None


def enable_dpi_awareness() -> bool:
    """Make the process DPI aware so pixels, metrics and cursor agree.

    On a 150% display an unaware process sees 1707x1067 for a 2560x1600 panel:
    GDI captures a stretched image, GetSystemMetrics returns logical units and
    every synthetic click is normalised against the wrong rectangle.

    Safe to call repeatedly; returns True when the process is aware.
    """
    global _dpi_aware
    if _dpi_aware:
        return True
    if not _IS_WINDOWS:
        return False

    set_context = getattr(_user32, "SetProcessDpiAwarenessContext", None)
    if set_context is not None:
        try:
            set_context.argtypes = [ctypes.c_void_p]
            set_context.restype = wt.BOOL
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
            if set_context(ctypes.c_void_p(-4)):
                _dpi_aware = True
                return True
        except OSError:
            pass

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        # 2 == PROCESS_PER_MONITOR_DPI_AWARE; S_OK == 0, E_ACCESSDENIED means already set
        if shcore.SetProcessDpiAwareness(2) in (0, -2147024891):
            _dpi_aware = True
            return True
    except OSError:
        pass

    try:
        if _user32.SetProcessDPIAware():
            _dpi_aware = True
            return True
    except OSError:
        pass
    return False
