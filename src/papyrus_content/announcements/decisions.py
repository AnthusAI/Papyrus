"""Announcements: the decision to say something (docs/announcement-records.md).

An Announcement is made once. Its id comes from its once-only key (``dedupeKey``) and the row is created with a condition on that id, so the same Story published
twice finds the first decision instead of making a second. It knows nothing about channels and holds no approval and no words: the Stories it is about are
``announces`` relations (with the version looked at), and each channel's version is a ``Delivery`` (``deliveries.py``).

``announce`` writes the Announcement together with its first Deliveries, in order, and finishes on a retry:

1. the Announcement row (a condition on its id);
2. each Delivery (a condition on its id) and its words;
3. the ``announces`` relations.

A crash anywhere leaves rows that the same call completes. A decision with no Delivery writes nothing at all, so a publish that qualifies on no channel leaves no
row. Reads are indexes: by once-only key, planned by release time, and a Story's Announcements through the relation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import links
from .deliveries import Conflict, DeliveryExists, Deliveries, Plan
from .links import StoryRef
from .records import (
    CANCELLED, DECISION_MODEL, PLANNED, RELEASED, RecordError, announcement_id, history_with, now_iso, stored, stored_dedupe_key, utc,
)

INDEX_BY_DEDUPE_KEY = "announcementDecisionsByDedupeKey"
INDEX_BY_STATE = "announcementDecisionsByState"


class AlreadyDecided(RecordError):
    """An Announcement for this once-only key exists. ``row`` is it."""

    def __init__(self, row: Mapping[str, Any]):
        super().__init__(f"{row.get('id')} already exists")
        self.row = dict(row)


@dataclass(frozen=True)
class Outcome:
    """What ``announce`` did: the Announcement, its Deliveries, and whether this call made the Announcement (False when it already existed)."""

    announcement: dict[str, Any]
    deliveries: list[dict[str, Any]]
    created: bool


class Announcements:
    def __init__(self, client: Any, deliveries: Deliveries | None = None):
        self.client = client
        self.deliveries = deliveries or Deliveries(client)

    # --- reads: every one is an index or a get ----------------------------------------------------------------------------------------------------

    def get(self, row_id: str) -> dict[str, Any] | None:
        row = self.client.get_record(DECISION_MODEL, row_id)
        return dict(row) if row else None

    def by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        """The Announcement for a once-only key, through the index on that key."""
        rows = self.client.list_by_index(INDEX_BY_DEDUPE_KEY, stored_dedupe_key(dedupe_key))
        return dict(rows[0]) if rows else None

    def planned_until(self, now: str) -> list[dict[str, Any]]:
        """The planned Announcements whose release time is at or before ``now``, from the planned-by-release-time index."""
        return [dict(row) for row in self.client.list_by_index(INDEX_BY_STATE, PLANNED, sort_condition={"le": utc(now)})]

    def planned_between(self, start: str, end: str) -> list[dict[str, Any]]:
        """The planned Announcements released between two times, for the calendar."""
        return [dict(row) for row in self.client.list_by_index(INDEX_BY_STATE, PLANNED, sort_condition={"between": [utc(start), utc(end)]})]

    def stories(self, announcement: str) -> list[dict[str, Any]]:
        return links.stories_of_announcement(self.client, announcement)

    def for_story(self, lineage_id: str) -> list[dict[str, Any]]:
        """Where a Story was announced: each Announcement that announces it, with its live Deliveries, one line per channel. Read through the relation, then
        one Announcement and one Deliveries index query each; nothing lists a table."""
        found = []
        for link in links.announcements_of_story(self.client, lineage_id):
            announcement = self.get(link["subjectId"])
            if announcement:
                found.append({"announcement": announcement, "versionLookedAt": link.get("objectVersionNumber"), "deliveries": self.deliveries.live_for_announcement(announcement["id"])})
        return found

    # --- decide -----------------------------------------------------------------------------------------------------------------------------------

    def announce(
        self, *, dedupe_key: str, kind: str, stories: Sequence[StoryRef], plans: Sequence[Plan], created_by: str, trigger: str,
        release_at: str | None = None, now: str | None = None,
    ) -> Outcome | None:
        """Decide to announce. Returns None, writing nothing, when no channel qualifies (``plans`` is empty). Calling it again for the same once-only key finds the
        Announcement and completes whatever a crash left undone; it never makes a second Announcement."""
        if not plans:
            return None
        if not stories:
            raise RecordError("An Announcement is about at least one Story.")
        now = now or now_iso()
        for plan in plans:
            self.deliveries.check(plan)   # a plan that breaks a rule is refused before the first write, so it leaves no Announcement behind
        row_id = announcement_id(dedupe_key)
        # An empty release time means as soon as allowed: now. It is stored, so the planned index holds every planned Announcement.
        release = utc(release_at) or now
        created = True
        try:
            announcement = self._create(row_id, dedupe_key, kind, release, created_by, trigger, now)
        except AlreadyDecided as found:
            announcement, created = found.row, False
        delivered = []
        for plan in plans:
            try:
                delivered.append(self.deliveries.create(row_id, plan, release_at=announcement["releaseAt"], by=created_by, now=now))
            except DeliveryExists as exists:
                self.deliveries.ensure_text(exists.row, plan.text, now=now)
                delivered.append(exists.row)
        for story in stories:
            links.announces(self.client, row_id, story, now=now)
        return Outcome(announcement, delivered, created)

    def _create(self, row_id: str, dedupe_key: str, kind: str, release: str, created_by: str, trigger: str, now: str) -> dict[str, Any]:
        found = self.get(row_id)
        if found:
            self._same_key(found, dedupe_key)
            raise AlreadyDecided(found)
        row = {
            "id": row_id, "dedupeKey": stored_dedupe_key(dedupe_key), "kind": kind, "state": PLANNED, "releaseAt": release, "createdBy": created_by, "trigger": trigger,
            "history": history_with({}, at=now, by=created_by, state=PLANNED, note=f"decided: {kind}"), "revision": 1, "createdAt": now, "updatedAt": now,
        }
        try:
            self.client.create_record(DECISION_MODEL, stored(row))
        except RuntimeError as error:
            if "conditional" in str(error).lower():
                found = self.get(row_id) or row
                self._same_key(found, dedupe_key)
                raise AlreadyDecided(found) from error
            raise
        return row

    @staticmethod
    def _same_key(found: Mapping[str, Any], dedupe_key: str) -> None:
        if found.get("dedupeKey") != stored_dedupe_key(dedupe_key):
            raise RecordError(f"{found.get('id')} belongs to the key {found.get('dedupeKey')!r}, not {dedupe_key!r}: two keys made one id.")

    # --- change one Announcement ------------------------------------------------------------------------------------------------------------------

    def _change(self, row: Mapping[str, Any], changes: Mapping[str, Any], *, by: str, note: str, now: str | None = None, expect_state: str | None = None) -> dict[str, Any]:
        now = now or now_iso()
        state = changes.get("state", row.get("state"))
        updated = {**row, **changes, "updatedAt": now, "revision": int(row.get("revision") or 1) + 1, "history": history_with(row, at=now, by=by, state=state, note=note)}
        payload = {name: updated[name] for name in (*changes, "history", "updatedAt", "revision")}
        condition: dict[str, Any] = {"revision": {"eq": int(row.get("revision") or 1)}}
        if expect_state:
            condition["state"] = {"eq": expect_state}
        if not self.client.update_record_if(DECISION_MODEL, {"id": row["id"], **stored(payload, clearing=True)}, condition):
            raise Conflict(f"{row['id']} was changed by someone else since it was read.")
        return updated

    def release(self, row: Mapping[str, Any], now: str, *, by: str = "schedule") -> dict[str, Any]:
        """Release a planned Announcement whose time has come, so its Deliveries may go once each is approved. Not before its time, and only once."""
        if row.get("state") != PLANNED:
            return dict(row)
        if utc(now) < row["releaseAt"]:
            raise RecordError(f"{row['id']} is planned for {row['releaseAt']}, not yet.")
        return self._change(row, {"state": RELEASED}, by=by, note="released", now=utc(now), expect_state=PLANNED)

    def release_due(self, now: str, *, by: str = "schedule") -> list[dict[str, Any]]:
        """Release every planned Announcement whose time has come: one index query for the due ones, one write for each. A release time in the past releases now."""
        released = []
        for row in self.planned_until(now):
            try:
                released.append(self.release(row, now, by=by))
            except Conflict:
                continue   # someone changed it (cancelled it, say) between the read and the write; the next pass reads it again
        return released

    def cancel(self, row: Mapping[str, Any], *, by: str, now: str | None = None) -> dict[str, Any]:
        """Stop an Announcement before release. Its Deliveries are withdrawn: nothing was sent, so there is nothing to take down. After release a Delivery is
        withdrawn on its own, because that may delete a public post."""
        if row.get("state") != PLANNED:
            raise RecordError(f"{row['id']} is {row.get('state')}; only a planned Announcement is cancelled.")
        now = now or now_iso()
        cancelled = self._change(row, {"state": CANCELLED}, by=by, note="cancelled before release", now=now, expect_state=PLANNED)
        for delivery in self.deliveries.live_for_announcement(row["id"]):
            self.deliveries.finish(delivery, "withdrawn", by=by, note="the Announcement was cancelled before release", now=now)
        return cancelled

    def story_changed(self, announcement: Mapping[str, Any], story: StoryRef, *, by: str, now: str | None = None) -> list[dict[str, Any]]:
        """A newer version of a Story the Announcement is about: it looks at that version now, and each Delivery that has not gone returns to a draft, so an approval
        of the earlier version no longer counts."""
        now = now or now_iso()
        links.announces(self.client, announcement["id"], story, now=now)
        return [self.deliveries.next_version(row, by=by, note=f"{story.lineage_id} changed to version {story.version_number}", now=now)
                for row in self.deliveries.live_for_announcement(announcement["id"])]
