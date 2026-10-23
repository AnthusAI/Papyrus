"""The automation-view function: `automationOverview` for editors and admins, read-only."""

from __future__ import annotations

from typing import Any

from papyrus_content.automation_view import handle


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return handle(event)
