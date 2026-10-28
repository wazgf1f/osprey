"""JSON configuration with defaults and validation.

Tasks can define their own keys; only the built-in keys are type checked, so a
config file stays a plain dict that is easy to pass around.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
from typing import Any, Dict, Mapping, Optional

from ..errors import ConfigError

logger = logging.getLogger(__name__)

DEFAULTS: Dict[str, Any] = {
    "threshold": 0.82,
    "scales": [1.0],
    "nms_iou": 0.3,
    "assets_dir": ".",
    "fps": 8.0,
    "dry_run": True,
    "abort_keys": ["f12"],
    "stop_file": None,
    "max_runtime": None,
    "speed": 1.0,
    "move_mode": "absolute",
    "all_screens": False,
}


def _merge(base: Dict[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge(dict(merged[key]), value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def validate_config(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Check the built-in keys and return a normalised copy."""
    config = dict(data)

    if "threshold" in config:
        value = config["threshold"]
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0):
            raise ConfigError("threshold must be a number within [0, 1], got %r" % (value,))
        config["threshold"] = float(value)

    if "nms_iou" in config:
        value = config["nms_iou"]
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0):
            raise ConfigError("nms_iou must be a number within [0, 1], got %r" % (value,))
        config["nms_iou"] = float(value)

    if "scales" in config:
        values = config["scales"]
        if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)) or not values:
            raise ConfigError("scales must be a non-empty list of positive numbers")
        cleaned = []
        for scale in values:
            if (not isinstance(scale, (int, float)) or isinstance(scale, bool)
                    or not math.isfinite(float(scale)) or float(scale) <= 0):
                raise ConfigError("scales must contain positive numbers, got %r" % (scale,))
            cleaned.append(float(scale))
        config["scales"] = cleaned

    if "fps" in config:
        value = config["fps"]
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(float(value)) or float(value) <= 0):
            raise ConfigError("fps must be a positive number, got %r" % (value,))
        config["fps"] = float(value)

    if "speed" in config:
        value = config["speed"]
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(float(value)) or float(value) <= 0):
            raise ConfigError("speed must be a positive number, got %r" % (value,))
        config["speed"] = float(value)

    if "dry_run" in config and not isinstance(config["dry_run"], bool):
        raise ConfigError("dry_run must be true or false, got %r" % (config["dry_run"],))

    if "abort_keys" in config:
        keys = config["abort_keys"]
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, (list, tuple)) or not all(isinstance(k, str) for k in keys):
            raise ConfigError("abort_keys must be a list of key names")
        config["abort_keys"] = list(keys)

    if config.get("max_runtime") is not None:
        value = config["max_runtime"]
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(float(value)) or float(value) <= 0):
            raise ConfigError("max_runtime must be a positive number of seconds or null")
        config["max_runtime"] = float(value)

    if config.get("stop_file") is not None and not isinstance(config["stop_file"], str):
        raise ConfigError("stop_file must be a path string or null")

    if "move_mode" in config and config["move_mode"] not in ("absolute", "relative"):
        raise ConfigError("move_mode must be 'absolute' or 'relative'")

    if "all_screens" in config and not isinstance(config["all_screens"], bool):
        raise ConfigError("all_screens must be true or false")

    if "assets_dir" in config and not isinstance(config["assets_dir"], str):
        raise ConfigError("assets_dir must be a directory path")

    return config


def load_config(path: Optional[str] = None, overrides: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Load defaults, then a JSON file, then explicit overrides."""
    data: Dict[str, Any] = copy.deepcopy(DEFAULTS)
    if path:
        if not os.path.exists(path):
            raise ConfigError("config file not found: %s" % path)
        try:
            # utf-8-sig tolerates the BOM Notepad writes.
            with open(path, "r", encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ConfigError("invalid JSON in %s: %s" % (path, exc)) from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError("could not read %s: %s" % (path, exc)) from exc
        if not isinstance(loaded, dict):
            raise ConfigError("config file must contain a JSON object")
        data = _merge(data, loaded)

    if overrides:
        data = _merge(data, {k: v for k, v in overrides.items() if v is not None})

    unknown = set(data) - set(DEFAULTS)
    if unknown:
        logger.debug("custom config keys: %s", ", ".join(sorted(unknown)))
    return validate_config(data)


def resolve_asset(config: Mapping[str, Any], path: str) -> str:
    """Resolve a template path against assets_dir when it is relative."""
    if os.path.isabs(path):
        return path
    base = str(config.get("assets_dir") or ".")
    return os.path.abspath(os.path.join(base, path))
