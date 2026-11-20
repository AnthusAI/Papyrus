"""The edit window of a Delivery, as data for each kind of Announcement and channel (PPY-e8ec54).

A Delivery is a draft with an edit window: it runs from its creation to ``releaseAt``, and it locks for the send job ``lockLeadMinutes`` before that. A weekly newsletter has a week; a
story post may have twenty minutes. Neither number is in the code: they are the ``editWindows`` list of the announcement settings (``settings.py``), and nothing is assumed where it
has no entry (the Delivery is released as soon as it is allowed and has no separate lock).

Each entry is ``{"kind": ..., "channel": ..., "windowMinutes": n, "lockLeadMinutes": m}``. ``kind`` and ``channel`` are each optional; the narrowest entry that fits wins: kind and channel
together, then the kind, then the channel, then an entry that names neither.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .x_account import AnnouncementError

if TYPE_CHECKING:   # the settings module imports this one inside the announcements function, which needs none of the Delivery code
    from .deliveries import Plan

KEY = "editWindows"


@dataclass(frozen=True)
class Window:
    kind: str | None
    channel: str | None
    window_minutes: int
    lock_lead_minutes: int

    @property
    def scope(self) -> str:
        return ", ".join(f"{name} {value}" for name, value in (("kind", self.kind), ("channel", self.channel)) if value) or "every kind and channel"


def _whole(value: Any, name: str, scope: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AnnouncementError("edit_window_invalid", f"The {name} for {scope} is a whole number of minutes, zero or more.")
    return value


def validate(entries: Any) -> list[dict[str, Any]]:
    """The edit windows checked against the rules, in the form the settings store: a list of entries, one for each scope, each lock lead within its window."""
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise AnnouncementError("edit_window_invalid", "The edit windows are a list: one entry for each kind and channel.")
    seen: set[tuple[str | None, str | None]] = set()
    checked: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise AnnouncementError("edit_window_invalid", "Each edit window names windowMinutes and lockLeadMinutes, and optionally a kind and a channel.")
        extra = sorted(set(entry) - {"kind", "channel", "windowMinutes", "lockLeadMinutes"})
        if extra:
            raise AnnouncementError("edit_window_invalid", f"An edit window has kind, channel, windowMinutes and lockLeadMinutes; not {', '.join(extra)}.")
        kind, channel = entry.get("kind") or None, entry.get("channel") or None
        for name, value in (("kind", kind), ("channel", channel)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise AnnouncementError("edit_window_invalid", f"The {name} of an edit window is a name.")
        window = Window(kind, channel, _whole(entry.get("windowMinutes"), "window", _scope(kind, channel)), _whole(entry.get("lockLeadMinutes", 0), "lock lead", _scope(kind, channel)))
        if window.lock_lead_minutes > window.window_minutes:
            raise AnnouncementError("edit_window_invalid", f"The lock for {window.scope} comes {window.lock_lead_minutes} minutes before the release, which is more than its {window.window_minutes} minute window.")
        if (kind, channel) in seen:
            raise AnnouncementError("edit_window_invalid", f"There are two edit windows for {window.scope}.")
        seen.add((kind, channel))
        checked.append({**({"kind": kind} if kind else {}), **({"channel": channel} if channel else {}), "windowMinutes": window.window_minutes, "lockLeadMinutes": window.lock_lead_minutes})
    return checked


def _scope(kind: str | None, channel: str | None) -> str:
    return Window(kind, channel, 0, 0).scope


def windows_of(settings: Mapping[str, Any]) -> list[Window]:
    return [Window(entry.get("kind"), entry.get("channel"), int(entry["windowMinutes"]), int(entry.get("lockLeadMinutes", 0))) for entry in settings.get(KEY) or []]


def resolve(windows: Sequence[Window], kind: str, channel: str) -> Window | None:
    """The narrowest window that fits this kind and channel, or None."""
    fits = [w for w in windows if w.kind in (None, kind) and w.channel in (None, channel)]
    return max(fits, key=lambda w: (w.kind is not None and w.channel is not None, w.kind is not None, w.channel is not None), default=None)


def _instant(value: str) -> datetime:
    """A UTC instant written ``2026-11-17T09:00:00Z`` (a time with an offset is converted; one with none is refused, so a local time is never read as UTC)."""
    text = value.strip()
    moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
    if moment.tzinfo is None:
        raise ValueError(f"A time needs its offset, so it is never read as the wrong zone: {value!r}.")
    return moment.astimezone(timezone.utc)


def _text(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def apply(settings: Mapping[str, Any], kind: str, plans: Sequence[Plan], *, now: str, release_at: str | None = None) -> tuple[str | None, list[Plan]]:
    """Give each channel's plan its release and lock times from the site's edit windows.

    The release time is ``now`` plus the window, unless the Announcement has its own (a roundup's scheduled time), which is kept; the lock time is the lead before it. A plan that already
    names a time keeps it. Returns the Announcement's release time (the earliest of its channels', or the one given) and the plans to create the Deliveries from."""
    windows = windows_of(settings)
    placed: list[Plan] = []
    for plan in plans:
        found = resolve(windows, kind, plan.channel)
        release = plan.release_at or release_at or (_text(_instant(now) + timedelta(minutes=found.window_minutes)) if found and found.window_minutes else None)
        lock = plan.lock_at or (_text(_instant(release) - timedelta(minutes=found.lock_lead_minutes)) if release and found and found.lock_lead_minutes else None)
        placed.append(replace(plan, release_at=release, lock_at=lock))
    releases = [plan.release_at for plan in placed if plan.release_at]
    return (release_at or (min(releases) if releases else None)), placed
