"""The editor builds and manipulates its step list (Windows only)."""

from __future__ import annotations

import logging
import sys
import unittest

from osprey.core.plan import Step

from .helpers import temp_dir


@unittest.skipUnless(sys.platform == "win32", "GUI smoke test runs on Windows")
class TestGuiSmoke(unittest.TestCase):
    def test_editor_builds_and_refreshes(self) -> None:
        import tkinter as tk

        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            editor.root.update()
            self.assertEqual(editor.steps, [])
            editor.steps.append(Step("wait", seconds=1.0))
            editor.steps.append(Step("press", key="enter"))
            editor._refresh()
            self.assertEqual(len(editor.tree.get_children()), 2)

            editor._collect()
            editor.threshold_var.set("nope")
            with self.assertRaises(Exception):
                editor._collect()
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()

    def test_capture_failure_restores_window(self) -> None:
        import tkinter as tk
        from unittest import mock

        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            with mock.patch("osprey.gui.GdiGrabber", side_effect=RuntimeError("no gdi")):
                with mock.patch("osprey.gui.messagebox.showerror") as show:
                    result = editor._capture_template()
            self.assertIsNone(result)
            self.assertTrue(show.called)
            self.assertNotEqual(editor.root.state(), "withdrawn")
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()

    def test_store_template_does_not_overwrite(self) -> None:
        import os
        import tkinter as tk

        import numpy as np

        from osprey.capture.base import Frame
        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            frame = Frame(np.zeros((40, 40, 4), dtype=np.uint8))
            with temp_dir() as folder:
                editor.base_dir = folder
                first = editor._store_template(frame, 0, 0, 10, 10)
                second = editor._store_template(frame, 0, 0, 10, 10)
                self.assertIsNotNone(first)
                self.assertIsNotNone(second)
                self.assertNotEqual(first, second)
                self.assertTrue(os.path.exists(first))
                self.assertTrue(os.path.exists(second))
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()

    def test_store_template_reports_write_failure(self) -> None:
        import tkinter as tk
        from unittest import mock

        import numpy as np

        from osprey.capture.base import Frame
        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            frame = Frame(np.zeros((40, 40, 4), dtype=np.uint8))
            with mock.patch("osprey.gui.save_image", side_effect=OSError("denied")):
                with mock.patch("osprey.gui.messagebox.showerror") as show:
                    result = editor._store_template(frame, 0, 0, 10, 10)
            self.assertIsNone(result)
            self.assertTrue(show.called)
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()

    def test_editing_is_locked_while_running(self) -> None:
        import tkinter as tk

        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            editor._running = True
            editor._set_running_buttons()
            before = list(editor.steps)
            editor._add_wait()
            self.assertEqual(editor.steps, before)
            self.assertEqual(str(editor.capture_button["state"]), "disabled")
            editor._running = False
            editor._set_running_buttons()
            editor._add_wait()
            self.assertEqual(len(editor.steps), len(before) + 1)
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()

    def test_stop_before_ready_is_remembered(self) -> None:
        import tkinter as tk

        from osprey.core.safety import Safety
        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            editor._stop()
            self.assertTrue(editor._stop_requested)
            safety = Safety(abort_keys=())
            ctx = type("Ctx", (), {"safety": safety, "input": None})()
            editor._on_ready(ctx)
            self.assertTrue(safety.aborted)
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()


if __name__ == "__main__":
    unittest.main()
