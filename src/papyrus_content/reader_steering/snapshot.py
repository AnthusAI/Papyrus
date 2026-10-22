"""Snapshot math: votes and profiles in, public-safe JSON out.

Nothing here knows a site, a storage layer or a clock: ``build_snapshot`` takes rows and a time and returns three
dictionaries. Public data holds opaque subject keys, counts, means, histograms, ``readerId`` and the chosen handle,
and never a siteSubject, a person id or an email.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .ranking import (
    COMBINATION_SHRINKAGE,
    COMBINATIONS,
    HypeGapGroups,
    RankingParameters,
    composite,
    front_score,
    hype_gap,
    rank,
    reader_share,
    rounded,
    shrinkage_front_score,
)

READER_DATA_DIRECTORY = "_data/reader"
ITEMS_FILE = f"{READER_DATA_DIRECTORY}/items.json"
BOARD_FILE = f"{READER_DATA_DIRECTORY}/board.json"
READERS_FILE = f"{READER_DATA_DIRECTORY}/readers.json"
SUBJECTS_FILE = f"{READER_DATA_DIRECTORY}/subjects.json"
SUBMISSIONS_FILE = f"{READER_DATA_DIRECTORY}/submissions.json"
VOTES_DIRECTORY = f"{READER_DATA_DIRECTORY}/votes"
COMMENTS_DIRECTORY = f"{READER_DATA_DIRECTORY}/comments"
COMMENT_VISIBLE = "visible"
SAFE_FILE_SUBJECT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._:-]*")
SNAPSHOT_FILES = (ITEMS_FILE, BOARD_FILE, READERS_FILE, SUBMISSIONS_FILE, SUBJECTS_FILE)
SUBMISSIONS_LISTED = 200
NEW_LISTED = 50
KIND_ITEM = "item"
KIND_SUBMISSION = "submission"
DEFAULT_SUBJECT_TYPES = (KIND_ITEM, KIND_SUBMISSION)
FLAG_KINDS = ("wrong", "belongs_under", "better_name")
SUBMISSION_ID = re.compile(r"sub-[0-9a-f]{24}")
SUBMISSION_PENDING = "pending"
SUBMISSION_PROMOTED = "promoted"
VISIBLE_SUBMISSION_STATES = (SUBMISSION_PENDING, SUBMISSION_PROMOTED)
RATING_VALUES = (1, 2, 3, 4, 5)
TOP_READERS = 50
SECONDS_PER_HOUR = 3600
SHRINKAGE_NEW_ACCOUNT_WEIGHT = 1 / 3
SHRINKAGE_RISING_MINIMUM_HOURS = 24.0
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
    hype_gap: HypeGapGroups | None = None
    subject_types: tuple[str, ...] = DEFAULT_SUBJECT_TYPES


def settings_from_mapping(raw: Mapping) -> SnapshotSettings:
    karma, ranking, limits = raw.get("karma") or {}, raw.get("ranking") or {}, raw.get("limits") or {}
    defaults = RankingParameters()
    hype = raw.get("hypeGap")
    combination = ranking.get("combination", defaults.combination)
    if combination not in COMBINATIONS:
        raise ValueError(f"ranking.combination must be one of {', '.join(COMBINATIONS)}")
    shrinking = combination == COMBINATION_SHRINKAGE  # the account-age rules default on only with shrinkage, so other sites do not change
    return SnapshotSettings(
        retirement_poll=raw.get("retirementPoll") is True,
        hype_gap=HypeGapGroups(plus=tuple(hype.get("plus") or ()), minus=tuple(hype.get("minus") or ())) if hype else None,
        dimensions=tuple(raw.get("dimensions") or ()),
        subject_types=tuple((raw.get("subjects") or {}).get("types") or DEFAULT_SUBJECT_TYPES),
        karma=KarmaWeights(upvote=float(karma.get("upvoteWeight", 1)), used_it=float(karma.get("usedItWeight", 2))),
        ranking=RankingParameters(
            half_life_hours=float(ranking.get("halfLifeHours", defaults.half_life_hours)),
            rising_window_hours=float(ranking.get("risingWindowHours", defaults.rising_window_hours)),
            reader_minimum=int(ranking.get("readerMinimum", defaults.reader_minimum)),
            editor_weight=float(ranking.get("editorWeight", defaults.editor_weight)),
            hype_minimum=int(raw.get("hypeMinimum", defaults.hype_minimum)),
            combination=combination,
            shrinkage_k=float(ranking.get("shrinkageK", defaults.shrinkage_k)),
            reader_share_cap=float(ranking.get("readerShareCap", defaults.reader_share_cap)),
            new_account_weight=float(ranking.get("newAccountWeight", SHRINKAGE_NEW_ACCOUNT_WEIGHT if shrinking else 1.0)),
            new_account_hours=float(limits.get("newAccountHours", defaults.new_account_hours)),
            rising_minimum_account_hours=float(
                ranking.get("risingMinimumAccountHours", SHRINKAGE_RISING_MINIMUM_HOURS if shrinking else 0.0)
            ),
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


def distinct_raters(votes: Iterable[Mapping], dimensions: Collection[str]) -> int:
    """Distinct readers (editors excluded) who left a valid rating on any dimension; upvotes and used-it do not count."""
    return len(
        {
            vote["readerId"]
            for vote in votes
            if vote.get("voterRole") == ROLE_READER
            and vote["dimension"] in dimensions
            and isinstance(vote["value"], int)
            and 1 <= vote["value"] <= 5
        }
    )


def account_ages(profiles: Iterable[Mapping]) -> Callable[[Mapping], float | None]:
    """A function giving a vote's account age in hours when it was cast, or ``None`` when the profile or a timestamp is unknown.

    Age at the time of the vote, not at the snapshot: a rating from a day-old sock stays discounted after the sock turns a day old.
    """
    created = {profile["readerId"]: seconds_of(profile["createdAt"]) for profile in profiles if profile.get("createdAt")}

    def age(vote: Mapping) -> float | None:
        start, cast = created.get(vote.get("readerId")), vote.get("createdAt")
        return None if start is None or not cast else (seconds_of(cast) - start) / SECONDS_PER_HOUR

    return age


def old_enough(age_hours: float | None, minimum_hours: float) -> bool:
    """Whether an account counts under a minimum age; an unknown age (no profile row) is not held against the vote."""
    return minimum_hours <= 0 or age_hours is None or age_hours >= minimum_hours


def weighted_reader_view(
    reader_votes: Mapping[str, list[tuple[int, float]]], dimensions: Iterable[str]
) -> tuple[dict[str, float | None], dict[str, float]]:
    """``(means, weights)`` per dimension from ``(value, weight)`` pairs: the weighted mean (``None`` without ratings) and the weight sum."""
    means: dict[str, float | None] = {}
    weights: dict[str, float] = {}
    for dimension in dimensions:
        pairs = reader_votes.get(dimension, [])
        total = sum(weight for _, weight in pairs)
        weights[dimension] = total
        means[dimension] = sum(value * weight for value, weight in pairs) / total if total > 0 else None
    return means, weights


def reader_rating_pairs(
    votes: Iterable[Mapping], dimensions: Collection[str], age_of: Callable[[Mapping], float | None], settings: SnapshotSettings
) -> dict[str, list[tuple[int, float]]]:
    """Valid reader ratings as ``(value, weight)``: weight ``new_account_weight`` when the account was younger than ``new_account_hours``, else 1."""
    ranking = settings.ranking
    pairs: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for vote in votes:
        if (
            vote.get("voterRole") == ROLE_READER
            and vote["dimension"] in dimensions
            and isinstance(vote["value"], int)
            and 1 <= vote["value"] <= 5
        ):
            age = age_of(vote)
            young = age is not None and age < ranking.new_account_hours
            pairs[vote["dimension"]].append((vote["value"], ranking.new_account_weight if young else 1.0))
    return pairs


def vote_subject_type(vote: Mapping) -> str:
    """The subject type of a vote row; rows written before subject types have none and are read by the shape of their key."""
    return vote.get("subjectType") or (KIND_SUBMISSION if SUBMISSION_ID.fullmatch(vote["subjectKey"]) else KIND_ITEM)


def subject_id_of(vote_or_flag: Mapping) -> str:
    """The id of the subject a row is about: the key itself for items and submissions, the key without its ``type:`` prefix for the rest."""
    kind = vote_subject_type(vote_or_flag)
    key = vote_or_flag["subjectKey"]
    return key if kind in DEFAULT_SUBJECT_TYPES else key[len(kind) + 1 :]


def vote_summary(
    votes: Iterable[Mapping], flags: Iterable[Mapping], age_of: Callable[[Mapping], float | None], settings: SnapshotSettings
) -> dict:
    """``{up, down, net, score, flags}`` for one subject from its up/down votes and flags.

    ``up`` and ``down`` are plain counts. ``net`` is the weighted up minus the weighted down, a vote from a profile younger than
    ``new_account_hours`` at the time it was cast weighing ``new_account_weight`` (an editor's vote always weighs 1). ``score``
    is the same shrinkage as the rating combination with a neutral prior of 0: ``share(n) * (U - D) / n`` with ``n = U + D``
    (weighted) and ``share = min(n / (k + n), reader_share_cap)``, so it lies between ``-cap`` and ``cap``. ``flags`` counts flags
    per kind and carries no reader.
    """
    ranking = settings.ranking
    up = down = 0
    weighted_up = weighted_down = 0.0
    for vote in votes:
        if vote["dimension"] != UP or vote["value"] not in (1, -1):
            continue
        age = age_of(vote)
        young = age is not None and age < ranking.new_account_hours and vote.get("voterRole") != ROLE_EDITOR
        weight = ranking.new_account_weight if young else 1.0
        if vote["value"] == 1:
            up += 1
            weighted_up += weight
        else:
            down += 1
            weighted_down += weight
    total = weighted_up + weighted_down
    score = rounded(reader_share(total, ranking) * (weighted_up - weighted_down) / total) if total > 0 else 0.0
    counts = {kind: 0 for kind in FLAG_KINDS}
    for flag in flags:
        if flag.get("kind") in counts:
            counts[flag["kind"]] += 1
    return {"up": up, "down": down, "net": rounded(weighted_up - weighted_down), "score": score, "flags": counts}


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
            if vote["value"] != 1:
                continue  # a downvote earns nothing and takes nothing away
            karma[submitter] += weights.upvote
        elif vote["dimension"] == USED_IT:
            karma[submitter] += weights.used_it
    return dict(karma)


def item_hype_gap(
    settings: SnapshotSettings,
    editor_means: Mapping[str, float | None],
    reader_means: Mapping[str, float | None],
    editor_counts: Mapping[str, int],
    reader_counts: Mapping[str, int],
) -> dict | None:
    """``{reader, editor}`` gaps, each ``None`` until its own ratings are enough; ``None`` altogether without ``hypeGap`` groups.

    The reader gap needs ``hype_minimum`` ratings on every dimension involved; the editor gap needs one editor rating on each.
    """
    groups = settings.hype_gap
    if groups is None:
        return None
    return {
        "reader": hype_gap(groups, reader_means, reader_counts, settings.ranking.hype_minimum),
        "editor": hype_gap(groups, editor_means, editor_counts, 1),
    }


@dataclass(frozen=True)
class Snapshot:
    items: dict
    board: dict
    readers: dict
    karma: dict[str, int]
    submissions: dict
    subjects: dict
    comments: dict[str, dict]
    """Subject key to the content of its comment file, for every subject with a visible comment or a stub."""
    votes: dict[str, dict] = field(default_factory=dict)
    """Subject type to the content of its ``votes/<type>.json`` file, for every enabled type."""


def visible_submissions(submissions: Iterable[Mapping]) -> list[Mapping]:
    """Pending and promoted submissions, newest first; hidden ones (and any other state) are never public."""
    visible = [submission for submission in submissions if submission.get("state") in VISIBLE_SUBMISSION_STATES]
    return sorted(visible, key=lambda submission: (submission["createdAt"], submission["id"]), reverse=True)


def submitters(submissions: Iterable[Mapping]) -> dict[str, str]:
    """Subject key to the readerId who submitted it: the submission id, and the draft item's key once it is promoted."""
    found: dict[str, str] = {}
    for submission in visible_submissions(submissions):
        found[submission["id"]] = submission["readerId"]
        if submission.get("itemId"):
            found[submission["itemId"]] = submission["readerId"]
    return found


def new_rows(published_items: Iterable[Mapping], submissions: Iterable[Mapping]) -> list[dict]:
    """``{subject, kind, at}``, newest first: published items and pending submissions interleaved by time (``at``), at most ``NEW_LISTED``."""
    rows = [(item["publishedAt"], KIND_ITEM, item["subject"]) for item in published_items if item.get("publishedAt")]
    rows += [(submission["createdAt"], KIND_SUBMISSION, submission["id"]) for submission in submissions if submission.get("state") == SUBMISSION_PENDING]
    rows.sort(key=lambda row: (seconds_of(row[0]), row[2]), reverse=True)
    return [{"subject": subject, "kind": kind, "at": at} for at, kind, subject in rows[:NEW_LISTED]]


def subject_index(subjects: Collection[str], published_items: Iterable[Mapping], submissions: Iterable[Mapping]) -> dict[str, dict]:
    """Subject key to ``{kind, title, url, section, date}`` for each wanted subject that is a published item or a visible submission.

    A submission also carries ``domain`` and ``state``; its ``url`` is the source it points to. Public-safe fields only.
    """
    wanted = set(subjects)
    found: dict[str, dict] = {}
    for item in published_items:
        if item["subject"] in wanted:
            found[item["subject"]] = {
                "kind": KIND_ITEM,
                "title": item["title"],
                "url": item["url"],
                "section": item.get("section"),
                "date": item.get("date"),
            }
    for submission in submissions:
        if submission["id"] in wanted and submission["id"] not in found:
            found[submission["id"]] = {
                "kind": KIND_SUBMISSION,
                "title": submission["title"],
                "url": submission["canonicalUrl"],
                "domain": submission["domain"],
                "state": submission["state"],
                "section": None,
                "date": submission["createdAt"][:10],
            }
    return found


def comments_key(subject: str) -> str | None:
    """The site key of a subject's comment file, or ``None`` for a subject that is not safe as a file name."""
    return f"{COMMENTS_DIRECTORY}/{subject}.json" if SAFE_FILE_SUBJECT.fullmatch(subject) else None


def comment_threads(comments: Iterable[Mapping], handles: Mapping[str, str], open_subjects: Collection[str]) -> dict[str, list[dict]]:
    """Per subject, the public comment list: visible comments oldest first, and a stub for a deleted or hidden top-level comment that still has visible replies.

    A stub is ``{id, stub: true, parent: null, createdAt}``: it keeps the thread readable and carries no author or text.
    """
    grouped: dict[str, list[Mapping]] = defaultdict(list)
    for comment in comments:
        if comment["subjectKey"] in open_subjects:
            grouped[comment["subjectKey"]].append(comment)
    threads: dict[str, list[dict]] = {}
    for subject, rows in grouped.items():
        ordered = sorted(rows, key=lambda comment: (comment["createdAt"], comment["id"]))
        with_replies = {comment.get("parentId") for comment in ordered if comment.get("state") == COMMENT_VISIBLE and comment.get("parentId")}
        entries: list[dict] = []
        for comment in ordered:
            if comment.get("state") == COMMENT_VISIBLE:
                entries.append(
                    {
                        "id": comment["id"],
                        "readerId": comment["readerId"],
                        "handle": handles.get(comment["readerId"]),
                        "body": comment["body"],
                        "createdAt": comment["createdAt"],
                        "parent": comment.get("parentId") or None,
                        "edited": bool(comment.get("editedAt")),
                    }
                )
            elif comment["id"] in with_replies and not comment.get("parentId"):
                entries.append({"id": comment["id"], "stub": True, "parent": None, "createdAt": comment["createdAt"]})
        if entries:
            threads[subject] = entries
    return threads


def public_submission(submission: Mapping, handles: Mapping[str, str]) -> dict:
    row = {
        "id": submission["id"],
        "url": submission["canonicalUrl"],
        "domain": submission["domain"],
        "title": submission["title"],
        "kind": submission.get("kind"),
        "readerId": submission["readerId"],
        "handle": handles.get(submission["readerId"]),
        "createdAt": submission["createdAt"],
        "state": submission["state"],
        "similar": list(submission.get("similar") or []),
    }
    if submission.get("note"):
        row["note"] = submission["note"]
    if submission.get("itemId"):
        row["itemId"] = submission["itemId"]
    return row


def typed_vote_files(
    votes: Iterable[Mapping], flags: Iterable[Mapping], age_of: Callable[[Mapping], float | None], settings: SnapshotSettings, generated_at: str
) -> dict[str, dict]:
    """Per enabled subject type, ``{generatedAt, type, subjects: {id: {up, down, net, score, flags}}}``; a type nobody voted on has an empty file."""
    votes_by: dict[tuple[str, str], list[Mapping]] = defaultdict(list)
    flags_by: dict[tuple[str, str], list[Mapping]] = defaultdict(list)
    for vote in votes:
        votes_by[(vote_subject_type(vote), subject_id_of(vote))].append(vote)
    for flag in flags:
        flags_by[(vote_subject_type(flag), subject_id_of(flag))].append(flag)
    files: dict[str, dict] = {}
    for kind in settings.subject_types:
        subjects = {
            identifier: vote_summary(votes_by.get((kind, identifier), ()), flags_by.get((kind, identifier), ()), age_of, settings)
            for identifier in sorted({identifier for (found, identifier) in (*votes_by, *flags_by) if found == kind})
        }
        files[kind] = {"generatedAt": generated_at, "type": kind, "subjects": subjects}
    return files


def votes_key(kind: str) -> str:
    return f"{VOTES_DIRECTORY}/{kind}.json"


def build_snapshot(
    votes: Iterable[Mapping],
    profiles: Iterable[Mapping],
    *,
    published_at: Mapping[str, str | None],
    now_seconds: float,
    settings: SnapshotSettings,
    submitter_of: Callable[[str], str | None] | None = None,
    submissions: Iterable[Mapping] = (),
    comments: Iterable[Mapping] = (),
    published_items: Iterable[Mapping] = (),
    flags: Iterable[Mapping] = (),
) -> Snapshot:
    """``published_at`` holds exactly the published subjects (its values may be ``None``); votes on any other subject are ignored.

    Visible submissions (pending or promoted) are subjects too, published when they were submitted. ``submitter_of`` defaults to
    the readers of those submissions, so upvotes and used-it reports on a submission (or on the item it became) earn its submitter karma.
    """
    generated_at = iso(now_seconds)
    item_rows = list(published_items)  # {subject, title, url, section, date, publishedAt}: the page facts the task resolved
    submission_rows = visible_submissions(submissions)
    published_at = {**{submission["id"]: submission["createdAt"] for submission in submission_rows}, **published_at}
    if submitter_of is None:
        submitter_of = submitters(submission_rows).get
    profile_rows = list(profiles)
    handles = {profile["readerId"]: profile["handle"] for profile in profile_rows if profile.get("handle")}
    threads = comment_threads(comments, handles, published_at)
    comment_counts = {subject: sum(1 for entry in entries if not entry.get("stub")) for subject, entries in threads.items()}
    enabled_types = settings.subject_types
    all_votes = [vote for vote in votes if vote_subject_type(vote) in enabled_types]
    all_flags = [flag for flag in flags if flag.get("subjectType") in enabled_types]

    def is_live(row: Mapping) -> bool:
        """Items and submissions count while they are published or visible; the other types have no record to check."""
        return row["subjectKey"] in published_at if vote_subject_type(row) in DEFAULT_SUBJECT_TYPES else True

    live_votes = [vote for vote in all_votes if is_live(vote)]
    live_flags = [flag for flag in all_flags if is_live(flag)]
    by_subject: dict[str, list[Mapping]] = defaultdict(list)
    flags_by_subject: dict[str, list[Mapping]] = defaultdict(list)
    for vote in live_votes:
        if vote_subject_type(vote) in DEFAULT_SUBJECT_TYPES:
            by_subject[vote["subjectKey"]].append(vote)
    for flag in live_flags:
        flags_by_subject[flag["subjectKey"]].append(flag)
        if vote_subject_type(flag) in DEFAULT_SUBJECT_TYPES:
            by_subject.setdefault(flag["subjectKey"], [])
    for subject, count in comment_counts.items():
        if count:
            by_subject.setdefault(subject, [])  # a subject with comments and no votes still gets its numbers (zeros) and its comment count

    items: dict[str, dict] = {}
    front_rows: list[dict] = []
    rising_rows: list[dict] = []
    window_start = now_seconds - settings.ranking.rising_window_hours * SECONDS_PER_HOUR
    age_of = account_ages(profile_rows)
    minimum_age = settings.ranking.rising_minimum_account_hours
    shrinking = settings.ranking.combination == COMBINATION_SHRINKAGE
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
        editor_counts = {dimension: stats[dimension][ROLE_EDITOR]["n"] for dimension in settings.dimensions}
        editor_composite, reader_composite = composite(editor_means.values()), composite(reader_means.values())
        upvotes = [vote for vote in subject_votes if vote["dimension"] == UP and vote["value"] == 1]
        used_it_reporters = {
            vote["readerId"]
            for vote in subject_votes
            if vote["dimension"] == USED_IT and vote.get("voterRole") != ROLE_EDITOR and old_enough(age_of(vote), minimum_age)
        }
        items[subject] = {
            "up": len(upvotes),
            "usedIt": sum(1 for vote in subject_votes if vote["dimension"] == USED_IT),
            "usedItReporters": len(used_it_reporters),
            "comments": comment_counts.get(subject, 0),
            "raters": distinct_raters(subject_votes, settings.dimensions),
            "ratings": stats,
            "editor": None if editor_composite is None else rounded(editor_composite),
            "reader": None if reader_composite is None else rounded(reader_composite),
            "hypeGap": item_hype_gap(settings, editor_means, reader_means, editor_counts, reader_counts),
            **{key: value for key, value in vote_summary(subject_votes, flags_by_subject.get(subject, ()), age_of, settings).items() if key != "up"},
        }
        published = published_at[subject]
        age_hours = (now_seconds - seconds_of(published)) / SECONDS_PER_HOUR if published else 0.0
        discounted = settings.ranking.new_account_weight != 1.0
        if shrinking or discounted:
            weighted_means, weighted_counts = weighted_reader_view(
                reader_rating_pairs(subject_votes, settings.dimensions, age_of, settings), settings.dimensions
            )
        else:
            weighted_means, weighted_counts = reader_means, reader_counts
        reader_n = max(weighted_counts.values(), default=0)
        if shrinking:
            score = shrinkage_front_score(
                [editor_means[dimension] for dimension in settings.dimensions],
                [weighted_means[dimension] for dimension in settings.dimensions],
                [weighted_counts[dimension] for dimension in settings.dimensions],
                age_hours,
                settings.ranking,
            )
        else:
            weighted_composite = composite(weighted_means.values()) if discounted else reader_composite
            score = front_score(editor_composite, weighted_composite, reader_n, age_hours, settings.ranking)
        reader_n = int(reader_n) if reader_n == int(reader_n) else rounded(reader_n)
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
        recent = sum(1 for vote in upvotes if seconds_of(vote["createdAt"]) >= window_start and old_enough(age_of(vote), minimum_age))
        if recent:
            rising_rows.append({"subject": subject, "upvotes": recent})

    karma = karma_by_reader(live_votes, submitter_of, settings.karma)
    profile_list = profile_rows
    karma_values = {profile["readerId"]: int(round(karma.get(profile["readerId"], 0))) for profile in profile_list}
    reader_rows = [
        {"readerId": profile["readerId"], "handle": profile["handle"], "karma": karma_values[profile["readerId"]]}
        for profile in profile_list
        if profile.get("handle") and karma_values[profile["readerId"]] > 0
    ]
    top_readers = sorted(reader_rows, key=lambda row: (-row["karma"], row["handle"]))[:TOP_READERS]

    for kind, payload in typed_vote_files(live_votes, live_flags, age_of, settings, generated_at).items():
        if kind in DEFAULT_SUBJECT_TYPES:
            continue
        for identifier, summary in payload["subjects"].items():
            key = f"{kind}:{identifier}"  # the subject key; items.json holds every subject under its key, so a reader of one file finds them all
            items[key] = {**summary, "comments": comment_counts.get(key, 0)}
    vote_files = typed_vote_files(live_votes, live_flags, age_of, settings, generated_at)
    ranking = settings.ranking
    front, rising, new = rank(front_rows, "score"), rank(rising_rows, "upvotes"), new_rows(item_rows, submission_rows)
    listed = {row["subject"] for row in (*front, *rising, *new)}
    return Snapshot(
        items={"generatedAt": generated_at, "items": items},
        board={
            "generatedAt": generated_at,
            "parameters": {
                "halfLifeHours": ranking.half_life_hours,
                "risingWindowHours": ranking.rising_window_hours,
                "readerMinimum": ranking.reader_minimum,
                "displayMinimum": ranking.hype_minimum,
                "editorWeight": ranking.editor_weight,
                "combination": ranking.combination,
                "shrinkageK": ranking.shrinkage_k,
                "readerShareCap": ranking.reader_share_cap,
                "newAccountWeight": ranking.new_account_weight,
                "newAccountHours": ranking.new_account_hours,
                "risingMinimumAccountHours": ranking.rising_minimum_account_hours,
            },
            "front": front,
            "rising": rising,
            "new": new,
        },
        subjects={
            "generatedAt": generated_at,
            "subjects": subject_index(listed, item_rows, submission_rows),
            "types": list(enabled_types),
            "votes": {kind: payload["subjects"] for kind, payload in vote_files.items()},
        },
        readers={"generatedAt": generated_at, "readers": top_readers},
        karma=karma_values,
        submissions={
            "generatedAt": generated_at,
            "submissions": [public_submission(submission, handles) for submission in submission_rows[:SUBMISSIONS_LISTED]],
        },
        comments={
            subject: {"generatedAt": generated_at, "subject": subject, "comments": entries}
            for subject, entries in threads.items()
            if comments_key(subject) is not None
        },
        votes=vote_files,
    )


def encoded(payload: Mapping) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
