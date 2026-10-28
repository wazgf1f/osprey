"""Live demo: find the target card on screen and click it once.

Dry run by default: detections are real, clicks are only logged. Add --live to
actually move the mouse and click.

    python examples/click_demo.py
    python examples/click_demo.py --live

Open examples/assets/target.png in any viewer, keep it visible, then run. The
task stops after the requested number of clicks, after --duration seconds, or
when you press F12.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from osprey.core.engine import Engine, EngineConfig
from osprey.core.task import Task
from osprey.errors import Aborted, OspreyError

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(HERE, "assets", "target.png")


class FindTarget(Task):
    name = "find-target"

    def __init__(self, template: str, *, clicks: int = 1, cooldown: float = 1.0,
                 threshold: float = 0.86) -> None:
        self.template = template
        self.wanted = clicks
        self.cooldown = cooldown
        self.threshold = threshold
        self.hits = 0
        self.last_hit = 0.0

    def setup(self, ctx) -> None:
        ctx.logger.info("looking for %s", os.path.basename(self.template))
        ctx.logger.info("move the window around; Osprey tracks its new position")

    def step(self, ctx) -> None:
        found = ctx.locate(self.template, threshold=self.threshold, scales=(1.0,))
        if found is None:
            return
        now = time.monotonic()
        if now - self.last_hit < self.cooldown:
            return
        x, y = ctx.point(found)
        ctx.logger.warning("target at desktop (%.0f, %.0f), score %.3f", x, y, found.score)
        ctx.click(found)
        self.hits += 1
        self.last_hit = now
        if self.hits >= self.wanted:
            raise Aborted("clicked the target %d time(s)" % self.hits)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", default=DEFAULT_TEMPLATE)
    parser.add_argument("--live", action="store_true", help="send real input")
    parser.add_argument("--threshold", type=float, default=0.86)
    parser.add_argument("--clicks", type=int, default=1)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--fps", type=float, default=6.0)
    args = parser.parse_args(argv)

    template = os.path.abspath(args.template)
    if not os.path.exists(template):
        print("template not found: %s (run tools/make_target.py)" % template, file=sys.stderr)
        return 2

    task = FindTarget(template, clicks=args.clicks, threshold=args.threshold)
    config = EngineConfig(
        fps=args.fps,
        duration=args.duration,
        dry_run=not args.live,
        abort_keys=("f12",),
    )
    print("open %s and keep it on screen" % template)
    print("mode:", "LIVE input" if args.live else "dry run (no input is sent)")
    print("press F12 to stop")

    try:
        stats = Engine(task, config=config, settings={"threshold": args.threshold}).run()
    except OspreyError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    print(json.dumps(stats.summary(), indent=2))
    if task.hits == 0:
        print("target never appeared on screen", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
