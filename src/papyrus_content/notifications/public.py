"""The reader-facing actions the ``/api/notifications`` routes send, answered by Caducus's public audience.

The routes have already checked that a request came from the site's own pages (``lib/notifications-api.ts``). Subscribers,
consent, suppression and tokens are Caducus's (``caducus.notify.audience``, docs/public-audiences.md in AnthusAI/Caducus);
this module only builds the audience's settings from the site's and hands the event over.
"""

from __future__ import annotations

from typing import Any, Mapping

from caducus.notify.audience import AudienceList, AudienceSettings
from caducus.notify.handlers.public import READER_ACTIONS, dispatch

from .events import KIND, PRODUCT
from .links import SiteLinks
from .settings import Settings

__all__ = ["READER_ACTIONS", "audience_settings", "handle"]


def audience_settings(settings: Settings, unsuppress: Any = None) -> AudienceSettings:
    return AudienceSettings(
        lists=tuple(
            AudienceList(id=entry["id"], kind=KIND, name=entry["name"], description=entry.get("description", ""))
            for entry in settings.lists
        ),
        consent=settings.consent,
        confirm_window_seconds=settings.confirm_window_seconds,
        links=SiteLinks(settings),
        product=PRODUCT,
        site=settings.site_id,
        provider_unsuppress=unsuppress,
    )


def handle(audience: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    return dispatch(audience, event)
