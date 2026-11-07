"""The image-service function: `imageRead` and `imageWrite` (editors and admins), the one door to the image operations."""

from __future__ import annotations

from typing import Any

from papyrus_content.image_service import handle


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    return handle(event)
