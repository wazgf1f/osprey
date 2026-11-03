"""A Task that lets OCR + a text model choose the next click."""

from __future__ import annotations

import functools
import json
import math
from typing import Any, Callable, Dict, List, Optional

from ..core.context import Context
from ..core.task import Task
from ..errors import ConfigError
from .deepseek import DeepSeekClient
from .ocr import OcrItem, default_ocr_backend, ocr_frame
from .vision import annotate_frame

SYSTEM_PROMPT = """You control a Windows desktop through OCR text boxes.
Choose exactly one action and reply with JSON only:
{"thought": "...", "action": "click", "element_id": 3}
{"thought": "...", "action": "wait", "seconds": 1}
{"thought": "...", "action": "scroll", "amount": -3}
{"thought": "...", "action": "done"}
Rules:
- click only an element_id present in the list.
- Prefer text that exactly matches the goal; use position when texts repeat.
- The goal is semantic. "next page" may appear as 下一页, 下一节, Next, >, or a
  similar next-navigation control; choose that control when it fits the goal.
- Do not use done only because the exact wording is missing. If the target may
  be below the fold, use scroll (amount -3 scrolls down, 3 scrolls up).
- Use wait when the screen is still loading.
- Use done when the goal is already satisfied or cannot be reached.
"""


VISION_SYSTEM_PROMPT = """You see a Windows screenshot with red numbered OCR boxes.
Reply with one JSON object only:
{"action": "click", "element_id": 3}
{"action": "wait", "seconds": 1}
{"action": "scroll", "amount": -3}
{"action": "done"}
Rules:
- Always use an element_id from the list; never return coordinates.
- Match the user's intent, not only exact text (下一页 may be 下一节 or Next).
- Scroll down when the target is below the fold.
- Wait while the page is loading; done only when finished or impossible.
"""


class OcrAgentTask(Task):
    name = "ocr-ai-agent"

    def __init__(self, *, client: Optional[DeepSeekClient] = None,
                 ocr: Optional[Callable[[Any], List[OcrItem]]] = None,
                 api_key: Optional[str] = None) -> None:
        self._client = client
        self._ocr = ocr
        self._api_key = api_key
        self.goal = ""
        self.max_steps = 30
        self.tick_wait = 0.8
        self.steps = 0
        self.history: List[str] = []
        self._ocr_failures = 0

    def setup(self, ctx: Context) -> None:
        self.goal = str(ctx.config.get("goal", "")).strip()
        if not self.goal:
            raise ConfigError("AI task needs a 'goal' in the config")
        self.max_steps = int(ctx.config.get("ai_max_steps", 30))
        self.tick_wait = float(ctx.config.get("ai_tick_wait", 0.8))
        if self._ocr is None:
            default_ocr_backend()
        self.client = self._client or DeepSeekClient(api_key=self._api_key)
        self.ocr = self._ocr or functools.partial(
            ocr_frame, detail=True, max_items=250)
        self.steps = 0
        self.history = []
        self._ocr_failures = 0

    def step(self, ctx: Context) -> None:
        if self.steps >= self.max_steps:
            ctx.safety.request_stop("AI step limit reached")
            return
        self.steps += 1
        try:
            items = self.ocr(ctx.frame)
        except Exception as exc:
            self._ocr_failures += 1
            ctx.logger.warning("OCR failed (%d/3): %s", self._ocr_failures, exc)
            if self._ocr_failures >= 3:
                ctx.safety.request_stop("OCR failed 3 times: %s" % exc)
                return
            ctx.sleep(self.tick_wait)
            return
        self._ocr_failures = 0
        if not items:
            ctx.logger.info("OCR found no text; waiting")
            ctx.sleep(self.tick_wait)
            return
        try:
            action = self._decide(ctx, items)
        except Exception as exc:
            message = str(exc)
            if "HTTP 401" in message or "HTTP 403" in message:
                ctx.logger.error("AI stopped: authentication failed")
                ctx.safety.request_stop("DeepSeek authentication failed")
                return
            ctx.logger.warning("AI decision failed: %s", exc)
            ctx.sleep(self.tick_wait)
            return
        self._apply(ctx, items, action)

    def _decide(self, ctx: Context, items: List[OcrItem]) -> Dict[str, Any]:
        elements = []
        for index, item in enumerate(items):
            x, y, width, height = item.box
            elements.append({
                "id": index,
                "text": item.text,
                "box": [x, y, width, height],
                "center": [round(item.center[0], 1), round(item.center[1], 1)],
            })
        payload = {
            "goal": self.goal,
            "screen": [ctx.frame.width, ctx.frame.height],
            "elements": elements,
            "history": self.history[-8:],
        }
        reply = self.client.complete_json(
            SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False))
        thought = str(reply.get("thought", "")).strip()
        if thought:
            ctx.logger.info("AI: %s", thought)
        return reply

    def _apply(self, ctx: Context, items: List[OcrItem], action: Dict[str, Any]) -> None:
        kind = action.get("action")
        if isinstance(kind, str):
            kind = kind.strip().lower()
        if kind == "click":
            element_id = action.get("element_id")
            if isinstance(element_id, str) and element_id.strip().isdigit():
                element_id = int(element_id.strip())
            elif isinstance(element_id, float) and element_id.is_integer():
                element_id = int(element_id)
            if isinstance(element_id, bool) or not isinstance(element_id, int):
                ctx.logger.warning("AI returned an invalid element_id: %r", element_id)
                ctx.sleep(self.tick_wait)
                return
            if not 0 <= element_id < len(items):
                ctx.logger.warning("AI chose element %s outside 0..%d",
                                   element_id, len(items) - 1)
                ctx.sleep(self.tick_wait)
                return
            item = items[element_id]
            button = action.get("button", "left")
            if button not in ("left", "right", "middle"):
                button = "left"
            ctx.click(item.center, button=button)
            self.history.append("click %d %r" % (element_id, item.text))
            ctx.sleep(self.tick_wait)
            return

        if kind == "wait":
            try:
                seconds = float(action.get("seconds", 1.0))
            except (TypeError, ValueError):
                seconds = 1.0
            if not math.isfinite(seconds):
                seconds = 1.0
            ctx.sleep(max(0.2, min(10.0, seconds)))
            return

        if kind == "scroll":
            try:
                amount = int(round(float(action.get("amount", -3))))
            except (TypeError, ValueError, OverflowError):
                amount = -3
            amount = max(-10, min(10, amount))
            if amount == 0:
                amount = -3
            xs = sorted(item.center[0] for item in items)
            ys = sorted(item.center[1] for item in items)
            target = (xs[len(xs) // 2], ys[len(ys) // 2])
            ctx.scroll(amount, target)
            self.history.append("scroll %d" % amount)
            ctx.sleep(self.tick_wait)
            return

        if kind == "done":
            self.history.append("done")
            ctx.safety.request_stop("AI goal reached")
            return

        ctx.logger.warning("AI returned an unsupported action: %r", kind)
        ctx.sleep(self.tick_wait)


class VisionAgentTask(OcrAgentTask):
    """Qwen-VL sees an annotated screenshot, but OCR boxes still own the click."""

    name = "vision-ai-agent"

    def __init__(self, *, vision, ocr=None) -> None:
        super().__init__(client=vision, ocr=ocr)
        self.vision = vision

    def setup(self, ctx: Context) -> None:
        super().setup(ctx)
        if self._ocr is None:
            # Local VLMs have a limited context; send fewer OCR elements.
            self.ocr = functools.partial(
                ocr_frame, detail=True, max_items=80)
        prepare = getattr(self.vision, "ensure_ready", None)
        if prepare is not None:
            ctx.logger.info("Preparing local Qwen-VL model %s",
                            getattr(self.vision, "model", ""))
            try:
                prepare(should_abort=ctx.safety.check)
            except TypeError:
                prepare()

    def _decide(self, ctx: Context, items: List[OcrItem]) -> Dict[str, Any]:
        elements = []
        for index, item in enumerate(items):
            x, y, width, height = item.box
            elements.append({
                "id": index,
                "text": item.text,
                "box": [x, y, width, height],
                "center": [round(item.center[0], 1), round(item.center[1], 1)],
            })
        payload = {
            "goal": self.goal,
            "screen": [ctx.frame.width, ctx.frame.height],
            "elements": elements,
            "history": self.history[-8:],
        }
        image = annotate_frame(ctx.frame, items)
        reply = self.vision.complete_json(
            VISION_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), image)
        kind = str(reply.get("action", "")).strip().lower()
        if kind in ("left_click", "click"):
            reply["action"] = "click"
            reply.setdefault("button", "left")
        elif kind == "right_click":
            reply["action"] = "click"
            reply["button"] = "right"
        elif kind in ("terminate", "finish", "complete", "stop"):
            reply["action"] = "done"
        elif kind in ("scroll_down", "scrolldown", "scroll down"):
            reply["action"] = "scroll"
            reply.setdefault("amount", -3)
        elif kind in ("scroll_up", "scrollup", "scroll up"):
            reply["action"] = "scroll"
            reply.setdefault("amount", 3)
        if reply.get("action") == "click" and "element_id" not in reply:
            coordinate = reply.get("coordinate") or reply.get("point")
            if coordinate is None and "x" in reply and "y" in reply:
                coordinate = [reply.get("x"), reply.get("y")]
            if isinstance(coordinate, (list, tuple)) and len(coordinate) >= 2:
                try:
                    scale = min(1.0, 1600.0 / max(1, ctx.frame.width))
                    px = float(coordinate[0]) / scale
                    py = float(coordinate[1]) / scale
                    nearest = min(
                        range(len(items)),
                        key=lambda index: (items[index].center[0] - px) ** 2
                        + (items[index].center[1] - py) ** 2,
                    )
                    reply["element_id"] = nearest
                    reply["thought"] = (str(reply.get("thought", "")) +
                                        " (coordinate mapped to OCR box)").strip()
                except (TypeError, ValueError):
                    pass
        thought = str(reply.get("thought", "")).strip()
        if thought:
            ctx.logger.info("AI: %s", thought)
        return reply
