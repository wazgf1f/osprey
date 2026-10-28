"""Keyboard and mouse control."""

from .win32 import InputController, cursor_position, is_key_pressed, resolve_key

__all__ = ["InputController", "cursor_position", "is_key_pressed", "resolve_key"]
