"""Issues: the ``ISSUE#`` rows, the send ledger and the newsroom operations on them (docs/newsletter.md).

Rows (single table):
  ISSUE#<id> / META        listId, kind, itemId, subject, status, contentHash, approvedBy/At, sendAt, scheduleName, counts, note...
                           ``gsiList`` is the constant ``#issues`` so the ``byList`` index lists every issue (no list id can start with ``#``)
  ISSUE#<id> / RENDER      the issue rendered once for sending (html, text, subject)
  ISSUE#<id> / SEND#<hid>  ledger: ``claimed`` before SES is called (at most once), then ``sent``, ``failed``, ``suppressed`` or ``skipped``

Statuses: draft, awaiting_approval, scheduled, sending, sent, cancelled, stopped, blocked.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from . import addresses
from .compose import ItemMissing, content_hash, load_source
from .store import Store, _de, _ser, iso

Response = dict[str, Any]

ISSUE_INDEX_PARTITION = "#issues"
COUNT_KEYS = ("queued", "sent", "failed", "suppressed", "skipped", "delivered", "bounced", "complained")
TERMINAL_COUNTS = ("sent", "failed", "suppressed", "skipped")
APPROVABLE = ("draft", "awaiting_approval", "scheduled", "blocked")  # blocked: fixed at its cause, then approved again
EDITORS = frozenset({"editor", "admin"})
ADMINS = frozenset({"admin"})
EDITED_NOTE = "edited after approval; approve again"
SUMMARY_FIELDS = (
    "issueId", "listId", "kind", "itemId", "sourceItemId", "subject", "status", "sendAt", "approvedBy", "approvedAt", "sentAt",
    "counts", "note", "archiveUrl", "createdAt", "updatedAt",
)


def reply(status_code: int, **body: Any) -> Response:
    return {"statusCode": status_code, "body": body}


def failure(status_code: int, error: str, message: str = "") -> Response:
    return reply(status_code, ok=False, error=error, message=message or error.replace("_", " "))


FORBIDDEN = failure(403, "forbidden", "This needs a different role.")


def new_issue_id() -> str:
    """16 hex characters; the first eight name the one-time schedule."""
    return uuid.uuid4().hex[:16]


def issue_key(issue_id: str) -> dict[str, str]:
    return {"pk": f"ISSUE#{issue_id}", "sk": "META"}


def send_key(issue_id: str, hid: str) -> dict[str, str]:
    return {"pk": f"ISSUE#{issue_id}", "sk": f"SEND#{hid}"}


def send_row(issue_id: str, hid: str, status: str, now: float) -> dict[str, Any]:
    """A new ledger row. ``gsiHid`` puts it in the sparse ``byHid`` index, so erasing a subscriber finds their rows in one query."""
    return {**send_key(issue_id, hid), "gsiHid": hid, "status": status, "at": iso(now)}


def render_key(issue_id: str) -> dict[str, str]:
    return {"pk": f"ISSUE#{issue_id}", "sk": "RENDER"}


def new_issue_row(
    issue_id: str, *, list_id: str, kind: str, subject: str, now: float, item_id: str | None = None,
    source_item_id: str | None = None, status: str = "draft",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        **issue_key(issue_id),
        "gsiList": ISSUE_INDEX_PARTITION,
        "issueId": issue_id,
        "listId": list_id,
        "kind": kind,
        "subject": subject,
        "status": status,
        "counts": {name: 0 for name in COUNT_KEYS},
        "createdAt": iso(now),
        "updatedAt": iso(now),
    }
    if item_id:
        row["itemId"] = item_id
    if source_item_id:
        row["sourceItemId"] = source_item_id
    return row


def summary(issue: Mapping[str, Any], settings: Any = None) -> dict[str, Any]:
    out = {name: issue[name] for name in SUMMARY_FIELDS if name in issue}
    entry = settings.list_named(issue.get("listId", "")) if settings is not None else None
    if entry is not None:
        out["listName"] = entry["name"]
    return out


def groups_of(event: Mapping[str, Any]) -> set[str]:
    groups = (event.get("identity") or {}).get("groups")
    return {group for group in groups if isinstance(group, str)} if isinstance(groups, list) else set()


def allowed(event: Mapping[str, Any], roles: frozenset[str]) -> bool:
    """The caller's role, taken from the identity claims AppSync verified (the AppSync rule is the first check, this the second)."""
    return bool(groups_of(event) & roles)


def actor_of(event: Mapping[str, Any]) -> str:
    identity = event.get("identity") or {}
    value = identity.get("username") or identity.get("sub") or ""
    return str(value)[:200]


def input_of(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("input")
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def parse_time(value: Any) -> float | None:
    """An ISO 8601 time (``Z`` or an offset; no zone means UTC) or epoch seconds, as epoch seconds."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class IssueStore:
    """DynamoDB access for issues and the ledger. Every status change is a conditional update."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.client = store.client
        self.table = store.table_name

    # -- issue rows ---------------------------------------------------------------------------------------------

    def create(self, row: dict[str, Any]) -> bool:
        """Put a new issue; False when the id exists."""
        try:
            self.client.put_item(TableName=self.table, Item=_ser(row), ConditionExpression="attribute_not_exists(pk)")
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def get(self, issue_id: str) -> dict[str, Any] | None:
        response = self.client.get_item(TableName=self.table, Key=_ser(issue_key(issue_id)), ConsistentRead=True)
        return _de(response["Item"]) if "Item" in response else None

    def list_all(self) -> list[dict[str, Any]]:
        keys: list[dict[str, Any]] = []
        start: dict[str, Any] | None = None
        while True:
            page = self.client.query(
                TableName=self.table,
                IndexName="byList",
                KeyConditionExpression="gsiList = :l",
                ExpressionAttributeValues=_ser({":l": ISSUE_INDEX_PARTITION}),
                **({"ExclusiveStartKey": start} if start else {}),
            )
            keys += [{"pk": item["pk"], "sk": item["sk"]} for item in page.get("Items", [])]
            start = page.get("LastEvaluatedKey")
            if not start:
                break
        rows: list[dict[str, Any]] = []
        for offset in range(0, len(keys), 100):
            pending = {self.table: {"Keys": keys[offset : offset + 100], "ConsistentRead": True}}
            while pending:
                response = self.client.batch_get_item(RequestItems=pending)
                rows += [_de(item) for item in response.get("Responses", {}).get(self.table, [])]
                pending = response.get("UnprocessedKeys") or {}
        return rows

    def update(
        self,
        issue_id: str,
        sets: Mapping[str, Any] | None = None,
        *,
        expect: tuple[str, ...] | str | None = None,
        remove: tuple[str, ...] = (),
        add_counts: Mapping[str, int] | None = None,
    ) -> bool:
        """Change an issue row. False when it is missing or its status is not one of ``expect``."""
        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        assignments: list[str] = []
        for index, (name, value) in enumerate(dict(sets or {}).items()):
            names[f"#s{index}"] = name
            values[f":s{index}"] = value
            assignments.append(f"#s{index} = :s{index}")
        if add_counts:
            names["#counts"] = "counts"
            values[":zero"] = 0
            for index, (name, amount) in enumerate(add_counts.items()):
                names[f"#c{index}"] = name
                values[f":c{index}"] = amount
                assignments.append(f"#counts.#c{index} = if_not_exists(#counts.#c{index}, :zero) + :c{index}")
        removals = []
        for index, name in enumerate(remove):
            names[f"#r{index}"] = name
            removals.append(f"#r{index}")
        names["#updated"] = "updatedAt"
        values[":now"] = iso(time.time())
        assignments.append("#updated = :now")
        expression = "SET " + ", ".join(assignments) + (" REMOVE " + ", ".join(removals) if removals else "")
        condition = "attribute_exists(pk)"
        if expect is not None:
            statuses = (expect,) if isinstance(expect, str) else tuple(expect)
            names["#status"] = "status"
            holders = []
            for index, status in enumerate(statuses):
                values[f":e{index}"] = status
                holders.append(f":e{index}")
            condition += f" AND #status IN ({', '.join(holders)})"
        try:
            self.client.update_item(
                TableName=self.table,
                Key=_ser(issue_key(issue_id)),
                UpdateExpression=expression,
                ConditionExpression=condition,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=_ser(values),
            )
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def finish_if_complete(self, issue_id: str, now: float) -> bool:
        """Mark a fully processed sending issue ``sent``. True only for the one caller whose conditional update wins."""
        issue = self.get(issue_id)
        if issue is None or issue.get("status") != "sending" or not issue.get("enqueuedAt"):
            return False
        counts = issue.get("counts") or {}
        if sum(int(counts.get(name, 0)) for name in TERMINAL_COUNTS) < int(counts.get("queued", 0)):
            return False
        return self.update(issue_id, {"status": "sent", "sentAt": iso(now)}, expect="sending")

    # -- the rendered issue -------------------------------------------------------------------------------------

    def put_render(self, issue_id: str, subject: str, html: str, text: str) -> None:
        self.client.put_item(
            TableName=self.table,
            Item=_ser({**render_key(issue_id), "subject": subject, "html": html, "text": text}),
        )

    def get_render(self, issue_id: str) -> dict[str, Any] | None:
        response = self.client.get_item(TableName=self.table, Key=_ser(render_key(issue_id)), ConsistentRead=True)
        return _de(response["Item"]) if "Item" in response else None

    # -- the ledger ---------------------------------------------------------------------------------------------

    def claim(self, issue_id: str, hid: str, now: float) -> bool:
        """Create the ledger row before calling SES. False when the row exists: someone already handled this address."""
        try:
            self.client.put_item(
                TableName=self.table,
                Item=_ser(send_row(issue_id, hid, "claimed", now)),
                ConditionExpression="attribute_not_exists(pk)",
            )
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def get_send(self, issue_id: str, hid: str) -> dict[str, Any] | None:
        response = self.client.get_item(TableName=self.table, Key=_ser(send_key(issue_id, hid)), ConsistentRead=True)
        return _de(response["Item"]) if "Item" in response else None

    def _transact(self, items: list[dict[str, Any]]) -> bool:
        try:
            self.client.transact_write_items(TransactItems=items)
        except self.client.exceptions.TransactionCanceledException as error:
            reasons = error.response.get("CancellationReasons") or []
            if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
                return False
            raise
        return True

    def _count(self, issue_id: str, name: str) -> dict[str, Any]:
        return {
            "Update": {
                "TableName": self.table,
                "Key": _ser(issue_key(issue_id)),
                "UpdateExpression": "SET #counts.#n = if_not_exists(#counts.#n, :zero) + :one",
                "ConditionExpression": "attribute_exists(pk)",
                "ExpressionAttributeNames": {"#counts": "counts", "#n": name},
                "ExpressionAttributeValues": _ser({":zero": 0, ":one": 1}),
            }
        }

    def record_outcome(
        self, issue_id: str, hid: str, status: str, now: float, *, message_id: str | None = None, error: str | None = None
    ) -> bool:
        """Turn a claimed row into ``sent`` or ``failed`` and count it, atomically. False when it was no longer ``claimed``."""
        expression = "SET #st = :st, #at = :at"
        values: dict[str, Any] = {":st": status, ":at": iso(now), ":claimed": "claimed"}
        names = {"#st": "status", "#at": "at"}
        if message_id:
            expression += ", messageId = :mid"
            values[":mid"] = message_id
        if error:
            expression += ", #err = :err"
            names["#err"] = "error"
            values[":err"] = error[:200]
        return self._transact(
            [
                {
                    "Update": {
                        "TableName": self.table,
                        "Key": _ser(send_key(issue_id, hid)),
                        "UpdateExpression": expression,
                        "ConditionExpression": "#st = :claimed",
                        "ExpressionAttributeNames": names,
                        "ExpressionAttributeValues": _ser(values),
                    }
                },
                self._count(issue_id, status),
            ]
        )

    def settle_unsent(self, issue_id: str, hid: str, status: str, now: float) -> bool:
        """Record an address that is not mailed (``suppressed`` or ``skipped``) and count it. False when already recorded."""
        return self._transact(
            [
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": _ser(send_row(issue_id, hid, status, now)),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                self._count(issue_id, status),
            ]
        )

    # -- recipients ---------------------------------------------------------------------------------------------

    def list_members(self, list_id: str) -> list[str]:
        """Every subscriber id on the list's ``byList`` index (subscribed on a confirmed profile)."""
        hids: list[str] = []
        start: dict[str, Any] | None = None
        while True:
            page = self.client.query(
                TableName=self.table,
                IndexName="byList",
                KeyConditionExpression="gsiList = :l",
                ExpressionAttributeValues=_ser({":l": list_id}),
                **({"ExclusiveStartKey": start} if start else {}),
            )
            hids += [item["pk"]["S"].removeprefix("SUB#") for item in page.get("Items", [])]
            start = page.get("LastEvaluatedKey")
            if not start:
                break
        return hids

    def membership_status(self, hid: str, list_id: str) -> str | None:
        response = self.client.get_item(
            TableName=self.table, Key=_ser({"pk": f"SUB#{hid}", "sk": f"LIST#{list_id}"}), ConsistentRead=True
        )
        return _de(response["Item"]).get("status") if "Item" in response else None


class IssueService:
    """The operations behind the newsroom panel, the roundup schedule and the send. Collaborators are injected."""

    def __init__(
        self,
        *,
        settings: Any,
        store: Store,
        mailer: Any,
        compliance: Any,
        postal: Any,
        scheduler: Any,
        queue: Any,
        content: Callable[[], Any],
        publisher: Callable[[str], Mapping[str, Any]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.issues = IssueStore(store)
        self.mailer = mailer
        self.compliance = compliance
        self.postal = postal
        self.scheduler = scheduler
        self.queue = queue
        self._content_factory = content
        self._content: Any = None
        self.publisher = publisher
        self.clock = clock

    @property
    def content(self) -> Any:
        if self._content is None:
            self._content = self._content_factory()
        return self._content

    def profile(self, hid: str) -> dict[str, Any] | None:
        return self.issues.store.get_profile(hid)

    def roundup_list(self, list_id: Any) -> Mapping[str, Any] | None:
        entry = self.settings.list_named(list_id) if isinstance(list_id, str) else None
        return entry if entry is not None and entry.get("kind") == "roundup" else None

    # -- reads --------------------------------------------------------------------------------------------------

    def list(self, event: Mapping[str, Any]) -> Response:
        if not allowed(event, EDITORS):
            return FORBIDDEN
        wanted = input_of(event)
        limit = wanted.get("limit") if isinstance(wanted.get("limit"), int) and not isinstance(wanted.get("limit"), bool) else 50
        rows = self.issues.list_all()
        if isinstance(wanted.get("listId"), str):
            rows = [row for row in rows if row.get("listId") == wanted["listId"]]
        if isinstance(wanted.get("status"), str):
            rows = [row for row in rows if row.get("status") == wanted["status"]]
        rows.sort(key=lambda row: row.get("createdAt", ""), reverse=True)
        return reply(200, ok=True, issues=[summary(row, self.settings) for row in rows[: max(1, min(limit, 200))]])

    def get(self, event: Mapping[str, Any]) -> Response:
        if not allowed(event, EDITORS):
            return FORBIDDEN
        issue = self._issue(input_of(event))
        if issue is None:
            return failure(404, "not_found", "No such issue.")
        out = summary(issue, self.settings)
        if issue.get("contentHash"):
            out["contentHash"] = issue["contentHash"]
            try:
                source = load_source(self.content, issue)
                out["editedSinceApproval"] = content_hash(source.subject, source.markus) != issue["contentHash"]
            except ItemMissing:
                out["editedSinceApproval"] = True
        return reply(200, ok=True, issue=out)

    def _issue(self, wanted: Mapping[str, Any]) -> dict[str, Any] | None:
        issue_id = wanted.get("issueId")
        if not isinstance(issue_id, str) or not issue_id.isalnum() or len(issue_id) > 40:
            return None
        return self.issues.get(issue_id)

    # -- state changes (admin) ----------------------------------------------------------------------------------

    def approve(self, event: Mapping[str, Any]) -> Response:
        if not allowed(event, ADMINS):
            return FORBIDDEN
        wanted = input_of(event)
        issue = self._issue(wanted)
        if issue is None:
            return failure(404, "not_found", "No such issue.")
        if issue.get("status") not in APPROVABLE:
            return failure(409, "invalid_state", f"An issue that is {issue.get('status')} cannot be approved.")
        entry = self.settings.list_named(issue.get("listId", ""))
        if entry is None:
            return failure(409, "invalid_state", "The issue's list is no longer configured.")
        from .compose import render
        from .scheduler import effective_send_time, schedule_name

        try:
            source = load_source(self.content, issue)
        except ItemMissing:
            return failure(409, "item_missing", "The issue's item no longer exists.")
        address = self.postal.resolve()
        try:
            render(self.settings, entry["name"], source, address or POSTAL_PLACEHOLDER)
        except Exception as error:  # noqa: BLE001 - a body that cannot render is the editor's to fix
            return failure(422, "render_failed", f"The issue cannot be rendered: {type(error).__name__}.")
        now = self.clock()
        send_at, adjusted = effective_send_time(parse_time(wanted.get("sendAt")), now)
        name = schedule_name(self.settings.site_id, issue["issueId"])
        self.scheduler.upsert(name, issue["issueId"], send_at)
        changed = self.issues.update(
            issue["issueId"],
            {
                "status": "scheduled",
                "subject": source.subject,
                "contentHash": content_hash(source.subject, source.markus),
                "approvedBy": actor_of(event),
                "approvedAt": iso(now),
                "sendAt": iso(send_at),
                "scheduleName": name,
            },
            expect=APPROVABLE,
            remove=("note",),
        )
        if not changed:
            if issue.get("status") != "scheduled":
                self.scheduler.delete(name)
            return failure(409, "invalid_state", "The issue changed; reload it.")
        warnings = [] if address else ["postal address missing: the send will be blocked until it is configured"]
        log("issue_approved", issue["issueId"], status="scheduled")
        return reply(200, ok=True, issue=summary(self.issues.get(issue["issueId"]) or {}, self.settings), adjusted=adjusted, warnings=warnings)

    def cancel(self, event: Mapping[str, Any]) -> Response:
        if not allowed(event, ADMINS):
            return FORBIDDEN
        issue = self._issue(input_of(event))
        if issue is None:
            return failure(404, "not_found", "No such issue.")
        if issue.get("status") != "scheduled":
            return failure(409, "invalid_state", "Only a scheduled issue can be cancelled; stop one that is sending.")
        if issue.get("scheduleName"):
            self.scheduler.delete(issue["scheduleName"])
        changed = self.issues.update(
            issue["issueId"],
            {"status": "draft", "note": f"cancelled by {actor_of(event)}"},
            expect="scheduled",
            remove=("contentHash", "approvedBy", "approvedAt", "sendAt", "scheduleName"),
        )
        if not changed:
            return failure(409, "invalid_state", "The issue started sending; stop it instead.")
        log("issue_cancelled", issue["issueId"], status="draft")
        return reply(200, ok=True, issue=summary(self.issues.get(issue["issueId"]) or {}, self.settings))

    def stop(self, event: Mapping[str, Any]) -> Response:
        if not allowed(event, ADMINS):
            return FORBIDDEN
        issue = self._issue(input_of(event))
        if issue is None:
            return failure(404, "not_found", "No such issue.")
        changed = self.issues.update(
            issue["issueId"], {"status": "stopped", "note": f"stopped by {actor_of(event)}"}, expect="sending"
        )
        if not changed:
            return failure(409, "invalid_state", "Only an issue that is sending can be stopped.")
        log("issue_stopped", issue["issueId"], status="stopped")
        return reply(200, ok=True, issue=summary(self.issues.get(issue["issueId"]) or {}, self.settings))

    # -- editors and admins -------------------------------------------------------------------------------------

    def create_draft(self, event: Mapping[str, Any]) -> Response:
        if not allowed(event, EDITORS):
            return FORBIDDEN
        entry = self.roundup_list(input_of(event).get("listId"))
        if entry is None:
            return failure(400, "bad_request", "Name a roundup list.")
        from .roundup import assemble

        result = assemble(self, entry, manual=True, actor=actor_of(event))
        return reply(200, ok=True, **result)

    def preview(self, event: Mapping[str, Any]) -> Response:
        if not allowed(event, EDITORS):
            return FORBIDDEN
        issue = self._issue(input_of(event))
        if issue is None:
            return failure(404, "not_found", "No such issue.")
        entry = self.settings.list_named(issue.get("listId", ""))
        if entry is None:
            return failure(409, "invalid_state", "The issue's list is no longer configured.")
        from .compose import render

        try:
            source = load_source(self.content, issue)
        except ItemMissing:
            return failure(409, "item_missing", "The issue's item no longer exists.")
        address = self.postal.resolve()
        try:
            rendered = render(
                self.settings, entry["name"], source, address or POSTAL_PLACEHOLDER, manage_url="#preview", unsubscribe_url="#preview"
            )
        except Exception as error:  # noqa: BLE001
            return failure(422, "render_failed", f"The issue cannot be rendered: {type(error).__name__}.")
        return reply(
            200, ok=True, subject=rendered.subject, html=rendered.html, text=rendered.text,
            bytes=len(rendered.html.encode("utf-8")), postalAddress=bool(address), contentHash=content_hash(source.subject, source.markus),
        )

    def test_send(self, event: Mapping[str, Any]) -> Response:
        """One copy to the signed-in editor's own address. The recipient comes from the identity claims, never from the input."""
        if not allowed(event, EDITORS):
            return FORBIDDEN
        identity = event.get("identity") or {}
        recipient = addresses.normalize(identity["email"]) if isinstance(identity.get("email"), str) else ""
        if not addresses.is_valid(recipient):
            return failure(400, "no_address", "Your account has no email address to send a test to.")
        issue = self._issue(input_of(event))
        if issue is None:
            return failure(404, "not_found", "No such issue.")
        entry = self.settings.list_named(issue.get("listId", ""))
        if entry is None:
            return failure(409, "invalid_state", "The issue's list is no longer configured.")
        address = self.postal.resolve()
        if not address:
            return failure(409, "postal_address_missing", "Configure the postal address before sending.")
        from .compose import render

        try:
            source = load_source(self.content, issue)
            rendered = render(self.settings, entry["name"], source, address, manage_url="#test", unsubscribe_url="#test", subject_prefix="[Test] ")
        except ItemMissing:
            return failure(409, "item_missing", "The issue's item no longer exists.")
        except Exception as error:  # noqa: BLE001
            return failure(422, "render_failed", f"The issue cannot be rendered: {type(error).__name__}.")
        self.mailer.send_issue(
            to=recipient, subject=rendered.subject, html=rendered.html, text=rendered.text, headers={},
            tags={"site": self.settings.site_id, "kind": "test"},
        )
        log("issue_test_sent", issue["issueId"])
        return reply(200, ok=True)

    # -- scheduler tasks ----------------------------------------------------------------------------------------

    def assemble_roundup(self, event: Mapping[str, Any]) -> Response:
        entry = self.roundup_list(event.get("listId"))
        if entry is None:
            return failure(400, "bad_request", "Unknown roundup list.")
        from .roundup import assemble

        return reply(200, ok=True, **assemble(self, entry, manual=False, actor="roundup-schedule"))

    def start_send(self, event: Mapping[str, Any]) -> Response:
        from .send import start_send

        issue_id = event.get("issueId")
        if not isinstance(issue_id, str) or not issue_id.isalnum():
            return failure(400, "bad_request", "Missing issue id.")
        return reply(200, ok=True, **start_send(self, issue_id))


POSTAL_PLACEHOLDER = "Postal address is not configured"


def log(event: str, issue_id: str, **fields: Any) -> None:
    """One structured line. Never an address, a subscriber id or the postal address."""
    print(json.dumps({"event": event, "issue": issue_id, **fields}))
