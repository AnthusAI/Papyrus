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
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

_FUNCTION_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if _FUNCTION_DIRECTORY not in sys.path:  # a Lambda already has its code directory on the path; a test loading this file by path does not
    sys.path.insert(0, _FUNCTION_DIRECTORY)
import ai_moderation  # noqa: E402
import moderation as moderation_rules  # noqa: E402
import proposals as proposal_rules  # noqa: E402

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
ACTION_COMMENT = "comment"
ACTION_REPORT = "report"
ACTION_FLAG = "flag"
SUBJECT_TYPE_ITEM = "item"
SUBJECT_TYPE_SUBMISSION = "submission"
SUBJECT_TYPES = (SUBJECT_TYPE_ITEM, SUBJECT_TYPE_SUBMISSION, "story", "proposal", "concept")
DEFAULT_SUBJECT_TYPES = (SUBJECT_TYPE_ITEM, SUBJECT_TYPE_SUBMISSION)
SUBJECT_ID = re.compile(r"[A-Za-z0-9._:-]{1,190}")
VOTE_DIMENSION = "up"
VOTE_PAYLOAD_KEYS = frozenset({"subject", "value"})
FLAG_WRONG = "wrong"
FLAG_BELONGS_UNDER = "belongs_under"
FLAG_BETTER_NAME = "better_name"
FLAG_KINDS = (FLAG_WRONG, FLAG_BELONGS_UNDER, FLAG_BETTER_NAME)
FLAG_PAYLOAD_KEYS = frozenset({"subject", "kind", "reason", "target", "name"})
MAXIMUM_FLAG_REASON = 500
MAXIMUM_SUGGESTED_NAME = 120
RATE_BUCKET_REPORT = "report"
REPORT_ID_PREFIX = "rep-"
MAXIMUM_REPORT_REASON = 500
MODERATION_MODES = ("off", "human", "ai")
AI_WORKER = "ai-review"
AI_TASK = {"worker": AI_WORKER}
AI_DEADLINE_MARGIN_SECONDS = 12
ACTION_COMMENT_EDIT = "comment-edit"
ACTION_COMMENT_DELETE = "comment-delete"
RATE_BUCKET_COMMENT = "comment"
COMMENT_ID_PREFIX = "cmt-"
COMMENT_ID = re.compile(r"cmt-[0-9a-f]{32}")
COMMENT_VISIBLE = "visible"
COMMENT_HIDDEN = "hidden"
COMMENT_DELETED = "deleted"
COMMENT_PAYLOAD_KEYS = frozenset({"subject", "body", "parent", "ratingContext"})
COMMENT_EDIT_KEYS = frozenset({"id", "body"})
COMMENT_DELETE_KEYS = frozenset({"id"})
LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
TEXT_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
RATE_BUCKET_REACTIONS = "react"
RATE_BUCKET_HANDLE = "handle"
RATE_BUCKET_SUBMIT = "submit"
DAY_SECONDS = 24 * HOUR_SECONDS
SUBMISSION_ID_PREFIX = "sub-"
SUBMISSION_ID = re.compile(r"sub-[0-9a-f]{24}")
SUBMISSION_DOMAIN_INDEX = "submissionsByDomain"
PROFILE_READER_INDEX = "profilesByReader"
REPORT_TARGET_INDEX = "reportsByTarget"
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
    comments_per_hour: int = 30
    comment_edit_minutes: int = 10
    comment_maximum_length: int = 2000
    comment_maximum_links: int = 3
    moderation_mode: str = "human"
    pre_moderation: bool = False
    reports_per_day: int = 20
    promote_item_type: str = "brief"
    promote_section: str = "unsectioned"
    ai_model: str = ai_moderation.DEFAULT_MODEL
    ai_key_parameter: str = ""
    subject_types: tuple[str, ...] = DEFAULT_SUBJECT_TYPES


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
        comments_per_hour=int((raw.get("comments") or {}).get("perHour", defaults.comments_per_hour)),
        comment_edit_minutes=int((raw.get("comments") or {}).get("editWindowMinutes", defaults.comment_edit_minutes)),
        comment_maximum_length=int((raw.get("comments") or {}).get("maximumLength", defaults.comment_maximum_length)),
        comment_maximum_links=int((raw.get("comments") or {}).get("maximumLinks", defaults.comment_maximum_links)),
        moderation_mode=str((raw.get("moderation") or {}).get("mode", defaults.moderation_mode)),
        pre_moderation=bool((raw.get("moderation") or {}).get("preModeration", defaults.pre_moderation)),
        reports_per_day=int((raw.get("moderation") or {}).get("reportsPerDay", defaults.reports_per_day)),
        ai_model=str(((raw.get("moderation") or {}).get("ai") or {}).get("model", defaults.ai_model)),
        ai_key_parameter=str(((raw.get("moderation") or {}).get("ai") or {}).get("apiKeyParameter", defaults.ai_key_parameter)),
        subject_types=tuple((raw.get("subjects") or {}).get("types") or defaults.subject_types),
        promote_item_type=str((raw.get("submissions") or {}).get("itemType", defaults.promote_item_type)),
        promote_section=str((raw.get("submissions") or {}).get("section", defaults.promote_section)),
    )


class ReaderStore(Protocol):
    def get_profile(self, site_subject: str) -> dict[str, Any] | None: ...

    def create_profile(self, profile: dict[str, Any]) -> bool: ...

    def claim_handle(self, site_subject: str, reader_id: str, handle: str, now_iso: str) -> str: ...

    def get_vote_values(self, vote_ids: list[str]) -> dict[str, int]: ...

    def put_vote(self, vote: dict[str, Any], now_iso: str) -> None: ...

    def delete_vote(self, vote_id: str) -> None: ...

    def put_flag(self, flag: dict[str, Any], now_iso: str) -> None: ...

    def is_published(self, subject_key: str) -> bool: ...

    def get_submission(self, submission_id: str) -> dict[str, Any] | None: ...

    def create_submission(self, submission: dict[str, Any]) -> bool: ...

    def recent_submissions_by_domain(self, domain: str, since_iso: str) -> list[dict[str, Any]]: ...

    def get_comment(self, comment_id: str) -> dict[str, Any] | None: ...

    def create_comment(self, comment: dict[str, Any]) -> None: ...

    def update_comment(self, comment_id: str, changes: dict[str, Any], now_iso: str, *, expected_state: str) -> bool: ...

    def put_report(self, report: dict[str, Any], target_key: str, target_table: str, now_iso: str) -> bool: ...

    def get_profile_by_reader(self, reader_id: str) -> dict[str, Any] | None: ...

    def get_action(self, action_id: str) -> dict[str, Any] | None: ...

    def transact_moderation(self, action: dict[str, Any], target_type: str, target_key: str, plan: Any, *, undoes: str | None = None) -> str: ...

    def close_reports(self, target: str, now_iso: str) -> int: ...

    def new_content(self) -> list[tuple[str, dict[str, Any]]]: ...

    def human_acted_on(self) -> set[str]: ...

    def count_action(self, reader_id: str, bucket: str, window_start: int, limit: int, expires_at: int) -> bool: ...

    def claim_snapshot_slot(self, now_seconds: float, debounce_seconds: int) -> int | None: ...

    def release_snapshot_slot(self, locked_until: int) -> None: ...


def reply(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "body": body}


def refusal(status: int, error: str, message: str, **extra: Any) -> dict[str, Any]:
    return reply(status, {"error": error, "message": message, **extra})


def iso(now_seconds: float) -> str:
    """UTC with milliseconds, so rows written in the same second still sort in the order they were written."""
    moment = datetime.fromtimestamp(now_seconds, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def seconds_of(iso_text: str) -> float:
    return datetime.strptime(iso_text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def vote_id(subject_key: str, reader_id: str, dimension: str) -> str:
    return f"{subject_key}#{reader_id}#{dimension}"


def subject_key(subject_type: str, subject_id: str) -> str:
    """The key a vote is stored under: items and submissions keep their bare id (so every vote written before subject types stays valid); other types are prefixed."""
    return subject_id if subject_type in (SUBJECT_TYPE_ITEM, SUBJECT_TYPE_SUBMISSION) else f"{subject_type}:{subject_id}"


def legacy_subject_type(key: str) -> str:
    """The type of a bare subject key: a submission id, otherwise an item."""
    return SUBJECT_TYPE_SUBMISSION if SUBMISSION_ID.fullmatch(key) else SUBJECT_TYPE_ITEM


def parse_subject(raw: Any, settings: ReaderSettings) -> tuple[tuple[str, str] | None, dict[str, Any] | None]:
    """``({type, id}) -> (type, id)``, or a refusal. A bare string is a subject written before subject types: its type is read from its shape."""
    if isinstance(raw, str):
        raw = {"type": legacy_subject_type(raw), "id": raw}
    if not isinstance(raw, dict) or set(raw) != {"type", "id"} or not isinstance(raw["type"], str) or not isinstance(raw["id"], str):
        return None, refusal(422, "invalid_subject", "Send the subject as {type, id}.")
    subject_type, subject_id = raw["type"], raw["id"]
    if subject_type not in SUBJECT_TYPES or subject_type not in settings.subject_types:
        return None, refusal(422, "unknown_subject_type", "That kind of subject cannot be voted on here.")
    if not SUBJECT_ID.fullmatch(subject_id):
        return None, refusal(422, "invalid_subject", "Send the id of the subject.")
    return (subject_type, subject_id), None


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
    raw_subjects = payload.get("subjects", [])
    if not isinstance(raw_subjects, list) or len(raw_subjects) > MAXIMUM_SUBJECTS:
        return refusal(422, "invalid_subjects", f"Send at most {MAXIMUM_SUBJECTS} subjects.")
    subjects: list[str] = []
    for raw in raw_subjects:
        if isinstance(raw, str) and SUBJECT_KEY.fullmatch(raw):
            subjects.append(raw)
            continue
        parsed, _ = parse_subject(raw, settings) if isinstance(raw, dict) else (None, None)
        if parsed is None:
            return refusal(422, "invalid_subjects", f"Send at most {MAXIMUM_SUBJECTS} subject keys or {{type, id}} subjects.")
        subjects.append(subject_key(*parsed))
    dimensions = [*TOGGLE_DIMENSIONS, *settings.dimensions]
    wanted = {vote_id(subject, profile["readerId"], dimension): (subject, dimension) for subject in subjects for dimension in dimensions}
    found = store.get_vote_values(list(wanted))
    votes: dict[str, dict[str, int]] = {}
    for stored_id, value in found.items():
        subject, dimension = wanted[stored_id]
        votes.setdefault(subject, {})[dimension] = value
    # The reader's own up (1) or down (-1) vote per requested subject, by subject key (the key format of items.json).
    subject_votes = {subject: held["up"] for subject, held in votes.items() if held.get("up") in (1, -1)}
    return reply(200, {**public_profile(profile), "votes": votes, "subjectVotes": subject_votes})


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
    parsed, refused = parse_subject(subject, settings)
    if refused:
        return refused
    subject_type, subject_id = parsed
    subject = subject_key(subject_type, subject_id)
    if not isinstance(dimension, str) or dimension not in allowed_dimensions:
        return refusal(422, "invalid_dimension", "That dimension is not available.")
    if profile.get("state") == STATE_BANNED:
        return refusal(403, "reader_banned", "This reader cannot take part.")
    if profile.get("state") == STATE_LIMITED:
        return refusal(403, "reader_limited", "This reader cannot vote or rate right now.")
    limited = within_rate_limit(store, profile, RATE_BUCKET_REACTIONS, action_limit(profile, settings, now_seconds), now_seconds)
    if limited:
        return limited
    if not subject_is_open(store, subject_type, subject_id):
        return refusal(404, "unknown_subject", "That item is not published.")
    stored_id = vote_id(subject, profile["readerId"], dimension)
    if value is None:
        store.delete_vote(stored_id)
    else:
        store.put_vote(
            {
                "id": stored_id,
                "subjectKey": subject,
                "subjectType": subject_type,
                "readerId": profile["readerId"],
                "dimension": dimension,
                "value": value,
                "voterRole": ROLE_EDITOR if is_staff else ROLE_READER,
            },
            iso(now_seconds),
        )
    schedule_snapshot()
    return reply(200, {"subject": subject, "dimension": dimension, "value": value})


def subject_is_open(store: ReaderStore, subject_type: str, subject_id: str) -> bool:
    """A published item, or a submission that is visible (pending or promoted); hidden submissions cannot be voted on.

    The other subject types have no record in this plugin (stories, proposals and concepts live in the site's own data), so any well-formed id is open.
    """
    if subject_type == SUBJECT_TYPE_SUBMISSION:
        submission = store.get_submission(subject_id)
        return submission is not None and submission.get("state") in VISIBLE_SUBMISSION_STATES
    if subject_type == SUBJECT_TYPE_ITEM:
        return store.is_published(subject_id)
    return True


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


def new_content_fields(settings: ReaderSettings, visible: str) -> dict[str, Any]:
    """``state`` and ``moderation`` for a new submission or comment.

    With moderation off nothing waits in a queue. With pre-moderation the item starts hidden ("held") until a moderator approves it.
    """
    if settings.moderation_mode == "off":
        return {"state": visible, "moderation": moderation_rules.MODERATION_APPROVED}
    if settings.pre_moderation:
        return {"state": "hidden", "moderation": moderation_rules.MODERATION_NEW}
    return {"state": visible, "moderation": moderation_rules.MODERATION_NEW}


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
        **new_content_fields(settings, SUBMISSION_PENDING),
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
            "state": "held" if submission["state"] == SUBMISSION_HIDDEN else SUBMISSION_PENDING,
            "extraction": EXTRACTION_PENDING,
            "similar": [{"subject": row["id"], "url": row["canonicalUrl"], "title": row["title"]} for row in similar_rows],
        },
    )


def clean_comment_body(value: Any, settings: ReaderSettings) -> tuple[str | None, dict[str, Any] | None]:
    """Plain text, trimmed, at most ``comment_maximum_length`` characters, ``comment_maximum_links`` links, no email address."""
    if not isinstance(value, str):
        return None, refusal(422, "invalid_body", "Send the comment as text.")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None, refusal(422, "invalid_body", "Write something first.")
    if TEXT_CONTROL_CHARACTERS.search(text):
        return None, refusal(422, "invalid_body", "A comment is plain text.")
    if len(text) > settings.comment_maximum_length:
        return None, refusal(422, "body_too_long", f"A comment is at most {settings.comment_maximum_length} characters.")
    if len(LINK.findall(text)) > settings.comment_maximum_links:
        return None, refusal(422, "too_many_links", f"A comment has at most {settings.comment_maximum_links} links.")
    if EMAIL_ADDRESS.search(text):
        return None, refusal(422, "invalid_body", "Public text cannot contain an email address. Remove it from the comment.")
    return text, None


def writes_comments(profile: dict[str, Any]) -> dict[str, Any] | None:
    if profile.get("state") == STATE_LIMITED:
        return refusal(403, "reader_limited", "This reader cannot comment right now.")
    if not profile.get("handle"):
        return refusal(422, "handle_required", "Choose a handle before commenting.")
    return None


def rating_context_for(store: ReaderStore, profile: dict[str, Any], subject: str, raw: Any, settings: ReaderSettings) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The rating a comment explains must be the reader's own current vote, so a comment cannot claim a rating nobody gave."""
    if raw is None:
        return None, None
    if not isinstance(raw, dict) or set(raw) != {"dimension", "value"}:
        return None, refusal(422, "invalid_rating_context", "Send ratingContext as {dimension, value}.")
    dimension, value = raw["dimension"], raw["value"]
    if not isinstance(dimension, str) or dimension not in (*TOGGLE_DIMENSIONS, *settings.dimensions) or isinstance(value, bool) or not isinstance(value, int):
        return None, refusal(422, "invalid_rating_context", "That rating context is not available.")
    stored = store.get_vote_values([vote_id(subject, profile["readerId"], dimension)])
    if stored.get(vote_id(subject, profile["readerId"], dimension)) != value:
        return None, refusal(422, "rating_context_mismatch", "Rate or vote first; a comment can only explain your own current rating.")
    return {"dimension": dimension, "value": value}, None


def comment_action(
    store: ReaderStore,
    profile: dict[str, Any],
    payload: dict[str, Any],
    settings: ReaderSettings,
    now_seconds: float,
    schedule_snapshot: Callable[[], None],
) -> dict[str, Any]:
    problem = writes_comments(profile)
    if problem:
        return problem
    if set(payload) - COMMENT_PAYLOAD_KEYS:
        return refusal(422, "invalid_comment", "Send only subject, body, parent and ratingContext.")
    subject = payload.get("subject")
    if not isinstance(subject, str) or not SUBJECT_KEY.fullmatch(subject):
        return refusal(422, "invalid_subject", "Send the key of a published item.")
    body, problem = clean_comment_body(payload.get("body"), settings)
    if problem:
        return problem
    parent_id = payload.get("parent")
    if parent_id is not None and (not isinstance(parent_id, str) or not COMMENT_ID.fullmatch(parent_id)):
        return refusal(422, "invalid_parent", "That comment cannot be replied to.")
    context, problem = rating_context_for(store, profile, subject, payload.get("ratingContext"), settings)
    if problem:
        return problem
    if context is not None and parent_id is not None:
        return refusal(422, "invalid_rating_context", "A reply does not explain a rating.")
    limited = within_rate_limit(store, profile, RATE_BUCKET_COMMENT, new_account_limit(profile, settings, now_seconds, settings.comments_per_hour), now_seconds)
    if limited:
        return limited
    if not subject_is_open(store, legacy_subject_type(subject), subject):
        return refusal(404, "unknown_subject", "That item is not published.")
    if parent_id is not None:
        parent = store.get_comment(parent_id)
        if parent is None or parent.get("subjectKey") != subject or parent.get("parentId") or parent.get("state") != COMMENT_VISIBLE:
            return refusal(422, "invalid_parent", "That comment cannot be replied to.")
    comment_id = COMMENT_ID_PREFIX + uuid.uuid4().hex
    created = iso(now_seconds)
    comment = {
        "id": comment_id,
        "subjectKey": subject,
        "readerId": profile["readerId"],
        "body": body,
        **new_content_fields(settings, COMMENT_VISIBLE),
        "createdAt": created,
    }
    if parent_id is not None:
        comment["parentId"] = parent_id
    if context is not None:
        comment["ratingContext"] = json.dumps(context, separators=(",", ":"))
    store.create_comment(comment)
    schedule_snapshot()
    return reply(
        201,
        {
            "id": comment_id, "subject": subject, "parent": parent_id, "body": body, "createdAt": created, "ratingContext": context,
            "state": "held" if comment["state"] == COMMENT_HIDDEN else COMMENT_VISIBLE,
        },
    )


def report_action(
    store: ReaderStore,
    profile: dict[str, Any],
    payload: dict[str, Any],
    settings: ReaderSettings,
    now_seconds: float,
    schedule_snapshot: Callable[[], None],
) -> dict[str, Any]:
    """A reader reports a visible submission or comment; it goes back to the moderation queue. One report per reader and target."""
    if set(payload) - {"target", "reason"}:
        return refusal(422, "invalid_report", "Send only target and reason.")
    target = payload.get("target")
    target_type = moderation_rules.target_type_of(target) if isinstance(target, str) else None
    if target_type not in (moderation_rules.TARGET_SUBMISSION, moderation_rules.TARGET_COMMENT):
        return refusal(422, "invalid_target", "Report a submission or a comment.")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > MAXIMUM_REPORT_REASON or CONTROL_CHARACTERS.search(reason):
        return refusal(422, "invalid_reason", f"Give a reason in plain text of at most {MAXIMUM_REPORT_REASON} characters.")
    limited = within_rate_limit(
        store, profile, RATE_BUCKET_REPORT, new_account_limit(profile, settings, now_seconds, settings.reports_per_day), now_seconds, DAY_SECONDS
    )
    if limited:
        return limited
    row = store.get_submission(target) if target_type == moderation_rules.TARGET_SUBMISSION else store.get_comment(target)
    visible = VISIBLE_SUBMISSION_STATES if target_type == moderation_rules.TARGET_SUBMISSION else (COMMENT_VISIBLE,)
    if row is None or row.get("state") not in visible:
        return refusal(404, "unknown_target", "That cannot be reported.")
    report = {
        "id": REPORT_ID_PREFIX + hashlib.sha256(f"{profile['readerId']}#{target}".encode("utf-8")).hexdigest()[:24],
        "targetType": target_type,
        "target": target,
        "reporterReaderId": profile["readerId"],
        "reason": reason.strip(),
        "state": "open",
        "createdAt": iso(now_seconds),
    }
    store.put_report(report, target, "submission" if target_type == moderation_rules.TARGET_SUBMISSION else "comment", iso(now_seconds))
    return reply(200, {"reported": True})


def flag_action(
    store: ReaderStore,
    profile: dict[str, Any],
    payload: dict[str, Any],
    settings: ReaderSettings,
    is_staff: bool,
    now_seconds: float,
    schedule_snapshot: Callable[[], None],
) -> dict[str, Any]:
    """A reader flags a subject as wrong, as belonging under another subject, or as needing a better name; a reason is required.

    One flag per reader, subject and kind: flagging again replaces the reason. Flags are stored apart from votes and reach the
    snapshot as counts only. The stored row holds the readerId, never a siteSubject.
    """
    if set(payload) - FLAG_PAYLOAD_KEYS:
        return refusal(422, "invalid_flag", "Send subject, kind, reason, and target or name for the kind.")
    kind = payload.get("kind")
    if kind not in FLAG_KINDS:
        return refusal(422, "invalid_flag_kind", f"Send kind as one of {', '.join(FLAG_KINDS)}.")
    parsed, refused = parse_subject(payload.get("subject"), settings)
    if refused:
        return refused
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > MAXIMUM_FLAG_REASON or CONTROL_CHARACTERS.search(reason):
        return refusal(422, "invalid_reason", f"Give a reason in plain text of at most {MAXIMUM_FLAG_REASON} characters.")
    if EMAIL_ADDRESS.search(reason):
        return refusal(422, "invalid_reason", "A reason cannot contain an email address.")
    target_key: str | None = None
    suggested: str | None = None
    if kind == FLAG_BELONGS_UNDER:
        target, refused = parse_subject(payload.get("target"), settings) if isinstance(payload.get("target"), dict) else (None, True)
        if refused or "name" in payload:
            return refusal(422, "invalid_target", "Send target as {type, id} for belongs_under.")
        target_key = subject_key(*target)
        if target_key == subject_key(*parsed):
            return refusal(422, "invalid_target", "A subject cannot belong under itself.")
    elif kind == FLAG_BETTER_NAME:
        suggested, refused = clean_text(payload.get("name"), "name", MAXIMUM_SUGGESTED_NAME, required=True)
        if refused or "target" in payload:
            return refused or refusal(422, "invalid_name", "Send name for better_name.")
    elif "target" in payload or "name" in payload:
        return refusal(422, "invalid_flag", "wrong takes only a reason.")
    if profile.get("state") == STATE_LIMITED:
        return refusal(403, "reader_limited", "This reader cannot flag right now.")
    limited = within_rate_limit(store, profile, RATE_BUCKET_REACTIONS, action_limit(profile, settings, now_seconds), now_seconds)
    if limited:
        return limited
    subject_type, subject_id = parsed
    if not subject_is_open(store, subject_type, subject_id):
        return refusal(404, "unknown_subject", "That subject cannot be flagged.")
    key = subject_key(subject_type, subject_id)
    store.put_flag(
        {
            "id": f"{key}#{profile['readerId']}#{kind}",
            "subjectKey": key,
            "subjectType": subject_type,
            "readerId": profile["readerId"],
            "kind": kind,
            "reason": reason.strip(),
            "targetKey": target_key,
            "suggestedName": suggested,
            "voterRole": ROLE_EDITOR if is_staff else ROLE_READER,
        },
        iso(now_seconds),
    )
    schedule_snapshot()
    return reply(200, {"subject": payload["subject"], "kind": kind})


def own_comment(store: ReaderStore, profile: dict[str, Any], payload: dict[str, Any], allowed: frozenset[str]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if set(payload) - allowed:
        return None, refusal(422, "invalid_comment", "Send only " + ", ".join(sorted(allowed)) + ".")
    comment_id = payload.get("id")
    if not isinstance(comment_id, str) or not COMMENT_ID.fullmatch(comment_id):
        return None, refusal(404, "unknown_comment", "That comment does not exist.")
    comment = store.get_comment(comment_id)
    if comment is None or comment.get("readerId") != profile["readerId"] or comment.get("state") == COMMENT_HIDDEN:
        return None, refusal(404, "unknown_comment", "That comment does not exist.")
    return comment, None


def edit_comment_action(
    store: ReaderStore,
    profile: dict[str, Any],
    payload: dict[str, Any],
    settings: ReaderSettings,
    now_seconds: float,
    schedule_snapshot: Callable[[], None],
) -> dict[str, Any]:
    problem = writes_comments(profile)
    if problem:
        return problem
    comment, problem = own_comment(store, profile, payload, COMMENT_EDIT_KEYS)
    if problem:
        return problem
    if comment.get("state") != COMMENT_VISIBLE:
        return refusal(409, "comment_deleted", "A deleted comment cannot be edited.")
    if now_seconds - seconds_of(comment["createdAt"]) > settings.comment_edit_minutes * 60:
        return refusal(403, "edit_window_closed", f"A comment can be edited for {settings.comment_edit_minutes} minutes after it is posted.")
    body, problem = clean_comment_body(payload.get("body"), settings)
    if problem:
        return problem
    limited = within_rate_limit(store, profile, RATE_BUCKET_COMMENT, new_account_limit(profile, settings, now_seconds, settings.comments_per_hour), now_seconds)
    if limited:
        return limited
    edited = iso(now_seconds)
    if not store.update_comment(comment["id"], {"body": body, "editedAt": edited, "reviewedAt": None, "signals": None}, edited, expected_state=COMMENT_VISIBLE):
        return refusal(409, "comment_changed", "That comment changed. Reload and try again.")
    schedule_snapshot()
    return reply(200, {"id": comment["id"], "body": body, "editedAt": edited})


def delete_comment_action(
    store: ReaderStore,
    profile: dict[str, Any],
    payload: dict[str, Any],
    settings: ReaderSettings,
    now_seconds: float,
    schedule_snapshot: Callable[[], None],
) -> dict[str, Any]:
    comment, problem = own_comment(store, profile, payload, COMMENT_DELETE_KEYS)
    if problem:
        return problem
    if comment.get("state") == COMMENT_DELETED:
        return reply(200, {"id": comment["id"], "state": COMMENT_DELETED})
    deleted = iso(now_seconds)
    if not store.update_comment(comment["id"], {"body": "", "deletedAt": deleted, "state": COMMENT_DELETED, "ratingContext": None}, deleted, expected_state=COMMENT_VISIBLE):
        return refusal(409, "comment_changed", "That comment changed. Reload and try again.")
    schedule_snapshot()
    return reply(200, {"id": comment["id"], "state": COMMENT_DELETED})


def typed_vote_action(store, profile, payload, settings, is_staff, now_seconds, schedule_snapshot):
    """``{subject: {type, id}, value: 1 | -1 | null}``: an up or down vote on any enabled subject type; ``null`` removes the reader's vote."""
    value = payload.get("value")
    if set(payload) - VOTE_PAYLOAD_KEYS or isinstance(value, bool) or value not in (1, -1, None):
        return refusal(422, "invalid_vote", "Send only subject and value, and value as 1, -1 or null.")
    answer = react(
        store, profile, subject=payload.get("subject"), dimension=VOTE_DIMENSION, allowed_dimensions=(VOTE_DIMENSION,),
        value=value, is_staff=is_staff, settings=settings, now_seconds=now_seconds, schedule_snapshot=schedule_snapshot,
    )
    if answer["statusCode"] == 200:
        answer = reply(200, {"subject": payload["subject"], "value": value})
    return answer


def vote_action(store, profile, payload, settings, is_staff, now_seconds, schedule_snapshot):
    if isinstance(payload.get("subject"), dict):
        return typed_vote_action(store, profile, payload, settings, is_staff, now_seconds, schedule_snapshot)
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
    if action == ACTION_COMMENT:
        return comment_action(store, profile, payload, settings, now_seconds, schedule_snapshot)
    if action == ACTION_COMMENT_EDIT:
        return edit_comment_action(store, profile, payload, settings, now_seconds, schedule_snapshot)
    if action == ACTION_COMMENT_DELETE:
        return delete_comment_action(store, profile, payload, settings, now_seconds, schedule_snapshot)
    if action == ACTION_REPORT:
        return report_action(store, profile, payload, settings, now_seconds, schedule_snapshot)
    if action == ACTION_FLAG:
        return flag_action(store, profile, payload, settings, event["isStaff"], now_seconds, schedule_snapshot)
    return refusal(400, "unknown_action", "Unknown action.")


def plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def _without_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}


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
        comment_table: str = "",
        report_table: str = "",
        action_table: str = "",
        item_table: str = "",
        proposal_table: str = "",
        flag_table: str = "",
    ) -> None:
        self._resource = resource
        self._names = {
            "profile": profile_table,
            "handle": handle_table,
            "vote": vote_table,
            "published": published_item_table,
            "rate": rate_table,
            "submission": submission_table,
            "comment": comment_table,
            "report": report_table,
            "action": action_table,
            "item": item_table,
            "proposal": proposal_table,
            "flag": flag_table,
        }

    def _table(self, key: str) -> Any:
        return self._resource.Table(self._names[key])

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        item = self._table("proposal").get_item(Key={"id": proposal_id}, ConsistentRead=True).get("Item")
        return plain(item) if item else None

    def create_proposal(self, row: dict[str, Any]) -> bool:
        item = {**_without_none(row), "__typename": "Proposal", "updatedAt": row["createdAt"]}
        try:
            self._table("proposal").put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True

    def change_proposal(self, proposal_id: str, changes: dict[str, Any], expected_state: str, now_iso: str, *, expected_updated_at: str | None = None) -> bool:
        """Apply ``changes`` if the state (and, when given, ``updatedAt``) is still what the caller saw; a value of ``None`` removes the attribute."""
        names = {"#st": "state", "#u": "updatedAt", **{f"#c{index}": key for index, key in enumerate(changes)}}
        sets = ", ".join(f"#c{index} = :c{index}" for index, value in enumerate(changes.values()) if value is not None)
        removes = ", ".join(f"#c{index}" for index, value in enumerate(changes.values()) if value is None)
        values = {":expected": expected_state, ":now": now_iso, **{f":c{index}": value for index, value in enumerate(changes.values()) if value is not None}}
        condition = "#st = :expected"
        if expected_updated_at is not None:
            condition += " AND #u = :seen"
            values[":seen"] = expected_updated_at
        expression = f"SET {sets + ', ' if sets else ''}#u = :now" + (f" REMOVE {removes}" if removes else "")
        try:
            self._table("proposal").update_item(
                Key={"id": proposal_id},
                UpdateExpression=expression,
                ConditionExpression=condition,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True

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
                "SET #t = :t, subjectKey = :s, subjectType = :st, readerId = :r, #d = :d, #v = :v, voterRole = :role, "
                "createdAt = if_not_exists(createdAt, :now), updatedAt = :now"
            ),
            ExpressionAttributeNames={"#t": "__typename", "#d": "dimension", "#v": "value"},
            ExpressionAttributeValues={
                ":t": "ReaderVote",
                ":s": vote["subjectKey"],
                ":st": vote.get("subjectType") or legacy_subject_type(vote["subjectKey"]),
                ":r": vote["readerId"],
                ":d": vote["dimension"],
                ":v": vote["value"],
                ":role": vote["voterRole"],
                ":now": now_iso,
            },
        )

    def delete_vote(self, vote_id_: str) -> None:
        self._table("vote").delete_item(Key={"id": vote_id_})

    def put_flag(self, flag: dict[str, Any], now_iso: str) -> None:
        self._table("flag").put_item(Item=_without_none({**flag, "__typename": "ReaderFlag", "createdAt": now_iso, "updatedAt": now_iso}))

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

    def get_comment(self, comment_id: str) -> dict[str, Any] | None:
        item = self._table("comment").get_item(Key={"id": comment_id}, ConsistentRead=True).get("Item")
        return plain(item) if item else None

    def create_comment(self, comment: dict[str, Any]) -> None:
        self._table("comment").put_item(
            Item={**comment, "__typename": "ReaderComment", "updatedAt": comment["createdAt"]}, ConditionExpression="attribute_not_exists(id)"
        )

    def update_comment(self, comment_id: str, changes: dict[str, Any], now_iso: str, *, expected_state: str) -> bool:
        """Sets the changed fields (``None`` removes one) while the comment is still in ``expected_state``."""
        names = {"#state": "state"}
        values: dict[str, Any] = {":expected": expected_state, ":now": now_iso}
        sets, removes = ["updatedAt = :now"], []
        for number, (field, value) in enumerate(changes.items()):
            names[f"#f{number}"] = field
            if value is None:
                removes.append(f"#f{number}")
            else:
                values[f":v{number}"] = value
                sets.append(f"#f{number} = :v{number}")
        expression = "SET " + ", ".join(sets) + (" REMOVE " + ", ".join(removes) if removes else "")
        try:
            self._table("comment").update_item(
                Key={"id": comment_id},
                UpdateExpression=expression,
                ConditionExpression="attribute_exists(id) AND #state = :expected",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True

    def put_report(self, report: dict[str, Any], target_key: str, target_table: str, now_iso: str) -> bool:
        """Stores the report and puts the target back in the queue in one transaction. A second report by the same reader changes nothing."""
        item = {**report, "__typename": "ReaderReport", "updatedAt": report["createdAt"]}
        try:
            self._resource.meta.client.transact_write_items(
                TransactItems=[
                    {"Put": {"TableName": self._names["report"], "Item": _without_none(item), "ConditionExpression": "attribute_not_exists(id)"}},
                    {
                        "Update": {
                            "TableName": self._names[target_table],
                            "Key": {"id": target_key},
                            "UpdateExpression": "SET moderation = :new, updatedAt = :now ADD reportCount :one",
                            "ConditionExpression": "attribute_exists(id)",
                            "ExpressionAttributeValues": {":new": moderation_rules.MODERATION_NEW, ":now": now_iso, ":one": 1},
                        }
                    },
                ]
            )
        except Exception as error:
            reasons = getattr(error, "response", {}).get("CancellationReasons") or []
            if [str(reason.get("Code", "")) for reason in reasons][:1] == ["ConditionalCheckFailed"]:
                return False
            raise
        return True

    def get_profile_by_reader(self, reader_id: str) -> dict[str, Any] | None:
        from boto3.dynamodb.conditions import Key

        page = self._table("profile").query(IndexName=PROFILE_READER_INDEX, KeyConditionExpression=Key("readerId").eq(reader_id))
        rows = page.get("Items", [])
        return plain(rows[0]) if rows else None

    def get_action(self, action_id: str) -> dict[str, Any] | None:
        item = self._table("action").get_item(Key={"id": action_id}, ConsistentRead=True).get("Item")
        return plain(item) if item else None

    def transact_moderation(self, action: dict[str, Any], target_type: str, target_key: str, plan: Any, *, undoes: str | None = None) -> str:
        """Writes the log row, the target change (only if the target still has the expected state) and, for an undo, the pointer on the original."""
        table_for = {moderation_rules.TARGET_SUBMISSION: "submission", moderation_rules.TARGET_COMMENT: "comment", moderation_rules.TARGET_READER: "profile"}
        names: dict[str, str] = {}
        values: dict[str, Any] = {":now": action["at"]}
        sets = ["updatedAt = :now"]
        conditions = ["attribute_exists(id)"]
        for number, (field, value) in enumerate(plan.changes.items()):
            names[f"#c{number}"] = field
            values[f":c{number}"] = value
            sets.append(f"#c{number} = :c{number}")
        for number, (field, value) in enumerate(plan.expected.items()):
            names[f"#e{number}"] = field
            values[f":e{number}"] = value
            conditions.append(f"#e{number} = :e{number}")
        items: list[dict[str, Any]] = [
            {"Put": {"TableName": self._names["action"], "Item": _without_none({**action, "__typename": "ModerationAction", "updatedAt": action["at"]}), "ConditionExpression": "attribute_not_exists(id)"}},
            {
                "Update": {
                    "TableName": self._names[table_for[target_type]],
                    "Key": {"id": target_key},
                    "UpdateExpression": "SET " + ", ".join(sets),
                    "ConditionExpression": " AND ".join(conditions),
                    "ExpressionAttributeNames": names,
                    "ExpressionAttributeValues": values,
                }
            },
        ]
        if undoes:
            items.append(
                {
                    "Update": {
                        "TableName": self._names["action"],
                        "Key": {"id": undoes},
                        "UpdateExpression": "SET undoneBy = :by, updatedAt = :now",
                        "ConditionExpression": "attribute_exists(id) AND attribute_not_exists(undoneBy)",
                        "ExpressionAttributeValues": {":by": action["id"], ":now": action["at"]},
                    }
                }
            )
        if plan.item is not None:
            items.append({"Put": {"TableName": self._names["item"], "Item": _without_none(plan.item), "ConditionExpression": "attribute_not_exists(id)"}})
        try:
            self._resource.meta.client.transact_write_items(TransactItems=items)
        except Exception as error:
            reasons = getattr(error, "response", {}).get("CancellationReasons") or []
            codes = [str(reason.get("Code", "")) for reason in reasons]
            if codes[1:2] == ["ConditionalCheckFailed"]:
                return "target_changed"
            if codes[2:3] == ["ConditionalCheckFailed"] and undoes:
                return "already_undone"
            raise
        return "ok"

    def close_reports(self, target: str, now_iso: str) -> int:
        from boto3.dynamodb.conditions import Key

        table = self._table("report")
        closed = 0
        kwargs: dict[str, Any] = {"IndexName": REPORT_TARGET_INDEX, "KeyConditionExpression": Key("target").eq(target)}
        while True:
            page = table.query(**kwargs)
            for row in page.get("Items", []):
                if row.get("state") == "open":
                    table.update_item(
                        Key={"id": row["id"]},
                        UpdateExpression="SET #s = :closed, closedAt = :now, updatedAt = :now",
                        ExpressionAttributeNames={"#s": "state"},
                        ExpressionAttributeValues={":closed": "closed", ":now": now_iso},
                    )
                    closed += 1
            if "LastEvaluatedKey" not in page:
                return closed
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _scan(self, table_key: str, **arguments: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while True:
            page = self._table(table_key).scan(**arguments)
            rows.extend(plain(item) for item in page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                return rows
            arguments["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def new_content(self) -> list[tuple[str, dict[str, Any]]]:
        """Submissions and comments waiting for a decision (``moderation: new``). A scan: the queue of a pilot is small."""
        from boto3.dynamodb.conditions import Attr

        waiting = Attr("moderation").eq(moderation_rules.MODERATION_NEW)
        return [
            *((moderation_rules.TARGET_SUBMISSION, row) for row in self._scan("submission", FilterExpression=waiting)),
            *((moderation_rules.TARGET_COMMENT, row) for row in self._scan("comment", FilterExpression=waiting)),
        ]

    def human_acted_on(self) -> set[str]:
        """Targets a person has decided on; the model never judges those again."""
        from boto3.dynamodb.conditions import Attr

        rows = self._scan("action", FilterExpression=Attr("by").eq(moderation_rules.BY_HUMAN))
        return {row["target"] for row in rows}

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
                    "Input": target.task_json,
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
    task_json: str = json.dumps(SNAPSHOT_TASK)

    def for_ai_review(self, own_function_arn: str) -> "SnapshotTarget":
        """In AI mode the debounced run is the AI worker (this function), which asks for the snapshot when it has decided."""
        return SnapshotTarget(own_function_arn, self.role_arn, json.dumps(AI_TASK))


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
        comment_table=environment.get("PAPYRUS_READER_COMMENT_TABLE", ""),
        report_table=environment.get("PAPYRUS_READER_REPORT_TABLE", ""),
        action_table=environment.get("PAPYRUS_READER_ACTION_TABLE", ""),
        item_table=environment.get("PAPYRUS_READER_ITEM_TABLE", ""),
        proposal_table=environment.get("PAPYRUS_READER_PROPOSAL_TABLE", ""),
        flag_table=environment.get("PAPYRUS_READER_FLAG_TABLE", ""),
    )


def read_api_key(settings: ReaderSettings, ssm_client: Any) -> str:
    """The model's API key from its SSM SecureString (never Secrets Manager). The caller keeps it out of logs and results."""
    name = settings.ai_key_parameter
    if not ai_moderation.PARAMETER_NAME.fullmatch(name):
        raise ValueError("moderation.ai.apiKeyParameter is not a /papyrus/<site>/openai-api-key name")
    value = ssm_client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"].strip()
    if not value:
        raise ValueError("the API key parameter is empty")
    return value


def run_ai_worker(
    *,
    store: Any,
    settings: ReaderSettings,
    now: Callable[[], float],
    deadline: float,
    read_key: Callable[[], str],
    model_factory: Callable[[str, str], Any],
    invoke_snapshot: Callable[[], None],
) -> dict[str, Any]:
    """The scheduled AI review: judge new items, then ask for a snapshot so decisions reach the public files.

    Anything that goes wrong is reported by error class name. The snapshot is requested whatever happens, so votes still show.
    """
    if settings.moderation_mode != "ai":
        return {"ok": False, "error": "ai_moderation_off"}
    result: dict[str, Any]
    try:
        model = model_factory(read_key(), settings.ai_model)
        report = ai_moderation.run_ai_moderation(
            store,
            model,
            now=now,
            settings=moderation_rules.ModerationSettings(item_type=settings.promote_item_type, section=settings.promote_section),
            deadline=deadline,
            iso=iso,
        )
        result = {"ok": True, **report.to_dict()}
    except Exception as error:  # noqa: BLE001 - never put the message in the result: it could echo a key or reader text
        result = {"ok": False, "error": type(error).__name__}
    try:
        invoke_snapshot()
    except Exception as error:  # noqa: BLE001
        result["snapshotError"] = type(error).__name__
    return result


def handle_staff_event(event: dict[str, Any], *, store: Any, settings: ReaderSettings, now_seconds: float, account_id: str | None = None) -> dict[str, Any]:
    """``moderateReader`` from AppSync: an editor or admin hides, approves, promotes, bans or undoes. Answers a receipt, never an exception."""
    if proposal_rules.event_field_name(event) in proposal_rules.MUTATIONS:
        return proposal_rules.handle_proposal_event(event, store, now_iso=iso(now_seconds), account_id=account_id)
    identity = event.get("identity") or {}
    claims = identity.get("claims") or {}
    groups = claims.get("cognito:groups") or identity.get("groups") or []
    if isinstance(groups, str):
        groups = [group.strip() for group in groups.strip("[]").replace(",", " ").split()]
    subject = identity.get("sub")
    if not isinstance(subject, str) or not subject or not moderation_rules.STAFF_GROUPS.intersection(groups):
        return moderation_rules.refused("not_staff", "Only editors and admins can moderate.").to_dict()
    arguments = event.get("arguments") or {}
    outcome = moderation_rules.apply_action(
        store,
        action=arguments.get("action"),
        target_type=arguments.get("targetType"),
        target=arguments.get("target"),
        reason=arguments.get("reason"),
        undo_of=arguments.get("undoOf"),
        actor_sub=subject,
        by=moderation_rules.BY_HUMAN,
        now_iso=iso(now_seconds),
        settings=moderation_rules.ModerationSettings(item_type=settings.promote_item_type, section=settings.promote_section),
    )
    return outcome.to_dict()


def function_account(context: Any) -> str | None:
    """The AWS account this function runs in, from its own ARN: the only account whose IAM operators may file proposals."""
    parts = str(getattr(context, "invoked_function_arn", None) or "").split(":")
    return parts[4] if len(parts) > 4 and parts[4] else None


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    import boto3

    settings = settings_from_environment()
    store = store_from_environment()
    now_seconds = time.time()
    if proposal_rules.is_appsync_event(event):
        return handle_staff_event(event, store=store, settings=settings, now_seconds=now_seconds, account_id=function_account(_context))
    target = snapshot_target_from_environment()
    if settings.moderation_mode == "ai" and target is not None and _context is not None:
        if event.get("worker") == AI_WORKER:
            remaining = _context.get_remaining_time_in_millis() / 1000 - AI_DEADLINE_MARGIN_SECONDS
            lambda_client = boto3.client("lambda")
            return run_ai_worker(
                store=store,
                settings=settings,
                now=time.time,
                deadline=time.time() + max(remaining, 5),
                read_key=lambda: read_api_key(settings, boto3.client("ssm")),
                model_factory=lambda key, model: ai_moderation.OpenAIModerationModel(key, model=model),
                invoke_snapshot=lambda: lambda_client.invoke(FunctionName=target.function_arn, InvocationType="Event", Payload=json.dumps(SNAPSHOT_TASK).encode("utf-8")),
            )
        target = target.for_ai_review(_context.invoked_function_arn)
    scheduler = snapshot_scheduler(store, settings, now_seconds, target, boto3.client("scheduler"))
    return handle_event(event, store=store, settings=settings, now_seconds=now_seconds, schedule_snapshot=scheduler)
