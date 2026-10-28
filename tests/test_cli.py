"""Task loading rules for the CLI."""

from __future__ import annotations

import os
import unittest

from osprey.cli import _load_task
from osprey.core.task import Task
from osprey.errors import ConfigError

from .helpers import temp_dir

SINGLE = """
from osprey.core.task import Task


class Only(Task):
    name = "only"

    def step(self, ctx):
        pass
"""

MULTIPLE = SINGLE + """

class Second(Task):
    name = "second"
"""

EXPLICIT = SINGLE + """

TASK = Only()
"""

FACTORY = SINGLE + """

def create_task():
    return Only()
"""

NOTHING = """
value = 42
"""


class TestLoadTask(unittest.TestCase):
    def _load(self, source: str) -> Task:
        with temp_dir() as folder:
            path = os.path.join(folder, "task_module.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(source)
            return _load_task(path)

    def test_single_class_is_autodetected(self) -> None:
        task = self._load(SINGLE)
        self.assertEqual(task.name, "only")

    def test_explicit_task_instance(self) -> None:
        task = self._load(EXPLICIT)
        self.assertEqual(task.name, "only")

    def test_factory_wins(self) -> None:
        task = self._load(FACTORY)
        self.assertEqual(task.name, "only")

    def test_multiple_classes_require_explicit_choice(self) -> None:
        with self.assertRaises(ConfigError):
            self._load(MULTIPLE)

    def test_no_task_raises(self) -> None:
        with self.assertRaises(ConfigError):
            self._load(NOTHING)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ConfigError):
            _load_task("definitely-not-here.py")

    def test_task_can_import_a_sibling_module(self) -> None:
        with temp_dir() as folder:
            with open(os.path.join(folder, "helper.py"), "w", encoding="utf-8") as handle:
                handle.write("VALUE = 7\n")
            path = os.path.join(folder, "task_module.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "from helper import VALUE\n"
                    "from osprey.core.task import Task\n\n\n"
                    "class Sibling(Task):\n"
                    "    name = 'sibling-%d' % VALUE\n\n"
                    "    def step(self, ctx):\n"
                    "        pass\n"
                )
            task = _load_task(path)
        self.assertEqual(task.name, "sibling-7")

    def test_broken_import_raises_config_error(self) -> None:
        with temp_dir() as folder:
            path = os.path.join(folder, "broken.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("import module_that_does_not_exist_12345\n")
            with self.assertRaises(ConfigError):
                _load_task(path)


if __name__ == "__main__":
    unittest.main()
