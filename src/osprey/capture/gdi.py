"""Screen capture through the Win32 GDI.

A DIB section is created once and kept selected into a memory DC, so BitBlt
writes straight into memory owned by NumPy. There is no GetDIBits round trip
and no per-frame allocation, which keeps a 1080p grab in the low milliseconds.

Resolution changes
------------------
The desktop rectangle is re-read on every grab. If the user changes display
resolution, plugs in a monitor or changes the scaling factor, the capture
buffers are rebuilt automatically instead of silently capturing the old size.

Coordinate system
-----------------
All coordinates are desktop pixels. Frames from a sub-region carry the region
origin, and Frame.crop() adjusts it, so a detection can always be converted to
a click position with a simple addition.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes as wt
from typing import List, Optional, Sequence, Tuple

import numpy as np

from ..errors import CaptureError
from ..win32util import enable_dpi_awareness
from .base import Frame, FrameSource

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:  # pragma: no branch - platform guard
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
else:  # pragma: no cover - exercised on non-Windows CI
    _user32 = None
    _gdi32 = None

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
LOGPIXELSX = 88
MONITORINFOF_PRIMARY = 1


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wt.DWORD),
    ]


# WINFUNCTYPE only exists on Windows; the callback is never used elsewhere.
MONITORENUMPROC = (
    ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(RECT), wt.LPARAM)
    if _IS_WINDOWS
    else None
)


def _bind() -> None:
    """Declare prototypes so ctypes checks arguments and pointers are not truncated."""
    if not _IS_WINDOWS:
        return

    _user32.GetDC.argtypes = [wt.HWND]
    _user32.GetDC.restype = wt.HDC
    _user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.POINTER(RECT), MONITORENUMPROC, wt.LPARAM]
    _user32.EnumDisplayMonitors.restype = wt.BOOL
    _user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFO)]
    _user32.GetMonitorInfoW.restype = wt.BOOL

    _gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    _gdi32.CreateCompatibleDC.restype = wt.HDC
    _gdi32.CreateDIBSection.argtypes = [
        wt.HDC,
        ctypes.POINTER(BITMAPINFO),
        wt.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wt.HANDLE,
        wt.DWORD,
    ]
    _gdi32.CreateDIBSection.restype = wt.HBITMAP
    _gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    _gdi32.SelectObject.restype = wt.HGDIOBJ
    _gdi32.BitBlt.argtypes = [
        wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD,
    ]
    _gdi32.BitBlt.restype = wt.BOOL
    _gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    _gdi32.DeleteObject.restype = wt.BOOL
    _gdi32.DeleteDC.argtypes = [wt.HDC]
    _gdi32.DeleteDC.restype = wt.BOOL
    _gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]
    _gdi32.GetDeviceCaps.restype = ctypes.c_int


if _IS_WINDOWS:  # pragma: no branch - platform guard
    _bind()


def _require_windows() -> None:
    if not _IS_WINDOWS:  # pragma: no cover - platform guard
        raise CaptureError("GDI screen capture is only available on Windows")


def virtual_screen_rect() -> Tuple[int, int, int, int]:
    """(x, y, width, height) of the whole virtual desktop, across monitors."""
    _require_windows()
    enable_dpi_awareness()
    return (
        int(_user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def screen_scale() -> float:
    """System DPI scale (1.0 for 96 DPI, 1.5 for 150%)."""
    _require_windows()
    enable_dpi_awareness()
    get_dpi = getattr(_user32, "GetDpiForSystem", None)
    if get_dpi is not None:
        try:
            get_dpi.restype = wt.UINT
            dpi = int(get_dpi())
            if dpi > 0:
                return dpi / 96.0
        except OSError:
            pass
    hdc = _user32.GetDC(None)
    try:
        return float(_gdi32.GetDeviceCaps(hdc, LOGPIXELSX)) / 96.0
    finally:
        _user32.ReleaseDC(None, hdc)


def monitors() -> List[dict]:
    """Every monitor as {rect, work, primary}, in desktop coordinates."""
    _require_windows()
    enable_dpi_awareness()
    found: List[dict] = []

    def callback(hmonitor, hdc, rect, data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            found.append(
                {
                    "rect": (
                        int(info.rcMonitor.left),
                        int(info.rcMonitor.top),
                        int(info.rcMonitor.right) - int(info.rcMonitor.left),
                        int(info.rcMonitor.bottom) - int(info.rcMonitor.top),
                    ),
                    "work": (
                        int(info.rcWork.left),
                        int(info.rcWork.top),
                        int(info.rcWork.right) - int(info.rcWork.left),
                        int(info.rcWork.bottom) - int(info.rcWork.top),
                    ),
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                }
            )
        return True

    _user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    return found


class GdiGrabber(FrameSource):
    """Capture the primary display, the full desktop, or a rectangle.

    full_desktop=True captures every monitor as one image, which is what you
    want when the target window may be dragged to a second screen. Coordinates
    are still desktop pixels, including negative origins.
    """

    def __init__(self, region: Optional[Sequence[int]] = None, full_desktop: bool = False) -> None:
        _require_windows()
        enable_dpi_awareness()

        self.full_desktop = bool(full_desktop)
        self._requested_region: Optional[Tuple[int, int, int, int]] = None
        if region is not None:
            values = tuple(int(v) for v in region)
            if len(values) != 4:
                raise CaptureError("region must be (x, y, width, height)")
            if values[2] <= 0 or values[3] <= 0:
                raise CaptureError("region width and height must be positive")
            self._requested_region = values  # type: ignore[assignment]

        self._hdc_screen = _user32.GetDC(None)
        if not self._hdc_screen:
            raise CaptureError("GetDC failed (no interactive desktop?)")

        self._hdc_mem = None
        self._hbmp = None
        self._old = None
        self._owner = None
        self._array: Optional[np.ndarray] = None
        self._width = 0
        self._height = 0
        self._origin: Tuple[int, int] = (0, 0)
        self._snapshot: Optional[Tuple[int, int, int, int]] = None
        self._closed = False
        self._configure()

    # -- geometry ----------------------------------------------------------
    def _screen_metrics(self) -> Tuple[int, int, int, int]:
        if self.full_desktop:
            return virtual_screen_rect()
        return (
            0,
            0,
            int(_user32.GetSystemMetrics(SM_CXSCREEN)),
            int(_user32.GetSystemMetrics(SM_CYSCREEN)),
        )

    def _resolve_capture_rect(self, metrics: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        mx, my, mw, mh = metrics
        if mw <= 0 or mh <= 0:
            raise CaptureError("could not determine the display size")
        if self._requested_region is None:
            return mx, my, mw, mh
        x, y, width, height = self._requested_region
        if x < mx or y < my or x + width > mx + mw or y + height > my + mh:
            raise CaptureError(
                "region %r is outside the desktop %dx%d at (%d, %d)"
                % (self._requested_region, mw, mh, mx, my)
            )
        return x, y, width, height

    def _configure(self) -> None:
        metrics = self._screen_metrics()
        origin_x, origin_y, width, height = self._resolve_capture_rect(metrics)
        self._release_buffers()
        self._origin = (origin_x, origin_y)
        self._width, self._height = width, height
        self._snapshot = metrics
        self._create_buffers()

    # -- lifecycle ---------------------------------------------------------
    def _create_buffers(self) -> None:
        bmi = BITMAPINFO()
        header = bmi.bmiHeader
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = self._width
        header.biHeight = -self._height  # negative: top-down rows
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        self._hdc_mem = _gdi32.CreateCompatibleDC(self._hdc_screen)
        self._hbmp = _gdi32.CreateDIBSection(
            self._hdc_screen, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
        )
        if not self._hdc_mem or not self._hbmp:
            self._release_buffers()
            raise CaptureError("could not create the capture buffers (GDI error)")

        self._old = _gdi32.SelectObject(self._hdc_mem, self._hbmp)
        if not self._old:
            self._release_buffers()
            raise CaptureError("SelectObject failed for the capture bitmap")

        capacity = self._width * self._height * 4
        owner = (ctypes.c_ubyte * capacity).from_address(bits.value)
        self._owner = owner  # keep the ctypes view alive for the array's lifetime
        self._array = np.ctypeslib.as_array(owner).reshape(self._height, self._width, 4)

    def _release_buffers(self) -> None:
        self._array = None
        self._owner = None
        if self._hdc_mem and self._old:
            _gdi32.SelectObject(self._hdc_mem, self._old)
        if self._hbmp:
            _gdi32.DeleteObject(self._hbmp)
        if self._hdc_mem:
            _gdi32.DeleteDC(self._hdc_mem)
        self._hdc_mem = self._hbmp = self._old = None

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._closed = True
        self._release_buffers()
        if getattr(self, "_hdc_screen", None):
            _user32.ReleaseDC(None, self._hdc_screen)
        self._hdc_screen = None

    def __enter__(self) -> "GdiGrabber":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:
            pass

    # -- capture -----------------------------------------------------------
    def grab(self) -> Frame:
        if self._closed or self._array is None:
            raise CaptureError("grabber is closed")
        metrics = self._screen_metrics()
        if metrics != self._snapshot:
            self._configure()
        x, y = self._origin
        ok = _gdi32.BitBlt(
            self._hdc_mem, 0, 0, self._width, self._height,
            self._hdc_screen, x, y, SRCCOPY,
        )
        if not ok:
            raise CaptureError("BitBlt failed (winerror %d)" % ctypes.get_last_error())
        return Frame(bgra=self._array.copy(), origin=self._origin)

    # -- introspection -----------------------------------------------------
    @property
    def size(self) -> Tuple[int, int]:
        return self._width, self._height

    @property
    def origin(self) -> Tuple[int, int]:
        return self._origin

    @property
    def screen_size(self) -> Tuple[int, int]:
        metrics = self._screen_metrics()
        return metrics[2], metrics[3]
