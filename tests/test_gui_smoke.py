"""The editor builds and manipulates its step list (Windows only)."""

from __future__ import annotations

import logging
import sys
import unittest

from osprey.core.plan import Step


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


if __name__ == "__main__":
    unittest.main()
