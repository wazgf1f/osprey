"""Plan parsing, validation and round-tripping."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

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

    def test_bad_field_types_raise_config_error(self) -> None:
        cases = [
            {"loop": "abc"},
            {"loop": 1.5},
            {"threshold": "high"},
            {"timeout": "later"},
            {"steps": [{"action": "wait", "seconds": "soon"}]},
            {"steps": [{"action": "click", "template": "a.png", "wait": "soon"}]},
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    Plan.from_dict(case)

    def test_numeric_strings_are_accepted(self) -> None:
        plan = Plan.from_dict({
            "threshold": "0.9",
            "loop": "2",
            "steps": [{"action": "wait", "seconds": "1.5"}],
        })
        self.assertEqual(plan.threshold, 0.9)
        self.assertEqual(plan.loop, 2)
        self.assertEqual(plan.steps[0].seconds, 1.5)

    def test_steps_must_be_step_objects(self) -> None:
        with self.assertRaises(ConfigError):
            Plan(steps="abc").validate()
        with self.assertRaises(ConfigError):
            Plan(steps=[None]).validate()

    def test_template_must_be_a_path_string(self) -> None:
        for template in (123, ["a.png"], {"path": "a.png"}):
            with self.subTest(template=template):
                with self.assertRaises(ConfigError):
                    Plan.from_dict({
                        "steps": [{"action": "click", "template": template}]
                    })

    def test_invalid_press_key_is_rejected_at_load(self) -> None:
        with self.assertRaises(ConfigError):
            Plan.from_dict({"steps": [{"action": "press", "key": "nope"}]})
        plan = Plan.from_dict({"steps": [{"action": "press", "key": "enter"}]})
        self.assertEqual(plan.steps[0].key, "enter")

    def test_step_numeric_strings_are_accepted(self) -> None:
        plan = Plan.from_dict({
            "steps": [{
                "action": "click",
                "template": "a.png",
                "threshold": "0.9",
                "timeout": "3",
                "scales": ["1.0", "1.25"],
            }]
        })
        step = plan.steps[0]
        self.assertEqual(step.threshold, 0.9)
        self.assertEqual(step.timeout, 3.0)
        self.assertEqual(step.scales, [1.0, 1.25])

    def test_non_finite_numbers_are_rejected(self) -> None:
        for kwargs in (
            {"threshold": float("nan")},
            {"timeout": float("inf")},
            {"fps": float("nan")},
            {"scales": [1.0, float("nan")]},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ConfigError):
                    Plan(**kwargs).validate()
        with self.assertRaises(ConfigError):
            Plan.from_dict({"steps": [{"action": "wait", "seconds": float("nan")}]})

    def test_load_accepts_utf8_bom(self) -> None:
        with temp_dir() as folder:
            path = os.path.join(folder, "plan.json")
            with open(path, "w", encoding="utf-8-sig") as handle:
                handle.write('{"steps": [{"action": "wait", "seconds": 1}]}')
            plan = Plan.load(path)
            self.assertEqual(len(plan.steps), 1)

    def test_load_directory_raises_config_error(self) -> None:
        with temp_dir() as folder:
            with self.assertRaises(ConfigError):
                Plan.load(folder)

    def test_path_template_round_trips(self) -> None:
        with temp_dir() as folder:
            plan = Plan(
                base_dir=folder,
                steps=[Step("click", template=Path("assets/a.png"))],
            )
            path = os.path.join(folder, "plan.json")
            plan.save(path)
            loaded = Plan.load(path)
            self.assertEqual(loaded.steps[0].template, os.path.join("assets", "a.png"))

    def test_save_elsewhere_pins_relative_templates(self) -> None:
        with temp_dir() as source, temp_dir() as target:
            plan = Plan(base_dir=source, steps=[Step("click", template="assets/a.png")])
            path = os.path.join(target, "plan.json")
            plan.save(path)
            loaded = Plan.load(path)
            expected = os.path.join(source, "assets", "a.png")
            self.assertEqual(loaded.steps[0].template, expected)
            self.assertEqual(plan.steps[0].template, expected)

    def test_save_in_place_keeps_relative_templates(self) -> None:
        with temp_dir() as folder:
            plan = Plan(base_dir=folder, steps=[Step("click", template="assets/a.png")])
            path = os.path.join(folder, "plan.json")
            plan.save(path)
            loaded = Plan.load(path)
            self.assertEqual(loaded.steps[0].template, "assets/a.png")

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ConfigError):
            Plan.load("no-such-plan.json")


if __name__ == "__main__":
    unittest.main()
