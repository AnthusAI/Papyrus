"""The pause for a site that has notifications but no newsletter.

The newsletter plugin owns the bounce-rate and complaint-rate alarms and the pause when it is present. Without it, the
notifications plugin creates the same two alarms and this function turns off sending on the site's configuration set when
either enters ALARM. Lifting the pause is an operator's decision (``docs/notifications.md``).
"""

from __future__ import annotations

from typing import Any, Mapping

from .settings import Settings


def alarm_names(site_id: str) -> tuple[str, str]:
    return (f"papyrus-notifications-{site_id}-bounce-rate", f"papyrus-notifications-{site_id}-complaint-rate")


def handle_alarm(settings: Settings, ses: Any, event: Mapping[str, Any]) -> str:
    """Pause the site's configuration set for an alarm of this site that entered ALARM."""
    detail = event.get("detail") or {}
    if detail.get("alarmName") not in alarm_names(settings.site_id) or (detail.get("state") or {}).get("value") != "ALARM":
        return "ignored"
    ses.put_configuration_set_sending_options(ConfigurationSetName=settings.configuration_set, SendingEnabled=False)
    return "paused"
