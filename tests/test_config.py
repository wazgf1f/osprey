"""Configuration loading and validation."""

from __future__ import annotations

import json
import os
import unittest

from .helpers import temp_dir

from osprey.core.config import DEFAULTS, load_config, resolve_asset, validate_config
from osprey.errors import ConfigError


class TestConfig(unittest.TestCase):
    def test_defaults_are_complete(self) -> None:
        config = load_config()
        for key, value in DEFAULTS.items():
            self.assertEqual(config[key], value)
        self.assertTrue(config["dry_run"])

    def test_file_overrides_and_merges(self) -> None:
        with temp_dir() as folder:
            path = os.path.join(folder, "task.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"threshold": 0.5, "scales": [1.0, 1.25], "my_key": {"a": 1}}, handle)
            config = load_config(path)
        self.assertEqual(config["threshold"], 0.5)
        self.assertEqual(config["scales"], [1.0, 1.25])
        self.assertEqual(config["my_key"], {"a": 1})
        self.assertEqual(config["fps"], DEFAULTS["fps"])

    def test_explicit_overrides_win(self) -> None:
        config = load_config(overrides={"threshold": 0.9, "fps": 20})
        self.assertEqual(config["threshold"], 0.9)
        self.assertEqual(config["fps"], 20)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ConfigError):
            load_config("does-not-exist.json")

    def test_bom_json_is_accepted(self) -> None:
        with temp_dir() as folder:
            path = os.path.join(folder, "config.json")
            with open(path, "w", encoding="utf-8-sig") as handle:
                json.dump({"threshold": 0.5}, handle)
            config = load_config(path)
            self.assertEqual(config["threshold"], 0.5)

    def test_bad_json_raises(self) -> None:
        with temp_dir() as folder:
            path = os.path.join(folder, "bad.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{nope")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_invalid_values_raise(self) -> None:
        cases = [
            {"threshold": 1.5},
            {"threshold": "high"},
            {"threshold": True},
            {"scales": []},
            {"scales": "1.0"},
            {"scales": [1.0, -0.5]},
            {"fps": 0},
            {"fps": float("nan")},
            {"speed": 0},
            {"scales": [float("inf")]},
            {"threshold": float("nan")},
            {"dry_run": "yes"},
            {"abort_keys": [1, 2]},
            {"max_runtime": -1},
            {"move_mode": "teleport"},
            {"all_screens": "yes"},
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    validate_config(case)

    def test_string_abort_key_is_promoted_to_list(self) -> None:
        config = validate_config({"abort_keys": "f11"})
        self.assertEqual(config["abort_keys"], ["f11"])

    def test_resolve_asset_uses_assets_dir(self) -> None:
        config = {"assets_dir": os.path.join("some", "dir")}
        resolved = resolve_asset(config, "button.png")
        self.assertTrue(os.path.isabs(resolved))
        self.assertTrue(resolved.endswith(os.path.join("some", "dir", "button.png")))
        absolute = os.path.abspath("C:/icons/x.png") if os.name == "nt" else "/icons/x.png"
        self.assertEqual(resolve_asset(config, absolute), absolute)


if __name__ == "__main__":
    unittest.main()
