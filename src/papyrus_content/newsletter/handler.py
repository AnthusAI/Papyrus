"""The ``newsletter`` Lambda: double opt-in subscriptions for one site.

Invoked directly by the CMS Next routes (``app/api/newsletter/*``), never by the public. The event names an action:

* ``subscribe``           {email, lists, page, consent, formId, honeypot, renderedAt, ip, userAgent, siteSubject?}
* ``confirm``             {token, ip, userAgent}
* ``confirm_page_state``  {token}: read only, for the page that asks the visitor to press the confirm button

Every action answers ``{"statusCode": int, "body": {...}}``. Later actions (unsubscribe, preferences, events, sending)
are added to ``ACTIONS``.

Subscribing never reveals what the site knows about an address: for any valid-looking input the answer is the same
``check_email``, whether the address is new, pending, confirmed, suppressed, rate limited or mail could not be sent.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from . import addresses, rate, tokens
from .confirmation import build_confirmation
from .keys import Keys, load_keys
from .mailer import Mailer
from .store import Conflict, Store, append_history, iso, membership_row, profile_key

Response = dict[str, Any]

MINIMUM_FILL_SECONDS = 2
MAXIMUM_AGE_SECONDS = 24 * 60 * 60
MAXIMUM_WORDING_CHARACTERS = 500
MAXIMUM_PAGE_CHARACTERS = 500
MAXIMUM_USER_AGENT_CHARACTERS = 300
MAXIMUM_ADDRESS_CHARACTERS = 64
WRITE_ATTEMPTS = 3
SITE_SUBJECT = re.compile(r"[A-Za-z0-9._:-]{1,200}")
DEFAULT_WORDING = "I agree to receive email from {name} and understand that I can unsubscribe at any time."


def respond(status_code: int, **body: Any) -> Response:
    return {"statusCode": status_code, "body": body}


CHECK_EMAIL = respond(202, status="check_email")


@dataclass(frozen=True)
class Settings:
    site_id: str
    site_origin: str
    sending_domain: str
    from_address: str
    from_name: str
    configuration_set: str
    lists: tuple[Mapping[str, str], ...]
    theme: Mapping[str, Any]
    item_url_style: str = "html"  # how the site's item pages are addressed (projection.json urls.style), for links in roundup drafts

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "Settings":
        return cls(
            site_id=environment["SITE_ID"],
            site_origin=environment["SITE_ORIGIN"],
            sending_domain=environment["SENDING_DOMAIN"],
            from_address=environment["FROM_ADDRESS"],
            from_name=environment["FROM_NAME"],
            configuration_set=environment["CONFIGURATION_SET"],
            lists=tuple(json.loads(environment["LISTS_JSON"])),
            theme=json.loads(environment["THEME_JSON"]),
            item_url_style=environment.get("ITEM_URL_STYLE", "html"),
        )

    def list_named(self, list_id: str) -> Mapping[str, str] | None:
        return next((entry for entry in self.lists if entry["id"] == list_id), None)


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _milliseconds(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,16}", value):
        return float(value)
    return None


class Newsletter:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        keys: Keys,
        mailer: Mailer,
        *,
        clock: Callable[[], float] = time.time,
        nonce: Callable[[], str] = lambda: secrets.token_urlsafe(12),
        issues: Any = None,
    ) -> None:
        self.issues = issues  # an ``issues.IssueService``: roundups, approval and sending
        self.settings = settings
        self.store = store
        self.keys = keys
        self.mailer = mailer
        self.clock = clock
        self.new_nonce = nonce

    # -- dispatch -----------------------------------------------------------------------------------------------

    def dispatch(self, event: Mapping[str, Any]) -> Response:
        action = event.get("action") or event.get("task")  # a scheduler task names itself with "task"
        method = ACTIONS.get(action) if isinstance(action, str) else None
        if method is None:
            return respond(400, status="error", error="unknown_action")
        return getattr(self, method)(event)

    # -- subscribe ----------------------------------------------------------------------------------------------

    def _automated(self, event: Mapping[str, Any], now: float) -> bool:
        """A filled honeypot, or a form filled faster than a person can or left open longer than a day."""
        if event.get("honeypot"):
            return True
        rendered = _milliseconds(event.get("renderedAt"))
        if rendered is None:
            return True
        age = now - rendered / 1000.0
        return age < MINIMUM_FILL_SECONDS or age > MAXIMUM_AGE_SECONDS

    def _requested_lists(self, raw: Any) -> list[str]:
        if isinstance(raw, str):
            raw = raw.split(",")
        if not isinstance(raw, list):
            return []
        known = {entry["id"] for entry in self.settings.lists}
        ordered: list[str] = []
        for entry in raw:
            identifier = entry.strip() if isinstance(entry, str) else ""
            if identifier in known and identifier not in ordered:
                ordered.append(identifier)
        return ordered

    def _consent(self, event: Mapping[str, Any], now: float, ip_hash: str) -> dict[str, Any]:
        wording = _text(event.get("consent"), MAXIMUM_WORDING_CHARACTERS).strip()
        return {
            "requestedAt": iso(now),
            "formId": _text(event.get("formId"), 100) or "newsletter",
            "pageUrl": _text(event.get("page"), MAXIMUM_PAGE_CHARACTERS),
            "wording": wording or DEFAULT_WORDING.format(name=self.settings.from_name),
            "requestIpHash": ip_hash,
        }

    def subscribe(self, event: Mapping[str, Any]) -> Response:
        now = self.clock()
        if self._automated(event, now):
            return CHECK_EMAIL
        raw_email = event.get("email")
        address = addresses.normalize(raw_email) if isinstance(raw_email, str) else ""
        if not addresses.is_valid(address):
            return respond(400, status="invalid_email")
        list_ids = self._requested_lists(event.get("lists"))
        if not list_ids:
            return respond(400, status="invalid_lists")

        hid = addresses.hid(self.keys.hash, address)
        ip = _text(event.get("ip"), MAXIMUM_ADDRESS_CHARACTERS) or "unknown"
        ip_hash = addresses.ip_hash(self.keys.hash, ip)
        limited = rate.check(self.store.count, ip_hash=ip_hash, hid=hid, site_id=self.settings.site_id, now=now)
        if limited is not None:
            rate.log_metric(self.settings.site_id, "SubscribeRateLimited", Scope=limited)
            return CHECK_EMAIL
        if self.store.is_suppressed(hid):
            return CHECK_EMAIL

        for _attempt in range(WRITE_ATTEMPTS):
            try:
                outcome = self._record_request(hid, address, list_ids, event, now, ip_hash)
            except Conflict:
                continue
            if outcome is not None:
                nonce, confirm_lists = outcome
                self._send_confirmation(address, hid, confirm_lists, nonce, now)
            return CHECK_EMAIL
        rate.log_metric(self.settings.site_id, "SubscribeConflict")
        return CHECK_EMAIL

    def _record_request(
        self, hid: str, address: str, list_ids: list[str], event: Mapping[str, Any], now: float, ip_hash: str
    ) -> tuple[str, list[str]] | None:
        """Write the pending state for this request. Returns (nonce, lists to confirm) when a confirmation must go out."""
        profile = self.store.get_profile(hid)
        memberships = self.store.memberships(hid) if profile else {}
        nonce = self.new_nonce()
        site_subject = event.get("siteSubject")
        subject = site_subject if isinstance(site_subject, str) and SITE_SUBJECT.fullmatch(site_subject) else None

        if profile is None:
            profile = {
                **profile_key(hid),
                "email": address,
                "status": "pending",
                "createdAt": iso(now),
                "updatedAt": iso(now),
                "confirmNonce": nonce,
                "consent": self._consent(event, now, ip_hash),
                "expiresAt": int(now) + 30 * 24 * 60 * 60,
                "history": [],
            }
            if subject:
                profile["siteSubject"] = subject
            append_history(profile, now, "signup_requested")
            rows = [membership_row(hid, list_id, "pending", now) for list_id in list_ids]
            self.store.save(profile, None, rows)
            return nonce, list_ids

        if subject and not profile.get("siteSubject"):
            profile["siteSubject"] = subject
        expected_rev = int(profile.get("rev", 0))
        stale = [
            list_id
            for list_id, row in memberships.items()
            if row.get("status") == "pending" and list_id not in list_ids
        ]

        if profile.get("status") == "confirmed":
            new_lists = [list_id for list_id in list_ids if memberships.get(list_id, {}).get("status") != "subscribed"]
            if not new_lists:
                return None
            profile["confirmNonce"] = nonce
            profile["updatedAt"] = iso(now)
            append_history(profile, now, "lists_requested")
            stale = [list_id for list_id in stale if list_id not in new_lists]
            rows = [membership_row(hid, list_id, "pending", now) for list_id in new_lists]
            self.store.save(profile, expected_rev, rows, stale)
            return nonce, new_lists

        # Pending, or unsubscribed and asking again: a fresh double opt-in with fresh consent evidence.
        resubscribe = profile.get("status") == "unsubscribed"
        profile["status"] = "pending"
        profile["confirmNonce"] = nonce
        profile["updatedAt"] = iso(now)
        profile["consent"] = self._consent(event, now, ip_hash)
        profile["expiresAt"] = int(now) + 30 * 24 * 60 * 60
        append_history(profile, now, "resubscribe_requested" if resubscribe else "confirmation_resent")
        rows = [membership_row(hid, list_id, "pending", now) for list_id in list_ids]
        self.store.save(profile, expected_rev, rows, stale)
        return nonce, list_ids

    def _send_confirmation(self, address: str, hid: str, list_ids: list[str], nonce: str, now: float) -> None:
        """Mail failures are logged and swallowed: the answer to the visitor must not depend on the address."""
        try:
            token = tokens.issue(
                self.keys.token,
                tokens.Claims(
                    hid=hid,
                    purpose="confirm",
                    lists=tuple(list_ids),
                    nonce=nonce,
                    expires_at=int(now) + tokens.CONFIRM_TOKEN_LIFETIME_SECONDS,
                ),
            )
            named = [self.settings.list_named(list_id) for list_id in list_ids]
            rendered = build_confirmation(
                site_origin=self.settings.site_origin,
                site_name=self.settings.from_name,
                theme_config=self.settings.theme,
                lists=[entry for entry in named if entry is not None],
                token=token,
            )
            self.mailer.send_confirmation(to=address, subject=rendered.subject, html=rendered.html, text=rendered.text)
        except Exception as error:  # noqa: BLE001 - see docstring
            print(json.dumps({"event": "confirmation_send_failed", "error": type(error).__name__}))
            rate.log_metric(self.settings.site_id, "ConfirmationSendFailed")

    # -- confirm ------------------------------------------------------------------------------------------------

    def _open_confirmation(self, token: Any) -> tuple[Response | None, tokens.Claims | None, dict[str, Any] | None, list[str]]:
        """Check a confirm token against the profile. Returns (refusal, claims, profile, lists)."""
        now = self.clock()
        try:
            claims = tokens.verify(self.keys.token, token, "confirm", now)
        except tokens.ExpiredToken:
            return respond(410, status="expired"), None, None, []
        except tokens.InvalidToken:
            return respond(400, status="invalid"), None, None, []
        profile = self.store.get_profile(claims.hid)
        stored_nonce = (profile or {}).get("confirmNonce")
        if (
            profile is None
            or not isinstance(stored_nonce, str)
            or claims.nonce is None
            or not hmac.compare_digest(stored_nonce.encode("utf-8"), claims.nonce.encode("utf-8"))
        ):
            return respond(410, status="expired"), None, None, []
        list_ids = [list_id for list_id in claims.lists if self.settings.list_named(list_id) is not None]
        if not list_ids or self.store.is_suppressed(claims.hid):
            return respond(410, status="expired"), None, None, []
        return None, claims, profile, list_ids

    def _named(self, list_ids: list[str]) -> list[dict[str, str]]:
        return [{"id": list_id, "name": self.settings.list_named(list_id)["name"]} for list_id in list_ids]  # type: ignore[index]

    def confirm_page_state(self, event: Mapping[str, Any]) -> Response:
        refusal, _claims, _profile, list_ids = self._open_confirmation(event.get("token"))
        if refusal is not None:
            return refusal
        return respond(200, status="ready", lists=self._named(list_ids))

    def confirm(self, event: Mapping[str, Any]) -> Response:
        for _attempt in range(WRITE_ATTEMPTS):
            refusal, claims, profile, list_ids = self._open_confirmation(event.get("token"))
            if refusal is not None:
                return refusal
            assert claims is not None and profile is not None
            now = self.clock()
            first_confirmation = profile.get("status") != "confirmed"
            expected_rev = int(profile.get("rev", 0))
            profile["status"] = "confirmed"
            profile.pop("confirmNonce", None)
            profile.pop("expiresAt", None)
            profile["updatedAt"] = iso(now)
            if first_confirmation:
                consent = dict(profile.get("consent") or {})
                consent.update(
                    confirmedAt=iso(now),
                    confirmIp=_text(event.get("ip"), MAXIMUM_ADDRESS_CHARACTERS),
                    confirmUserAgent=_text(event.get("userAgent"), MAXIMUM_USER_AGENT_CHARACTERS),
                )
                profile["consent"] = consent
            append_history(profile, now, "confirmed" if first_confirmation else "lists_confirmed")
            rows = [membership_row(claims.hid, list_id, "subscribed", now, profile_confirmed=True) for list_id in list_ids]
            try:
                self.store.save(profile, expected_rev, rows)
            except Conflict:
                continue
            manage = tokens.issue(self.keys.token, tokens.Claims(hid=claims.hid, purpose="manage"))
            return respond(200, status="confirmed", lists=self._named(list_ids), manageToken=manage)
        return respond(410, status="expired")

    # -- issues: roundups, approval and sending (delegated to ``issues.IssueService``) -----------------------------

    def issue_list(self, event: Mapping[str, Any]) -> Response:
        return self.issues.list(event)

    def issue_get(self, event: Mapping[str, Any]) -> Response:
        return self.issues.get(event)

    def issue_approve(self, event: Mapping[str, Any]) -> Response:
        return self.issues.approve(event)

    def issue_cancel(self, event: Mapping[str, Any]) -> Response:
        return self.issues.cancel(event)

    def issue_stop(self, event: Mapping[str, Any]) -> Response:
        return self.issues.stop(event)

    def issue_test_send(self, event: Mapping[str, Any]) -> Response:
        return self.issues.test_send(event)

    def issue_create_draft(self, event: Mapping[str, Any]) -> Response:
        return self.issues.create_draft(event)

    def issue_preview(self, event: Mapping[str, Any]) -> Response:
        return self.issues.preview(event)

    def task_assemble_roundup(self, event: Mapping[str, Any]) -> Response:
        return self.issues.assemble_roundup(event)

    def task_start_send(self, event: Mapping[str, Any]) -> Response:
        return self.issues.start_send(event)


ACTIONS: dict[str, str] = {
    "subscribe": "subscribe",
    "confirm": "confirm",
    "confirm_page_state": "confirm_page_state",
    "issue_list": "issue_list",
    "issue_get": "issue_get",
    "issue_approve": "issue_approve",
    "issue_cancel": "issue_cancel",
    "issue_stop": "issue_stop",
    "issue_test_send": "issue_test_send",
    "issue_create_draft": "issue_create_draft",
    "issue_preview": "issue_preview",
    # EventBridge Scheduler tasks, named by "task"
    "assemble-roundup": "task_assemble_roundup",
    "start-send": "task_start_send",
}

_default: Newsletter | None = None


def build(environment: Mapping[str, str] = os.environ) -> Newsletter:
    from .runtime import build_issue_service

    settings = Settings.from_environment(environment)
    store = Store(environment["TABLE_NAME"])
    keys = load_keys(environment["KEY_PARAMETER"])
    mailer = Mailer(
        from_name=settings.from_name,
        from_address=settings.from_address,
        configuration_set=settings.configuration_set,
        site_id=settings.site_id,
    )
    return Newsletter(settings, store, keys, mailer, issues=build_issue_service(environment, settings, store, keys, mailer))


def handler(event: Mapping[str, Any], _context: Any = None) -> Response:
    global _default
    if _default is None:
        _default = build()
    return _default.dispatch(event)
