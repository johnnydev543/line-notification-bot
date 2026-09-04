"""Tests for the chat command framework."""

from line_notification_bot.core import commands


def _reset_registry():
    """Clear registered commands to keep tests isolated."""
    commands._COMMANDS.clear()
    commands._rebuild_help()


def teardown_function():
    _reset_registry()


def test_help_lists_registered_commands():
    commands.init_default_commands()

    def dummy(args, reply_token):
        return "ok"

    commands.register_command("status", "desc", dummy)
    out = commands.handle_user_message("help")
    assert "Line Notification Bot" in out
    assert "status" in out
    assert "help" in out


def test_unknown_command_gets_hint():
    commands.init_default_commands()
    out = commands.handle_user_message("frobnicate")
    assert "收到" in out
    assert "help" in out


def test_handler_exception_returns_error_text():
    commands.init_default_commands()

    def boom(args, reply_token):
        raise RuntimeError("boom")

    commands.register_command("explode", "desc", boom)
    out = commands.handle_user_message("explode")
    assert "explode" in out
    assert "錯誤" in out


def test_empty_message_falls_back_to_help():
    commands.init_default_commands()
    out = commands.handle_user_message("   ")
    assert "Line Notification Bot" in out


def test_command_with_args_receives_remainder():
    commands.init_default_commands()
    seen = {}

    def echo(args, reply_token):
        seen["args"] = args
        return "ok"

    commands.register_command("echo", "desc", echo)
    assert commands.handle_user_message("echo hello world") == "ok"
    assert seen["args"] == "hello world"