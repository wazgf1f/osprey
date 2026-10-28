"""Task API: the unit of automation.

A task owns the decision logic. The engine owns capture, timing, safety and
teardown, and calls the task once per tick:

    setup(ctx) -> [step(ctx) -> step(ctx) -> ...] -> teardown(ctx)

Everything a task needs (current frame, detector, input, config) hangs off
the Context, so tasks stay small and testable.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class Task:
    """Base class for automation tasks."""

    name: str = "task"

    def setup(self, ctx) -> None:
        """Called once before the loop; acquire resources, reset state."""

    def step(self, ctx) -> None:
        """Called once per frame. Raise Aborted (or return) to stop."""
        raise NotImplementedError

    def teardown(self, ctx) -> None:
        """Called once after the loop, including on errors."""


class FunctionTask(Task):
    """Wrap a plain function as a task, for one-off experiments."""

    def __init__(self, func: Callable, name: Optional[str] = None) -> None:
        self.func = func
        self.name = name or getattr(func, "__name__", "function")

    def step(self, ctx) -> None:
        self.func(ctx)


class StateMachine:
    """Small explicit state machine for multi-step tasks.

    Each state has an optional on_enter, on_tick and on_exit. on_tick may
    return the name of the next state; anything else keeps the current state.
    """

    def __init__(self, initial: str, *, name: str = "state_machine") -> None:
        self.name = name
        self.current = initial
        self._states: Dict[str, dict] = {}
        self._started = False

    def add(
        self,
        state: str,
        *,
        on_enter: Optional[Callable] = None,
        on_tick: Optional[Callable] = None,
        on_exit: Optional[Callable] = None,
    ) -> "StateMachine":
        if not state:
            raise ValueError("state name must not be empty")
        self._states[state] = {"on_enter": on_enter, "on_tick": on_tick, "on_exit": on_exit}
        return self

    def __contains__(self, state: str) -> bool:
        return state in self._states

    def start(self, ctx) -> None:
        if self.current not in self._states:
            raise KeyError("initial state %r was never added" % (self.current,))
        self._started = True
        self._run_hook(self.current, "on_enter", ctx)

    def goto(self, ctx, state: str) -> None:
        if state not in self._states:
            raise KeyError("unknown state %r" % (state,))
        if state == self.current:
            return
        self._run_hook(self.current, "on_exit", ctx)
        previous, self.current = self.current, state
        logger.debug("%s: %s -> %s", self.name, previous, state)
        self._run_hook(state, "on_enter", ctx)

    def step(self, ctx) -> None:
        if not self._started:
            self.start(ctx)
        if self.current not in self._states:
            raise KeyError("state %r disappeared" % (self.current,))
        hook = self._states[self.current]["on_tick"]
        if hook is None:
            return
        next_state = hook(ctx)
        if isinstance(next_state, str) and next_state != self.current:
            self.goto(ctx, next_state)

    def _run_hook(self, state: str, hook: str, ctx) -> None:
        callback = self._states[state][hook]
        if callback is not None:
            callback(ctx)

    def __repr__(self) -> str:
        return "StateMachine(name=%r, current=%r, states=%r)" % (
            self.name, self.current, sorted(self._states),
        )
