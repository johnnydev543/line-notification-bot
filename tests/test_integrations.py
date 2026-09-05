"""Tests for integration formatting + registry auto-discovery."""

from line_notification_bot.integrations.generic import format_generic_payload
from line_notification_bot.integrations.monitoring import (
    extract_link,
    format_grafana_alert,
)


GRAFANA_PAYLOAD = {
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighCPU", "instance": "web-1"},
            "valueString": "96.4% > 90%",
            "panelURL": "http://grafana.example.com/d/xyz?panel=7",
            "dashboardURL": "http://grafana.example.com/d/xyz",
            "generatorURL": "http://grafana.example.com/alerting/abc/edit",
        },
        {"status": "resolved", "labels": {"alertname": "DiskFull", "instance": "db-1"}},
    ],
    "commonLabels": {"alertname": "HighCPU", "severity": "warning"},
    "externalURL": "http://grafana.example.com/",
}


def test_grafana_format_firing():
    text = format_grafana_alert(GRAFANA_PAYLOAD)
    assert "Grafana Alert: HighCPU" in text
    assert "Severity: warning" in text
    assert "Firing: 1 | Resolved: 1" in text
    assert "HighCPU（96.4% > 90%）" in text
    assert "DiskFull (db-1)" in text


def test_grafana_link_prefers_panel_then_dashboard_then_generator():
    assert extract_link(GRAFANA_PAYLOAD) == "http://grafana.example.com/d/xyz?panel=7"

    no_panel = {
        "alerts": [{"dashboardURL": "http://g.example/d/x", "generatorURL": "http://g.example/a/e"}],
    }
    assert extract_link(no_panel) == "http://g.example/d/x"

    no_dash = {"alerts": [{"generatorURL": "http://g.example/a/e"}]}
    assert extract_link(no_dash) == "http://g.example/a/e"

    # Falls back to externalURL when alerts have no links at all.
    assert extract_link({"externalURL": "http://g.example/"}) == "http://g.example/"
    assert extract_link({}) == ""


def test_grafana_format_resolved():
    payload = dict(GRAFANA_PAYLOAD, status="resolved")
    text = format_grafana_alert(payload)
    assert "✅" in text
    assert "Status: resolved" in text


def test_grafana_preformatted_text_passthrough():
    """A custom payload with a `text` field is sent to LINE verbatim.

    The layout, source label and domains are owned by the Grafana template;
    the bot must not touch the content (not even URL rewriting).
    """
    body = "🔥 Prod | Grafana Alert: X\n\n🔗 https://grafana.prod.example/alerting/list"
    assert format_grafana_alert({"text": body}) == body
    # Whitespace-only text is ignored and falls back to formatting.
    fallback = format_grafana_alert({"text": "   ", **GRAFANA_PAYLOAD})
    assert "Grafana Alert: HighCPU" in fallback


def test_grafana_truncates_long_alert_lists():
    payload = dict(
        GRAFANA_PAYLOAD,
        alerts=[
            {"status": "firing", "labels": {"alertname": f"A{i}"}}
            for i in range(8)
        ],
    )
    text = format_grafana_alert(payload)
    assert "還有 3 個" in text


def test_generic_text_passthrough():
    assert format_generic_payload({"text": "Deploy finished"}) == "Deploy finished"


def test_generic_structured_summary():
    text = format_generic_payload({"title": "Nightly Backup", "host": "db-01"})
    assert "Nightly Backup" in text
    assert "host: db-01" in text


def test_generic_long_value_truncated():
    text = format_generic_payload({"title": "t", "detail": "x" * 500})
    assert len(text) < 400


def test_registry_discovers_builtin_integrations(flask_app):
    from line_notification_bot.integrations import registry

    names = set(registry.all_integrations().keys())
    assert {"generic", "monitoring"} <= names


def test_registry_skips_invalid_modules(flask_app, monkeypatch, tmp_path):
    """A module without the required attributes is skipped, not fatal."""
    from line_notification_bot.integrations import registry

    class Bad:
        name = "bad"
        # format_payload missing on purpose

    bad_instance = Bad()
    registry.register(bad_instance)
    assert registry.get("bad") is bad_instance
    # Clean up so other tests are unaffected.
    registry._REGISTRY.pop("bad", None)