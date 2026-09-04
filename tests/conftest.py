"""Shared pytest fixtures for line-notification-bot tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the repo root is on sys.path when running pytest from anywhere.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def flask_app(monkeypatch):
    """Import the Flask app with LINE disabled so no real API calls happen."""
    monkeypatch.setenv("LINE_TARGET_IDS", "U123TEST")
    monkeypatch.setenv("NOTIFY_SECRET", "")
    # Re-import config to pick up env, then the app module (which triggers
    # _initialize()). The package imports are cached across tests, so reset
    # the singletons deterministically instead.
    import app as app_module
    from line_notification_bot.core import commands, line_client
    from line_notification_bot.core.config import config
    from line_notification_bot.integrations import registry

    config.line_channel_access_token = ""
    config.line_channel_secret = ""
    config.target_ids = ["U123TEST"]
    config.notify_secret = ""
    config.enabled_integrations = []
    if not registry.all_integrations():
        commands.init_default_commands()
        registry.load_integrations()

    app_module.app.config["TESTING"] = True
    return app_module


@pytest.fixture()
def client(flask_app):
    return flask_app.app.test_client()


@pytest.fixture()
def configured(flask_app):
    """App with LINE configured and the push call stubbed out."""
    from line_notification_bot.core.config import config
    from line_notification_bot.core import line_client

    config.line_channel_access_token = "test-token"
    config.line_channel_secret = "test-secret"
    config.target_ids = ["U123TEST"]
    sent: list[tuple[str, list[dict]]] = []

    def fake_push(to, messages):
        sent.append((to, messages))
        return True

    line_client.line_client.push = fake_push
    return flask_app, sent