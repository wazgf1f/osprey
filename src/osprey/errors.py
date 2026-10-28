"""Exception hierarchy for Osprey."""

from __future__ import annotations


class OspreyError(RuntimeError):
    """Base class for every error raised by Osprey."""


class CaptureError(OspreyError):
    """The screen could not be captured."""


class VisionError(OspreyError):
    """A vision operation received invalid input or could not run."""


class ConfigError(OspreyError):
    """A configuration file is missing, malformed or out of range."""


class Aborted(OspreyError):
    """The user (or a safety guard) asked the engine to stop."""
