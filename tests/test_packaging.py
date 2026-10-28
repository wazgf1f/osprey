"""The installer must follow the package version, not a second hardcoded one."""

from __future__ import annotations

import importlib.util
import pathlib
import unittest

from .helpers import temp_dir

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_build_installer():
    spec = importlib.util.spec_from_file_location(
        "osprey_build_installer", ROOT / "packaging" / "build_installer.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBuildInstaller(unittest.TestCase):
    def test_version_matches_package(self) -> None:
        module = load_build_installer()
        self.assertEqual(module.VERSION, module.package_version())

    def test_shortcut_script_gets_version(self) -> None:
        module = load_build_installer()
        with temp_dir() as folder:
            path = pathlib.Path(folder) / "shortcuts.ps1"
            module.write_utf8_sig(path, 'DisplayVersion "__VERSION__"')
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn(module.VERSION, text)
            self.assertNotIn("__VERSION__", text)

    def test_render_replaces_installer_version(self) -> None:
        module = load_build_installer()
        rendered = module.render_setup_source("9.9.9")
        self.assertIn("Osprey 9.9.9", rendered)
        self.assertIn("版本 9.9.9", rendered)
        self.assertNotIn("0.1.0", rendered)


if __name__ == "__main__":
    unittest.main()
