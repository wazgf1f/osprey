"""Command line interface: doctor, grab, find, run."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import platform
import sys
import time
from typing import List, Optional, Sequence, Tuple

from . import __version__
from .core.config import load_config, resolve_asset
from .core.engine import Engine, EngineConfig
from .core.task import Task
from .errors import ConfigError, OspreyError
from .vision.io import draw_detections, load_gray, save_image
from .vision.match import match_template

logger = logging.getLogger("osprey")


def _parse_region(text: str) -> Tuple[int, int, int, int]:
    parts = text.replace(" ", "").split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must be x,y,width,height")
    try:
        values = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("region values must be integers") from exc
    if values[2] <= 0 or values[3] <= 0:
        raise argparse.ArgumentTypeError("region width and height must be positive")
    return values  # type: ignore[return-value]


def _parse_scales(text: str) -> Tuple[float, ...]:
    try:
        values = tuple(float(part) for part in text.replace(" ", "").split(",") if part)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scales must be comma-separated numbers") from exc
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("scales must be positive numbers")
    return values


def np_as_rgb(frame) -> "object":
    """BGRA frame -> contiguous RGB array (Pillow cannot take negative strides)."""
    import numpy as np

    return np.ascontiguousarray(frame.bgr[..., ::-1])


def _grabber(region: Optional[Sequence[int]], all_screens: bool = False):
    from .capture.gdi import GdiGrabber

    return GdiGrabber(region=region, full_desktop=all_screens)


def cmd_play(args: argparse.Namespace) -> int:
    from .core.plan import Plan
    from .core.sequence import SequenceTask

    plan = Plan.load(args.plan)
    if args.loop is not None:
        plan.loop = args.loop
    if args.fps is not None:
        plan.fps = args.fps
    plan.validate()

    engine = Engine(
        SequenceTask(plan),
        config=EngineConfig(
            fps=plan.fps,
            duration=args.duration,
            dry_run=not args.live,
            abort_keys=("f12",),
        ),
        settings={"threshold": plan.threshold, "scales": plan.scales},
    )
    stats = engine.run()
    print(json.dumps(stats.summary(), indent=2, ensure_ascii=False))
    return 0 if not stats.errors else 1


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from .gui import run_gui
    except ImportError as exc:
        print("the editor needs tkinter: %s" % exc, file=sys.stderr)
        return 2
    return run_gui(args.plan)


def cmd_grab(args: argparse.Namespace) -> int:
    with _grabber(args.region, args.all_screens) as grabber:
        frame = grabber.grab()
    save_image(args.output, np_as_rgb(frame))
    print("saved %dx%d screenshot to %s" % (frame.width, frame.height, args.output))
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    template_path = resolve_asset(config, args.template)
    with _grabber(args.region, args.all_screens) as grabber:
        frame = grabber.grab()

    detections = match_template(
        frame.gray(),
        load_gray(template_path),
        threshold=args.threshold if args.threshold is not None else config["threshold"],
        scales=args.scales if args.scales else config["scales"],
        max_results=args.max_results,
        nms_iou=config["nms_iou"],
        backend=args.backend,
    )
    if not detections:
        print("no match above threshold in %dx%d frame" % (frame.width, frame.height))
        return 1
    for det in detections:
        print(
            "x=%d y=%d w=%d h=%d score=%.4f scale=%.3f desktop=(%d,%d)"
            % (
                det.x, det.y, det.w, det.h, det.score, det.scale,
                det.x + frame.origin[0], det.y + frame.origin[1],
            )
        )
    if args.save:
        save_image(args.save, draw_detections(np_as_rgb(frame), detections))
        print("annotated frame saved to %s" % args.save)
    return 0


def cmd_crop(args: argparse.Namespace) -> int:
    """Capture a rectangle and save it as a template."""
    with _grabber(args.region, args.all_screens) as grabber:
        frame = grabber.grab()
    save_image(args.output, np_as_rgb(frame))
    print(
        "saved %dx%d template at desktop (%d, %d) to %s"
        % (frame.width, frame.height, frame.origin[0], frame.origin[1], args.output)
    )
    print("tip: capture templates on the machine and display scaling where they will run")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print("osprey %s" % __version__)
    print("python      : %s" % platform.python_version())
    print("platform    : %s (%s)" % (platform.platform(), platform.machine()))
    try:
        import numpy

        print("numpy       : %s" % numpy.__version__)
    except Exception:
        print("numpy       : MISSING")
        return 2
    try:
        import PIL

        print("pillow      : %s" % PIL.__version__)
    except Exception:
        print("pillow      : MISSING")
        return 2
    try:
        import cv2

        print("opencv      : %s (fast backend available)" % cv2.__version__)
    except Exception:
        print("opencv      : not installed (numpy backend will be used)")

    if sys.platform != "win32":
        print("capture     : unavailable (Osprey targets Windows)")
        return 2
    try:
        from .capture.gdi import GdiGrabber, enable_dpi_awareness, monitors, screen_scale

        print("dpi aware   : %s" % enable_dpi_awareness())
        print("dpi scale   : %.3fx" % screen_scale())
        for index, monitor in enumerate(monitors()):
            mx, my, mw, mh = monitor["rect"]
            print("monitor %-3d : %dx%d at (%d, %d)%s"
                  % (index, mw, mh, mx, my, "  [primary]" if monitor["primary"] else ""))
        with GdiGrabber() as grabber:
            print("screen      : %dx%d at origin %r"
                  % (grabber.screen_size[0], grabber.screen_size[1], grabber.origin))
            grabber.grab()  # warm up GDI
            timings = []
            for _ in range(5):
                start = time.perf_counter()
                frame = grabber.grab()
                timings.append((time.perf_counter() - start) * 1000.0)
        print("capture ms  : min %.1f  mean %.1f  max %.1f"
              % (min(timings), sum(timings) / len(timings), max(timings)))
        print("brightness  : %.1f (0 means a black or locked screen)" % frame.mean_brightness())
    except Exception as exc:
        print("capture     : FAILED - %s" % exc)
        return 2

    input_state = _probe_input()
    print("input       : %s" % input_state)
    if input_state.startswith("ok"):
        print("status      : ready")
    else:
        print("status      : capture ready, input unavailable (dry runs only)")
    return 0


def _probe_input() -> str:
    """Nudge the cursor, verify it moved, put it back."""
    try:
        from .input.win32 import InputController, cursor_position

        start = cursor_position()
        controller = InputController(dry_run=False)
        # One nudge can be swallowed on a busy desktop; try a few offsets.
        for offset in (12, 40, 12):
            controller.move_to(start[0] + offset, start[1] + offset, humanize=False)
            time.sleep(0.08)
            moved = cursor_position()
            controller.move_to(start[0], start[1], humanize=False)
            time.sleep(0.04)
            if moved != start:
                return "ok (cursor moved and was restored)"
        return "BLOCKED (this desktop rejects synthetic input; dry runs still work)"
    except Exception as exc:
        return "FAILED - %s" % exc


def _load_task(path: str) -> Task:
    if not os.path.exists(path):
        raise ConfigError("task file not found: %s" % path)
    spec = importlib.util.spec_from_file_location("osprey_user_task", path)
    if spec is None or spec.loader is None:
        raise ConfigError("cannot import %s" % path)
    task_dir = os.path.dirname(os.path.abspath(path))
    if task_dir not in sys.path:
        sys.path.insert(0, task_dir)

    module = importlib.util.module_from_spec(spec)
    sys.modules["osprey_user_task"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop("osprey_user_task", None)
        raise ConfigError(
            "could not import %s: %s: %s" % (path, type(exc).__name__, exc)
        ) from exc

    factory = getattr(module, "create_task", None)
    if callable(factory):
        task = factory()
    else:
        task = getattr(module, "TASK", None)
        if task is None:
            # A module with exactly one Task subclass is unambiguous; accept it.
            classes = [
                value for value in vars(module).values()
                if isinstance(value, type) and issubclass(value, Task) and value is not Task
            ]
            if len(classes) == 1:
                task = classes[0]()
            elif not classes:
                raise ConfigError(
                    "%s defines no Task subclass; add one, or expose TASK / create_task()" % path
                )
            else:
                raise ConfigError(
                    "%s defines several Task subclasses (%s); expose TASK or create_task()"
                    % (path, ", ".join(sorted(cls.__name__ for cls in classes)))
                )
        elif isinstance(task, type):
            task = task()
    if not isinstance(task, Task):
        raise ConfigError("task must be an osprey Task instance, got %r" % (type(task),))
    return task


def cmd_run(args: argparse.Namespace) -> int:
    overrides = {}
    if args.fps is not None:
        overrides["fps"] = args.fps
    if args.duration is not None:
        overrides["duration"] = args.duration
    if args.speed is not None:
        overrides["speed"] = args.speed
    if args.max_runtime is not None:
        overrides["max_runtime"] = args.max_runtime
    if args.assets_dir:
        overrides["assets_dir"] = args.assets_dir
    if args.live:
        overrides["dry_run"] = False

    config = load_config(args.config, overrides)
    task = _load_task(args.task)

    engine_config = EngineConfig.from_mapping(config)
    engine = Engine(task, config=engine_config, settings=config)
    stats = engine.run()
    print(json.dumps(stats.summary(), indent=2, ensure_ascii=False))
    return 0 if not stats.errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="osprey",
        description="Screen-vision automation for Windows: capture, detect, act.",
    )
    parser.add_argument("--version", action="version", version="osprey " + __version__)
    parser.add_argument("-v", "--verbose", action="count", default=0, help="more logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_grab = sub.add_parser("grab", help="save a screenshot")
    p_grab.add_argument("output")
    p_grab.add_argument("--region", type=_parse_region)
    p_grab.add_argument("--all-screens", action="store_true",
                        help="capture every monitor as one image")
    p_grab.set_defaults(func=cmd_grab)

    p_find = sub.add_parser("find", help="locate a template on screen")
    p_find.add_argument("template")
    p_find.add_argument("--config")
    p_find.add_argument("--region", type=_parse_region)
    p_find.add_argument("--all-screens", action="store_true",
                        help="search every monitor as one image")
    p_find.add_argument("--threshold", type=float)
    p_find.add_argument("--scales", type=_parse_scales)
    p_find.add_argument("--max-results", type=int, default=5)
    p_find.add_argument("--backend", choices=["auto", "numpy", "opencv"], default="auto")
    p_find.add_argument("--save", help="write an annotated PNG here")
    p_find.set_defaults(func=cmd_find)

    p_play = sub.add_parser("play", help="run a plan.json sequence")
    p_play.add_argument("plan")
    p_play.add_argument("--live", action="store_true", help="send real input")
    p_play.add_argument("--loop", type=int, help="override the plan loop count (0 = forever)")
    p_play.add_argument("--fps", type=float)
    p_play.add_argument("--duration", type=float)
    p_play.set_defaults(func=cmd_play)

    p_gui = sub.add_parser("gui", help="open the visual plan editor")
    p_gui.add_argument("plan", nargs="?", help="optional plan.json to open")
    p_gui.set_defaults(func=cmd_gui)

    p_crop = sub.add_parser("crop", help="save a screen region as a template")
    p_crop.add_argument("output")
    p_crop.add_argument("--region", type=_parse_region, required=True)
    p_crop.add_argument("--all-screens", action="store_true")
    p_crop.set_defaults(func=cmd_crop)

    p_doctor = sub.add_parser("doctor", help="check the environment")
    p_doctor.set_defaults(func=cmd_doctor)

    p_run = sub.add_parser("run", help="run a task file")
    p_run.add_argument("task")
    p_run.add_argument("--config")
    p_run.add_argument("--fps", type=float)
    p_run.add_argument("--duration", type=float, help="stop after N seconds")
    p_run.add_argument("--max-runtime", type=float, help="hard safety cap in seconds")
    p_run.add_argument("--speed", type=float, help="input speed multiplier")
    p_run.add_argument("--assets-dir")
    p_run.add_argument("--live", action="store_true", help="actually send input (default is dry run)")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except (OspreyError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
