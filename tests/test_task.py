"""Task and state machine behaviour."""

from __future__ import annotations

import unittest

from osprey.core.task import FunctionTask, StateMachine, Task


class TestTask(unittest.TestCase):
    def test_base_task_requires_step(self) -> None:
        with self.assertRaises(NotImplementedError):
            Task().step(None)

    def test_function_task_delegates(self) -> None:
        seen = []
        task = FunctionTask(lambda ctx: seen.append(ctx), name="probe")
        self.assertEqual(task.name, "probe")
        task.step("ctx")
        self.assertEqual(seen, ["ctx"])


class TestStateMachine(unittest.TestCase):
    def test_transitions_and_hooks(self) -> None:
        events = []
        machine = StateMachine("idle")
        machine.add(
            "idle",
            on_enter=lambda ctx: events.append("enter idle"),
            on_tick=lambda ctx: "working",
            on_exit=lambda ctx: events.append("exit idle"),
        )
        machine.add(
            "working",
            on_enter=lambda ctx: events.append("enter working"),
            on_tick=lambda ctx: None,
        )
        machine.start(None)
        self.assertEqual(machine.current, "idle")
        machine.step(None)
        self.assertEqual(machine.current, "working")
        self.assertEqual(events, ["enter idle", "exit idle", "enter working"])

    def test_self_transition_is_a_noop(self) -> None:
        machine = StateMachine("a")
        machine.add("a", on_tick=lambda ctx: "a")
        machine.start(None)
        machine.step(None)
        self.assertEqual(machine.current, "a")

    def test_unknown_state_raises(self) -> None:
        machine = StateMachine("a")
        machine.add("a")
        machine.start(None)
        with self.assertRaises(KeyError):
            machine.goto(None, "b")

    def test_missing_initial_state_raises(self) -> None:
        machine = StateMachine("ghost")
        with self.assertRaises(KeyError):
            machine.start(None)

    def test_step_autostarts(self) -> None:
        entered = []
        machine = StateMachine("a")
        machine.add("a", on_enter=lambda ctx: entered.append(True))
        machine.step(None)
        self.assertEqual(entered, [True])

    def test_hooks_may_be_omitted(self) -> None:
        machine = StateMachine("a")
        machine.add("a")
        machine.start(None)
        machine.step(None)


if __name__ == "__main__":
    unittest.main()
