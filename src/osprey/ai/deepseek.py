"""Minimal DeepSeek chat client using only the standard library."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

FENCE = chr(96) * 3


class DeepSeekError(RuntimeError):
    pass


def parse_json_reply(content: str) -> Dict[str, Any]:
    """Extract a JSON object from a reply, tolerating Markdown fences."""
    text = (content or "").strip()
    if text.startswith(FENCE):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == FENCE:
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise DeepSeekError("model did not return a JSON object: %r" % (content,))
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise DeepSeekError("invalid JSON from model: %s" % exc) from exc
    if not isinstance(value, dict):
        raise DeepSeekError("model returned %s, expected an object" % type(value).__name__)
    return value


class DeepSeekClient:
    def __init__(self, api_key: Optional[str] = None, *, model: Optional[str] = None,
                 base_url: Optional[str] = None, timeout: float = 45.0) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise DeepSeekError("DEEPSEEK_API_KEY is not set")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.base_url = (base_url or os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.timeout = float(timeout)

    def complete_json(self, system: str, user: str) -> Dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:800]
            raise DeepSeekError("DeepSeek HTTP %d: %s" % (exc.code, detail)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeepSeekError("DeepSeek request failed: %s" % exc) from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError("unexpected DeepSeek response: %r" % (data,)) from exc
        return parse_json_reply(content)
