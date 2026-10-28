"""Run a declarative Plan as an engine task."""

from __future__ import annotations

import os

from .plan import Plan, Step
from .task import Task


class SequenceTask(Task):
    """Executes plan steps in order, with waits and loop support."""

    name = "sequence"

    def __init__(self, plan: Plan, *, assets_dir: str = "") -> None:
        self.plan = plan
        self.assets_dir = assets_dir or plan.base_dir
        self.index = 0
        self.completed = 0
        self.steps_done = 0

    def setup(self, ctx) -> None:
        self.index = 0
        self.completed = 0
        self.steps_done = 0
        if not self.plan.steps:
            ctx.logger.warning("plan has no steps")
            ctx.safety.request_stop("plan has no steps")
            return
        ctx.logger.info(
            "plan %r: %d step(s), loop=%s, threshold=%.2f",
            self.plan.name, len(self.plan.steps),
            "forever" if self.plan.loop == 0 else self.plan.loop,
            self.plan.threshold,
        )

    def step(self, ctx) -> None:
        if self.index >= len(self.plan.steps):
            self.index = 0
        current = self.plan.steps[self.index]
        ctx.logger.info("step %d/%d: %s", self.index + 1, len(self.plan.steps),
                        current.action)
        self._run_step(ctx, current)
        self.steps_done += 1
        self.index += 1

        if self.index >= len(self.plan.steps):
            self.completed += 1
            if self.plan.loop != 0 and self.completed >= self.plan.loop:
                ctx.logger.info("plan finished after %d pass(es)", self.completed)
                ctx.safety.request_stop("plan finished")
            else:
                self.index = 0

    def _resolve(self, template: str) -> str:
        if os.path.isabs(template):
            return template
        return os.path.abspath(os.path.join(self.assets_dir, template))

    def _run_step(self, ctx, step: Step) -> None:
        if step.action == "wait":
            ctx.sleep(step.seconds)
            return

        if step.action == "press":
            ctx.input.press(step.key)
            ctx.stats.actions += 1
            if step.wait:
                ctx.sleep(step.wait)
            return

        if step.action == "drag":
            ctx.drag(step.start, step.end, duration=step.duration, button=step.button)
            if step.wait:
                ctx.sleep(step.wait)
            return

        template = self._resolve(step.template)
        detection = ctx.wait_for(
            template,
            timeout=step.timeout if step.timeout is not None else self.plan.timeout,
            interval=0.12,
            threshold=step.threshold if step.threshold is not None else self.plan.threshold,
            scales=tuple(step.scales if step.scales is not None else self.plan.scales),
        )
        if detection is None:
            policy = step.on_missing or self.plan.on_missing
            name = os.path.basename(template)
            if policy == "skip":
                ctx.logger.warning("not found, skipping: %s", name)
                if step.wait:
                    ctx.sleep(step.wait)
                return
            ctx.logger.warning("not found, stopping: %s", name)
            ctx.safety.request_stop("template not found: %s" % name)
            return

        if step.action == "click":
            ctx.click(detection)
        else:
            ctx.move(detection)

        if step.wait:
            ctx.sleep(step.wait)
