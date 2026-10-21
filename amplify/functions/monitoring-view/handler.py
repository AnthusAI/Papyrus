"""The monitoring-view function: `monitoringOverview` for editors and admins, read-only."""

from __future__ import annotations

from typing import Any

from papyrus_content.monitoring_view import handle


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return handle(event)
