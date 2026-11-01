"""Single-item signals and the merged idea queue (PPY-2e72e3)."""

from __future__ import annotations

from papyrus_content.ideas.context_packs import build_packs, rank_packs
from papyrus_content.ideas.item_signals import ITEM, ordered_lineage_ids, ordered_queue, score_items
from papyrus_content.ideas.monitor_stories import MonitoredItem
from papyrus_content.ideas.signal_inputs import ConceptLink
from test_idea_context_packs import LOOKUPS, NOW, acceptance_votes, inputs, message, moment, vote


def candidate(lineage: str, monitor: str | None = None, score: float | None = None) -> MonitoredItem:
    verdict = None if score is None else {"label": "include", "score": score, "positiveLabel": "include"}
    return MonitoredItem(lineage, lineage, f"Title {lineage}", f"https://example.org/{lineage}", moment(1), None, monitor, "accepted", verdict=verdict)


def background(count: int = 30):
    return [vote(f"background-{number}", 20 + number, concepts=()) for number in range(count)]


def lively_thread(lineage: str, count: int = 6):
    return [message(number, 0.5 + number * 0.1, thread=f"thread-{lineage}", anchor=f"reference#{lineage}") for number in range(count)]


def test_a_monitor_less_reference_with_a_lively_thread_outranks_a_quiet_monitored_one():
    candidates = [candidate("quiet", "hn", 0.6), candidate("lively", None)]
    signals = inputs(messages=lively_thread("lively"), votes=[vote("lively", 2), *background()])
    scored = score_items(signals, candidates)
    assert scored[0].item.lineage_id == "lively" and scored[0].signal["type"] == ITEM and scored[0].surprise > 0


def test_a_quiet_site_scores_no_single_item_candidate():
    candidates = [candidate(f"ref-{number}") for number in range(5)]
    assert score_items(inputs(votes=[vote("ref-1", 3, concepts=())]), candidates) == []


def test_the_cyclotron_probability_is_a_percentile_against_the_site_own_candidates():
    candidates = [candidate(f"ref-{number}", "hn", 0.01 * number) for number in range(1, 41)]
    scored = score_items(inputs(), candidates)
    assert scored[0].item.lineage_id == "ref-40"
    assert 0 < len(scored) < len(candidates)
    assert [row.surprise for row in scored] == sorted((row.surprise for row in scored), reverse=True)


def test_concept_links_and_accepted_concepts_count_for_an_item():
    signals = inputs(votes=[*acceptance_votes()[21:], *background(60)], links=[ConceptLink("plain", "concept-voice", "mentions")])
    scored = score_items(signals, [candidate("plain"), candidate("unlinked")])
    assert [row.item.lineage_id for row in scored] == ["plain"]


def test_packs_and_single_items_share_one_queue_and_neither_starves():
    signals = inputs(messages=lively_thread("lively"), votes=[*acceptance_votes(), *background()])
    packs = rank_packs(build_packs(signals, LOOKUPS, now=NOW))
    scored = score_items(signals, [candidate("lively")])
    queue = ordered_queue(packs, scored)
    assert {entry.kind for entry in queue} == {"pack", "item"}
    assert len(queue) == len(packs) + len(scored)
    assert ordered_lineage_ids(queue) == ["lively"]
    surprises = [entry.surprise for entry in queue[:2]]
    assert surprises == sorted(surprises, reverse=True)


def test_only_items_are_queued_when_there_are_no_packs():
    scored = score_items(inputs(messages=lively_thread("lively"), votes=background()), [candidate("lively")])
    assert [entry.kind for entry in ordered_queue([], scored)] == ["item"]
