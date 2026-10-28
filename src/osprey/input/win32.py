"""Keyboard and mouse synthesis through SendInput.

Why SendInput and not pyautogui?
--------------------------------
SendInput is the same API a physical keyboard uses. Osprey sends scan codes
(not virtual keys) for keyboards, which is what DirectInput-era games and many
engines actually read, and it sends absolute coordinates normalised over the
whole virtual desktop, so multi-monitor setups behave.

Coordinates are desktop pixels, the same system Frame.origin uses.

This module is Windows-only; importing it elsewhere raises on first use.
"""

from __future__ import annotations

import ctypes
import math
import random
import sys
import time
from ctypes import wintypes as wt
from typing import Callable, List, Optional, Sequence, Tuple

from ..errors import Aborted
from ..win32util import enable_dpi_awareness

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:  # pragma: no branch - platform guard
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
else:  # pragma: no cover - non-Windows CI
    _user32 = None

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

WHEEL_DELTA = 120

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

MAPVK_VK_TO_VSC = 0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def _bind() -> None:
    if not _IS_WINDOWS:
        return
    _user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    _user32.SendInput.restype = wt.UINT
    _user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
    _user32.MapVirtualKeyW.restype = wt.UINT
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    _user32.GetCursorPos.restype = wt.BOOL
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int


if _IS_WINDOWS:  # pragma: no branch - platform guard
    _bind()


_NAMED_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "ins": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "win": 0x5B,
    "lwin": 0x5B,
    "rwin": 0x5C,
    "menu": 0x5D,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "lalt": 0xA4,
    "ralt": 0xA5,
    "multiply": 0x6A,
    "add": 0x6B,
    "subtract": 0x6D,
    "decimal": 0x6E,
    "divide": 0x6F,
}

# Keys whose scan code needs the extended-key flag for correct behaviour.
_EXTENDED_KEYS = frozenset(
    {
        0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,  # arrows, page, home, end
        0x2D, 0x2E, 0x2F, 0x5B, 0x5C, 0x5D, 0x6F, 0x90,  # insert, delete, menu, win, numlock
        0xA3, 0xA5,  # right ctrl, right alt
    }
)


def resolve_key(key) -> int:
    """Accept 'a', 'F12', 'enter', 'space', ... or a virtual-key integer."""
    if isinstance(key, bool):
        raise TypeError("key must be a string or an int, not bool")
    if isinstance(key, int):
        if not 0 < key < 0x100:
            raise ValueError("virtual-key code out of range: %r" % (key,))
        return key
    if not isinstance(key, str):
        raise TypeError("key must be a string or an int, got %r" % (type(key).__name__,))

    name = key.strip().lower()
    if len(name) == 1 and (name.isascii() and name.isalnum()):
        return ord(name.upper())
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    if name.startswith("f") and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    raise ValueError("unknown key name: %r" % (key,))


def _require_windows() -> None:
    if not _IS_WINDOWS:  # pragma: no cover - platform guard
        raise RuntimeError("keyboard and mouse control requires Windows")


def _send(*events: INPUT) -> None:
    _require_windows()
    array = (INPUT * len(events))(*events)
    sent = _user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(ctypes.get_last_error(), "SendInput failed")


def _key_event(vk: int, up: bool) -> INPUT:
    scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) if _IS_WINDOWS else 0
    flags = KEYEVENTF_SCANCODE
    if vk in _EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    event = KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=event))


def _unicode_event(unit: int, up: bool) -> INPUT:
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    event = KEYBDINPUT(wVk=0, wScan=unit, dwFlags=flags, time=0, dwExtraInfo=0)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=event))


def _mouse_event(dx: int, dy: int, data: int, flags: int) -> INPUT:
    event = MOUSEINPUT(dx=int(dx), dy=int(dy), mouseData=int(data), dwFlags=flags, time=0,
                       dwExtraInfo=0)
    return INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=event))


def virtual_screen() -> Tuple[int, int, int, int]:
    """(x, y, width, height) of the whole virtual desktop."""
    _require_windows()
    enable_dpi_awareness()
    return (
        int(_user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def cursor_position() -> Tuple[int, int]:
    """Current cursor position in desktop pixels."""
    _require_windows()
    enable_dpi_awareness()
    point = wt.POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        raise OSError(ctypes.get_last_error(), "GetCursorPos failed")
    return int(point.x), int(point.y)


def is_key_pressed(key) -> bool:
    """True while the key is physically down (works without a message loop)."""
    _require_windows()
    return bool(_user32.GetAsyncKeyState(resolve_key(key)) & 0x8000)


def _absolute_xy(x: int, y: int) -> Tuple[int, int]:
    if not _IS_WINDOWS:
        # Dry runs never send the event; avoid touching Win32 metrics off Windows.
        return (0, 0)
    vx, vy, vw, vh = virtual_screen()
    ax = int(round((x - vx) * 65535.0 / max(1, vw - 1)))
    ay = int(round((y - vy) * 65535.0 / max(1, vh - 1)))
    return max(0, min(65535, ax)), max(0, min(65535, ay))


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _bezier(p0, p1, p2, p3, t: float) -> Tuple[float, float]:
    u = 1.0 - t
    x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
    y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
    return x, y


class InputController:
    """Humanised keyboard and mouse control with a dry-run mode.

    Every public method is a no-op that only records history when dry_run is
    set, which makes tasks testable without touching the real cursor.
    """

    def __init__(
        self,
        *,
        dry_run: bool = True,
        should_abort: Optional[Callable[[], bool]] = None,
        speed: float = 1.0,
        seed: Optional[int] = None,
        move_mode: str = "absolute",
    ) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        if move_mode not in ("absolute", "relative"):
            raise ValueError("move_mode must be 'absolute' or 'relative'")
        if _IS_WINDOWS:
            enable_dpi_awareness()
        self.dry_run = bool(dry_run)
        self.should_abort = should_abort
        self.speed = float(speed)
        self.move_mode = move_mode
        self.history: List[str] = []
        self._rng = random.Random(seed)
        self._held_keys: set = set()
        self._held_buttons: set = set()

    # -- internals ---------------------------------------------------------
    def _check_abort(self) -> None:
        if self.should_abort is not None and self.should_abort():
            raise Aborted("input cancelled by safety guard")

    def _emit(self, description: str, *events: INPUT) -> None:
        self._check_abort()
        self.history.append(description)
        if self.dry_run or not events:
            return
        _send(*events)

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    # -- mouse -------------------------------------------------------------
    def position(self) -> Tuple[int, int]:
        if self.dry_run:
            return (0, 0)
        return cursor_position()

    def move_to(
        self,
        x: int,
        y: int,
        *,
        duration: Optional[float] = None,
        humanize: bool = True,
    ) -> None:
        """Glide the cursor to (x, y) along a slightly curved path."""
        x, y = int(round(x)), int(round(y))
        if not humanize:
            ax, ay = _absolute_xy(x, y)
            self._emit(
                "move %d,%d" % (x, y),
                _mouse_event(ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
            )
            return

        start = self.position()
        distance = math.hypot(x - start[0], y - start[1])
        if distance < 1:
            return

        if duration is None:
            duration = min(0.8, max(0.10, 0.08 + distance / 2600.0))
        duration = duration / self.speed
        steps = int(max(5, min(48, distance / 30.0 + 5)))

        spread = min(40.0, distance * 0.12)
        nx = -(y - start[1]) / distance
        ny = (x - start[0]) / distance
        bow1 = self._rng.uniform(-spread, spread)
        bow2 = self._rng.uniform(-spread, spread)
        p1 = (
            start[0] + (x - start[0]) * 0.30 + nx * bow1,
            start[1] + (y - start[1]) * 0.30 + ny * bow1,
        )
        p2 = (
            start[0] + (x - start[0]) * 0.70 + nx * bow2,
            start[1] + (y - start[1]) * 0.70 + ny * bow2,
        )

        previous = start
        for index in range(1, steps + 1):
            parameter = _ease_out_cubic(index / float(steps))
            px, py = _bezier(start, p1, p2, (x, y), parameter)
            if index == steps:
                px, py = float(x), float(y)
            if self.move_mode == "relative":
                dx = int(round(px - previous[0]))
                dy = int(round(py - previous[1]))
                self._emit(
                    "move %d,%d" % (int(round(px)), int(round(py))),
                    _mouse_event(dx, dy, 0, MOUSEEVENTF_MOVE),
                )
            else:
                ax, ay = _absolute_xy(int(round(px)), int(round(py)))
                self._emit(
                    "move %d,%d" % (int(round(px)), int(round(py))),
                    _mouse_event(ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
                )
            previous = (px, py)
            self._sleep(max(0.0, duration / steps * self._rng.uniform(0.7, 1.3)))

    _BUTTONS = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }

    def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.07,
        move: bool = True,
    ) -> None:
        """Click at (x, y), or wherever the cursor already is when omitted."""
        if button not in self._BUTTONS:
            raise ValueError("button must be one of %s" % (sorted(self._BUTTONS),))
        if clicks < 1:
            raise ValueError("clicks must be at least 1")
        if x is not None and y is not None and move:
            self.move_to(x, y)

        down, up = self._BUTTONS[button]
        for index in range(clicks):
            self._emit("click %s" % button, _mouse_event(0, 0, 0, down))
            self._held_buttons.add(button)
            self._sleep(self._rng.uniform(0.03, 0.07))
            self._emit("release %s" % button, _mouse_event(0, 0, 0, up))
            self._held_buttons.discard(button)
            if index < clicks - 1:
                self._sleep(interval)

    def scroll(self, clicks: float, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Positive scrolls up, negative scrolls down."""
        if x is not None and y is not None:
            self.move_to(x, y)
        amount = int(round(clicks * WHEEL_DELTA))
        if amount == 0:
            return
        self._emit("scroll %d" % amount, _mouse_event(0, 0, amount, MOUSEEVENTF_WHEEL))

    # -- keyboard ----------------------------------------------------------
    def key_down(self, key) -> None:
        vk = resolve_key(key)
        self._emit("key_down %s" % key, _key_event(vk, False))
        self._held_keys.add(vk)

    def key_up(self, key) -> None:
        vk = resolve_key(key)
        self._emit("key_up %s" % key, _key_event(vk, True))
        self._held_keys.discard(vk)

    def press(self, key, *, presses: int = 1, interval: float = 0.05) -> None:
        if presses < 1:
            raise ValueError("presses must be at least 1")
        for index in range(presses):
            self.key_down(key)
            self._sleep(self._rng.uniform(0.03, 0.08))
            self.key_up(key)
            if index < presses - 1:
                self._sleep(interval)

    def hold(self, key, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must not be negative")
        self.key_down(key)
        self._sleep(seconds)
        self.key_up(key)

    def write(self, text: str, *, interval: float = 0.012) -> None:
        """Type arbitrary Unicode text using WM_CHAR-style unicode events."""
        for character in text:
            encoded = character.encode("utf-16-le")
            for offset in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[offset:offset + 2], "little")
                self._emit("type %r" % character, _unicode_event(unit, False))
                self._emit("type-up %r" % character, _unicode_event(unit, True))
                self._sleep(interval * self._rng.uniform(0.5, 1.5))

    def release_all(self) -> None:
        """Best-effort release so an abort never leaves a key or button stuck."""
        for key in list(self._held_keys):
            try:
                self._emit("key_up %s" % key, _key_event(key, True))
            except Exception:
                pass
            self._held_keys.discard(key)
        for button in list(self._held_buttons):
            try:
                down, up = self._BUTTONS[button]
                self._emit("release %s" % button, _mouse_event(0, 0, 0, up))
            except Exception:
                pass
            self._held_buttons.discard(button)
