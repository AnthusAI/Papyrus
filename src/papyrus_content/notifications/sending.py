"""Sending as the site: the site's own SES identity and configuration set, shared with its newsletter.

* ``SiteMailer``       tags every message with the site, and names the one SES refusal that means "this set is paused"
* ``SiteEmailChannel`` Caducus's email channel plus three site rules: a paused set is a ``failed`` delivery with a reason,
  public-class mail is refused without a postal address (and carries it in the footer), and every sent message id is
  remembered so the SES event for it finds its delivery
* ``SesDeliveryEvents`` the EventBridge SES event of a message this site sent, applied to the delivery log

The newsletter reads the same configuration set's events and ignores any without a valid ``sub`` tag; this plugin ignores
any without a ``site`` tag naming this site and a ``delivery`` tag, so neither consumer touches the other's mail.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

from caducus.notify.channels.base import Outcome
from caducus.notify.channels.email import EmailChannel, Mailer
from caducus.notify.delivery_log import DeliveryLog
from caducus.notify.logs import emit
from caducus.notify.store import Store

from .settings import Settings

LOGGER = logging.getLogger("papyrus.notifications.sending")
PUBLIC_CLASS = "public"
MESSAGE_PARTITION = "MSG#"
MESSAGE_SORT = "DELIVERY"
#: SES answers a send through a configuration set whose sending is off with this code (SES v2 ``SendingPausedException``).
PAUSED_CODES = ("SendingPausedException", "SendingPaused")


class SendingPaused(Exception):
    """The site's configuration set has sending turned off."""


def pause_reason(configuration_set: str) -> str:
    return f"sending is paused for configuration set {configuration_set or 'default'}"


class SiteMailer(Mailer):
    def __init__(self, inner: Mailer, site_id: str, configuration_set: str = ""):
        self._inner = inner
        self._site_id = site_id
        self._set = configuration_set

    def send(self, *, to_address, subject, text, html, tags):  # type: ignore[no-untyped-def]
        try:
            return self._inner.send(
                to_address=to_address, subject=subject, text=text, html=html, tags={**tags, "site": self._site_id}
            )
        except Exception as error:  # noqa: BLE001 - botocore is imported lazily by the inner mailer
            code = getattr(error, "response", {}).get("Error", {}).get("Code") if hasattr(error, "response") else None
            if code in PAUSED_CODES:
                raise SendingPaused(pause_reason(self._set)) from error
            raise

    def max_send_rate(self) -> float:
        return self._inner.max_send_rate()


class SiteEmailChannel(EmailChannel):
    def __init__(self, store: Store, log: DeliveryLog, directory: Any, mailer: Mailer, *, postal_address: Callable[[], Optional[str]], **kwargs: Any):
        super().__init__(store, log, directory, mailer, **kwargs)
        self._store_, self._log_, self._postal = store, log, postal_address

    def _fail(self, delivery: Mapping[str, Any], reason: str) -> Outcome:
        self._log_.advance(delivery["eventId"], delivery["deliveryId"], "failed", reason=reason)
        emit(LOGGER, "email_refused", eventId=delivery["eventId"], deliveryId=delivery["deliveryId"], reason=reason)
        return Outcome("failed", reason=reason)

    def send(self, delivery: Mapping[str, Any]) -> Outcome:
        if delivery.get("class") == PUBLIC_CLASS:
            address = (self._postal() or "").strip()
            if not address:
                return self._fail(delivery, "postal address missing")
            self._renderer.postal_address = address  # type: ignore[attr-defined]
        try:
            outcome = super().send(delivery)
        except SendingPaused as error:
            return self._fail(delivery, str(error))
        finally:
            if hasattr(self._renderer, "postal_address"):
                self._renderer.postal_address = None  # type: ignore[attr-defined]
        if outcome.provider_message_id:
            self._store_.put(
                {
                    "pk": MESSAGE_PARTITION + outcome.provider_message_id,
                    "sk": MESSAGE_SORT,
                    "eventId": delivery["eventId"],
                    "deliveryId": delivery["deliveryId"],
                    "expiresAt": delivery["expiresAt"],
                }
            )
        return outcome


def _tag(mail: Mapping[str, Any], name: str) -> str:
    values = (mail.get("tags") or {}).get(name)
    value = values[0] if isinstance(values, list) and values else values
    return value if isinstance(value, str) else ""


def apply_ses_event(store: Store, log: DeliveryLog, settings: Settings, envelope: Mapping[str, Any]) -> str:
    """Apply one EventBridge SES event to the delivery log. Returns what happened."""
    detail = envelope.get("detail") or {}
    mail = detail.get("mail") or {}
    if _tag(mail, "site") != settings.site_id or not _tag(mail, "delivery"):
        return "ignored"
    kind = detail.get("eventType")
    if kind == "Delivery":
        status, reason = "delivered", None
    elif kind == "Bounce":
        bounce = detail.get("bounce") or {}
        permanent = bounce.get("bounceType") == "Permanent"
        status, reason = ("bounced" if permanent else "delayed"), f"{bounce.get('bounceType', 'Undetermined')} bounce"
    elif kind == "Complaint":
        status, reason = "complained", "complaint"
    elif kind == "Reject":
        status, reason = "rejected", "rejected by SES"
    elif kind == "DeliveryDelay":
        status, reason = "delayed", "delivery delayed"
    else:
        return "ignored"
    message_id = mail.get("messageId")
    row = store.get(MESSAGE_PARTITION + message_id, MESSAGE_SORT) if isinstance(message_id, str) else None
    if row is None:
        return "unknown_message"
    log.advance(row["eventId"], row["deliveryId"], status, reason=reason)
    return status
