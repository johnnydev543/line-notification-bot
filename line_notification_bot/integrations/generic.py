"""Generic webhook integration for any JSON payload.

Provides a universal fallback so the bot is *not* tied to Grafana/Prometheus:

* ``/webhook/generic`` — accepts any JSON and posts a compact summary to LINE.
* A simple text format: ``{"text": "hello"}`` posts exactly ``hello``.

This is the reference for writing your own integration: accept a payload,
return message objects, optionally register commands.
"""

from __future__ import annotations

import json
import logging

from ..core.commands import register_command
from .registry import IntegrationResult

logger = logging.getLogger("line_notification_bot.integrations.generic")

MAX_SUMMARY_KEYS = 10
MAX_VALUE_LENGTH = 120


def _truncate(value, limit: int = MAX_VALUE_LENGTH) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_generic_payload(payload: dict) -> str:
    """Turn an arbitrary JSON payload into a readable multi-line summary."""
    # Simplest contract: {"text": "..."} → send that text as-is.
    if isinstance(payload.get("text"), str) and payload["text"].strip():
        return payload["text"]

    title = payload.get("title") or payload.get("message") or "📢 通知"

    lines = [f"📢 {_truncate(title, 200)}", ""]

    # Render remaining key/value pairs in a compact table-ish form.
    shown = 0
    for key, value in payload.items():
        if key in ("text", "title", "message") or shown >= MAX_SUMMARY_KEYS:
            continue
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = value
        lines.append(f"{key}: {_truncate(rendered)}")
        shown += 1

    if shown == 0:
        lines.append(json.dumps(payload, ensure_ascii=False)[:800])

    return "\n".join(lines)


class GenericIntegration:
    name = "generic"

    def format_payload(self, payload: dict) -> IntegrationResult:
        text = format_generic_payload(payload)
        return IntegrationResult(ok=True, messages=[{"type": "text", "text": text}])

    def register_commands(self) -> None:
        register_command("ping", "測試 bot 是否存活", _cmd_ping)


def _cmd_ping(_args: str, _reply_token: str | None) -> str:
    return "pong 🏓"


integration = GenericIntegration()