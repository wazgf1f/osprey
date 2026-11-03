"""Per-run text logs under %LOCALAPPDATA%\\Osprey\\logs."""

from __future__ import annotations

import datetime
import faulthandler
import logging
import os
import platform
import sys
from pathlib import Path
from typing import Optional, Sequence

_ACTIVE_PATH: Optional[Path] = None
_ACTIVE_HANDLER: Optional[logging.Handler] = None


def log_directory() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~/.local/share")
    return Path(base) / "Osprey" / "logs"


def _prune(folder: Path, keep: int = 40) -> None:
    try:
        files = sorted(folder.glob("osprey-*.log"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
    except OSError:
        return
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def start_run_log(component: str = "osprey",
                  argv: Optional[Sequence[str]] = None) -> Optional[Path]:
    """Create one UTF-8 log file per process; repeated calls return the same file."""
    global _ACTIVE_PATH, _ACTIVE_HANDLER
    if _ACTIVE_PATH is not None:
        return _ACTIVE_PATH
    try:
        folder = log_directory()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = folder / ("osprey-%s-%s-p%d.log" %
                         (component, stamp, os.getpid()))
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            "%Y-%m-%d %H:%M:%S"))
        logger = logging.getLogger("osprey")
        logger.addHandler(handler)
        if logger.level == logging.NOTSET or logger.level > logging.INFO:
            logger.setLevel(logging.INFO)
        _ACTIVE_PATH = path
        _ACTIVE_HANDLER = handler
        try:
            faulthandler.enable(file=handler.stream, all_threads=True)
        except Exception:
            pass
        logger.info("===== Osprey run =====")
        logger.info("version=%s component=%s pid=%d", _version(), component, os.getpid())
        logger.info("python=%s platform=%s", sys.version.split()[0], platform.platform())
        logger.info("cwd=%s", os.getcwd())
        logger.info("argv=%r", list(argv if argv is not None else sys.argv))
        logger.info("log=%s", path)
        _prune(folder)
        return path
    except Exception:
        return None


def active_log_path() -> Optional[Path]:
    return _ACTIVE_PATH


def _version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:
        return "unknown"


def install_exception_hook() -> None:
    """Log uncaught exceptions instead of losing them in a windowed exe."""
    logger = logging.getLogger("osprey")
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            logger.critical("uncaught exception", exc_info=(exc_type, exc, tb))
        except Exception:
            pass
        previous(exc_type, exc, tb)

    sys.excepthook = hook
