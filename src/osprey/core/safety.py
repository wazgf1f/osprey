"""Stop conditions: a panic key, a stop file, a runtime cap.

The panic key is polled with GetAsyncKeyState, so it works even while the
engine is busy inside a task and no window has focus. F12 is the default
because it is rarely bound by games or apps.
"""

from __future__ import annotations

import os
import time
from typing import Iterable, Optional, Sequence, Tuple

from ..errors import Aborted


class Safety:
    """Tracks whether the current run should keep going."""

    def __init__(
        self,
        *,
        abort_keys: Sequence[str] = ("f12",),
        stop_file: Optional[str] = None,
        max_runtime: Optional[float] = None,
    ) -> None:
        if max_runtime is not None and max_runtime <= 0:
            raise ValueError("max_runtime must be positive")
        if isinstance(abort_keys, str):
            abort_keys = (abort_keys,)
        self.abort_keys: Tuple[str, ...] = tuple(abort_keys)

        from ..input.win32 import resolve_key

        for key in self.abort_keys:
            try:
                resolve_key(key)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid abort key %r: %s" % (key, exc)) from exc
        self.stop_file = stop_file
        self.max_runtime = max_runtime
        self._started_at: Optional[float] = None
        self._aborted = False
        self._reason: Optional[str] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._started_at = time.monotonic()

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    def request_stop(self, reason: str) -> None:
        if not self._aborted:
            self._aborted = True
            self._reason = reason

    def reset(self) -> None:
        self._aborted = False
        self._reason = None
        self._started_at = time.monotonic()

    # -- polling -----------------------------------------------------------
    def _poll(self) -> Optional[str]:
        """Return a stop reason if one is present, without raising."""
        if self._aborted:
            return self._reason or "aborted"

        if self.stop_file and os.path.exists(self.stop_file):
            return "stop file created: %s" % self.stop_file

        if self.abort_keys:
            from ..input.win32 import is_key_pressed

            try:
                for key in self.abort_keys:
                    if is_key_pressed(key):
                        return "panic key pressed: %s" % key
            except (RuntimeError, ValueError):
                pass  # not on Windows, or already validated; other guards apply

        if self.max_runtime is not None and self._started_at is not None:
            if time.monotonic() - self._started_at >= self.max_runtime:
                return "maximum runtime reached (%.1fs)" % self.max_runtime
        return None

    def should_abort(self) -> bool:
        """Non-raising check, suitable as an input guard callback."""
        reason = self._poll()
        if reason is not None:
            self.request_stop(reason)
        return self._aborted

    def check(self) -> None:
        """Raise Aborted when any stop condition is met."""
        reason = self._poll()
        if reason is not None:
            self.request_stop(reason)
            raise Aborted(reason)
