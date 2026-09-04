"""Tests for integration formatting + registry auto-discovery."""

from line_notification_bot.integrations.generic import format_generic_payload
from line_notification_bot.integrations.monitoring import format_grafana_alert


GRAFANA_PAYLOAD = {
    "status": "firing",
    "alerts": [
        {"status": "firing", "labels": {"alertname": "HighCPU", "instance": "web-1"}},
        {"status": "resolved", "labels": {"alertname": "DiskFull", "instance": "db-1"}},
    ],
    "commonLabels": {"alertname": "HighCPU", "severity": "warning"},
    "panelUrl": "http://grafana.example.com/d/xyz",
}


def test_grafana_format_firing():
    text = format_grafana_alert(GRAFANA_PAYLOAD)
    assert "Grafana Alert: HighCPU" in text
    assert "Severity: warning" in text
    assert "Firing: 1 | Resolved: 1" in text
    assert "HighCPU (web-1)" in text
    assert "DiskFull (db-1)" in text
    assert "http://grafana.example.com/d/xyz" in text


def test_grafana_format_resolved():
    payload = dict(GRAFANA_PAYLOAD, status="resolved")
    text = format_grafana_alert(payload)
    assert "✅" in text
    assert "Status: resolved" in text


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