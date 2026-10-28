"""End-to-end loop behaviour with a synthetic screen."""

from __future__ import annotations

import unittest

from osprey.core.engine import Engine, EngineConfig
from osprey.core.task import Task
from osprey.input.win32 import InputController

from .helpers import FakeScreen, make_frame, sample_template


class FindAndClick(Task):
    name = "find-and-click"

    def __init__(self, template) -> None:
        self.template = template
        self.hits = 0
        self.torn_down = False
        self.setup_frame_size = None

    def setup(self, ctx) -> None:
        self.setup_frame_size = (ctx.frame.width, ctx.frame.height)

    def step(self, ctx) -> None:
        det = ctx.locate(self.template)
        if det is not None:
            ctx.click(det, move=False)  # keep the test fast: no cursor glide
            self.hits += 1

    def teardown(self, ctx) -> None:
        self.torn_down = True


class Exploding(Task):
    def setup(self, ctx) -> None:
        self.torn_down = False

    def step(self, ctx) -> None:
        raise RuntimeError("boom")

    def teardown(self, ctx) -> None:
        self.torn_down = True


class TestEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.template = sample_template()
        self.source = FakeScreen(lambda: make_frame(self.template, (40, 30)))

    def test_runs_and_clicks(self) -> None:
        controller = InputController(dry_run=True, seed=2)
        task = FindAndClick(self.template)
        engine = Engine(
            task,
            config=EngineConfig(fps=50, duration=0.2, abort_keys=()),
            source=self.source,
            controller=controller,
            settings={"threshold": 0.9, "scales": [1.0]},
        )
        stats = engine.run()
        self.assertGreaterEqual(stats.ticks, 3)
        self.assertGreaterEqual(task.hits, 1)
        self.assertGreaterEqual(stats.actions, 1)
        # Injected sources are owned by the caller, not by the engine.
        self.assertFalse(self.source.closed)
        self.assertTrue(task.torn_down)
        self.assertEqual(task.setup_frame_size, (200, 160))
        self.assertIsNotNone(stats.finished_at)

    def test_task_errors_propagate_but_cleanup_runs(self) -> None:
        task = Exploding()
        engine = Engine(
            task,
            config=EngineConfig(fps=50, duration=1.0, abort_keys=()),
            source=self.source,
            controller=InputController(dry_run=True),
        )
        with self.assertRaises(RuntimeError):
            engine.run()
        self.assertTrue(task.torn_down)
        self.assertFalse(self.source.closed)
        self.source.close()

    def test_duration_is_respected(self) -> None:
        engine = Engine(
            FindAndClick(self.template),
            config=EngineConfig(fps=100, duration=0.15, abort_keys=()),
            source=self.source,
            controller=InputController(dry_run=True),
            settings={"threshold": 0.9},
        )
        stats = engine.run()
        self.assertLess(stats.elapsed, 2.0)
        self.assertGreater(stats.ticks, 0)

    def test_first_grab_failure_closes_owned_source(self) -> None:
        from osprey.core.task import Task

        class Noop(Task):
            def step(self, ctx) -> None:
                pass

        class Exploding:
            def __init__(self) -> None:
                self.closed = False

            def grab(self):
                raise RuntimeError("no display")

            def close(self) -> None:
                self.closed = True

        source = Exploding()
        engine = Engine(
            Noop(),
            config=EngineConfig(abort_keys=(), dry_run=True),
            controller=InputController(dry_run=True),
        )
        engine._default_source = lambda: source
        with self.assertRaises(RuntimeError):
            engine.run()
        self.assertTrue(source.closed)

    def test_abort_key_string_is_not_split(self) -> None:
        self.assertEqual(EngineConfig(abort_keys="f12").abort_keys, ("f12",))
        mapped = EngineConfig.from_mapping({"abort_keys": "f12"})
        self.assertEqual(mapped.abort_keys, ("f12",))

    def test_numeric_strings_are_coerced(self) -> None:
        config = EngineConfig(fps="8", duration="2.5", max_runtime="10", speed="1.5")
        self.assertEqual(config.fps, 8.0)
        self.assertEqual(config.duration, 2.5)
        self.assertEqual(config.max_runtime, 10.0)
        self.assertEqual(config.speed, 1.5)

    def test_non_finite_numbers_are_rejected(self) -> None:
        for kwargs in (
            {"fps": float("nan")},
            {"duration": float("inf")},
            {"max_runtime": float("nan")},
            {"speed": float("inf")},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    EngineConfig(**kwargs)

    def test_invalid_numbers_raise_value_error(self) -> None:
        for kwargs in (
            {"fps": "fast"},
            {"duration": "soon"},
            {"max_runtime": True},
            {"speed": "quick"},
            {"dry_run": "no"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    EngineConfig(**kwargs)

    def test_config_validation(self) -> None:
        for kwargs in ({"fps": 0}, {"duration": -1}, {"speed": 0}, {"move_mode": "warp"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    EngineConfig(**kwargs)


if __name__ == "__main__":
    unittest.main()
