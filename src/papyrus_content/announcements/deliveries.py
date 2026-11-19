"""Deliveries: one channel's version of an Announcement (docs/announcement-records.md).

A ``Delivery`` row is catalog only. Its words are one file in S3 (a ModelAttachment of the row, role ``delivery_text``); the row holds the key and a content
hash, never the text. Every read is an index: an Announcement's Deliveries, an account's Deliveries newest first, the Deliveries that are due.

**One live Delivery for each Announcement, channel and account.** The id carries a generation (``<announcement>#<channel>#<account>#g<n>``) and a Delivery is created
with a condition on its id. A second Delivery for the same three therefore cannot be made as a first one; it is made with ``supersede``, as the next generation.

**Approval lives here, on the Delivery,** because two channels of one Announcement may differ (LinkedIn ``hard`` while X is ``none``): ``approval``, where that value
came from (``approvalPolicy``), and the one version a person or the policy approved (``approvedVersion``, ``approvedBy``, ``approvedAt``). A later version is not
approved.

**Every wait is a named time on the row.** ``releaseAt``, ``lockAt`` and ``nextAttemptAt`` (with ``waitingFor``); ``dueAt`` is the earliest still pending and, with
``dueKey``, is present only while one is. A lock is a fact (``lockedAt``, ``lockedVersion``), not something held.

**Every edit is a new version** (PPY-e8ec54). ``version`` is the newest; the words of each are one file in S3 and ``versions`` (the log) holds each file's key and hash, who saved it and
which version it replaced (``delivery_text.py``). ``textKey`` and ``contentHash`` are the newest version's. The version that goes out is the locked one (``lockedVersion``), so an edit
made while an attempt is open is a later, preferred version and the attempt is not changed. ``delivery_versions.py`` makes the saves, candidates and pinned blocks; ``delivery_lock.py``
raises and lifts the lock.

Writes that change an existing row are conditional on the row's ``revision`` (it goes up by one with every change), so two writers never silently overwrite each other:
the second raises ``Conflict``.
There are no transactions across AppSync tables; ``supersede`` is ordered conditional writes that finish on a retry (see its docstring).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Protocol, Sequence

from . import delivery_text
from .delivery_text import content_hash  # noqa: F401  (re-exported: the one hash of the words and the picture that go out together)
from .records import (
    APPROVALS, ATTEMPT_SENT, AUTOMATIC, BEFORE_SEND_STATES, BLOCKED, CHECK_FAILED_CODE, DELIVERY_MODEL, DELIVERY_STATES, DRAFTED, FAILED, LIVE_STATES, MANUAL, MODES, NONE, READY, SENT, SOFT, STARTED, UNKNOWN, SUPERSEDED, SYSTEM,
    BUDGET_CYCLE, WAITING_FOR, RecordError, account_key, delivery_id, history_with, json_list, now_iso, attempt_log, open_attempt_of, require_catalog_only, stored, utc, with_due,
)

OWNER_KIND = "delivery"
ROLE = "delivery_text"
INDEX_BY_ANNOUNCEMENT = "deliveriesByAnnouncement"
INDEX_BY_ACCOUNT = "deliveriesByAccount"
INDEX_BY_DUE = "deliveriesByDue"

# Why a Delivery is not releasable yet, in the words the list shows.
NOT_WAITING = "not waiting to be sent"
BY_HAND = "a person posts it by hand and records the address"
NOT_READY = "the words are not ready"
BEFORE_RELEASE = "waiting for its release time"
NEEDS_APPROVAL = "waiting for approval"
NEEDS_REVIEW = "waiting for review until the lock time"
WAITING_FOR_TIME = "waiting for {what} until its next attempt time"


class DeliveryExists(RecordError):
    """A Delivery for this Announcement, channel, account and generation exists. ``row`` is it."""

    def __init__(self, row: Mapping[str, Any]):
        super().__init__(f"{row.get('id')} already exists")
        self.row = dict(row)


class NeedsSupersedes(RecordError):
    """A live Delivery already exists for this Announcement, channel and account. A new one is a correction: name the one it replaces (``supersede``)."""


class AlreadySuperseded(RecordError):
    """The Delivery already has a correction. ``row`` is the Delivery that replaced it."""

    def __init__(self, old: str, successor: str):
        super().__init__(f"{old} was already corrected by {successor}")
        self.successor = successor


class OpenAttempt(RecordError):
    """The Delivery has an attempt with no answer yet (``started`` or ``unknown``). It is settled first: until the provider's record says whether the post exists,
    a correction or a second attempt could put a second post out."""


class NotSent(RecordError):
    """The Delivery never went out, so there is nothing to correct. Its words are edited on the Delivery itself (``write_words``, or a new text version)."""


class Conflict(RecordError):
    """Another writer changed the row since it was read. Read it again and decide again."""


class CorrectedDifferently(Conflict):
    """Someone already corrected the Delivery, with other words than these. ``successor`` is their Delivery; nothing of this caller's was written."""

    def __init__(self, old: str, successor: str):
        super().__init__(f"{old} was already corrected by {successor} with different words; read it again and decide whether that correction is the one you want.")
        self.successor = successor


class DeliveryFiles(Protocol):
    """A Delivery's files in S3. Each is named: ``v<number>`` for a version's words and ``c<number>`` for a candidate's, and a file is written once."""

    def describe(self, delivery: str, text: str, name: str = "v1") -> dict[str, str]: ...

    def put(self, delivery: str, text: str, *, now: str, name: str = "v1") -> None: ...

    def get(self, delivery: str, name: str = "v1") -> str | None: ...


class AttachmentFiles:
    """A Delivery's words as ModelAttachments of the row, one for each file (``newsroom/payloads/delivery/<id>/delivery-text/delivery-v3.md``)."""

    def __init__(self, client: Any):
        self.client = client

    def _entry(self, delivery: str, text: str, now: str | None, name: str) -> dict[str, Any]:
        from ..model_attachments import build_text_model_payload_attachment

        return build_text_model_payload_attachment(
            {"ownerKind": OWNER_KIND, "ownerId": delivery, "role": ROLE, "sortKey": name, "filename": f"delivery-{name}.md", "mediaType": "text/markdown", "content": text, "now": now}
        )

    def describe(self, delivery: str, text: str, name: str = "v1") -> dict[str, str]:
        attachment = self._entry(delivery, text, None, name)["attachment"]
        return {"key": attachment["storagePath"], "sha256": attachment["sha256"]}

    def put(self, delivery: str, text: str, *, now: str, name: str = "v1") -> None:
        from ..model_attachments import upload_attachment_body

        entry = self._entry(delivery, text, now, name)
        upload_attachment_body(self.client, entry["attachment"], entry["body"])

    def get(self, delivery: str, name: str = "v1") -> str | None:
        from ..model_attachments import download_attachment_buffer

        found = [a for a in self.client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", delivery, limit=100)
                 if a.get("role") == ROLE and a.get("sortKey") == name and str(a.get("status") or "active").lower() not in {"deleted", "aborted"}]
        if not found:
            return None
        body = download_attachment_buffer(self.client, found[0])
        return body.decode("utf-8") if body is not None else None


@dataclass(frozen=True)
class Plan:
    """What one channel's Delivery is to be, before it is written."""

    channel: str
    account_id: str
    approval: str
    approval_policy: str
    text: str
    mode: str = AUTOMATIC
    audience: Sequence[str] = ()
    image_key: str | None = None
    drafted_by: str = "machine"
    checks: Sequence[Mapping[str, Any]] = ()
    state: str = READY
    lock_at: str | None = None
    release_at: str | None = None   # this channel's own release time (its edit window), else the Announcement's


class DueTimers(Protocol):
    """What ``Deliveries`` calls wherever a Delivery's due time is written, so a time that comes raises one wake (``delivery_timers.DeliveryTimers``)."""

    def sync(self, row: Mapping[str, Any]) -> None: ...


class Deliveries:
    def __init__(self, client: Any, files: DeliveryFiles | None = None, timers: DueTimers | None = None):
        self.client = client
        self.files = files or AttachmentFiles(client)
        self.timers = timers

    # --- reads: every one is an index or a get ----------------------------------------------------------------------------------------------------

    def get(self, row_id: str) -> dict[str, Any] | None:
        row = self.client.get_record(DELIVERY_MODEL, row_id)
        return dict(row) if row else None

    def for_announcement(self, announcement: str) -> list[dict[str, Any]]:
        """An Announcement's Deliveries, oldest first, every generation of every channel."""
        return [dict(row) for row in self.client.list_by_index(INDEX_BY_ANNOUNCEMENT, announcement)]

    def live_for_announcement(self, announcement: str) -> list[dict[str, Any]]:
        """The Deliveries of an Announcement that no correction replaced: the highest generation of each channel and account."""
        newest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self.for_announcement(announcement):
            key = (row["channel"], row["accountId"])
            if key not in newest or int(row["generation"]) > int(newest[key]["generation"]):
                newest[key] = row
        return list(newest.values())

    def for_account(self, channel: str, account_id: str) -> Iterator[dict[str, Any]]:
        """The account's Deliveries, newest first, one page at a time. Stop reading and no further page is fetched."""
        yield from (dict(row) for row in self.client.iterate_newest_first(INDEX_BY_ACCOUNT, account_key(channel, account_id)))

    def last_post_at(self, channel: str, account_id: str, *, besides: str | None = None) -> str | None:
        """When the account last posted, or may have: the time of the latest attempt that was sent or has no answer yet (an unanswered attempt may have posted).

        The account's Deliveries are read newest first (by when each was made), one page at a time, and reading stops at the first that has such an attempt;
        ``besides`` leaves one Delivery out: the one being asked about. Nothing else is read."""
        for row in self.for_account(channel, account_id):
            if row["id"] == besides:
                continue
            times = [str(entry.get("closedAt") or entry["at"]) for entry in attempt_log(row) if entry.get("outcome") in (ATTEMPT_SENT, STARTED, UNKNOWN)]
            if times:
                return max(times)
        return None

    def spacing_until(self, row: Mapping[str, Any], minutes: int) -> str | None:
        """The time the account's post spacing ends for this Delivery: the account's last post plus ``minutes``. None when the account has not posted."""
        last = self.last_post_at(row["channel"], row["accountId"], besides=row["id"])
        if last is None:
            return None
        return utc(datetime.fromisoformat(str(utc(last))[:-1] + "+00:00") + timedelta(minutes=int(minutes)))

    def due(self, now: str) -> list[dict[str, Any]]:
        """The Deliveries whose earliest pending time is at or before ``now``, from the sparse due index. A Delivery with nothing pending is not in it."""
        from .records import due_key

        return [dict(row) for row in self.client.list_by_index(INDEX_BY_DUE, due_key(), sort_condition={"le": utc(now)})]

    def text(self, row: Mapping[str, Any]) -> str | None:
        """The words of the Delivery's newest version, read from S3."""
        return self.text_of(row, delivery_text.head_entry(row))

    def text_of(self, row: Mapping[str, Any], entry: Mapping[str, Any] | None) -> str | None:
        """The words one line of the version log names, read from S3."""
        return self.files.get(row["id"], entry["file"]) if entry else None

    def sendable(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        """The log line of the version that goes out: the locked one once the Delivery is locked, otherwise the newest."""
        return delivery_text.sendable_entry(row)

    def sent_text(self, row: Mapping[str, Any]) -> str | None:
        """The words that go out, read from S3. An edit after the lock never changes them."""
        return self.text_of(row, self.sendable(row))

    # --- create -----------------------------------------------------------------------------------------------------------------------------------

    def create(self, announcement: str, plan: Plan, *, release_at: str, by: str, now: str | None = None, generation: int = 1, supersedes: str | None = None) -> dict[str, Any]:
        """Take the Delivery for this Announcement, channel, account and generation, or raise ``DeliveryExists`` with the row that holds it.

        The row is written first (the upload function refuses a file whose owner does not exist), then the words. To add a Delivery for a channel and account that may
        already have one, use ``add``."""
        now = now or now_iso()
        self.check(plan)
        release = utc(plan.release_at or release_at)
        row_id = delivery_id(announcement, plan.channel, plan.account_id, generation)
        existing = self.get(row_id)
        if existing:
            raise DeliveryExists(existing)
        name = delivery_text.version_file(1)
        file = self.files.describe(row_id, plan.text, name) if plan.text else None   # a draft a person has yet to write has no words and no file
        first = self.first_version(1, name, file, plan, by=by, at=now) if file else None
        approved = plan.approval == NONE
        row: dict[str, Any] = {
            "id": row_id, "announcementId": announcement, "channel": plan.channel, "accountId": plan.account_id, "accountKey": account_key(plan.channel, plan.account_id),
            "audience": list(plan.audience) or None, "mode": plan.mode, "state": plan.state, "generation": generation, "version": 1,
            "textKey": file["key"] if file else None, "imageKey": plan.image_key, "contentHash": first["contentHash"] if first else None, "versions": [first] if first else None,
            "draftedBy": plan.drafted_by, "checks": list(plan.checks) or None,
            "approval": plan.approval, "approvalPolicy": plan.approval_policy,
            "approvedVersion": 1 if approved else None, "approvedBy": SYSTEM if approved else None, "approvedAt": now if approved else None,
            "releaseAt": release, "lockAt": utc(plan.lock_at) or release, "supersedes": supersedes,
            "history": history_with({}, at=now, by=by, state=plan.state, note=f"drafted for {plan.channel}" + (f", correcting {supersedes}" if supersedes else "")),
            "revision": 1, "createdAt": now, "updatedAt": now,
        }
        require_catalog_only(row)
        row = with_due(row)
        try:
            self.client.create_record(DELIVERY_MODEL, stored(row))
        except RuntimeError as error:
            if "conditional" in str(error).lower():
                raise DeliveryExists(self.get(row_id) or row) from error
            raise
        if plan.text:
            self.files.put(row_id, plan.text, now=now, name=name)
        self._sync(row)
        return row

    @staticmethod
    def first_version(number: int, name: str, described: Mapping[str, str], plan: Plan, *, by: str, at: str) -> dict[str, Any]:
        """The log line of a Delivery's first words: a machine draft is the machine's, unpinned; a person's own words are the person's and pinned."""
        owner = delivery_text.MACHINE if plan.drafted_by == "machine" else delivery_text.HUMAN
        texts = delivery_text.split_blocks(plan.text)
        flags = [delivery_text.MACHINE_FLAGS if owner == delivery_text.MACHINE else delivery_text.HUMAN_FLAGS] * len(texts)
        return delivery_text.version_entry(number, name, described, image_key=plan.image_key, by=by, owner=owner, at=at, replaces=None, texts=texts, flags=flags)

    def add(self, announcement: str, plan: Plan, *, release_at: str, by: str, now: str | None = None) -> dict[str, Any]:
        """Add a Delivery to an existing Announcement (a channel that qualified later). Refused with ``NeedsSupersedes`` when the Announcement already has a Delivery
        for this channel and account that no correction replaced: a second one is a correction, so name the one it replaces with ``supersede``."""
        self._require_no_live(announcement, plan.channel, plan.account_id)
        return self.create(announcement, plan, release_at=release_at, by=by, now=now)

    def ensure_text(self, row: Mapping[str, Any], text: str, *, now: str | None = None) -> None:
        """Finish a crashed create: write the words of the first version when the row exists and the file does not. The words are the same text the row's hash names;
        a later version is finished by the save that wrote it, never from the plan."""
        entry = delivery_text.entry_of(row, 1)
        if text and entry and self.files.get(row["id"], entry["file"]) is None:
            self.files.put(row["id"], text, now=now or now_iso(), name=entry["file"])

    def check(self, plan: Plan) -> None:
        """Refuse a plan that breaks a rule, before anything is written."""
        if plan.approval not in APPROVALS:
            raise RecordError(f"approval is one of {', '.join(APPROVALS)}; not {plan.approval!r}.")
        if plan.mode not in MODES:
            raise RecordError(f"mode is one of {', '.join(MODES)}; not {plan.mode!r}.")
        if plan.state not in (DRAFTED, READY):
            raise RecordError(f"A Delivery starts as drafted or ready; not {plan.state!r}.")
        if plan.state == READY and not plan.text.strip():
            raise RecordError("A Delivery with no words is a draft, not ready: only a draft may wait for a person to write it.")
        if not plan.channel or not plan.account_id:
            raise RecordError("A Delivery names its channel and its account.")
        if not plan.approval_policy:
            raise RecordError("A Delivery records where its approval value came from (approvalPolicy).")

    def _require_no_live(self, announcement: str, channel: str, account_id: str) -> None:
        for row in self.for_announcement(announcement):
            if row["channel"] == channel and row["accountId"] == account_id and row.get("state") != SUPERSEDED:
                raise NeedsSupersedes(f"{announcement} already has a live Delivery for {channel} {account_id} ({row['id']}); a new one corrects it, so name it with supersede.")

    # --- changes to one row -----------------------------------------------------------------------------------------------------------------------

    def _change(self, row: Mapping[str, Any], changes: Mapping[str, Any], *, by: str, note: str, now: str | None = None) -> dict[str, Any]:
        """Write changes, one history line and the new due time, in one write that holds only if nobody changed the row since it was read."""
        now = now or now_iso()
        updated = {**row, **changes, "updatedAt": now, "revision": int(row.get("revision") or 1) + 1}
        updated["history"] = history_with(row, at=now, by=by, state=updated.get("state"), note=note)
        updated = with_due(updated)
        require_catalog_only(updated)
        payload = {name: updated.get(name) for name in (*changes, "history", "updatedAt", "revision", "dueAt", "dueKey")}
        won = self.client.update_record_if(DELIVERY_MODEL, {"id": row["id"], **stored(payload, clearing=True)}, {"revision": {"eq": int(row.get("revision") or 1)}})
        if not won:
            raise Conflict(f"{row['id']} was changed by someone else since it was read.")
        self._sync(updated)
        return updated

    def _sync(self, row: Mapping[str, Any]) -> None:
        """A due time was written: the Delivery's follow-up timer follows it (moved when the time moved, deleted when nothing is pending)."""
        if self.timers is not None:
            self.timers.sync(row)

    def mark_ready(self, row: Mapping[str, Any], *, by: str, now: str | None = None) -> dict[str, Any]:
        """The words are drafted and checked."""
        if not row.get("textKey"):
            raise RecordError(f"{row['id']} has no words, so it is not ready.")
        return self._change(row, {"state": READY}, by=by, note="ready", now=now)

    def write_words(self, row: Mapping[str, Any], plan: Plan, *, by: str, now: str | None = None) -> dict[str, Any]:
        """Give a draft that has no words its first words: an edit of the same Delivery, not a correction. The Delivery becomes ready at the approval the plan names.

        The words file is written first (the Delivery row exists, so the upload is accepted) and the row second, so a crash between them leaves a draft with no words
        and the same call is made again."""
        if row.get("textKey") or row.get("state") != DRAFTED:
            raise RecordError(f"{row['id']} is {row.get('state')} and already has its words or is past the draft; only a draft with no words is written into.")
        self.check(plan)
        now = now or now_iso()
        name = delivery_text.version_file(int(row["version"]))
        file = self.files.describe(row["id"], plan.text, name)
        self.files.put(row["id"], plan.text, now=now, name=name)
        first = self.first_version(int(row["version"]), name, file, plan, by=by, at=now)
        approved = plan.approval == NONE
        changes: dict[str, Any] = {
            "state": READY, "textKey": file["key"], "contentHash": first["contentHash"], "imageKey": plan.image_key, "draftedBy": plan.drafted_by, "versions": [first],
            "approval": plan.approval, "approvalPolicy": plan.approval_policy,
            "approvedVersion": int(row["version"]) if approved else None, "approvedBy": SYSTEM if approved else None, "approvedAt": now if approved else None,
        }
        return self._change(row, changes, by=by, note="words written", now=now)

    def approve(self, row: Mapping[str, Any], *, version: int, by: str, now: str | None = None) -> dict[str, Any]:
        """Approve one version of the Delivery. Approving a version that is not the current one is refused: an approval names the version a person saw."""
        if int(version) != int(row["version"]):
            raise RecordError(f"{row['id']} is at version {row['version']}; an approval names one version, and {version} is not it.")
        if row.get("state") not in LIVE_STATES:
            raise RecordError(f"{row['id']} is {row.get('state')}; only a live Delivery is approved.")
        return self._change(row, {"approvedVersion": int(version), "approvedBy": by, "approvedAt": now or now_iso()}, by=by, note=f"approved version {version}", now=now)

    def change_approval(self, row: Mapping[str, Any], approval: str, *, by: str, now: str | None = None) -> dict[str, Any]:
        """An editor changes the review of this one Delivery, before it goes. The publication's policy and the Announcement's other Deliveries are not touched, and the row
        records that a person chose it (``approvalPolicy``).

        Moving to ``none`` is the editor's own decision to let the current version go: it is approved by that person. Moving away from ``none`` takes back the policy's
        approval (``system``) of the current version, so it waits for a person; an approval a person gave stays."""
        if approval not in APPROVALS:
            raise RecordError(f"approval is one of {', '.join(APPROVALS)}; not {approval!r}.")
        if row.get("state") not in BEFORE_SEND_STATES:
            raise RecordError(f"{row['id']} is {row.get('state')}; the review of a Delivery changes only before it goes.")
        if approval == row.get("approval"):
            return dict(row)
        now = now or now_iso()
        changes: dict[str, Any] = {"approval": approval, "approvalPolicy": f"set for this Delivery by {by}"}
        if approval == NONE:
            changes.update(approvedVersion=int(row["version"]), approvedBy=by, approvedAt=now)
        elif row.get("approvedBy") == SYSTEM:
            changes.update(approvedVersion=None, approvedBy=None, approvedAt=None)
        return self._change(row, changes, by=by, note=f"review changed from {row.get('approval')} to {approval}", now=now)

    def is_approved(self, row: Mapping[str, Any]) -> bool:
        """Whether the version that goes out is approved: the locked one once the Delivery is locked, otherwise the newest. A later version than ``approvedVersion`` is not."""
        return row.get("approvedVersion") is not None and int(row["approvedVersion"]) == delivery_text.sendable_number(row)

    def next_version(self, row: Mapping[str, Any], *, by: str, note: str, now: str | None = None) -> dict[str, Any]:
        """The Story changed after the words were made: the Delivery moves to its next version and back to a draft, so it waits again. Under approval ``none`` the
        policy approves the new version at once; under ``soft`` or ``hard`` the earlier approval does not carry over. A Delivery already sending or final is left as it
        is: a correction to something already out is a new Delivery."""
        if row.get("state") not in (DRAFTED, READY, BLOCKED):
            return dict(row)
        version = int(row["version"]) + 1
        changes: dict[str, Any] = {"version": version, "state": DRAFTED}
        carried = delivery_text.head_entry(row)
        if carried:   # the Story changed and the words did not: the new version shares its predecessor's file until it is drafted again
            changes["versions"] = [*delivery_text.versions_of(row), {**carried, "number": version, "replaces": int(row["version"]), "by": by, "at": now or now_iso(), "carried": True}]
        if row.get("lockedAt"):   # a lock on words the Story has outgrown is lifted: nothing locked goes out unapproved against a Story that changed
            changes.update(lockedAt=None, lockedVersion=None)
        if row.get("approval") == NONE:
            changes.update(approvedVersion=version, approvedBy=SYSTEM, approvedAt=now or now_iso())
        return self._change(row, changes, by=by, note=note, now=now)

    def lock(self, row: Mapping[str, Any], *, by: str, now: str | None = None) -> dict[str, Any]:
        """Lock the Delivery for the send job: the version approved at this moment is the one that is sent. The lock is a fact on the row; nothing holds it."""
        if row.get("lockedAt"):
            return dict(row)
        if row.get("approvedVersion") is None:
            raise RecordError(f"{row['id']} has no approved version to lock.")
        now = now or now_iso()
        return self._change(row, {"lockedAt": now, "lockedVersion": int(row["approvedVersion"])}, by=by, note=f"locked version {row['approvedVersion']}", now=now)

    def wait_until(self, row: Mapping[str, Any], at: str, waiting_for: str, *, by: str, now: str | None = None) -> dict[str, Any]:
        """Name the next time the Delivery will be tried and what it is waiting for."""
        if waiting_for not in WAITING_FOR:
            raise RecordError(f"waitingFor is one of {', '.join(WAITING_FOR)}; not {waiting_for!r}.")
        return self._change(row, {"nextAttemptAt": utc(at), "waitingFor": waiting_for}, by=by, note=f"waiting for {waiting_for}", now=now)

    def stop_waiting(self, row: Mapping[str, Any], *, by: str, now: str | None = None) -> dict[str, Any]:
        return self._change(row, {"nextAttemptAt": None, "waitingFor": None}, by=by, note="no longer waiting", now=now)

    def finish(self, row: Mapping[str, Any], state: str, *, by: str, note: str, now: str | None = None) -> dict[str, Any]:
        """Move the Delivery to a state. A state with nothing pending leaves it out of the due index."""
        if state not in DELIVERY_STATES:
            raise RecordError(f"A Delivery state is one of {', '.join(DELIVERY_STATES)}; not {state!r}.")
        return self._change(row, {"state": state}, by=by, note=note, now=now)

    def record_counts(self, row: Mapping[str, Any], counts: Mapping[str, int], cost: str | None, *, by: str, now: str | None = None) -> dict[str, Any]:
        """Write the counts Caducus's records add up to (``counts.DeliveryCounts.refresh`` calls this), and the cost when Caducus charged something. The state is not
        touched: counts say what became of the readers, the attempts say how the send went. The history line names the counts so a change is visible."""
        from .counts import counts_text

        changes: dict[str, Any] = {"counts": dict(counts)}
        if cost is not None:
            changes["cost"] = cost
        return self._change(row, changes, by=by, note=f"counts from Caducus: {counts_text(counts)}", now=now)

    def move_release(self, row: Mapping[str, Any], release_at: str, *, by: str, now: str | None = None) -> dict[str, Any]:
        """A new release time. The lock time follows when it was equal to the old release time (no separate lock)."""
        release = utc(release_at)
        changes: dict[str, Any] = {"releaseAt": release}
        if row.get("lockAt") == row.get("releaseAt"):
            changes["lockAt"] = release
        return self._change(row, changes, by=by, note=f"release moved to {release}", now=now)

    # --- release ----------------------------------------------------------------------------------------------------------------------------------

    def releasable(self, row: Mapping[str, Any], now: str) -> tuple[bool, str | None]:
        """Whether the Delivery may go now, and if not, why in plain words.

        Only a ``ready`` Delivery goes, or a ``blocked`` one whose budget stop named the time it ends. A wait the Delivery named (``nextAttemptAt``) must have ended.
        The release time must have come and the words must be ready. Then the approval decides: ``none`` goes (the policy approved this version), ``hard`` waits for a
        person to approve this version, ``soft`` goes when a person approved this version or the lock time has come with nobody having stopped it.

        This reads only the row. The rules about the other rows and the words file (the highest generation, not superseded, a file that matches the hash) are checked
        when an attempt opens (``attempts.Attempts.open``)."""
        now = utc(now)
        state = row.get("state")
        if row.get("mode") == MANUAL:
            return False, BY_HAND
        if state == DRAFTED:
            return False, NOT_READY
        budget_wait_ended = state == BLOCKED and row.get("waitingFor") == BUDGET_CYCLE and row.get("nextAttemptAt")
        if state != READY and not budget_wait_ended:
            return False, NOT_WAITING
        if now < row["releaseAt"]:
            return False, BEFORE_RELEASE
        if row.get("nextAttemptAt") and now < row["nextAttemptAt"]:
            return False, WAITING_FOR_TIME.format(what=row.get("waitingFor") or "a wait")
        if self.is_approved(row):
            return True, None
        if row["approval"] == SOFT and now >= row["lockAt"]:
            return True, None
        return False, NEEDS_REVIEW if row["approval"] == SOFT else NEEDS_APPROVAL

    def retry(self, row: Mapping[str, Any], *, by: str, now: str | None = None) -> dict[str, Any]:
        """A person decided a failed Delivery should be tried again: back to ready. The next try is the next attempt, and the attempts so far stay in the log."""
        if row.get("state") != FAILED:
            raise RecordError(f"{row['id']} is {row.get('state')}; only a failed Delivery is tried again.")
        return self._change(row, {"state": READY}, by=by, note="tried again by a person", now=now)

    def block_draft(self, row: Mapping[str, Any], *, by: str, note: str, now: str | None = None) -> dict[str, Any]:
        """The checks on a draft's words failed: it is blocked before any attempt, and nothing about it is pending (no time, so it is never overdue). A person's answer, or a
        change to an input, is what moves it on (``resume``)."""
        if row.get("state") not in (DRAFTED, READY):
            raise RecordError(f"{row['id']} is {row.get('state')}; only a draft or a ready Delivery is blocked for a failed check.")
        return self._change(row, {"state": BLOCKED, "blockedReason": CHECK_FAILED_CODE}, by=by, note=note, now=now)

    def resume(self, row: Mapping[str, Any], *, by: str, now: str | None = None) -> dict[str, Any]:
        """A person lifted the pause (or answered the reason a Delivery was blocked): back to ready, with no wait left on the row. The next try is the next attempt."""
        if row.get("state") != BLOCKED:
            raise RecordError(f"{row['id']} is {row.get('state')}; only a blocked Delivery is resumed.")
        return self._change(row, {"state": READY, "blockedReason": None, "nextAttemptAt": None, "waitingFor": None}, by=by, note="resumed", now=now)

    # --- a correction -----------------------------------------------------------------------------------------------------------------------------

    def supersede(self, old: Mapping[str, Any], plan: Plan, *, release_at: str | None = None, by: str, now: str | None = None) -> dict[str, Any]:
        """Replace a Delivery that went out with a corrected one: the next generation, written with ``supersedes``, and the old one marked ``superseded`` and pointing forward.

        Only a sent Delivery is corrected (``NotSent``); one that never went is edited, not corrected. A Delivery with an attempt that has no answer yet is settled first
        (``OpenAttempt``). The old row is read again here, so a caller's copy may be stale.

        AppSync has no transaction across writes, so this is three ordered, conditional writes that a retry finishes:

        1. create the next generation (conditional on its id, so two corrections of one Delivery cannot both win);
        2. mark the old Delivery superseded (conditional on its ``revision``, and only when it has no ``supersededBy``);
        3. write the ``supersedes`` relation (an upsert).

        A crash after 1 leaves a successor that names the old Delivery and an old one still live; after 2, an old one that points at the successor and no relation.
        Calling ``supersede`` again with the same words finds the successor and writes whatever is missing, from a fresh read of the old row or a stale one.
        A call with other words finds the successor and raises ``CorrectedDifferently``: it is somebody else's correction, and neither its row nor its words file is
        touched. The live Delivery of a channel and account is always the highest generation, so no reader sees two."""
        now = now or now_iso()
        if (plan.channel, plan.account_id) != (old["channel"], old["accountId"]):
            raise RecordError("A correction is for the same channel and account as the Delivery it replaces.")
        current = self.get(old["id"]) or dict(old)
        generation = int(current["generation"]) + 1
        successor_id = delivery_id(current["announcementId"], current["channel"], current["accountId"], generation)
        if current.get("supersededBy") not in (None, successor_id):
            raise AlreadySuperseded(current["id"], current["supersededBy"])
        found = self.get(successor_id)
        if found is None:
            if current.get("supersededBy"):
                raise RecordError(f"{current['id']} points at {successor_id}, which does not exist.")
            if open_attempt_of(current):
                raise OpenAttempt(f"{old['id']} has an attempt with no answer yet (attempt {open_attempt_of(current)['number']}); it is settled before a correction is made.")
            if current.get("state") != SENT:
                raise NotSent(f"{old['id']} is {current.get('state')}, not sent; a Delivery that never went is edited, not corrected.")
            successor = self.create(current["announcementId"], plan, release_at=release_at or current["releaseAt"], by=by, now=now, generation=generation, supersedes=current["id"])
        else:
            if found.get("supersedes") != current["id"]:
                raise RecordError(f"{successor_id} exists and does not correct {old['id']}.")
            if found.get("contentHash") != self._plan_hash(successor_id, plan):
                raise CorrectedDifferently(current["id"], successor_id)
            self.ensure_text(found, plan.text, now=now)
            successor = found
        self._finish_supersede(current, successor, by=by, now=now)
        return self.get(successor["id"]) or successor

    def _plan_hash(self, row_id: str, plan: Plan) -> str | None:
        """The content hash a Delivery made from this plan carries (None for a draft with no words)."""
        return content_hash(self.files.describe(row_id, plan.text)["sha256"], plan.image_key) if plan.text else None

    def _finish_supersede(self, old: Mapping[str, Any], successor: Mapping[str, Any], *, by: str, now: str) -> None:
        current = self.get(old["id"]) or dict(old)
        if current.get("supersededBy") is None:
            self._change(current, {"state": SUPERSEDED, "supersededBy": successor["id"]}, by=by, note=f"corrected by {successor['id']}", now=now)
        elif current["supersededBy"] != successor["id"]:
            raise AlreadySuperseded(old["id"], current["supersededBy"])
        from . import links   # the writer of the relations needs PyYAML (the relation types), which the reads of a Delivery do not

        links.supersedes(self.client, successor["id"], old["id"], now=now)

    def history(self, row: Mapping[str, Any]) -> list[dict[str, Any]]:
        return json_list(row.get("history"))
