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

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

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
ACTION_SUBMIT = "submit"
RATE_BUCKET_REACTIONS = "react"
RATE_BUCKET_HANDLE = "handle"
RATE_BUCKET_SUBMIT = "submit"
DAY_SECONDS = 24 * HOUR_SECONDS
SUBMISSION_ID_PREFIX = "sub-"
SUBMISSION_ID = re.compile(r"sub-[0-9a-f]{24}")
SUBMISSION_DOMAIN_INDEX = "submissionsByDomain"
SUBMISSION_PENDING = "pending"
SUBMISSION_PROMOTED = "promoted"
SUBMISSION_HIDDEN = "hidden"
VISIBLE_SUBMISSION_STATES = (SUBMISSION_PENDING, SUBMISSION_PROMOTED)
EXTRACTION_PENDING = "pending"
SUBMISSION_PAYLOAD_KEYS = frozenset({"url", "title", "kind", "note"})
MAXIMUM_URL_LENGTH = 2048
MAXIMUM_TITLE_LENGTH = 200
MAXIMUM_NOTE_LENGTH = 500
MAXIMUM_SIMILAR = 5
EMAIL_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*\.)+[A-Za-z]{2,}")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SNAPSHOT_TASK = {"projectionTask": {"task": "reader-snapshot"}}
SNAPSHOT_SCHEDULE_PREFIX = "papyrus-reader-snapshot-"
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
    submissions_per_day: int = 10
    similar_hours: int = 48
    submission_kinds: tuple[str, ...] = ("link",)


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
        submissions_per_day=int((raw.get("submissions") or {}).get("perDay", defaults.submissions_per_day)),
        similar_hours=int((raw.get("submissions") or {}).get("similarHours", defaults.similar_hours)),
        submission_kinds=tuple((raw.get("submissions") or {}).get("kinds") or defaults.submission_kinds),
    )


class ReaderStore(Protocol):
    def get_profile(self, site_subject: str) -> dict[str, Any] | None: ...

    def create_profile(self, profile: dict[str, Any]) -> bool: ...

    def claim_handle(self, site_subject: str, reader_id: str, handle: str, now_iso: str) -> str: ...

    def get_vote_values(self, vote_ids: list[str]) -> dict[str, int]: ...

    def put_vote(self, vote: dict[str, Any], now_iso: str) -> None: ...

    def delete_vote(self, vote_id: str) -> None: ...

    def is_published(self, subject_key: str) -> bool: ...

    def get_submission(self, submission_id: str) -> dict[str, Any] | None: ...

    def create_submission(self, submission: dict[str, Any]) -> bool: ...

    def recent_submissions_by_domain(self, domain: str, since_iso: str) -> list[dict[str, Any]]: ...

    def count_action(self, reader_id: str, bucket: str, window_start: int, limit: int, expires_at: int) -> bool: ...

    def claim_snapshot_slot(self, now_seconds: float, debounce_seconds: int) -> int | None: ...

    def release_snapshot_slot(self, locked_until: int) -> None: ...


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
    store: ReaderStore, profile: dict[str, Any], bucket: str, limit: int, now_seconds: float, window_seconds: int = HOUR_SECONDS
) -> dict[str, Any] | None:
    window_start = int(now_seconds // window_seconds) * window_seconds
    window_end = window_start + window_seconds
    if store.count_action(profile["readerId"], bucket, window_start, limit, window_end + HOUR_SECONDS):
        return None
    return refusal(429, "rate_limited", "Too many actions. Try again later.", retryAfter=max(1, int(window_end - now_seconds)))


def new_account_limit(profile: dict[str, Any], settings: ReaderSettings, now_seconds: float, full_limit: int) -> int:
    """The limit for an action: a third (``new_account_divisor``) of it while the profile is younger than ``new_account_hours``."""
    age_hours = (now_seconds - seconds_of(profile["createdAt"])) / HOUR_SECONDS
    return max(1, full_limit // settings.new_account_divisor) if age_hours < settings.new_account_hours else full_limit


class InvalidUrl(ValueError):
    pass


def canonical_source_url(value: Any) -> str:
    """The canonical form of a source URL. Identical to ``papyrus_content.reference_intake.canonical_source_url`` (a test pins them together)."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) <= 32 for c in value):
        raise InvalidUrl("source_uri must be an HTTP(S) URL without whitespace.")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port is not None and port != {"http": 80, "https": 443}[parts.scheme.lower()]:
            host += f":{port}"
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError) as error:
        raise InvalidUrl("source_uri must be a valid HTTP(S) URL without credentials.") from error


def submission_id_for(canonical_url: str) -> str:
    return SUBMISSION_ID_PREFIX + hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:24]


def domain_of(canonical_url: str) -> str:
    return (urlsplit(canonical_url).hostname or "").lower()


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
    if not subject_is_open(store, subject):
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


def subject_is_open(store: ReaderStore, subject: str) -> bool:
    """A published item, or a submission that is visible (pending or promoted); hidden submissions cannot be voted on."""
    if SUBMISSION_ID.fullmatch(subject):
        submission = store.get_submission(subject)
        return submission is not None and submission.get("state") in VISIBLE_SUBMISSION_STATES
    return store.is_published(subject)


def clean_text(value: Any, label: str, maximum: int, *, required: bool) -> tuple[str | None, dict[str, Any] | None]:
    if value is None or value == "":
        if required:
            return None, refusal(422, f"invalid_{label}", f"Send a {label}.")
        return None, None
    if not isinstance(value, str) or CONTROL_CHARACTERS.search(value):
        return None, refusal(422, f"invalid_{label}", f"The {label} must be plain text.")
    if EMAIL_ADDRESS.search(value):
        return None, refusal(422, f"invalid_{label}", f"Public text cannot contain an email address. Remove it from the {label}.")
    text = " ".join(value.split()) if label == "title" else value.strip()
    if not text and required:
        return None, refusal(422, f"invalid_{label}", f"Send a {label}.")
    if len(text) > maximum:
        return None, refusal(422, f"invalid_{label}", f"The {label} is at most {maximum} characters.")
    return text or None, None


def public_submission(submission: dict[str, Any]) -> dict[str, Any]:
    promoted = submission.get("state") == SUBMISSION_PROMOTED and submission.get("itemId")
    return {"subject": submission["itemId"] if promoted else submission["id"], "url": submission["canonicalUrl"], "title": submission["title"], "state": submission["state"]}


def duplicate(existing: dict[str, Any]) -> dict[str, Any]:
    if existing.get("state") not in VISIBLE_SUBMISSION_STATES:
        return refusal(409, "duplicate_submission", "That link was already submitted.")
    return refusal(409, "duplicate_submission", "That link was already submitted.", existing=public_submission(existing))


def submit_action(
    store: ReaderStore,
    profile: dict[str, Any],
    payload: dict[str, Any],
    settings: ReaderSettings,
    now_seconds: float,
    schedule_snapshot: Callable[[], None],
) -> dict[str, Any]:
    if profile.get("state") == STATE_LIMITED:
        return refusal(403, "reader_limited", "This reader cannot submit right now.")
    if not profile.get("handle"):
        return refusal(422, "handle_required", "Choose a handle before submitting a link.")
    if set(payload) - SUBMISSION_PAYLOAD_KEYS:
        return refusal(422, "invalid_submission", "Send only url, title, kind and note.")
    raw_url = payload.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip() or len(raw_url) > MAXIMUM_URL_LENGTH:
        return refusal(422, "invalid_url", "Send the link as an http or https address.")
    try:
        canonical = canonical_source_url(raw_url.strip())
    except InvalidUrl:
        return refusal(422, "invalid_url", "Send the link as an http or https address.")
    if len(canonical) > MAXIMUM_URL_LENGTH or EMAIL_ADDRESS.search(canonical):
        return refusal(422, "invalid_url", "Send the link as an http or https address without an email address in it.")
    title, problem = clean_text(payload.get("title"), "title", MAXIMUM_TITLE_LENGTH, required=True)
    if problem:
        return problem
    note, problem = clean_text(payload.get("note"), "note", MAXIMUM_NOTE_LENGTH, required=False)
    if problem:
        return problem
    kind = payload.get("kind", settings.submission_kinds[0])
    if not isinstance(kind, str) or kind not in settings.submission_kinds:
        return refusal(422, "invalid_kind", "That kind is not available.")
    limit = new_account_limit(profile, settings, now_seconds, settings.submissions_per_day)
    limited = within_rate_limit(store, profile, RATE_BUCKET_SUBMIT, limit, now_seconds, DAY_SECONDS)
    if limited:
        return limited
    submission_id = submission_id_for(canonical)
    existing = store.get_submission(submission_id)
    if existing is not None:
        return duplicate(existing)
    domain = domain_of(canonical)
    since = iso(now_seconds - settings.similar_hours * HOUR_SECONDS)
    similar_rows = [
        row
        for row in store.recent_submissions_by_domain(domain, since)
        if row.get("state") in VISIBLE_SUBMISSION_STATES and row["id"] != submission_id
    ]
    similar_rows.sort(key=lambda row: row["createdAt"], reverse=True)
    similar_rows = similar_rows[:MAXIMUM_SIMILAR]
    submission = {
        "id": submission_id,
        "canonicalUrl": canonical,
        "domain": domain,
        "title": title,
        "kind": kind,
        "readerId": profile["readerId"],
        "state": SUBMISSION_PENDING,
        "similar": [row["id"] for row in similar_rows],
        "extractionState": EXTRACTION_PENDING,
        "createdAt": iso(now_seconds),
    }
    if note:
        submission["note"] = note
    if not store.create_submission(submission):
        return duplicate(store.get_submission(submission_id) or submission)
    schedule_snapshot()
    return reply(
        201,
        {
            "subject": submission_id,
            "url": canonical,
            "title": title,
            "kind": kind,
            "state": SUBMISSION_PENDING,
            "extraction": EXTRACTION_PENDING,
            "similar": [{"subject": row["id"], "url": row["canonicalUrl"], "title": row["title"]} for row in similar_rows],
        },
    )


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
    if action == ACTION_SUBMIT:
        return submit_action(store, profile, payload, settings, now_seconds, schedule_snapshot)
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

    def __init__(
        self,
        *,
        resource: Any,
        profile_table: str,
        handle_table: str,
        vote_table: str,
        published_item_table: str,
        rate_table: str,
        submission_table: str = "",
    ) -> None:
        self._resource = resource
        self._names = {
            "profile": profile_table,
            "handle": handle_table,
            "vote": vote_table,
            "published": published_item_table,
            "rate": rate_table,
            "submission": submission_table,
        }

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

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        item = self._table("submission").get_item(Key={"id": submission_id}, ConsistentRead=True).get("Item")
        return plain(item) if item else None

    def create_submission(self, submission: dict[str, Any]) -> bool:
        item = {**submission, "__typename": "ReaderSubmission", "updatedAt": submission["createdAt"]}
        try:
            self._table("submission").put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True

    def recent_submissions_by_domain(self, domain: str, since_iso: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        rows: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "IndexName": SUBMISSION_DOMAIN_INDEX,
            "KeyConditionExpression": Key("domain").eq(domain) & Key("createdAt").gte(since_iso),
        }
        while True:
            page = self._table("submission").query(**kwargs)
            rows.extend(plain(item) for item in page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                return rows
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

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

    def claim_snapshot_slot(self, now_seconds: float, debounce_seconds: int) -> int | None:
        """Opens a debounce window and returns when it closes, or ``None`` when a window is already open."""
        locked_until = int(now_seconds) + debounce_seconds
        try:
            self._table("rate").put_item(
                Item={"pk": "snapshot-debounce", "lockedUntil": locked_until, "expiresAt": locked_until + debounce_seconds + HOUR_SECONDS},
                ConditionExpression="attribute_not_exists(pk) OR lockedUntil <= :now",
                ExpressionAttributeValues={":now": int(now_seconds)},
            )
        except Exception as error:
            if is_conditional_failure(error):
                return None
            raise
        return locked_until

    def release_snapshot_slot(self, locked_until: int) -> None:
        """Reopens the window this call opened, so the next write can schedule the run that failed to schedule."""
        try:
            self._table("rate").delete_item(
                Key={"pk": "snapshot-debounce"},
                ConditionExpression="lockedUntil = :until",
                ExpressionAttributeValues={":until": locked_until},
            )
        except Exception as error:
            if not is_conditional_failure(error):
                raise


def snapshot_schedule_name(locked_until: int) -> str:
    return f"{SNAPSHOT_SCHEDULE_PREFIX}{locked_until}"


def snapshot_scheduler(
    store: ReaderStore, settings: ReaderSettings, now_seconds: float, target: "SnapshotTarget | None", scheduler_client: Any
) -> Callable[[], None]:
    """Trailing-edge debounce: the first write in a window schedules one run at the end of the window.

    Later writes in the window schedule nothing, because the run at the end of the window reads them all. A failure never
    fails the vote; it reopens the window so the next write tries again.
    """

    def schedule() -> None:
        if target is None:
            return
        locked_until = None
        try:
            locked_until = store.claim_snapshot_slot(now_seconds, settings.snapshot_debounce_seconds)
            if locked_until is None:
                return
            scheduler_client.create_schedule(
                Name=snapshot_schedule_name(locked_until),
                ScheduleExpression="at(" + time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(locked_until)) + ")",
                ScheduleExpressionTimezone="UTC",
                FlexibleTimeWindow={"Mode": "OFF"},
                ActionAfterCompletion="DELETE",
                Target={
                    "Arn": target.function_arn,
                    "RoleArn": target.role_arn,
                    "Input": json.dumps(SNAPSHOT_TASK),
                    "RetryPolicy": {"MaximumRetryAttempts": 0},
                },
            )
        except Exception as error:
            print(json.dumps({"readerSnapshotScheduleFailed": type(error).__name__}))
            if locked_until is not None and type(error).__name__ != "ConflictException":
                try:
                    store.release_snapshot_slot(locked_until)
                except Exception as release_error:
                    print(json.dumps({"readerSnapshotReleaseFailed": type(release_error).__name__}))

    return schedule


@dataclass(frozen=True)
class SnapshotTarget:
    function_arn: str
    role_arn: str


def snapshot_target_from_environment(environment: dict[str, str] | None = None) -> SnapshotTarget | None:
    environment = os.environ if environment is None else environment
    function_arn = environment.get("PAPYRUS_READER_SNAPSHOT_FUNCTION_ARN", "")
    role_arn = environment.get("PAPYRUS_READER_SCHEDULER_ROLE_ARN", "")
    return SnapshotTarget(function_arn, role_arn) if function_arn and role_arn else None


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
        submission_table=environment.get("PAPYRUS_READER_SUBMISSION_TABLE", ""),
    )


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    import boto3

    settings = settings_from_environment()
    store = store_from_environment()
    now_seconds = time.time()
    scheduler = snapshot_scheduler(store, settings, now_seconds, snapshot_target_from_environment(), boto3.client("scheduler"))
    return handle_event(event, store=store, settings=settings, now_seconds=now_seconds, schedule_snapshot=scheduler)
