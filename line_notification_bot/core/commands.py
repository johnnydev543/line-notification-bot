"""Command framework for bidirectional chat interaction.

Users send text commands in LINE; the bot dispatches them to a registry of
handlers. Core provides generic commands (``help``), and integrations may
register their own commands (e.g. monitoring's ``status`` / ``alerts``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .line_client import line_client

logger = logging.getLogger("line_notification_bot")

# Handler signature: (arg_string, reply_token or None) -> response text
Handler = Callable[[str, str | None], str]

_COMMANDS: dict[str, Handler] = {}
_HELP_TEXT: str = ""


def register_command(name: str, description: str, handler: Handler) -> None:
    """Register a chat command. Later registrations with the same name win."""
    _COMMANDS[name.lower().strip()] = handler
    _rebuild_help()


def _rebuild_help() -> None:
    global _HELP_TEXT
    if not _COMMANDS:
        _HELP_TEXT = ""
        return
    lines = ["🤖 Line Notification Bot — 指令:"]
    lines.append("  help    — 顯示此說明")
    for name, _handler in sorted(_COMMANDS.items()):
        if name == "help":
            continue
        lines.append(f"  {name}")
    _HELP_TEXT = "\n".join(lines)


def _builtin_help(_args: str, _reply_token: str | None) -> str:
    if _HELP_TEXT:
        return _HELP_TEXT
    return "🤖 Line Notification Bot\n目前沒有可用指令。"


def get_commands() -> dict[str, Handler]:
    """Return the command registry (read-only copy)."""
    return dict(_COMMANDS)


def init_default_commands() -> None:
    """Register the built-in ``help`` command. Call once at startup."""
    register_command("help", "顯示可用指令", _builtin_help)


def handle_user_message(text: str, reply_token: str | None = None) -> str:
    """Dispatch a user chat message to the matching command handler."""
    text = text.strip()
    lowered = text.lower()

    if not lowered:
        return _builtin_help("", reply_token)

    parts = lowered.split(maxsplit=1)
    name = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    handler = _COMMANDS.get(name)
    if handler is None:
        return (
            f"收到: 「{text[:100]}」\n"
            "輸入 help 查看可用指令"
        )

    try:
        return handler(args, reply_token)
    except Exception:  # noqa: BLE001
        logger.exception("Command %r raised an exception", name)
        return f"❌ 執行指令 '{name}' 時發生錯誤，請稍後再試"


def dispatch_and_reply(text: str, reply_token: str, fallback_user_id: str | None = None) -> None:
    """Handle a message and send the response via Reply (preferred) or Push."""
    response = handle_user_message(text, reply_token)
    sent = line_client.reply_text(reply_token, response)
    if not sent and fallback_user_id:
        line_client.push_text(fallback_user_id, response)