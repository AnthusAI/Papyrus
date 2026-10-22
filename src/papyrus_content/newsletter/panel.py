"""The newsroom's Newsletter panel: counts, subscribers, export, erasure, resume and delivery history.

Every function takes the service (``handler.Newsletter``) and the event the AppSync proxy forwarded
(``{"action", "input", "identity": {username, sub, groups, email}}``) and answers ``{"statusCode", "body"}`` like the issue
operations. AppSync admits the groups first; each function checks the verified groups again. Editors may read counts and
delivery history (addresses masked); the subscriber list, the export, erasure and resume are admin only.

None of these actions is reachable from the public routes, and ``recount`` (an operator repair) has no AppSync operation.
"""

from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

from . import addresses, records
from .issues import ADMINS, EDITORS, FORBIDDEN, allowed, failure, input_of, reply
from .manage import mask
from .pause import resume_site
from .store import SITE_COUNT_ID, _de, _ser

EVENT_LIMIT = 100
SUBSCRIBER_PAGE = 50
EXPORT_PAGE = 200
DELIVERY_PAGE = 100
SCAN_WINDOW = 400  # raw rows read per scan call; the filter then keeps profiles only
READ_WORKERS = 8
PROFILE_STATUSES = ("pending", "confirmed", "unsubscribed")


# -- cursors -----------------------------------------------------------------------------------------------------------


def encode_cursor(key: Mapping[str, Any] | None) -> str | None:
    if not key:
        return None
    return base64.urlsafe_b64encode(json.dumps(key, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(value: Any) -> dict[str, Any] | None:
    """A cursor is a DynamoDB ``LastEvaluatedKey`` in wire form: ``{"pk": {"S": ...}, "sk": {"S": ...}}``. Anything else is ignored."""
    if not isinstance(value, str) or not value or len(value) > 600:
        return None
    try:
        key = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (ValueError, TypeError):
        return None
    if not isinstance(key, dict) or set(key) != {"pk", "sk"}:
        return None
    if not all(isinstance(key[name], dict) and isinstance(key[name].get("S"), str) for name in key):
        return None
    return {name: {"S": key[name]["S"]} for name in ("pk", "sk")}


# -- profiles ----------------------------------------------------------------------------------------------------------


def _memberships(svc: Any, hid: str) -> list[dict[str, str]]:
    rows = svc.store.memberships(hid)
    known = {entry["id"] for entry in svc.settings.lists}
    return [{"id": list_id, "status": str(row.get("status", ""))} for list_id, row in sorted(rows.items()) if list_id in known]


def _profile_key(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {"pk": {"S": profile["pk"]}, "sk": {"S": "PROFILE"}}


def _scan_profiles(
    svc: Any, cursor: dict[str, Any] | None, wanted: int, statuses: tuple[str, ...], list_id: str = ""
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Up to ``wanted`` profiles in table order, each with its memberships (``_lists``), and a cursor to resume after the last.

    A scan reads the whole table (ledger rows included), so each call reads a bounded window and loops until it has enough.
    """
    store = svc.store
    found: list[dict[str, Any]] = []
    start = cursor
    values: dict[str, Any] = {":profile": "PROFILE", ":sub": "SUB#"}
    condition = "sk = :profile AND begins_with(pk, :sub)"
    if statuses:
        keys = {f":s{index}": value for index, value in enumerate(statuses)}
        values.update(keys)
        condition += f" AND #status IN ({', '.join(keys)})"
    names = {"#status": "status"} if statuses else {}
    resume: dict[str, Any] | None = None
    while len(found) < wanted:
        page = store.client.scan(
            TableName=store.table_name,
            FilterExpression=condition,
            ExpressionAttributeValues=_ser(values),
            Limit=SCAN_WINDOW,
            ConsistentRead=True,
            **({"ExpressionAttributeNames": names} if names else {}),
            **({"ExclusiveStartKey": start} if start else {}),
        )
        profiles = [_de(item) for item in page.get("Items", [])]
        resume = page.get("LastEvaluatedKey")
        if len(profiles) > wanted - len(found) and not list_id:  # no list filter: no need to look further than the page needs
            profiles = profiles[: wanted - len(found)]
            resume = _profile_key(profiles[-1])
        with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
            lists = list(pool.map(lambda profile: _memberships(svc, profile["pk"].removeprefix("SUB#")), profiles))
        found += [{**profile, "_lists": entry} for profile, entry in zip(profiles, lists) if not list_id or any(item["id"] == list_id for item in entry)]
        start = resume
        if not resume:
            break
    if len(found) > wanted:
        found = found[:wanted]
        resume = _profile_key(found[-1])
    return found, resume


def _consent(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    consent = profile.get("consent")
    return consent if isinstance(consent, dict) else {}


# -- operations --------------------------------------------------------------------------------------------------------


def overview(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """Counts per list and in total, the suppressed count, the paused state and the last 100 events. Editors and admins."""
    if not allowed(event, EDITORS):
        return FORBIDDEN
    store = svc.store
    site = store.get_counts(SITE_COUNT_ID)
    if not site.get("seeded"):  # first use, or counters that started after subscribers already existed
        store.recount([entry["id"] for entry in svc.settings.lists], svc.clock())
        site = store.get_counts(SITE_COUNT_ID)
    lists = []
    for entry in svc.settings.lists:
        counts = store.get_counts(entry["id"])
        item: dict[str, Any] = {
            "id": entry["id"],
            "name": entry["name"],
            "kind": entry.get("kind", ""),
            **{name: max(0, int(counts.get(name, 0))) for name in ("confirmed", "pending", "unsubscribed")},
        }
        if entry.get("timezone"):
            item["timezone"] = entry["timezone"]
        lists.append(item)
    state = records.get_state(store)
    return reply(
        200,
        ok=True,
        lists=lists,
        totals={name: max(0, int(site.get(name, 0))) for name in ("confirmed", "pending", "unsubscribed")},
        suppressed=max(0, int(site.get("suppressed", 0))),
        paused={key: state[key] for key in ("paused", "reason", "pausedAt", "resumedAt") if key in state} or {"paused": False},
        events=_recent_events(svc),
    )


def _recent_events(svc: Any) -> list[dict[str, str]]:
    """The newest event rows, without the subscriber id: type, time, issue, list and bounce type."""
    store = svc.store
    response = store.client.query(
        TableName=store.table_name,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues=_ser({":pk": "EVENTS"}),
        ScanIndexForward=False,
        Limit=EVENT_LIMIT,
    )
    events = []
    for raw in response.get("Items", []):
        row = _de(raw)
        entry = {"type": str(row.get("type", "")), "at": str(row.get("sk", "")).split("#", 1)[0]}
        for name in ("issue", "list", "detail"):
            if row.get(name):
                entry[name] = str(row[name])
        events.append(entry)
    return events


def subscribers(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """A page of subscribers with their addresses. Admin only."""
    if not allowed(event, ADMINS):
        return FORBIDDEN
    wanted = input_of(event)
    status, list_id = wanted.get("status"), wanted.get("listId")
    if status is not None and status not in PROFILE_STATUSES:
        return failure(400, "bad_request", "Status is pending, confirmed or unsubscribed.")
    if list_id is not None and (not isinstance(list_id, str) or svc.settings.list_named(list_id) is None):
        return failure(400, "bad_request", "Unknown list.")
    profiles, last = _scan_profiles(svc, decode_cursor(wanted.get("cursor")), SUBSCRIBER_PAGE, (status,) if status else (), list_id or "")
    rows = []
    for profile in profiles:
        row: dict[str, Any] = {
            "email": profile.get("email", ""),
            "status": profile.get("status", ""),
            "lists": profile["_lists"],
            "createdAt": profile.get("createdAt", ""),
        }
        if _consent(profile).get("confirmedAt"):
            row["confirmedAt"] = _consent(profile)["confirmedAt"]
        rows.append(row)
    cursor = encode_cursor(last)
    return reply(200, ok=True, subscribers=rows, **({"cursor": cursor} if cursor else {}))


def export(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """Confirmed and pending subscribers with their consent evidence, a page at a time (pass ``cursor`` back). Admin only.

    The browser builds the CSV. Request IP hashes, confirming IPs and user agents are not exported.
    """
    if not allowed(event, ADMINS):
        return FORBIDDEN
    profiles, last = _scan_profiles(svc, decode_cursor(input_of(event).get("cursor")), EXPORT_PAGE, ("confirmed", "pending"))
    rows = []
    for profile in profiles:
        consent = _consent(profile)
        rows.append(
            {
                "email": profile.get("email", ""),
                "status": profile.get("status", ""),
                "lists": ";".join(f"{entry['id']}:{entry['status']}" for entry in profile["_lists"]),
                "createdAt": profile.get("createdAt", ""),
                "consentRequestedAt": consent.get("requestedAt", ""),
                "consentConfirmedAt": consent.get("confirmedAt", ""),
                "consentFormId": consent.get("formId", ""),
                "consentPageUrl": consent.get("pageUrl", ""),
                "consentWording": consent.get("wording", ""),
            }
        )
    cursor = encode_cursor(last)
    return reply(200, ok=True, rows=rows, **({"cursor": cursor} if cursor else {}))


def erase(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """Erase one subscriber by address (profile, memberships, suppression, ledger rows). Admin only."""
    if not allowed(event, ADMINS):
        return FORBIDDEN
    raw = input_of(event).get("email")
    address = addresses.normalize(raw) if isinstance(raw, str) else ""
    if not addresses.is_valid(address):
        return failure(400, "bad_request", "That is not a valid email address.")
    removed = records.erase_subscriber(svc.store, addresses.hid(svc.keys.hash, address))
    return reply(200, ok=True, removed=removed)


def resume(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """Turn sending back on after a bounce or complaint alarm paused it. Admin only."""
    if not allowed(event, ADMINS):
        return FORBIDDEN
    resume_site(svc.store, svc.mailer, svc.clock())
    return reply(200, ok=True, paused=False)


def deliveries(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """Ledger rows of one issue. Addresses are masked for editors and complete for admins."""
    if not allowed(event, EDITORS):
        return FORBIDDEN
    wanted = input_of(event)
    issue_id = wanted.get("issueId")
    if not isinstance(issue_id, str) or not issue_id.isalnum() or len(issue_id) > 40 or svc.issues.issues.get(issue_id) is None:
        return failure(404, "not_found", "No such issue.")
    store = svc.store
    start = decode_cursor(wanted.get("cursor"))
    if start is not None and start["pk"]["S"] != f"ISSUE#{issue_id}":
        start = None
    response = store.client.query(
        TableName=store.table_name,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues=_ser({":pk": f"ISSUE#{issue_id}", ":prefix": "SEND#"}),
        Limit=DELIVERY_PAGE,
        **({"ExclusiveStartKey": start} if start else {}),
    )
    ledger = [_de(item) for item in response.get("Items", [])]
    hids = [row["sk"].removeprefix("SEND#") for row in ledger]
    emails = _emails(svc, hids)
    full = allowed(event, ADMINS)
    rows = []
    for row, hid in zip(ledger, hids):
        email = emails.get(hid)
        entry: dict[str, Any] = {
            "address": "(erased)" if not email else email if full else mask(email),
            "status": row.get("status", ""),
            "at": row.get("at", ""),
        }
        for name in ("eventAt", "error"):
            if row.get(name):
                entry[name] = row[name]
        rows.append(entry)
    cursor = encode_cursor(response.get("LastEvaluatedKey"))
    return reply(200, ok=True, deliveries=rows, **({"cursor": cursor} if cursor else {}))


def _emails(svc: Any, hids: list[str]) -> dict[str, str]:
    """Addresses by subscriber id; an erased subscriber has none."""
    store = svc.store
    found: dict[str, str] = {}
    for offset in range(0, len(hids), 100):
        pending: Any = {
            store.table_name: {"Keys": [_ser({"pk": f"SUB#{hid}", "sk": "PROFILE"}) for hid in hids[offset : offset + 100]], "ProjectionExpression": "pk, email"}
        }
        while pending:
            response = store.client.batch_get_item(RequestItems=pending)
            for raw in response.get("Responses", {}).get(store.table_name, []):
                row = _de(raw)
                found[row["pk"].removeprefix("SUB#")] = str(row.get("email", ""))
            pending = response.get("UnprocessedKeys") or {}
    return found


def recount(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite every COUNT row from the table (operator repair; no AppSync operation reaches it)."""
    result = svc.store.recount([entry["id"] for entry in svc.settings.lists], svc.clock())
    return {"statusCode": 200, "body": {"status": "recounted", **result}}


PANEL_ACTIONS = {
    "panel_overview": overview,
    "panel_subscribers": subscribers,
    "panel_export": export,
    "panel_erase": erase,
    "panel_resume": resume,
    "panel_deliveries": deliveries,
    "recount": recount,
}
