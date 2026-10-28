"""SequenceTask executes plan steps in order."""

from __future__ import annotations

import os
import unittest

from osprey.core.engine import Engine, EngineConfig
from osprey.core.plan import Plan, Step
from osprey.core.sequence import SequenceTask
from osprey.input.win32 import InputController
from osprey.vision.io import save_image

from .helpers import FakeScreen, make_frame, sample_template, temp_dir


class TestSequence(unittest.TestCase):
    def _run(self, plan: Plan, source: FakeScreen, duration: float = 3.0):
        controller = InputController(dry_run=True, seed=5)
        engine = Engine(
            SequenceTask(plan),
            config=EngineConfig(fps=20, duration=duration, abort_keys=()),
            source=source,
            controller=controller,
            settings={"threshold": 0.85, "scales": [1.0]},
        )
        return engine.run(), controller

    def _click_plan(self, folder: str, template, **kwargs) -> Plan:
        path = os.path.join(folder, "t.png")
        save_image(path, template)
        return Plan(
            base_dir=folder,
            steps=[Step("click", template="t.png", wait=0.05)],
            threshold=0.85,
            **kwargs,
        ).validate()

    def test_click_then_press_in_order(self) -> None:
        template = sample_template()
        with temp_dir() as folder:
            path = os.path.join(folder, "t.png")
            save_image(path, template)
            plan = Plan(
                base_dir=folder,
                steps=[
                    Step("click", template="t.png", wait=0.05),
                    Step("press", key="enter", wait=0.05),
                ],
                threshold=0.85,
            ).validate()
            source = FakeScreen(lambda: make_frame(template, (40, 30)))
            stats, controller = self._run(plan, source)

        self.assertEqual(stats.stop_reason, "plan finished")
        clicks = [item for item in controller.history if item.startswith("click")]
        self.assertTrue(clicks)
        self.assertIn("key_down enter", controller.history)
        self.assertLess(controller.history.index(clicks[0]),
                        controller.history.index("key_down enter"))

    def test_loop_two_passes(self) -> None:
        template = sample_template(seed=21)
        with temp_dir() as folder:
            plan = self._click_plan(folder, template, loop=2)
            source = FakeScreen(lambda: make_frame(template, (30, 20)))
            stats, controller = self._run(plan, source)
        self.assertEqual(stats.stop_reason, "plan finished")
        self.assertEqual(sum(1 for item in controller.history if item.startswith("click")), 2)

    def test_missing_template_stops(self) -> None:
        template = sample_template()
        other = sample_template(seed=99)
        with temp_dir() as folder:
            path = os.path.join(folder, "t.png")
            save_image(path, template)
            plan = Plan(base_dir=folder,
                        steps=[Step("click", template="t.png", timeout=0.2)],
                        threshold=0.85).validate()
            source = FakeScreen(lambda: make_frame(other, (40, 30)))
            stats, controller = self._run(plan, source, duration=3.0)
        self.assertIn("not found", stats.stop_reason or "")
        self.assertEqual(controller.history, [])

    def test_missing_template_can_be_skipped(self) -> None:
        template = sample_template()
        other = sample_template(seed=77)
        with temp_dir() as folder:
            path = os.path.join(folder, "t.png")
            save_image(path, template)
            plan = Plan(base_dir=folder, on_missing="skip",
                        steps=[Step("click", template="t.png", timeout=0.2),
                               Step("wait", seconds=0.05)],
                        threshold=0.85).validate()
            source = FakeScreen(lambda: make_frame(other, (40, 30)))
            stats, _controller = self._run(plan, source)
        self.assertEqual(stats.stop_reason, "plan finished")

    def test_empty_plan_stops_immediately(self) -> None:
        with temp_dir() as folder:
            plan = Plan(base_dir=folder).validate()
            source = FakeScreen(lambda: make_frame(sample_template()))
            stats, _controller = self._run(plan, source, duration=2.0)
        self.assertIn("no steps", stats.stop_reason or "")


    def test_press_counts_as_action(self) -> None:
        with temp_dir() as folder:
            plan = Plan(
                base_dir=folder,
                steps=[Step("press", key="enter", wait=0.01)],
            ).validate()
            source = FakeScreen(lambda: make_frame(sample_template()))
            stats, _controller = self._run(plan, source)
        self.assertEqual(stats.stop_reason, "plan finished")
        self.assertEqual(stats.actions, 1)

    def test_assets_dir_override_is_used(self) -> None:
        template = sample_template(seed=33)
        with temp_dir() as plan_dir, temp_dir() as assets_dir:
            save_image(os.path.join(assets_dir, "t.png"), template)
            plan = Plan(
                base_dir=plan_dir,
                steps=[Step("click", template="t.png", wait=0.05)],
                threshold=0.85,
            ).validate()
            source = FakeScreen(lambda: make_frame(template, (30, 20)))
            controller = InputController(dry_run=True)
            engine = Engine(
                SequenceTask(plan, assets_dir=assets_dir),
                config=EngineConfig(fps=20, duration=2.0, abort_keys=()),
                source=source,
                controller=controller,
                settings={"threshold": 0.85},
            )
            stats = engine.run()
        self.assertEqual(stats.stop_reason, "plan finished")
        self.assertTrue(any(item.startswith("click") for item in controller.history))


if __name__ == "__main__":
    unittest.main()
