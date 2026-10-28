"""Declarative click plans.

A plan is a JSON file describing a sequence of steps:

    {
      "name": "daily",
      "threshold": 0.86,
      "timeout": 8,
      "fps": 6,
      "loop": 1,
      "on_missing": "stop",
      "steps": [
        {"action": "click", "template": "assets/accept.png", "wait": 1.0},
        {"action": "wait", "seconds": 2.0},
        {"action": "press", "key": "enter", "wait": 0.5}
      ]
    }

Relative template paths resolve against the plan file's directory, so a plan
and its assets folder can be copied to another machine together.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..errors import ConfigError

ACTIONS = ("click", "move", "wait", "press")
MISSING_POLICIES = ("stop", "skip")


def _require_number(value: Any, name: str, *, minimum: float = 0.0,
                    maximum: Optional[float] = None) -> float:
    if isinstance(value, bool):
        raise ConfigError("%s must be a number, got %r" % (name, value))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("%s must be a number, got %r" % (name, value)) from exc
    if not math.isfinite(number):
        raise ConfigError("%s must be finite, got %r" % (name, value))
    if number < minimum:
        raise ConfigError("%s must be >= %s, got %s" % (name, minimum, number))
    if maximum is not None and number > maximum:
        raise ConfigError("%s must be <= %s, got %s" % (name, maximum, number))
    return number


def _field_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ConfigError("%s must be a number, got %r" % (name, value))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("%s must be a number, got %r" % (name, value)) from exc
    if not math.isfinite(number):
        raise ConfigError("%s must be finite, got %r" % (name, value))
    return number


def _field_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ConfigError("%s must be an integer, got %r" % (name, value))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("%s must be an integer, got %r" % (name, value)) from exc
    if not math.isfinite(number) or number != int(number):
        raise ConfigError("%s must be an integer, got %r" % (name, value))
    return int(number)


def _require_scales(value: Any) -> List[float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)) or not value:
        raise ConfigError("scales must be a non-empty list of positive numbers")
    scales = []
    for item in value:
        scales.append(_require_number(item, "scale", minimum=0.01))
    return scales


@dataclass
class Step:
    action: str
    template: str = ""
    seconds: float = 0.0
    wait: float = 0.0
    key: str = ""
    threshold: Optional[float] = None
    timeout: Optional[float] = None
    scales: Optional[List[float]] = None
    on_missing: Optional[str] = None

    def validate(self, index: int) -> None:
        where = "step %d" % (index + 1)
        if self.action not in ACTIONS:
            raise ConfigError("%s: unknown action %r (use %s)"
                              % (where, self.action, ", ".join(ACTIONS)))
        if self.action in ("click", "move"):
            if not self.template:
                raise ConfigError("%s: %s needs a template" % (where, self.action))
        if self.action == "wait":
            if self.seconds <= 0:
                raise ConfigError("%s: wait needs seconds > 0" % where)
        if self.action == "press":
            if not self.key:
                raise ConfigError("%s: press needs a key name" % where)
            from ..input.win32 import resolve_key

            try:
                resolve_key(self.key)
            except (TypeError, ValueError) as exc:
                raise ConfigError("%s: invalid key %r" % (where, self.key)) from exc
        if self.wait < 0:
            raise ConfigError("%s: wait must not be negative" % where)
        if self.threshold is not None:
            self.threshold = _require_number(self.threshold, where + " threshold",
                                             maximum=1.0)
        if self.timeout is not None:
            self.timeout = _require_number(self.timeout, where + " timeout", minimum=0.01)
        if self.scales is not None:
            self.scales = _require_scales(self.scales)
        if self.on_missing is not None and self.on_missing not in MISSING_POLICIES:
            raise ConfigError("%s: on_missing must be 'stop' or 'skip'" % where)

    def describe_target(self) -> str:
        if self.action in ("click", "move"):
            return os.path.basename(self.template) or "(no template)"
        if self.action == "wait":
            return "%.2f s" % self.seconds
        if self.action == "press":
            return self.key
        return ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"action": self.action}
        if self.template:
            data["template"] = self.template
        if self.seconds:
            data["seconds"] = self.seconds
        if self.wait:
            data["wait"] = self.wait
        if self.key:
            data["key"] = self.key
        if self.threshold is not None:
            data["threshold"] = self.threshold
        if self.timeout is not None:
            data["timeout"] = self.timeout
        if self.scales is not None:
            data["scales"] = list(self.scales)
        if self.on_missing is not None:
            data["on_missing"] = self.on_missing
        return data

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "Step":
        if not isinstance(data, dict):
            raise ConfigError("step %d must be an object" % (index + 1))
        if "action" not in data:
            raise ConfigError("step %d has no action" % (index + 1))
        step = cls(
            action=str(data["action"]),
            template=str(data.get("template", "") or ""),
            seconds=_field_float(data.get("seconds", 0) or 0, "seconds"),
            wait=_field_float(data.get("wait", 0) or 0, "wait"),
            key=str(data.get("key", "") or ""),
            threshold=_field_float(data["threshold"], "threshold")
            if data.get("threshold") is not None else None,
            timeout=_field_float(data["timeout"], "timeout")
            if data.get("timeout") is not None else None,
            scales=data.get("scales"),
            on_missing=data.get("on_missing"),
        )
        step.validate(index)
        return step


@dataclass
class Plan:
    name: str = "plan"
    steps: List[Step] = field(default_factory=list)
    threshold: float = 0.86
    timeout: float = 8.0
    fps: float = 6.0
    loop: int = 1
    on_missing: str = "stop"
    scales: List[float] = field(default_factory=lambda: [1.0])
    base_dir: str = field(default_factory=os.getcwd, repr=False, compare=False)

    def validate(self) -> "Plan":
        if not isinstance(self.name, str):
            raise ConfigError("name must be a string")
        self.threshold = _require_number(self.threshold, "threshold", maximum=1.0)
        self.timeout = _require_number(self.timeout, "timeout", minimum=0.01)
        self.fps = _require_number(self.fps, "fps", minimum=0.1)
        if isinstance(self.loop, bool) or not isinstance(self.loop, int) or self.loop < 0:
            raise ConfigError("loop must be an integer >= 0 (0 means forever)")
        if self.on_missing not in MISSING_POLICIES:
            raise ConfigError("on_missing must be 'stop' or 'skip'")
        self.scales = _require_scales(self.scales)
        for index, step in enumerate(self.steps):
            step.validate(index)
        return self

    def resolve(self, template: str) -> str:
        if os.path.isabs(template):
            return template
        return os.path.abspath(os.path.join(self.base_dir, template))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "threshold": self.threshold,
            "timeout": self.timeout,
            "fps": self.fps,
            "loop": self.loop,
            "on_missing": self.on_missing,
            "scales": list(self.scales),
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Any, *, base_dir: Optional[str] = None) -> "Plan":
        if not isinstance(data, dict):
            raise ConfigError("plan must be a JSON object")
        steps_data = data.get("steps", [])
        if not isinstance(steps_data, list):
            raise ConfigError("steps must be a list")
        plan = cls(
            name=str(data.get("name", "plan")),
            steps=[Step.from_dict(item, index) for index, item in enumerate(steps_data)],
            threshold=_field_float(data.get("threshold", 0.86), "threshold"),
            timeout=_field_float(data.get("timeout", 8.0), "timeout"),
            fps=_field_float(data.get("fps", 6.0), "fps"),
            loop=_field_int(data.get("loop", 1), "loop"),
            on_missing=str(data.get("on_missing", "stop")),
            scales=data.get("scales", [1.0]),
            base_dir=base_dir or os.getcwd(),
        )
        return plan.validate()

    @classmethod
    def load(cls, path: str) -> "Plan":
        if not os.path.exists(path):
            raise ConfigError("plan file not found: %s" % path)
        try:
            # utf-8-sig tolerates the BOM Notepad writes.
            with open(path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ConfigError("invalid JSON in %s: %s" % (path, exc)) from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError("could not read %s: %s" % (path, exc)) from exc
        return cls.from_dict(data, base_dir=os.path.dirname(os.path.abspath(path)))

    def save(self, path: str) -> None:
        self.validate()
        target = os.path.abspath(path)
        folder = os.path.dirname(target)
        if folder:
            os.makedirs(folder, exist_ok=True)

        data = self.to_dict()
        if folder and os.path.abspath(folder) != os.path.abspath(self.base_dir):
            # Relative templates are anchored to the plan file. Saving elsewhere
            # would silently break them, so pin them to absolute paths first.
            for step_data, step in zip(data["steps"], self.steps):
                if (step.action in ("click", "move") and step.template
                        and not os.path.isabs(step.template)):
                    absolute = self.resolve(step.template)
                    step_data["template"] = absolute
                    step.template = absolute

        with open(target, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        self.base_dir = folder
