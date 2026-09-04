"""Webhook adapter protocol and registry.

An *integration* is a pluggable adapter that:
  1. Accepts an inbound HTTP payload (e.g. Grafana alertmanager JSON),
  2. Formats it into one or more LINE message objects,
  3. Optionally registers chat commands (bidirectional interaction).

Integrations are auto-discovered in the ``integrations`` package: any module
defining ``Integration`` subclass instances named ``integration`` will be
registered by the loader. The core knows nothing about Grafana or Prometheus —
they are just integrations.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.config import config

logger = logging.getLogger("line_notification_bot")


@dataclass
class IntegrationResult:
    """Outcome of formatting an inbound payload."""

    ok: bool
    messages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # How many targets the message should be delivered to. Empty = all
    # configured targets.
    target_ids: list[str] = field(default_factory=list)


class Integration(Protocol):
    """Structural interface every integration must satisfy."""

    # Unique, stable name used by ENABLED_INTEGRATIONS and routing.
    name: str

    def format_payload(self, payload: dict[str, Any]) -> IntegrationResult:
        """Convert an inbound webhook payload into LINE message objects."""
        ...

    def register_commands(self) -> None:
        """Optionally register chat commands (may be a no-op)."""
        ...


_REGISTRY: dict[str, Integration] = {}


def register(integration: Integration) -> None:
    """Add an integration to the registry."""
    if integration.name in _REGISTRY:
        logger.warning("Integration %r already registered — replacing", integration.name)
    _REGISTRY[integration.name] = integration
    logger.info("Registered integration: %s", integration.name)


def get(name: str) -> Integration | None:
    return _REGISTRY.get(name)


def all_integrations() -> dict[str, Integration]:
    return dict(_REGISTRY)


def is_enabled(name: str) -> bool:
    enabled = config.enabled_integrations
    if not enabled:
        return True
    return name in enabled


def load_integrations() -> list[str]:
    """Auto-discover and register all integrations in the integrations package.

    A module is considered an integration module if it exposes module-level
    ``integration`` object (or ``integrations`` list) satisfying the protocol.
    """
    import line_notification_bot.integrations as pkg

    loaded: list[str] = []
    for module_info in pkgutil.iter_modules(pkg.__path__):
        if module_info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(
                f"line_notification_bot.integrations.{module_info.name}"
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to import integration module %r", module_info.name)
            continue

        candidates: list[Integration] = []
        single = getattr(module, "integration", None)
        if single is not None:
            candidates.append(single)
        multiple = getattr(module, "integrations", None)
        if isinstance(multiple, (list, tuple)):
            candidates.extend(multiple)

        for candidate in candidates:
            required = ("name", "format_payload", "register_commands")
            if not all(hasattr(candidate, attr) for attr in required):
                logger.warning(
                    "Skipping invalid integration %r in module %r",
                    getattr(candidate, "name", candidate),
                    module_info.name,
                )
                continue
            register(candidate)
            loaded.append(candidate.name)

    # Register chat commands from every enabled integration.
    for name, integration in _REGISTRY.items():
        if is_enabled(name):
            try:
                integration.register_commands()
            except Exception:  # noqa: BLE001
                logger.exception("Integration %r failed to register commands", name)

    logger.info("Loaded %d integrations: %s", len(loaded), loaded)
    return loaded