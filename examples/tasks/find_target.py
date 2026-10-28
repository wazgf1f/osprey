"""A copy-paste starting point for your own task.

Run it with:

    osprey run examples/tasks/find_target.py --config examples/tasks/config.json

Dry run is the default; add --live to actually click.
"""

from osprey.core.task import Task


class FindTarget(Task):
    name = "find-target"

    def setup(self, ctx):
        self.template = "target.png"   # relative to assets_dir in the config
        self.threshold = float(ctx.config.get("threshold", 0.86))
        self.scales = tuple(ctx.config.get("scales", [1.0]))
        self.hits = 0

    def step(self, ctx):
        # roi=(x, y, w, h) limits the search; drop it to scan the whole screen.
        found = ctx.locate(self.template, threshold=self.threshold, scales=self.scales)
        if found is None:
            return

        x, y = ctx.point(found)
        ctx.logger.warning("target at (%.0f, %.0f), score %.3f", x, y, found.score)
        ctx.click(found)
        self.hits += 1
        ctx.sleep(0.8)

        if self.hits >= 3:
            ctx.safety.request_stop("clicked the target three times")
