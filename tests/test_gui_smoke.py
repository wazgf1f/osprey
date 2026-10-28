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

    def test_window_geometry_always_fits_screen(self) -> None:
        from osprey.gui import _window_geometry

        for screen_w, screen_h in ((2560, 1600), (1920, 1080), (1366, 768),
                                   (1024, 600), (800, 600), (640, 480)):
            with self.subTest(screen=(screen_w, screen_h)):
                width, height = _window_geometry(screen_w, screen_h)
                self.assertLessEqual(width, screen_w)
                self.assertLessEqual(height, screen_h)
                self.assertGreaterEqual(width, 320)
                self.assertGreaterEqual(height, 240)

        self.assertEqual(_window_geometry(2560, 1600), (1320, 880))
        self.assertEqual(_window_geometry(800, 600), (720, 560))

    def test_capture_failure_restores_window(self) -> None:
        import tkinter as tk
        from unittest import mock

        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            with mock.patch("osprey.gui.GdiGrabber", side_effect=RuntimeError("no gdi")) as grabber_cls:
                with mock.patch("osprey.gui.messagebox.showerror") as show:
                    result = editor._capture_template()
            self.assertTrue(grabber_cls.call_args.kwargs.get("full_desktop"))
            self.assertIsNone(result)
            self.assertTrue(show.called)
            self.assertNotEqual(editor.root.state(), "withdrawn")
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()

    def test_capture_overlay_handles_negative_origin(self) -> None:
        import tkinter as tk

        import numpy as np

        from osprey.capture.base import Frame
        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            overlay = tk.Toplevel(editor.root)
            overlay.overrideredirect(True)
            frame = Frame(np.zeros((40, 60, 4), dtype=np.uint8), origin=(-100, 50))
            editor._place_capture_overlay(overlay, frame)
            overlay.update_idletasks()
            self.assertEqual(overlay.winfo_width(), 60)
            self.assertEqual(overlay.winfo_height(), 40)
            overlay.destroy()
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

    def test_duplicate_selected_step(self) -> None:
        import tkinter as tk

        from osprey.core.plan import Step
        from osprey.gui import PlanEditor

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            original = Step("click", template="a.png", wait=1.5,
                            threshold=0.9, scales=[1.0, 1.25])
            editor.steps = [original, Step("wait", seconds=2.0)]
            editor._refresh()
            editor.tree.selection_set("0")
            editor._duplicate_selected()
            self.assertEqual(len(editor.steps), 3)
            duplicate = editor.steps[1]
            self.assertIsNot(duplicate, original)
            self.assertEqual(duplicate.template, "a.png")
            self.assertEqual(duplicate.wait, 1.5)
            self.assertEqual(duplicate.threshold, 0.9)
            self.assertEqual(duplicate.scales, [1.0, 1.25])
            duplicate.scales.append(1.5)
            self.assertEqual(original.scales, [1.0, 1.25])
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()

    def test_step_dialog_keeps_drag_fields(self) -> None:
        import tkinter as tk

        from osprey.core.plan import Step
        from osprey.gui import PlanEditor, StepDialog

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            step = Step("drag", start=(10, 20), end=(300, 400),
                        duration=0.6, button="right")
            dialog = StepDialog(editor.root, step)
            dialog._ok()
            self.assertIsNotNone(dialog.value)
            self.assertEqual(dialog.value.start, (10, 20))
            self.assertEqual(dialog.value.end, (300, 400))
            self.assertEqual(dialog.value.duration, 0.6)
            self.assertEqual(dialog.value.button, "right")
        finally:
            logging.getLogger("osprey").removeHandler(editor._log_handler)
            editor.root.destroy()

    def test_step_dialog_keeps_scales(self) -> None:
        import tkinter as tk

        from osprey.gui import PlanEditor, StepDialog

        try:
            editor = PlanEditor()
        except tk.TclError as exc:  # pragma: no cover - headless session
            self.skipTest("no display available: %s" % exc)

        try:
            step = Step("click", template="a.png", scales=[1.0, 1.25])
            dialog = StepDialog(editor.root, step)
            dialog._ok()
            self.assertIsNotNone(dialog.value)
            self.assertEqual(dialog.value.scales, [1.0, 1.25])
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
