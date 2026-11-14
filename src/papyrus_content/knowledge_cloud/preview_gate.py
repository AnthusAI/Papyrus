"""Hold a knowledge run's bulk writes of Items until a person has seen them (PPY-84b0dd).

On 2026-11-02 a run published 1,366 wiki pages nobody had looked at. The ``wiki-sync`` stage is where the run writes Items, so the stage
asks this module before its ``--apply``: it plans the sync as a dry run, and ``decide`` answers *proceed* or *hold*.

* **A site's first run is a preview.** With no earlier run to compare with, the plan (counts by page kind and entity kind, and a sample)
  waits for a person: a hard-gate review request in the Notification Center. Accepting it makes the plan part of the site's history.
* **A later run proceeds unless its output differs sharply from the site's own history.** For every series (pages to create, update,
  or revise, by kind, and the total) the count is compared with what the earlier runs predict: the earlier counts give the mean and,
  once there are two, the spread (``predictive_tail``). A run is held when a series is more surprising than ``1 / ((n + 1) * k)``: the
  chance that the newest of ``n + 1`` runs happens to be the biggest of them, shared among the ``k`` series that wrote anything. Nothing
  here is a fixed cap: the more history a site has, the stricter the test, and the spread it learned decides what is normal for that site.
* **A held run writes nothing.** ``wiki-sync`` stops before ``--apply``, and ``projection`` skips the execution, so no page goes live and no
  snapshot with links to pages that do not exist is published. The next run plans again: an approved plan (or one close to it) goes through.

History is one small JSON file in the run state (``history/wiki-sync.json``): every evaluated run, its series and what became of it. A held
entry counts as history only once its request was accepted by a person; an agent's answer does not count.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

HISTORY_FILE = "history/wiki-sync.json"
RAISED_BY = "knowledge-run"
TOTAL = "all:writes"
UNCHANGED = "unchanged"
WRITTEN, HELD, APPROVED, REJECTED = "written", "held", "approved", "rejected"
#: Outcomes whose counts teach the comparison: what the run wrote, and what a person accepted.
LEARNED = (WRITTEN, APPROVED)
REQUEST_STATES = ("approved", "rejected", "open")
MAX_REQUEST_TEXT = 2000  # the review request's own limit on `ask` (review_requests.MAX_TEXT)


# -- the plan ----------------------------------------------------------------------------------------------------------
def _label(entry: Mapping[str, Any]) -> str:
    kind, entity_kind = entry.get("kind"), entry.get("entityKind")
    return f"{kind or entry.get('section') or 'page'}/{entity_kind}" if entity_kind else str(kind or entry.get("section") or "page")


def series_of(plan: Mapping[str, Any]) -> dict[str, int]:
    """What the sync would write, by ``<page kind>/<entity kind>:<action>``, plus the total. Pages it would leave alone are not counted."""
    counts: dict[str, int] = {}
    for page in plan.get("pages") or ():
        if page.get("action") != UNCHANGED:
            key = f"{_label(page)}:{page['action']}"
            counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    return {**dict(sorted(counts.items())), **({TOTAL: total} if total else {})}


def fingerprint_of(plan: Mapping[str, Any]) -> str:
    """The same plan has the same fingerprint: the pages and what would happen to each."""
    entries = sorted(
        [f"{page.get('section')}/{page.get('slug')}", page["action"]] for page in plan.get("pages") or () if page.get("action") != UNCHANGED
    )
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()[:16]


# -- the comparison ----------------------------------------------------------------------------------------------------
def predictive(counts: Sequence[int]) -> tuple[float, float]:
    """Mean and variance of the next run's count, learned from the earlier runs' counts.

    The mean is the Jeffreys estimate ``(sum + 1/2) / n`` (so a series never seen before still has a small, nonzero rate). The variance is
    that of a count whose rate is itself uncertain, ``mean * (1 + 1/n)``, or the spread the history actually shows (the sample variance, once
    there are two runs) with the same allowance, whichever is larger: a site whose counts swing widely is not held for swinging."""
    n = len(counts)
    mean = (sum(counts) + 0.5) / n
    spread = 0.0
    if n >= 2:
        average = sum(counts) / n
        spread = sum((count - average) ** 2 for count in counts) / (n - 1)
    return mean, max(mean, spread) * (1 + 1 / n)


def log10_tail(count: int, mean: float, variance: float) -> float:
    """log10 of the chance that a run's count is ``count`` or more, for a negative binomial with this mean and variance (a Poisson when the
    variance is no larger than the mean). A count at or below the mean is never extreme: 0 (a chance of 1)."""
    if count <= mean:
        return 0.0
    if variance <= mean * (1 + 1e-9):
        def log_pmf(k: int) -> float:
            return k * math.log(mean) - mean - math.lgamma(k + 1)
    else:
        size, p = mean * mean / (variance - mean), mean / variance

        def log_pmf(k: int) -> float:
            return math.lgamma(k + size) - math.lgamma(size) - math.lgamma(k + 1) + size * math.log(p) + k * math.log1p(-p)

    k = count
    total = term = log_pmf(k)
    while True:  # the terms past the mean shrink; stop when the next ones can no longer move the sum
        k += 1
        term = log_pmf(k)
        high, low = max(total, term), min(total, term)
        total = high + math.log1p(math.exp(low - high))
        if term < total - 40:
            break
    return min(total / math.log(10), 0.0)


@dataclass(frozen=True)
class Finding:
    series: str
    count: int
    expected: float
    log10_tail: float

    def to_dict(self) -> dict[str, Any]:
        return {"series": self.series, "count": self.count, "expected": round(self.expected, 2), "log10Tail": round(self.log10_tail, 1)}


@dataclass(frozen=True)
class Decision:
    action: str  # "proceed" or "hold"
    reason: str  # nothing_to_write | approved_plan | first_run | rejected_plan | within_history | differs_from_history
    findings: tuple[Finding, ...] = ()
    runs_compared: int = 0
    threshold: float | None = None

    @property
    def hold(self) -> bool:
        return self.action == "hold"


def compare(series: Mapping[str, int], earlier: Sequence[Mapping[str, int]]) -> Decision:
    """Compare this run's series with the earlier runs'. ``earlier`` must not be empty."""
    n = len(earlier)
    tested = {key: count for key, count in series.items() if count > 0}
    threshold = 1 / ((n + 1) * len(tested))
    flagged: list[Finding] = []
    for key, count in sorted(tested.items()):
        mean, variance = predictive([int(run.get(key, 0)) for run in earlier])
        log_tail = log10_tail(count, mean, variance)
        if log_tail < math.log10(threshold):
            flagged.append(Finding(key, count, mean, log_tail))
    return Decision("hold" if flagged else "proceed", "differs_from_history" if flagged else "within_history", tuple(flagged), n, threshold)


def decide(series: Mapping[str, int], fingerprint: str, learned: Sequence[Mapping[str, int]], approved: set[str], rejected: set[str]) -> Decision:
    if not series.get(TOTAL):
        return Decision("proceed", "nothing_to_write", runs_compared=len(learned))
    if fingerprint in approved:
        return Decision("proceed", "approved_plan", runs_compared=len(learned))
    if fingerprint in rejected:
        return Decision("hold", "rejected_plan", runs_compared=len(learned))
    if not learned:
        return Decision("hold", "first_run")
    return compare(series, learned)


# -- the history -------------------------------------------------------------------------------------------------------
def load_history(state: Any) -> list[dict[str, Any]]:
    text = state.read_text(HISTORY_FILE)
    return list(json.loads(text).get("runs", [])) if text else []


def save_history(state: Any, entries: Sequence[Mapping[str, Any]]) -> None:
    state.write_text(HISTORY_FILE, json.dumps({"version": 1, "runs": list(entries)}, indent=2, sort_keys=True))


def request_status(request: Mapping[str, Any]) -> str:
    """``approved`` only when a person accepted it; ``rejected`` when it was answered another way or withdrawn; else ``open``."""
    state = request.get("state")
    answer = request.get("answer") or {}
    if state == "answered" and answer.get("decision") == "approve" and not str(answer.get("by") or "").startswith("agent:"):
        return "approved"
    return "rejected" if state in ("answered", "withdrawn", "timed_out") else "open"


def settle(entries: list[dict[str, Any]], get_request: Callable[[str], Mapping[str, Any]]) -> bool:
    """Read the requests of held entries and mark them approved or rejected (in place). Returns whether anything changed."""
    changed = False
    for entry in entries:
        if entry.get("outcome") == HELD and entry.get("requestId"):
            status = request_status(get_request(entry["requestId"]))
            if status != "open":
                entry["outcome"] = APPROVED if status == "approved" else REJECTED
                changed = True
    return changed


def record(entries: list[dict[str, Any]], entry: Mapping[str, Any]) -> None:
    """Add a run's entry, replacing an earlier entry of the same run and plan (a retried stage)."""
    entries[:] = [old for old in entries if (old.get("runId"), old.get("fingerprint")) != (entry.get("runId"), entry.get("fingerprint"))]
    entries.append(dict(entry))


# -- the request a person reads -----------------------------------------------------------------------------------------
def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def request_id(publication: str, fingerprint: str) -> str:
    return f"rr-wiki-sync-{publication}-{fingerprint}".lower()


def _sample(plan: Mapping[str, Any], room: int) -> list[str]:
    """Titles to show: a few from every series in turn, in a stable but arbitrary order (a hash of the title, so it is not just the first
    alphabetically), until ``room`` characters are used."""
    groups: dict[str, list[str]] = {}
    for page in plan.get("pages") or ():
        if page.get("action") != UNCHANGED and page.get("title"):
            groups.setdefault(f"{_label(page)}:{page['action']}", []).append(str(page["title"]))
    for titles in groups.values():
        titles.sort(key=lambda title: hashlib.sha256(title.encode()).hexdigest())
    picked: dict[str, list[str]] = {key: [] for key in sorted(groups)}
    used, progressed = 0, True
    while progressed:
        progressed = False
        for key, chosen in picked.items():
            if len(chosen) >= len(groups[key]):
                continue
            title = groups[key][len(chosen)]
            cost = len(title) + 2 + (0 if chosen else len(key) + 4)
            if used + cost > room:
                return [f"{name}: {', '.join(values)}" for name, values in picked.items() if values]
            chosen.append(title)
            used += cost
            progressed = True
    return [f"{name}: {', '.join(values)}" for name, values in picked.items() if values]


def describe(plan: Mapping[str, Any], series: Mapping[str, int], decision: Decision, *, publication: str) -> tuple[str, str]:
    """The ``reason`` (headline) and ``ask`` (details) of the review request. The ask stays within the request's own text limit."""
    total = series.get(TOTAL, 0)
    if decision.reason == "first_run":
        reason = f"First knowledge run for {publication}: {_plural(total, 'page')} would be written. Nothing has been written."
        why = "This is the site's first run, so a person looks at what it would write before it writes anything."
    else:
        worst = decision.findings[0] if decision.findings else None
        reason = f"Knowledge run for {publication} held: {_plural(total, 'page')} would be written, which is unlike this site's earlier runs. Nothing has been written."
        why = "; ".join(
            f"{finding.series} would write {finding.count:,} (this site's earlier runs predict about {finding.expected:,.1f})" for finding in decision.findings[:3]
        ) or (f"{worst.series}" if worst else "")
    kinds = [f"{key} {count:,}" for key, count in sorted(series.items(), key=lambda pair: (-pair[1], pair[0])) if key != TOTAL]  # the biggest first
    close = (
        "Accept to let the next run write pages like these. Reject to keep the run held. Until one of those, nothing is written and the next run checks again."
    )
    head = f"{why}\n\nWould write ({_plural(total, 'page')}): "
    sample_room = MAX_REQUEST_TEXT - len(head) - len(close) - 40
    shown, size = [], 0
    for item in kinds:
        if size + len(item) + 2 > sample_room // 2:
            shown.append(f"and {len(kinds) - len(shown)} more kinds")
            break
        shown.append(item)
        size += len(item) + 2
    table = ", ".join(shown)
    room = MAX_REQUEST_TEXT - len(head) - len(table) - len(close) - 30
    sample = _sample(plan, max(room, 0))
    ask = head + table + ("\n\nA sample:\n" + "\n".join(sample) if sample else "") + "\n\n" + close
    return reason, ask[:MAX_REQUEST_TEXT]


@dataclass
class GateResult:
    decision: Decision
    series: dict[str, int]
    fingerprint: str
    request_id: str | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)

    def details(self) -> dict[str, Any]:
        return {
            "status": "held" if self.decision.hold else "proceed", "reason": self.decision.reason, "writes": self.series.get(TOTAL, 0),
            "fingerprint": self.fingerprint, "requestId": self.request_id, "runsCompared": self.decision.runs_compared,
            "threshold": self.decision.threshold, "findings": [finding.to_dict() for finding in self.decision.findings], "series": self.series,
        }
