"""Grafana + Prometheus monitoring integration.

Demonstrates how to build an integration on top of the generic bot:

* Inbound:  Grafana Alerting webhook → ``/webhook/monitoring`` → LINE
* Outbound: chat commands ``status`` and ``alerts`` query the stack.

Configuration (all optional — integration degrades gracefully):

    GRAFANA_URL      default http://grafana:3000
    GRAFANA_TOKEN    service account token (needed for ``alerts`` command)
    PROMETHEUS_URLS  comma-separated, default http://prometheus:9090
"""

from __future__ import annotations

import logging
import os

import requests

from ..core.commands import register_command
from ..core.config import config
from .registry import IntegrationResult

logger = logging.getLogger("line_notification_bot.integrations.monitoring")

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000")
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN", "")
PROMETHEUS_URLS = [
    url.strip()
    for url in os.environ.get("PROMETHEUS_URLS", "http://prometheus:9090").split(",")
    if url.strip()
]


# ---------------------------------------------------------------------------
# Outbound: query helpers (chat commands)
# ---------------------------------------------------------------------------
def query_grafana_health() -> str:
    try:
        resp = requests.get(f"{GRAFANA_URL}/api/health", timeout=5)
        data = resp.json()
        return f"✅ Grafana: {data.get('version', 'unknown')} — {data.get('database', 'unknown')}"
    except Exception as exc:  # noqa: BLE001
        return f"❌ Grafana: {exc}"


def query_prometheus_health() -> list[str]:
    results: list[str] = []
    for url in PROMETHEUS_URLS:
        try:
            resp = requests.get(f"{url}/-/healthy", timeout=5)
            if resp.status_code == 200:
                results.append(f"✅ Prometheus: {url}")
            else:
                results.append(f"⚠️ Prometheus: {url} (HTTP {resp.status_code})")
        except Exception as exc:  # noqa: BLE001
            results.append(f"❌ Prometheus: {url} — {exc}")
    return results


def query_grafana_alerts() -> str:
    if not GRAFANA_TOKEN:
        return "❌ 未設定 GRAFANA_TOKEN，無法查詢告警"
    try:
        resp = requests.get(
            f"{GRAFANA_URL}/api/alertmanager/grafana/api/v2/alerts",
            headers={"Authorization": f"Bearer {GRAFANA_TOKEN}"},
            params={"active": "true", "silenced": "false"},
            timeout=config.request_timeout,
        )
        if resp.status_code != 200:
            return f"❌ Grafana API 回傳 {resp.status_code}"
        alerts = resp.json()
        if not alerts:
            return "✅ 目前沒有觸發中的告警"
        lines = [f"🔥 {len(alerts)} 個觸發中的告警:"]
        for alert in alerts[:10]:
            name = alert.get("labels", {}).get("alertname", "unknown")
            severity = alert.get("labels", {}).get("severity", "")
            state = alert.get("status", {}).get("state", "")
            icon = "🔥" if state == "firing" else "⚠️"
            lines.append(f"  {icon} {name} [{severity}]")
        if len(alerts) > 10:
            lines.append(f"  ... 還有 {len(alerts) - 10} 個")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"❌ 查詢告警失敗: {exc}"


# ---------------------------------------------------------------------------
# Inbound: Grafana webhook payload → LINE message
# ---------------------------------------------------------------------------
# Source identification and URL normalization are deployment-specific and
# therefore configurable via environment variables instead of hardcoding
# anyone's hostnames here:
#
#   ALERT_SOURCES="10.0.0.5=Home Grafana,grafana.example.com=Prod"
#   ALERT_URL_REWRITES="http://10.0.0.5:3000=https://grafana.example.com"
#
# Each mapping is a comma-separated list of "<needle>=<label-or-url>" pairs.
# For ALERT_SOURCES the needle is matched against the receiver name and the
# externalURL (host part); the label is what gets shown in LINE messages.
# For ALERT_URL_REWRITES the needle is a URL prefix to replace with the value.

def _parse_mapping(var_name: str) -> list[tuple[str, str]]:
    pairs = []
    for item in os.environ.get(var_name, "").split(","):
        item = item.strip()
        if "=" in item:
            needle, value = item.split("=", 1)
            needle, value = needle.strip(), value.strip()
            if needle:
                pairs.append((needle, value))
    # Longest needles first so "grafana.home.example" wins over "home".
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return pairs


_SOURCE_LABELS = _parse_mapping("ALERT_SOURCES")
_URL_REWRITES = _parse_mapping("ALERT_URL_REWRITES")


def detect_source(payload: dict) -> str:
    """Identify which Grafana instance sent this webhook.

    Matched against the receiver name first (contact points may be named per
    source, e.g. "LINE Bot [prod]"), then the externalURL host. Falls back to
    the externalURL hostname itself so unknown instances are still labelled.
    """
    receiver = str(payload.get("receiver", ""))
    external_url = str(payload.get("externalURL", ""))
    host = external_url.split("//")[-1].split("/")[0].split(":")[0] if external_url else ""

    for needle, label in _SOURCE_LABELS:
        if needle in receiver or needle in external_url or needle == host:
            return label

    return f"🖥️ {host or 'unknown'}"


def _normalize_url(text: str) -> str:
    """Rewrite internal-only URLs to public ones (if configured)."""
    for internal, public in _URL_REWRITES:
        text = text.replace(internal, public)
    return text


def extract_link(payload: dict) -> str:
    """Best-effort extraction of a clickable link for the alert group.

    Grafana puts URLs per-alert (dashboardURL / panelURL / generatorURL);
    the legacy top-level "panelUrl" key never exists in real payloads.
    Preference: panel > dashboard > generator (rule editor) > externalURL.
    """
    for key in ("panelURL", "dashboardURL", "generatorURL"):
        for alert in payload.get("alerts", []):
            url = str(alert.get(key) or "")
            if url:
                return url
    return str(payload.get("externalURL") or "")


def format_grafana_alert(payload: dict) -> str:
    """Convert a Grafana Alertmanager webhook payload into LINE text."""
    alerts = payload.get("alerts", [])
    status = payload.get("status", "unknown")
    alert_name = payload.get("commonLabels", {}).get("alertname", "Unknown Alert")
    severity = payload.get("commonLabels", {}).get("severity", "")
    firing_count = sum(1 for a in alerts if a.get("status") == "firing")
    resolved_count = sum(1 for a in alerts if a.get("status") == "resolved")

    icon = "🔥" if status == "firing" else "✅" if status == "resolved" else "⚠️"
    source = detect_source(payload)

    lines = [f"{icon} {source}｜Grafana Alert: {alert_name}"]
    if severity:
        lines.append(f"Severity: {severity}")
    lines.append(f"Status: {status}")
    lines.append(f"Firing: {firing_count} | Resolved: {resolved_count}")

    for alert in alerts[:5]:
        a_status = alert.get("status", "")
        a_name = alert.get("labels", {}).get("alertname", "")
        a_instance = alert.get("labels", {}).get("instance", "")
        a_value = alert.get("valueString") or ""
        a_icon = "🔥" if a_status == "firing" else "✅"
        detail = f"  {a_icon} {a_name}"
        if a_value:
            detail += f"（{a_value}）"
        elif a_instance:
            detail += f" ({a_instance})"
        lines.append(detail)

    if len(alerts) > 5:
        lines.append(f"  ... 還有 {len(alerts) - 5} 個")

    link = extract_link(payload)
    if link:
        lines.append(f"\n🔗 {_normalize_url(link)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Integration object
# ---------------------------------------------------------------------------
class MonitoringIntegration:
    name = "monitoring"

    # ------------------------------------------------------------------
    def format_payload(self, payload: dict) -> IntegrationResult:
        text = format_grafana_alert(payload)
        return IntegrationResult(ok=True, messages=[{"type": "text", "text": text}])

    # ------------------------------------------------------------------
    def register_commands(self) -> None:
        register_command("status", "查詢 Grafana & Prometheus 健康狀態", _cmd_status)
        register_command("alerts", "查詢目前觸發中的告警", _cmd_alerts)


def _cmd_status(_args: str, _reply_token: str | None) -> str:
    lines = ["📊 系統健康狀態", query_grafana_health()]
    lines.extend(query_prometheus_health())
    return "\n".join(lines)


def _cmd_alerts(_args: str, _reply_token: str | None) -> str:
    return query_grafana_alerts()


integration = MonitoringIntegration()