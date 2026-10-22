"""Snapshot math: votes and profiles in, public-safe JSON out.

Nothing here knows a site, a storage layer or a clock: ``build_snapshot`` takes rows and a time and returns three
dictionaries. Public data holds opaque subject keys, counts, means, histograms, ``readerId`` and the chosen handle,
and never a siteSubject, a person id or an email.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .ranking import RankingParameters, composite, front_score, hype_gap, rank, rounded

READER_DATA_DIRECTORY = "_data/reader"
ITEMS_FILE = f"{READER_DATA_DIRECTORY}/items.json"
BOARD_FILE = f"{READER_DATA_DIRECTORY}/board.json"
READERS_FILE = f"{READER_DATA_DIRECTORY}/readers.json"
SNAPSHOT_FILES = (ITEMS_FILE, BOARD_FILE, READERS_FILE)
RATING_VALUES = (1, 2, 3, 4, 5)
TOP_READERS = 50
SECONDS_PER_HOUR = 3600
ROLE_READER = "reader"
ROLE_EDITOR = "editor"
UP = "up"
USED_IT = "used-it"


@dataclass(frozen=True)
class KarmaWeights:
    upvote: float = 1.0
    used_it: float = 2.0


@dataclass(frozen=True)
class SnapshotSettings:
    dimensions: tuple[str, ...] = ()
    karma: KarmaWeights = field(default_factory=KarmaWeights)
    ranking: RankingParameters = field(default_factory=RankingParameters)
    retirement_poll: bool = False


def settings_from_mapping(raw: Mapping) -> SnapshotSettings:
    karma, ranking = raw.get("karma") or {}, raw.get("ranking") or {}
    defaults = RankingParameters()
    return SnapshotSettings(
        retirement_poll=raw.get("retirementPoll") is True,
        dimensions=tuple(raw.get("dimensions") or ()),
        karma=KarmaWeights(upvote=float(karma.get("upvoteWeight", 1)), used_it=float(karma.get("usedItWeight", 2))),
        ranking=RankingParameters(
            half_life_hours=float(ranking.get("halfLifeHours", defaults.half_life_hours)),
            rising_window_hours=float(ranking.get("risingWindowHours", defaults.rising_window_hours)),
            reader_minimum=int(ranking.get("readerMinimum", defaults.reader_minimum)),
            editor_weight=float(ranking.get("editorWeight", defaults.editor_weight)),
            hype_minimum=int(raw.get("hypeMinimum", defaults.hype_minimum)),
        ),
    )


def seconds_of(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def iso(now_seconds: float) -> str:
    return datetime.fromtimestamp(now_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rating_stats(values: Collection[int]) -> dict:
    """``{mean, n, hist}`` with ``hist[i]`` the number of ``i + 1`` ratings; the mean is ``None`` when there are none."""
    histogram = [sum(1 for value in values if value == rating) for rating in RATING_VALUES]
    return {"mean": rounded(sum(values) / len(values)) if values else None, "n": len(values), "hist": histogram}


def ratings_by_role(votes: Iterable[Mapping], dimensions: Collection[str]) -> dict[str, dict[str, list[int]]]:
    grouped: dict[str, dict[str, list[int]]] = {role: defaultdict(list) for role in (ROLE_READER, ROLE_EDITOR)}
    for vote in votes:
        role = vote.get("voterRole")
        if vote["dimension"] in dimensions and role in grouped and isinstance(vote["value"], int) and 1 <= vote["value"] <= 5:
            grouped[role][vote["dimension"]].append(vote["value"])
    return grouped


def karma_by_reader(
    votes: Iterable[Mapping], submitter_of: Callable[[str], str | None], weights: KarmaWeights
) -> dict[str, float]:
    """Upvotes received by a reader's submissions from others times ``upvote``, plus used-it reports on them times ``used_it``.

    Until submissions exist ``submitter_of`` answers ``None`` for every subject and every karma is 0.
    """
    karma: dict[str, float] = defaultdict(float)
    for vote in votes:
        submitter = submitter_of(vote["subjectKey"])
        if submitter is None or submitter == vote["readerId"]:
            continue
        if vote["dimension"] == UP:
            karma[submitter] += weights.upvote
        elif vote["dimension"] == USED_IT:
            karma[submitter] += weights.used_it
    return dict(karma)


@dataclass(frozen=True)
class Snapshot:
    items: dict
    board: dict
    readers: dict
    karma: dict[str, int]


def build_snapshot(
    votes: Iterable[Mapping],
    profiles: Iterable[Mapping],
    *,
    published_at: Mapping[str, str | None],
    now_seconds: float,
    settings: SnapshotSettings,
    submitter_of: Callable[[str], str | None] = lambda subject: None,
) -> Snapshot:
    """``published_at`` holds exactly the published subjects (its values may be ``None``); votes on any other subject are ignored."""
    generated_at = iso(now_seconds)
    live_votes = [vote for vote in votes if vote["subjectKey"] in published_at]
    by_subject: dict[str, list[Mapping]] = defaultdict(list)
    for vote in live_votes:
        by_subject[vote["subjectKey"]].append(vote)

    items: dict[str, dict] = {}
    front_rows: list[dict] = []
    rising_rows: list[dict] = []
    window_start = now_seconds - settings.ranking.rising_window_hours * SECONDS_PER_HOUR
    for subject in sorted(by_subject):
        subject_votes = by_subject[subject]
        grouped = ratings_by_role(subject_votes, settings.dimensions)
        stats = {
            dimension: {role: rating_stats(grouped[role].get(dimension, [])) for role in (ROLE_READER, ROLE_EDITOR)}
            for dimension in settings.dimensions
        }
        editor_means = {dimension: stats[dimension][ROLE_EDITOR]["mean"] for dimension in settings.dimensions}
        reader_means = {dimension: stats[dimension][ROLE_READER]["mean"] for dimension in settings.dimensions}
        reader_counts = {dimension: stats[dimension][ROLE_READER]["n"] for dimension in settings.dimensions}
        editor_composite, reader_composite = composite(editor_means.values()), composite(reader_means.values())
        upvotes = [vote for vote in subject_votes if vote["dimension"] == UP]
        items[subject] = {
            "up": len(upvotes),
            "usedIt": sum(1 for vote in subject_votes if vote["dimension"] == USED_IT),
            "ratings": stats,
            "editor": None if editor_composite is None else rounded(editor_composite),
            "reader": None if reader_composite is None else rounded(reader_composite),
            "hypeGap": hype_gap(editor_means, reader_means, reader_counts, settings.ranking.hype_minimum),
        }
        published = published_at[subject]
        age_hours = (now_seconds - seconds_of(published)) / SECONDS_PER_HOUR if published else 0.0
        reader_n = max(reader_counts.values(), default=0)
        score = front_score(editor_composite, reader_composite, reader_n, age_hours, settings.ranking)
        if score is not None:
            front_rows.append(
                {
                    "subject": subject,
                    "score": score,
                    "editor": items[subject]["editor"],
                    "reader": items[subject]["reader"],
                    "readerN": reader_n,
                    "ageHours": rounded(max(age_hours, 0.0)),
                }
            )
        recent = sum(1 for vote in upvotes if seconds_of(vote["createdAt"]) >= window_start)
        if recent:
            rising_rows.append({"subject": subject, "upvotes": recent})

    karma = karma_by_reader(live_votes, submitter_of, settings.karma)
    profile_list = list(profiles)
    karma_values = {profile["readerId"]: int(round(karma.get(profile["readerId"], 0))) for profile in profile_list}
    reader_rows = [
        {"readerId": profile["readerId"], "handle": profile["handle"], "karma": karma_values[profile["readerId"]]}
        for profile in profile_list
        if profile.get("handle") and karma_values[profile["readerId"]] > 0
    ]
    top_readers = sorted(reader_rows, key=lambda row: (-row["karma"], row["handle"]))[:TOP_READERS]

    ranking = settings.ranking
    return Snapshot(
        items={"generatedAt": generated_at, "items": items},
        board={
            "generatedAt": generated_at,
            "parameters": {
                "halfLifeHours": ranking.half_life_hours,
                "risingWindowHours": ranking.rising_window_hours,
                "readerMinimum": ranking.reader_minimum,
                "editorWeight": ranking.editor_weight,
            },
            "front": rank(front_rows, "score"),
            "rising": rank(rising_rows, "upvotes"),
        },
        readers={"generatedAt": generated_at, "readers": top_readers},
        karma=karma_values,
    )


def encoded(payload: Mapping) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
