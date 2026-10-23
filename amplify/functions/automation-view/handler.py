"""The automation-view function: `automationOverview` (editors, admins and operator IAM roles, read only) and `runAutomation` (editors and admins)."""

from __future__ import annotations

from typing import Any

from papyrus_content.automation_view import handle


def _account(context: Any) -> str | None:
    arn = getattr(context, "invoked_function_arn", None)
    parts = str(arn or "").split(":")
    return parts[4] if len(parts) > 4 and parts[4] else None


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    return handle(event, account_id=_account(context))
