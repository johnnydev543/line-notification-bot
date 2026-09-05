"""Tests for integration formatting + registry auto-discovery."""

from line_notification_bot.integrations.generic import format_generic_payload
from line_notification_bot.integrations.monitoring import (
    detect_source,
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


def test_grafana_source_detection(monkeypatch):
    monkeypatch.setenv(
        "ALERT_SOURCES",
        "10.0.0.5=Home Grafana,grafana.prod.example=Prod",
    )
    # Re-import module-level mappings for the test.
    from line_notification_bot.integrations import monitoring
    monitoring._SOURCE_LABELS = monitoring._parse_mapping("ALERT_SOURCES")

    assert detect_source({"externalURL": "http://10.0.0.5:3000/"}) == "Home Grafana"
    assert detect_source({"externalURL": "https://grafana.prod.example/"}) == "Prod"
    # Receiver-name matching works even without an externalURL.
    assert detect_source({"receiver": "LINE Bot [grafana.prod.example]", "externalURL": ""}) == "Prod"
    # Unknown hosts fall back to the hostname itself.
    assert detect_source({"externalURL": "https://grafana.foo.io/"}) == "🖥️ grafana.foo.io"
    assert detect_source({}) == "🖥️ unknown"


def test_grafana_format_resolved():
    payload = dict(GRAFANA_PAYLOAD, status="resolved")
    text = format_grafana_alert(payload)
    assert "✅" in text
    assert "Status: resolved" in text


def test_grafana_preformatted_text_passthrough(monkeypatch):
    """A custom payload with a `text` field is sent to LINE verbatim."""
    monkeypatch.setenv(
        "ALERT_URL_REWRITES",
        "http://10.0.0.5:3000=https://grafana.prod.example",
    )
    from line_notification_bot.integrations import monitoring
    monitoring._URL_REWRITES = monitoring._parse_mapping("ALERT_URL_REWRITES")

    payload = {
        "text": "🔥 🏠 Home｜Grafana Alert: X\nhttps://10.0.0.5:3000/alerting/list",
    }
    text = format_grafana_alert(payload)
    assert text.startswith("🔥 🏠 Home｜Grafana Alert: X")
    assert "https://grafana.prod.example/alerting/list" in text

    # Whitespace-only text is ignored and falls back to formatting.
    fallback = format_grafana_alert({"text": "   ", **GRAFANA_PAYLOAD})
    assert "Grafana Alert: HighCPU" in fallback


def test_grafana_internal_urls_rewritten_to_public(monkeypatch):
    monkeypatch.setenv(
        "ALERT_URL_REWRITES",
        "http://10.0.0.5:3000=https://grafana.prod.example",
    )
    from line_notification_bot.integrations import monitoring
    monitoring._URL_REWRITES = monitoring._parse_mapping("ALERT_URL_REWRITES")

    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "X"},
                "generatorURL": "http://10.0.0.5:3000/alerting/list",
            }
        ],
        "commonLabels": {"alertname": "X"},
        "externalURL": "http://10.0.0.5:3000/",
    }
    text = format_grafana_alert(payload)
    assert "https://grafana.prod.example/alerting/list" in text
    assert "10.0.0.5" not in text.split("｜")[0]  # source label still identifies host


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