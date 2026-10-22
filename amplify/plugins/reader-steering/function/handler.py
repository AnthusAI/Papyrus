"""reader-actions: the one function behind the reader API of the reader-steering plugin.

The CMS app's reader routes invoke it with ``{publication, siteSubject, isStaff, action, payload}`` after they
have checked the session, the Origin and the body size. It validates every field, rate limits per reader,
and writes the ReaderProfile, ReaderHandle and ReaderVote tables directly with its own role. It answers
``{statusCode, body}``; the body never contains the siteSubject.

The siteSubject is the per-site pairwise id that Prospectus returns. The global person id never reaches this
function. Only ``ss1_`` subjects are accepted, plus ``ssdev_`` ones when the site was synthesized for
development or test (docs/reader-steering.md).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Protocol

SITE_SUBJECT = re.compile(r"ss1_[A-Za-z0-9_-]{43}")
INTERIM_SUBJECT = re.compile(r"ssdev_[A-Za-z0-9_-]{43}")
SUBJECT_KEY = re.compile(r"[A-Za-z0-9._:-]{1,200}")
HANDLE = re.compile(r"[a-z0-9_-]{3,24}")
TOGGLE_DIMENSIONS = ("up", "used-it")
PUBLISHED_ID_PREFIX = "published-"
MAXIMUM_SUBJECTS = 50
MINIMUM_RATING = 1
MAXIMUM_RATING = 5
HOUR_SECONDS = 3600
HANDLE_CHANGES_PER_HOUR = 10
STATE_ACTIVE = "active"
STATE_LIMITED = "limited"
STATE_BANNED = "banned"
ROLE_READER = "reader"
ROLE_EDITOR = "editor"
ACTION_ME = "me"
ACTION_HANDLE = "handle"
ACTION_VOTE = "vote"
ACTION_RATING = "rating"
RATE_BUCKET_REACTIONS = "react"
RATE_BUCKET_HANDLE = "handle"
SNAPSHOT_TASK = {"projectionTask": {"task": "reader-snapshot"}}
RESERVED_HANDLES = frozenset(
    "admin administrator root system sysadmin moderator mod mods staff editor editors support help security "
    "official anonymous anon guest null undefined none me you everyone nobody deleted reader readers "
    "papyrus anthus prospectus api www mail abuse postmaster webmaster".split()
)


@dataclass(frozen=True)
class ReaderSettings:
    dimensions: tuple[str, ...] = ()
    actions_per_hour: int = 120
    new_account_hours: int = 24
    new_account_divisor: int = 3
    reserved_handles: frozenset[str] = frozenset()
    allow_interim_subjects: bool = False
    snapshot_debounce_seconds: int = 60


def settings_from_environment(environment: dict[str, str] | None = None) -> ReaderSettings:
    environment = os.environ if environment is None else environment
    raw = json.loads(environment.get("PAPYRUS_READER_SETTINGS") or "{}")
    limits = raw.get("limits") or {}
    defaults = ReaderSettings()
    return ReaderSettings(
        dimensions=tuple(raw.get("dimensions") or ()),
        actions_per_hour=int(limits.get("actionsPerHour", defaults.actions_per_hour)),
        new_account_hours=int(limits.get("newAccountHours", defaults.new_account_hours)),
        new_account_divisor=int(limits.get("newAccountDivisor", defaults.new_account_divisor)),
        reserved_handles=frozenset(raw.get("reservedHandles") or ()),
        allow_interim_subjects=bool(raw.get("allowInterimSubjects", False)),
        snapshot_debounce_seconds=int(raw.get("snapshotDebounceSeconds", defaults.snapshot_debounce_seconds)),
    )


class ReaderStore(Protocol):
    def get_profile(self, site_subject: str) -> dict[str, Any] | None: ...

    def create_profile(self, profile: dict[str, Any]) -> bool: ...

    def claim_handle(self, site_subject: str, reader_id: str, handle: str, now_iso: str) -> str: ...

    def get_vote_values(self, vote_ids: list[str]) -> dict[str, int]: ...

    def put_vote(self, vote: dict[str, Any], now_iso: str) -> None: ...

    def delete_vote(self, vote_id: str) -> None: ...

    def is_published(self, subject_key: str) -> bool: ...

    def count_action(self, reader_id: str, bucket: str, window_start: int, limit: int, expires_at: int) -> bool: ...

    def claim_snapshot_slot(self, now_seconds: float, debounce_seconds: int) -> bool: ...


def reply(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "body": body}


def refusal(status: int, error: str, message: str, **extra: Any) -> dict[str, Any]:
    return reply(status, {"error": error, "message": message, **extra})


def iso(now_seconds: float) -> str:
    return datetime.fromtimestamp(now_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def seconds_of(iso_text: str) -> float:
    return datetime.strptime(iso_text, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc).timestamp()


def vote_id(subject_key: str, reader_id: str, dimension: str) -> str:
    return f"{subject_key}#{reader_id}#{dimension}"


def valid_site_subject(value: Any, settings: ReaderSettings) -> bool:
    if not isinstance(value, str):
        return False
    if SITE_SUBJECT.fullmatch(value):
        return True
    return settings.allow_interim_subjects and INTERIM_SUBJECT.fullmatch(value) is not None


def action_limit(profile: dict[str, Any], settings: ReaderSettings, now_seconds: float) -> int:
    age_hours = (now_seconds - seconds_of(profile["createdAt"])) / HOUR_SECONDS
    if age_hours < settings.new_account_hours:
        return max(1, settings.actions_per_hour // settings.new_account_divisor)
    return settings.actions_per_hour


def within_rate_limit(
    store: ReaderStore, profile: dict[str, Any], bucket: str, limit: int, now_seconds: float
) -> dict[str, Any] | None:
    window_start = int(now_seconds // HOUR_SECONDS) * HOUR_SECONDS
    window_end = window_start + HOUR_SECONDS
    if store.count_action(profile["readerId"], bucket, window_start, limit, window_end + HOUR_SECONDS):
        return None
    return refusal(429, "rate_limited", "Too many actions. Try again later.", retryAfter=max(1, int(window_end - now_seconds)))


def ensure_profile(store: ReaderStore, site_subject: str, now_seconds: float) -> dict[str, Any]:
    profile = store.get_profile(site_subject)
    if profile is not None:
        return profile
    created = {
        "id": site_subject,
        "siteSubject": site_subject,
        "readerId": str(uuid.uuid4()),
        "state": STATE_ACTIVE,
        "karma": 0,
        "createdAt": iso(now_seconds),
    }
    if store.create_profile(created):
        return created
    existing = store.get_profile(site_subject)
    if existing is None:
        raise RuntimeError("The reader profile could not be created.")
    return existing


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "readerId": profile["readerId"],
        "handle": profile.get("handle"),
        "karma": int(profile.get("karma") or 0),
        "state": profile.get("state", STATE_ACTIVE),
    }


def my_state(store: ReaderStore, profile: dict[str, Any], payload: dict[str, Any], settings: ReaderSettings) -> dict[str, Any]:
    subjects = payload.get("subjects", [])
    if (
        not isinstance(subjects, list)
        or len(subjects) > MAXIMUM_SUBJECTS
        or not all(isinstance(subject, str) and SUBJECT_KEY.fullmatch(subject) for subject in subjects)
    ):
        return refusal(422, "invalid_subjects", f"Send at most {MAXIMUM_SUBJECTS} item keys.")
    dimensions = [*TOGGLE_DIMENSIONS, *settings.dimensions]
    wanted = {vote_id(subject, profile["readerId"], dimension): (subject, dimension) for subject in subjects for dimension in dimensions}
    found = store.get_vote_values(list(wanted))
    votes: dict[str, dict[str, int]] = {}
    for stored_id, value in found.items():
        subject, dimension = wanted[stored_id]
        votes.setdefault(subject, {})[dimension] = value
    return reply(200, {**public_profile(profile), "votes": votes})


def set_handle(
    store: ReaderStore, profile: dict[str, Any], payload: dict[str, Any], settings: ReaderSettings, now_seconds: float
) -> dict[str, Any]:
    requested = payload.get("handle")
    if not isinstance(requested, str):
        return refusal(422, "invalid_handle", "Send a handle.")
    handle = requested.lower()
    if not HANDLE.fullmatch(handle):
        return refusal(422, "invalid_handle", "A handle has 3 to 24 letters, digits, hyphens or underscores.")
    if handle in RESERVED_HANDLES or handle in settings.reserved_handles:
        return refusal(422, "reserved_handle", "That handle is reserved.")
    if profile.get("handle"):
        return refusal(409, "handle_already_set", "The handle is set once and cannot be changed.")
    limited = within_rate_limit(store, profile, RATE_BUCKET_HANDLE, HANDLE_CHANGES_PER_HOUR, now_seconds)
    if limited:
        return limited
    outcome = store.claim_handle(profile["siteSubject"], profile["readerId"], handle, iso(now_seconds))
    if outcome == "taken":
        return refusal(409, "handle_taken", "That handle is taken.")
    if outcome == "already_set":
        return refusal(409, "handle_already_set", "The handle is set once and cannot be changed.")
    return reply(200, {**public_profile({**profile, "handle": handle})})


def react(
    store: ReaderStore,
    profile: dict[str, Any],
    *,
    subject: Any,
    dimension: Any,
    allowed_dimensions: tuple[str, ...],
    value: int | None,
    is_staff: bool,
    settings: ReaderSettings,
    now_seconds: float,
    schedule_snapshot: Callable[[], None],
) -> dict[str, Any]:
    if not isinstance(subject, str) or not SUBJECT_KEY.fullmatch(subject):
        return refusal(422, "invalid_subject", "Send the key of a published item.")
    if not isinstance(dimension, str) or dimension not in allowed_dimensions:
        return refusal(422, "invalid_dimension", "That dimension is not available.")
    if profile.get("state") == STATE_BANNED:
        return refusal(403, "reader_banned", "This reader cannot take part.")
    if profile.get("state") == STATE_LIMITED:
        return refusal(403, "reader_limited", "This reader cannot vote or rate right now.")
    limited = within_rate_limit(store, profile, RATE_BUCKET_REACTIONS, action_limit(profile, settings, now_seconds), now_seconds)
    if limited:
        return limited
    if not store.is_published(subject):
        return refusal(404, "unknown_subject", "That item is not published.")
    stored_id = vote_id(subject, profile["readerId"], dimension)
    if value is None:
        store.delete_vote(stored_id)
    else:
        store.put_vote(
            {
                "id": stored_id,
                "subjectKey": subject,
                "readerId": profile["readerId"],
                "dimension": dimension,
                "value": value,
                "voterRole": ROLE_EDITOR if is_staff else ROLE_READER,
            },
            iso(now_seconds),
        )
    schedule_snapshot()
    return reply(200, {"subject": subject, "dimension": dimension, "value": value})


def vote_action(store, profile, payload, settings, is_staff, now_seconds, schedule_snapshot):
    on = payload.get("on")
    if not isinstance(on, bool):
        return refusal(422, "invalid_vote", "Send on as true or false.")
    return react(
        store, profile, subject=payload.get("subject"), dimension=payload.get("dimension"), allowed_dimensions=TOGGLE_DIMENSIONS,
        value=1 if on else None, is_staff=is_staff, settings=settings, now_seconds=now_seconds, schedule_snapshot=schedule_snapshot,
    )


def rating_action(store, profile, payload, settings, is_staff, now_seconds, schedule_snapshot):
    value = payload.get("value")
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not MINIMUM_RATING <= value <= MAXIMUM_RATING):
        return refusal(422, "invalid_rating", f"Send a whole number from {MINIMUM_RATING} to {MAXIMUM_RATING}, or null.")
    return react(
        store, profile, subject=payload.get("subject"), dimension=payload.get("dimension"), allowed_dimensions=settings.dimensions,
        value=value, is_staff=is_staff, settings=settings, now_seconds=now_seconds, schedule_snapshot=schedule_snapshot,
    )


def handle_event(
    event: dict[str, Any],
    *,
    store: ReaderStore,
    settings: ReaderSettings,
    now_seconds: float,
    schedule_snapshot: Callable[[], None],
) -> dict[str, Any]:
    site_subject, action, payload = event.get("siteSubject"), event.get("action"), event.get("payload")
    if not valid_site_subject(site_subject, settings):
        return refusal(403, "reader_identity_invalid", "The reader identity is not valid for this site.")
    if not isinstance(payload, dict) or not isinstance(event.get("isStaff"), bool):
        return refusal(400, "malformed_request", "The request is malformed.")
    profile = ensure_profile(store, site_subject, now_seconds)
    if action == ACTION_ME:
        return my_state(store, profile, payload, settings)
    if profile.get("state") == STATE_BANNED:
        return refusal(403, "reader_banned", "This reader cannot take part.")
    if action == ACTION_HANDLE:
        return set_handle(store, profile, payload, settings, now_seconds)
    if action == ACTION_VOTE:
        return vote_action(store, profile, payload, settings, event["isStaff"], now_seconds, schedule_snapshot)
    if action == ACTION_RATING:
        return rating_action(store, profile, payload, settings, event["isStaff"], now_seconds, schedule_snapshot)
    return refusal(400, "unknown_action", "Unknown action.")


def plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def is_conditional_failure(error: Exception) -> bool:
    return str(getattr(error, "response", {}).get("Error", {}).get("Code", "")) == "ConditionalCheckFailedException"


class DynamoReaderStore:
    """The Amplify model tables written directly: items carry ``__typename``, ``createdAt`` and ``updatedAt`` so staff can list them."""

    def __init__(self, *, resource: Any, profile_table: str, handle_table: str, vote_table: str, published_item_table: str, rate_table: str) -> None:
        self._resource = resource
        self._names = {"profile": profile_table, "handle": handle_table, "vote": vote_table, "published": published_item_table, "rate": rate_table}

    def _table(self, key: str) -> Any:
        return self._resource.Table(self._names[key])

    def get_profile(self, site_subject: str) -> dict[str, Any] | None:
        item = self._table("profile").get_item(Key={"id": site_subject}, ConsistentRead=True).get("Item")
        return plain(item) if item else None

    def create_profile(self, profile: dict[str, Any]) -> bool:
        item = {**profile, "__typename": "ReaderProfile", "updatedAt": profile["createdAt"]}
        try:
            self._table("profile").put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True

    def claim_handle(self, site_subject: str, reader_id: str, handle: str, now_iso: str) -> str:
        client = self._resource.meta.client
        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._names["handle"],
                            "Item": {"id": handle, "__typename": "ReaderHandle", "readerId": reader_id, "createdAt": now_iso, "updatedAt": now_iso},
                            "ConditionExpression": "attribute_not_exists(id)",
                        }
                    },
                    {
                        "Update": {
                            "TableName": self._names["profile"],
                            "Key": {"id": site_subject},
                            "UpdateExpression": "SET #h = :h, updatedAt = :now",
                            "ConditionExpression": "attribute_exists(id) AND attribute_not_exists(#h)",
                            "ExpressionAttributeNames": {"#h": "handle"},
                            "ExpressionAttributeValues": {":h": handle, ":now": now_iso},
                        }
                    },
                ]
            )
        except Exception as error:
            reasons = getattr(error, "response", {}).get("CancellationReasons") or []
            codes = [str(reason.get("Code", "")) for reason in reasons]
            if codes[:1] == ["ConditionalCheckFailed"]:
                return "taken"
            if codes[1:2] == ["ConditionalCheckFailed"]:
                return "already_set"
            raise
        return "claimed"

    def get_vote_values(self, vote_ids: list[str]) -> dict[str, int]:
        found: dict[str, int] = {}
        table_name = self._names["vote"]
        for start in range(0, len(vote_ids), 100):
            pending = {table_name: {"Keys": [{"id": stored_id} for stored_id in vote_ids[start : start + 100]], "ProjectionExpression": "id, #v", "ExpressionAttributeNames": {"#v": "value"}}}
            while pending:
                response = self._resource.batch_get_item(RequestItems=pending)
                for item in response.get("Responses", {}).get(table_name, []):
                    found[item["id"]] = int(item["value"])
                pending = response.get("UnprocessedKeys") or {}
        return found

    def put_vote(self, vote: dict[str, Any], now_iso: str) -> None:
        self._table("vote").update_item(
            Key={"id": vote["id"]},
            UpdateExpression=(
                "SET #t = :t, subjectKey = :s, readerId = :r, #d = :d, #v = :v, voterRole = :role, "
                "createdAt = if_not_exists(createdAt, :now), updatedAt = :now"
            ),
            ExpressionAttributeNames={"#t": "__typename", "#d": "dimension", "#v": "value"},
            ExpressionAttributeValues={
                ":t": "ReaderVote",
                ":s": vote["subjectKey"],
                ":r": vote["readerId"],
                ":d": vote["dimension"],
                ":v": vote["value"],
                ":role": vote["voterRole"],
                ":now": now_iso,
            },
        )

    def delete_vote(self, vote_id_: str) -> None:
        self._table("vote").delete_item(Key={"id": vote_id_})

    def is_published(self, subject_key: str) -> bool:
        item = self._table("published").get_item(Key={"id": PUBLISHED_ID_PREFIX + subject_key}, ProjectionExpression="#s", ExpressionAttributeNames={"#s": "status"}).get("Item")
        return bool(item) and item.get("status") == "published"

    def count_action(self, reader_id: str, bucket: str, window_start: int, limit: int, expires_at: int) -> bool:
        try:
            self._table("rate").update_item(
                Key={"pk": f"{reader_id}#{bucket}#{window_start}"},
                UpdateExpression="ADD hits :one SET expiresAt = :expires",
                ConditionExpression="attribute_not_exists(hits) OR hits < :limit",
                ExpressionAttributeValues={":one": 1, ":expires": expires_at, ":limit": limit},
            )
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True

    def claim_snapshot_slot(self, now_seconds: float, debounce_seconds: int) -> bool:
        try:
            self._table("rate").put_item(
                Item={"pk": "snapshot-debounce", "lockedUntil": int(now_seconds) + debounce_seconds, "expiresAt": int(now_seconds) + 2 * debounce_seconds + HOUR_SECONDS},
                ConditionExpression="attribute_not_exists(pk) OR lockedUntil <= :now",
                ExpressionAttributeValues={":now": int(now_seconds)},
            )
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True


def snapshot_scheduler(store: ReaderStore, settings: ReaderSettings, now_seconds: float, function_name: str, lambda_client: Any) -> Callable[[], None]:
    """At most one asynchronous reader-snapshot invoke per debounce window; a failure never fails the vote."""

    def schedule() -> None:
        if not function_name:
            return
        try:
            if not store.claim_snapshot_slot(now_seconds, settings.snapshot_debounce_seconds):
                return
            lambda_client.invoke(FunctionName=function_name, InvocationType="Event", Payload=json.dumps(SNAPSHOT_TASK).encode("utf-8"))
        except Exception as error:
            print(json.dumps({"readerSnapshotScheduleFailed": type(error).__name__}))

    return schedule


def store_from_environment(environment: dict[str, str] | None = None) -> DynamoReaderStore:
    import boto3

    environment = os.environ if environment is None else environment
    return DynamoReaderStore(
        resource=boto3.resource("dynamodb"),
        profile_table=environment["PAPYRUS_READER_PROFILE_TABLE"],
        handle_table=environment["PAPYRUS_READER_HANDLE_TABLE"],
        vote_table=environment["PAPYRUS_READER_VOTE_TABLE"],
        published_item_table=environment["PAPYRUS_READER_PUBLISHED_ITEM_TABLE"],
        rate_table=environment["PAPYRUS_READER_RATE_TABLE"],
    )


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    import boto3

    settings = settings_from_environment()
    store = store_from_environment()
    now_seconds = time.time()
    scheduler = snapshot_scheduler(
        store, settings, now_seconds, os.environ.get("PAPYRUS_READER_SNAPSHOT_FUNCTION", ""), boto3.client("lambda")
    )
    return handle_event(event, store=store, settings=settings, now_seconds=now_seconds, schedule_snapshot=scheduler)
