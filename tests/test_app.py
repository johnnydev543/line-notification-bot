"""Tests for Flask endpoints (notify, webhooks, callback, health)."""

import base64
import hashlib
import hmac
import json


def _sign(body: bytes, secret: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()


# ---------------------------------------------------------------------------
# /health & /integrations
# ---------------------------------------------------------------------------
def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "line_configured" in data
    assert data["target_ids_count"] == 1


def test_integrations_lists_loaded(client):
    resp = client.get("/integrations")
    assert resp.status_code == 200
    names = {item["name"] for item in resp.get_json()["integrations"]}
    assert {"generic", "monitoring"} <= names
    assert "/webhook/generic" in {i["webhook"] for i in resp.get_json()["integrations"]}


# ---------------------------------------------------------------------------
# /webhook/<name>
# ---------------------------------------------------------------------------
def test_unknown_integration_returns_404(client):
    resp = client.post("/webhook/nope", json={"a": 1})
    assert resp.status_code == 404
    assert "unknown integration" in resp.get_json()["error"]


def test_monitoring_webhook_requires_line_config(client):
    resp = client.post("/webhook/monitoring", json={"status": "firing", "alerts": []})
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "LINE not configured"


def test_monitoring_webhook_pushes_when_configured(configured):
    app, sent = configured
    client = app.app.test_client()
    resp = client.post("/webhook/monitoring", json={
        "status": "firing",
        "alerts": [{"status": "firing", "labels": {"alertname": "T"}}],
        "commonLabels": {"alertname": "T"},
    })
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "sent", "targets": 1}
    assert len(sent) == 1
    to, messages = sent[0]
    assert to == "U123TEST"
    assert messages[0]["type"] == "text"
    assert "Grafana Alert: T" in messages[0]["text"]


def test_webhook_rejects_invalid_json(client):
    resp = client.post(
        "/webhook/monitoring",
        data="not json",
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_legacy_push_routes_to_monitoring(configured):
    """The deprecated /push alias still feeds the monitoring integration."""
    app, sent = configured
    client = app.app.test_client()
    resp = client.post("/push", json={
        "status": "firing",
        "alerts": [{"status": "firing", "labels": {"alertname": "Legacy"}}],
        "commonLabels": {"alertname": "Legacy"},
    })
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "sent", "targets": 1}
    assert "Grafana Alert: Legacy" in sent[0][1][0]["text"]


def test_legacy_push_rejects_invalid_json(client):
    resp = client.post("/push", data="not json", content_type="application/json")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /notify (generic)
# ---------------------------------------------------------------------------
def test_notify_open_when_no_secret(configured):
    app, sent = configured
    client = app.app.test_client()
    resp = client.post("/notify", json={"text": "hello"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "sent"
    assert sent[0][1][0]["text"] == "hello"


def test_notify_requires_bearer_when_secret_set(configured):
    app, sent = configured
    from line_notification_bot.core.config import config

    config.notify_secret = "s3cret"
    client = app.app.test_client()
    assert client.post("/notify", json={"text": "x"}).status_code == 401
    wrong = client.post(
        "/notify",
        json={"text": "x"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401
    right = client.post(
        "/notify",
        json={"text": "x"},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert right.status_code == 200
    assert len(sent) == 1


def test_notify_rejects_invalid_json(client):
    resp = client.post("/notify", data="not json", content_type="application/json")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /callback (LINE webhook)
# ---------------------------------------------------------------------------
def test_callback_rejects_bad_signature(flask_app):
    from line_notification_bot.core.config import config

    config.line_channel_secret = "test-secret"
    client = flask_app.app.test_client()
    resp = client.post(
        "/callback",
        data=b"{}",
        headers={"X-Line-Signature": "invalid"},
    )
    assert resp.status_code == 401


def test_callback_rejects_when_secret_unset(flask_app):
    from line_notification_bot.core.config import config

    config.line_channel_secret = ""
    client = flask_app.app.test_client()
    resp = client.post(
        "/callback",
        data=b"{}",
        headers={"X-Line-Signature": _sign(b"{}", "whatever")},
    )
    assert resp.status_code == 401


def test_callback_valid_signature_replies(configured):
    """A valid signed text message goes through the command dispatcher."""
    from line_notification_bot.core.config import config
    from line_notification_bot.core import commands, line_client

    app, _sent = configured
    config.line_channel_secret = "test-secret"
    replies: list[str] = []
    line_client.line_client.reply_text = lambda token, text: replies.append(text) or True

    event = {
        "events": [
            {
                "type": "message",
                "replyToken": "reply-token-1",
                "source": {"userId": "U123TEST"},
                "message": {"type": "text", "text": "ping"},
            }
        ]
    }
    body = json.dumps(event).encode()
    client = app.app.test_client()
    resp = client.post(
        "/callback",
        data=body,
        headers={"X-Line-Signature": _sign(body, "test-secret")},
    )
    assert resp.status_code == 200
    assert resp.data == b"OK"
    assert replies and replies[0] == "pong 🏓"


def test_callback_non_text_events_ignored(configured):
    from line_notification_bot.core.config import config

    app, _sent = configured
    config.line_channel_secret = "test-secret"
    event = {"events": [{"type": "follow", "replyToken": "rt"}]}
    body = json.dumps(event).encode()
    client = app.app.test_client()
    resp = client.post(
        "/callback",
        data=body,
        headers={"X-Line-Signature": _sign(body, "test-secret")},
    )
    assert resp.status_code == 200


def test_callback_invalid_json_400(flask_app):
    from line_notification_bot.core.config import config

    config.line_channel_secret = "test-secret"
    client = flask_app.app.test_client()
    body = b"not json"
    resp = client.post(
        "/callback",
        data=body,
        headers={"X-Line-Signature": _sign(body, "test-secret")},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# LineClient unit tests
# ---------------------------------------------------------------------------
def test_split_text_within_limit():
    from line_notification_bot.core.line_client import LineClient

    assert LineClient._split_text("hello", 10) == ["hello"]


def test_split_text_over_limit():
    from line_notification_bot.core.line_client import LineClient

    chunks = LineClient._split_text("x" * 25, 10)
    assert [len(c) for c in chunks] == [10, 10, 5]


def test_verify_signature_roundtrip():
    from line_notification_bot.core.line_client import LineClient

    lc = LineClient(channel_access_token="t", channel_secret="s")
    body = b'{"events":[]}'
    assert lc.verify_signature(body, _sign(body, "s"))
    assert not lc.verify_signature(body, "bad")


def test_verify_signature_requires_secret():
    from line_notification_bot.core.line_client import LineClient

    lc = LineClient(channel_access_token="t", channel_secret="")
    assert not lc.verify_signature(b"x", "sig")