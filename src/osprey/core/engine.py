"""The run loop: capture, step the task, respect safety, clean up."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple

from ..capture.base import FrameSource
from ..errors import Aborted
from ..input.win32 import InputController
from .context import Context
from .safety import Safety
from .stats import Stats
from .task import Task

logger = logging.getLogger(__name__)


def _engine_number(value: Any, name: str, *, allow_none: bool = False) -> Optional[float]:
    if value is None:
        if allow_none:
            return None
        raise ValueError("%s is required" % name)
    if isinstance(value, bool):
        raise ValueError("%s must be a number, got %r" % (name, value))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be a number, got %r" % (name, value)) from exc
    if not math.isfinite(number):
        raise ValueError("%s must be finite, got %r" % (name, value))
    return number


@dataclass
class EngineConfig:
    """Loop-level settings, independent of what the task does."""

    fps: float = 8.0
    duration: Optional[float] = None
    dry_run: bool = True
    abort_keys: Tuple[str, ...] = ("f12",)
    stop_file: Optional[str] = None
    max_runtime: Optional[float] = None
    speed: float = 1.0
    move_mode: str = "absolute"

    def __post_init__(self) -> None:
        if isinstance(self.abort_keys, str):
            self.abort_keys = (self.abort_keys,)
        else:
            self.abort_keys = tuple(self.abort_keys)
        if not isinstance(self.dry_run, bool):
            raise ValueError("dry_run must be true or false, got %r" % (self.dry_run,))
        self.fps = _engine_number(self.fps, "fps")
        self.duration = _engine_number(self.duration, "duration", allow_none=True)
        self.max_runtime = _engine_number(self.max_runtime, "max_runtime", allow_none=True)
        self.speed = _engine_number(self.speed, "speed")
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.duration is not None and self.duration <= 0:
            raise ValueError("duration must be positive or None")
        if self.max_runtime is not None and self.max_runtime <= 0:
            raise ValueError("max_runtime must be positive or None")
        if self.speed <= 0:
            raise ValueError("speed must be positive")
        if self.move_mode not in ("absolute", "relative"):
            raise ValueError("move_mode must be 'absolute' or 'relative'")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EngineConfig":
        return cls(
            fps=data.get("fps", 8.0),
            duration=data.get("duration"),
            dry_run=data.get("dry_run", True),
            abort_keys=data.get("abort_keys", ("f12",)),
            stop_file=data.get("stop_file"),
            max_runtime=data.get("max_runtime"),
            speed=data.get("speed", 1.0),
            move_mode=str(data.get("move_mode", "absolute")),
        )


class Engine:
    """Owns the loop and the wiring; the task owns all decisions."""

    def __init__(
        self,
        task: Task,
        *,
        config: Optional[EngineConfig] = None,
        settings: Optional[Mapping[str, Any]] = None,
        source: Optional[FrameSource] = None,
        controller: Optional[InputController] = None,
    ) -> None:
        self.task = task
        self.config = config or EngineConfig()
        self.settings = dict(settings or {})
        self.source = source
        self.controller = controller
        self.stats = Stats()

    def run(self, on_ready: Optional[Callable[[Context], None]] = None) -> Stats:
        cfg = self.config
        source = self.source if self.source is not None else self._default_source()
        owns_source = self.source is None

        safety = Safety(
            abort_keys=cfg.abort_keys,
            stop_file=cfg.stop_file,
            max_runtime=cfg.max_runtime,
        )
        controller = self.controller or InputController(
            dry_run=cfg.dry_run,
            should_abort=safety.should_abort,
            speed=cfg.speed,
            move_mode=cfg.move_mode,
        )

        first_frame = source.grab()
        ctx = Context(
            frame=first_frame,
            screen=source,
            input=controller,
            safety=safety,
            config=self.settings,
            stats=self.stats,
            logger=logging.getLogger("osprey.task"),
        )

        if cfg.dry_run:
            logger.warning("DRY RUN: detections are real, input is only logged")
        logger.info(
            "starting %s on a %dx%d screen at %.1f fps (panic key: %s)",
            getattr(self.task, "name", type(self.task).__name__),
            first_frame.width,
            first_frame.height,
            cfg.fps,
            ", ".join(cfg.abort_keys) or "none",
        )

        period = 1.0 / cfg.fps
        safety.start()
        started = time.monotonic()
        deadline = started
        ctx_ready = False

        try:
            self.task.setup(ctx)
            ctx_ready = True
            if on_ready is not None:
                on_ready(ctx)
            while True:
                safety.check()
                ctx.frame = source.grab()
                self.task.step(ctx)
                self.stats.ticks += 1

                if cfg.duration is not None and time.monotonic() - started >= cfg.duration:
                    self.stats.finish("duration reached")
                    break

                deadline += period
                delay = deadline - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    deadline = time.monotonic()
        except Aborted as exc:
            self.stats.finish(str(exc))
            logger.warning("stopped: %s", exc)
        except KeyboardInterrupt:
            self.stats.finish("keyboard interrupt")
            logger.warning("interrupted by keyboard")
        except Exception as exc:
            self.stats.errors += 1
            self.stats.finish("error: %s" % exc)
            logger.exception("task failed")
            raise
        finally:
            try:
                controller.release_all()
            except Exception:  # pragma: no cover - defensive
                logger.exception("could not release input state")
            if ctx_ready:
                try:
                    self.task.teardown(ctx)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("task teardown failed")
            if owns_source:
                source.close()
            logger.info(
                "run finished in %.2fs: %d ticks, %d detections, %d actions",
                self.stats.elapsed,
                self.stats.ticks,
                self.stats.detections,
                self.stats.actions,
            )
        return self.stats

    def _default_source(self) -> FrameSource:
        from ..capture.gdi import GdiGrabber

        return GdiGrabber(full_desktop=bool(self.settings.get("all_screens", False)))
