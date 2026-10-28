"""Plan parsing, validation and round-tripping."""

from __future__ import annotations

import json
import os
import unittest

from osprey.core.plan import Plan, Step
from osprey.errors import ConfigError

from .helpers import temp_dir


class TestPlan(unittest.TestCase):
    def test_round_trip(self) -> None:
        plan = Plan(
            name="daily",
            steps=[
                Step("click", template="assets/a.png", wait=1.5, threshold=0.9),
                Step("wait", seconds=2.0),
                Step("press", key="enter", wait=0.2),
            ],
            threshold=0.88,
            timeout=6.0,
            fps=4.0,
            loop=3,
            on_missing="skip",
            scales=[1.0, 1.25],
        ).validate()
        rebuilt = Plan.from_dict(plan.to_dict())
        self.assertEqual(rebuilt.name, "daily")
        self.assertEqual(rebuilt.loop, 3)
        self.assertEqual(rebuilt.on_missing, "skip")
        self.assertEqual(rebuilt.scales, [1.0, 1.25])
        self.assertEqual(rebuilt.steps[0].template, "assets/a.png")
        self.assertEqual(rebuilt.steps[0].wait, 1.5)
        self.assertEqual(rebuilt.steps[1].seconds, 2.0)
        self.assertEqual(rebuilt.steps[2].key, "enter")

    def test_save_and_load_resolves_relative_templates(self) -> None:
        with temp_dir() as folder:
            path = os.path.join(folder, "plan.json")
            Plan(steps=[Step("click", template="img/a.png")]).save(path)
            loaded = Plan.load(path)
            self.assertEqual(loaded.base_dir, os.path.dirname(os.path.abspath(path)))
            self.assertEqual(loaded.resolve("img/a.png"),
                             os.path.join(os.path.dirname(os.path.abspath(path)), "img", "a.png"))
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["steps"][0]["action"], "click")

    def test_invalid_steps(self) -> None:
        cases = [
            Step("dance"),
            Step("click"),
            Step("wait", seconds=0),
            Step("press"),
            Step("click", template="a.png", on_missing="explode"),
            Step("click", template="a.png", scales=[0]),
            Step("click", template="a.png", threshold=2),
        ]
        for step in cases:
            with self.subTest(step=step):
                with self.assertRaises(ConfigError):
                    step.validate(0)

    def test_invalid_plan_values(self) -> None:
        for kwargs in (
            {"loop": -1},
            {"loop": 1.5},
            {"threshold": 1.5},
            {"timeout": 0},
            {"fps": 0},
            {"on_missing": "maybe"},
            {"scales": []},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ConfigError):
                    Plan(**kwargs).validate()

    def test_empty_plan_is_allowed_for_editing(self) -> None:
        plan = Plan().validate()
        self.assertEqual(plan.steps, [])

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ConfigError):
            Plan.load("no-such-plan.json")


if __name__ == "__main__":
    unittest.main()
