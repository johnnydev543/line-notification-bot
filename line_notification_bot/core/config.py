"""Application configuration.

All configuration comes from environment variables. The bot is generic;
monitoring-stack settings (Grafana/Prometheus) live under the
``integrations.monitoring`` namespace so the core stays clean.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_list(name: str, default: str = "") -> list[str]:
    """Parse a comma-separated env var into a list of non-empty strings."""
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    """Centralised bot configuration."""

    # --- LINE credentials -------------------------------------------------
    line_channel_access_token: str = field(
        default_factory=lambda: os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    )
    line_channel_secret: str = field(
        default_factory=lambda: os.environ.get("LINE_CHANNEL_SECRET", "")
    )
    # Push targets: one or more LINE User IDs / Group IDs.
    # Comma-separated env var supported: LINE_TARGET_IDS="U123,U456"
    target_ids: list[str] = field(
        default_factory=lambda: _env_list("LINE_TARGET_IDS", "")
        or (
            [os.environ["LINE_USER_ID"]]
            if os.environ.get("LINE_USER_ID", "").strip()
            else []
        )
    )

    # --- Server -----------------------------------------------------------
    port: int = field(default_factory=lambda: int(os.environ.get("PORT", "5000")))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    timezone: str = field(default_factory=lambda: os.environ.get("TZ", "UTC"))

    # --- Limits -----------------------------------------------------------
    # LINE hard limit is 5000 chars for text messages; keep a safety margin.
    max_text_length: int = field(
        default_factory=lambda: int(os.environ.get("LINE_MAX_TEXT_LENGTH", "4800"))
    )
    request_timeout: int = field(
        default_factory=lambda: int(os.environ.get("HTTP_TIMEOUT", "10"))
    )

    # --- Integration toggles ----------------------------------------------
    # Comma-separated list of enabled integrations. Empty = enable all
    # registered integrations.
    enabled_integrations: list[str] = field(
        default_factory=lambda: _env_list("ENABLED_INTEGRATIONS", "")
    )

    # --- Generic notification endpoint security ---------------------------
    # Shared secret for POST /notify (generic push API). Empty = open
    # (only safe on a trusted internal network).
    notify_secret: str = field(
        default_factory=lambda: os.environ.get("NOTIFY_SECRET", "")
    )

    # ------------------------------------------------------------------
    @property
    def line_configured(self) -> bool:
        return bool(
            self.line_channel_access_token
            and self.line_channel_secret
            and self.target_ids
        )

    def summary(self) -> dict:
        """Return a redacted config summary for /health."""
        return {
            "line_token_configured": bool(self.line_channel_access_token),
            "line_secret_configured": bool(self.line_channel_secret),
            "target_ids_count": len(self.target_ids),
            "enabled_integrations": self.enabled_integrations or "all",
            "notify_secret_configured": bool(self.notify_secret),
            "port": self.port,
            "log_level": self.log_level,
        }


# Module-level singleton, imported by the rest of the app.
config = Config()