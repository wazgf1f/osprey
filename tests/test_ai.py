"""OCR + text-model agent (no network or OCR backend required)."""

from __future__ import annotations

import json
import unittest

from osprey.ai.agent import OcrAgentTask
from osprey.ai.deepseek import DeepSeekError, parse_json_reply
from osprey.ai.ocr import OcrError, OcrItem
from osprey.errors import OspreyError
from osprey.core.context import Context
from osprey.core.safety import Safety
from osprey.input.win32 import InputController

from .helpers import FakeScreen, make_frame, sample_template


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.last = None

    def complete_json(self, system, user):
        self.last = (system, user)
        return self.replies.pop(0)


def make_context(goal="click OK"):
    frame = make_frame(sample_template())
    return Context(
        frame=frame,
        screen=FakeScreen(lambda: frame),
        input=InputController(dry_run=True),
        safety=Safety(abort_keys=()),
        config={"goal": goal, "ai_tick_wait": 0.0},
    )


class TestErrors(unittest.TestCase):
    def test_ai_errors_are_osprey_errors(self) -> None:
        self.assertTrue(issubclass(DeepSeekError, OspreyError))
        self.assertTrue(issubclass(OcrError, OspreyError))


class TestParseReply(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(parse_json_reply('{"action": "done"}')["action"], "done")

    def test_fenced_json(self) -> None:
        fence = chr(96) * 3
        text = fence + 'json\n{"action": "click", "element_id": 2}\n' + fence
        self.assertEqual(parse_json_reply(text)["element_id"], 2)

    def test_non_json_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            parse_json_reply("I would click the button")


class TestOcrAgent(unittest.TestCase):
    def test_clicks_the_element_chosen_by_the_model(self) -> None:
        items = [OcrItem("Cancel", (0, 0, 40, 20)),
                 OcrItem("OK", (100, 50, 40, 20))]
        client = FakeClient([
            {"thought": "OK is visible", "action": "click", "element_id": 1},
            {"thought": "done", "action": "done"},
        ])
        task = OcrAgentTask(client=client, ocr=lambda _frame: items)
        ctx = make_context()
        task.setup(ctx)

        task.step(ctx)
        self.assertEqual(ctx.stats.actions, 1)
        self.assertTrue(any(entry.startswith("click") for entry in ctx.input.history))
        payload = json.loads(client.last[1])
        self.assertEqual(payload["goal"], "click OK")
        self.assertEqual(payload["elements"][1]["text"], "OK")

        task.step(ctx)
        self.assertTrue(ctx.safety.aborted)

    def test_numeric_string_and_uppercase_action_are_accepted(self) -> None:
        items = [OcrItem("OK", (10, 10, 20, 20))]
        client = FakeClient([
            {"action": "CLICK", "element_id": "0"},
            {"action": "DONE"},
        ])
        task = OcrAgentTask(client=client, ocr=lambda _frame: items)
        ctx = make_context()
        task.setup(ctx)
        task.step(ctx)
        self.assertEqual(ctx.stats.actions, 1)
        task.step(ctx)
        self.assertTrue(ctx.safety.aborted)

    def test_invalid_element_id_does_not_click(self) -> None:
        items = [OcrItem("OK", (10, 10, 20, 20))]
        client = FakeClient([{"action": "click", "element_id": 9}])
        task = OcrAgentTask(client=client, ocr=lambda _frame: items)
        ctx = make_context()
        task.setup(ctx)
        task.step(ctx)
        self.assertEqual(ctx.stats.actions, 0)
        self.assertEqual(ctx.input.history, [])

    def test_missing_goal_is_rejected(self) -> None:
        task = OcrAgentTask(client=FakeClient([]), ocr=lambda _frame: [])
        with self.assertRaises(Exception):
            task.setup(make_context(goal=""))

    def test_no_text_does_not_call_the_model(self) -> None:
        client = FakeClient([])
        task = OcrAgentTask(client=client, ocr=lambda _frame: [])
        ctx = make_context()
        task.setup(ctx)
        task.step(ctx)
        self.assertIsNone(client.last)


if __name__ == "__main__":
    unittest.main()
