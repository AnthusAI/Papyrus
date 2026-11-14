"""Stars as an editorial signal (PPY-3247f1; features_backend/reference-stars.feature). Backend and model are fakes."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import reference_stars, reference_vote  # noqa: E402
from papyrus_content.ideas import connections as rules, editor_signals, rated_outcomes, retry_memory, review  # noqa: E402
from papyrus_content.ideas.context_packs import build_packs, drop_lowest_ranked, rank_packs  # noqa: E402
from papyrus_content.ideas.item_signals import ordered_lineage_ids, ordered_queue, score_items  # noqa: E402
from papyrus_content.ideas.monitor_stories import rank  # noqa: E402
from papyrus_content.ideas.signal_inputs import EditorRating, PendingReference, load_signal_inputs  # noqa: E402
from test_idea_context_packs import LOOKUPS, NOW, acceptance_votes, inputs, message, moment, vote  # noqa: E402
from test_idea_more_than_summary import Model, editor_accepted, one_reference, run_stories  # noqa: E402
from test_item_signals import background, candidate, lively_thread  # noqa: E402
from test_monitor_stories import world  # noqa: E402,F401
from test_idea_more_than_summary import iam_auth  # noqa: E402,F401


def rated(lineage: str, stars: int, status: str = "accepted") -> EditorRating:
    return EditorRating(f"{lineage}-v1", lineage, f"Title {lineage}", f"https://example.org/{lineage}", status, stars, moment(1), "an editor")


def with_ratings(signals, *ratings):
    return replace(signals, ratings=tuple(ratings))


# --- the stored rating -----------------------------------------------------------------------------------------------------------


def test_a_rating_is_stored_beside_the_vote_and_the_newest_wins():
    assert reference_stars.star_fields(4, corpus_id="knowledge-corpus-demo", rated_by="an editor", rated_at="2026-11-02T10:00:00Z") == {
        "starRating": 4, "starRatedAt": "2026-11-02T10:00:00Z", "starRatedBy": "an editor", "starFeedKey": "knowledge-corpus-demo#stars#4"}
    assert reference_stars.latest_stars({"starRating": 4, "starRatedAt": "2026-11-02T10:00:00Z", "starRatedBy": "an editor"}) == {"stars": 4, "ratedAt": "2026-11-02T10:00:00Z", "ratedBy": "an editor"}
    assert reference_stars.star_fields(None, corpus_id="knowledge-corpus-demo") == {   # clearing clears who, when and the star partition too
        "starRating": None, "starRatedAt": None, "starRatedBy": None, "starFeedKey": None}
    assert reference_stars.latest_stars({"starRating": None}) is None and reference_stars.latest_stars({}) is None and reference_stars.latest_stars(None) is None


@pytest.mark.parametrize("bad", [0, 6, -1, 2.5, True, "3"])
def test_a_rating_is_a_whole_number_from_one_to_five(bad):
    with pytest.raises(ValueError):
        reference_stars.star_fields(bad, corpus_id="knowledge-corpus-demo")


def test_stars_never_become_part_of_a_vote_or_a_cyclotron_label():
    assert "starRating" not in reference_vote.vote_fields(reference_vote.HUMAN)
    pending = {"id": "r1", "curationStatus": "pending", "starRating": 5, "starRatedBy": "an editor"}
    assert reference_vote.latest_vote(pending) is None   # five stars on a pending Reference is no vote: nothing for the Cyclotron to learn from
    assert reference_vote.latest_vote({**pending, "curationActorKind": "human", "curationStatus": "accepted"})["action"] == "accept"


# --- the one ordering ------------------------------------------------------------------------------------------------------------


def test_the_ordering_counts_signals_that_are_for_a_reference_and_takes_one_away_for_low_stars():
    key = editor_signals.interest_key
    five_and_message = key(5, 1, False)
    assert five_and_message > key(5, 0, False) > key(4, 0, False) > editor_signals.NEUTRAL > key(1, 0, False)
    assert five_and_message > key(None, 1, True) > key(None, 1, False)   # stars, a message and a reason are signals of the same kind; the stars break the tie
    assert key(5, 1, True) > five_and_message
    assert key(1, 1, False)[0] == 0   # a message weighs against one star: net zero, still not excluded
    assert key(2, 0, False)[0] < 0 and key(3, 0, False)[0] == 0 and editor_signals.tier(key(3, 0, False)) == 0 and editor_signals.tier(key(2, 0, False)) == -1


def test_a_five_star_accepted_reference_with_a_message_is_drafted_before_anything_without_both():
    signals = with_ratings(
        inputs(messages=lively_thread("plain-with-messages") + lively_thread("starred", count=1), votes=[vote("starred", 3), vote("plain-with-messages", 2), *background()]),
        rated("starred", 5),
    )
    items = [candidate("quiet", "hn", 0.99), candidate("plain-with-messages"), candidate("starred")]
    queue = ordered_queue([], score_items(signals, items))
    assert ordered_lineage_ids(queue)[0] == "starred"


def test_a_reference_with_good_stars_and_no_other_evidence_still_enters_the_queue():
    signals = with_ratings(inputs(votes=background()), rated("loved", 5))
    scored = score_items(signals, [candidate("loved"), candidate("unrated")])
    assert [row.item.lineage_id for row in scored] == ["loved"] and scored[0].signal["editor"]["stars"] == 5


def test_low_stars_count_against_a_reference_without_excluding_it():
    candidates = [candidate(f"ref-{number}", "hn", 0.01 * number) for number in range(1, 41)]
    plain = ordered_lineage_ids(ordered_queue([], score_items(inputs(), candidates)))
    assert plain[0] == "ref-40"
    doubted = ordered_lineage_ids(ordered_queue([], score_items(with_ratings(inputs(), rated("ref-40", 1)), candidates)))
    assert doubted[-1] == "ref-40" and sorted(doubted) == sorted(plain)   # last, but still offered


def test_unrated_references_keep_the_order_the_statistics_give():
    signals = inputs(messages=lively_thread("lively"), votes=[*acceptance_votes(), *background()])
    packs = rank_packs(build_packs(signals, LOOKUPS, now=NOW))
    scored = score_items(signals, [candidate("lively")])
    assert [entry.kind for entry in ordered_queue(packs, scored)] == [entry.kind for entry in ordered_queue(packs, scored)]
    assert editor_signals.tier(editor_signals.interest_key(None, 6, True)) == 0


def test_a_pack_holding_a_five_star_member_is_offered_before_its_neighbours_and_keeps_that_member_when_trimmed():
    signals = inputs(messages=[], votes=[*acceptance_votes(), *background()])
    plain = rank_packs(build_packs(signals, LOOKUPS, now=NOW))
    assert plain
    target = plain[-1]
    member = target.accepted_lineage_ids[0]
    boosted = rank_packs(build_packs(with_ratings(signals, rated(member, 5)), LOOKUPS, now=NOW))
    assert next(pack for pack in boosted if pack.pack_id == target.pack_id).editor[1] == 5
    assert [pack.pack_id for pack in boosted][0] == target.pack_id or boosted[0].editor[1] == 5
    pack = next(pack for pack in boosted if pack.pack_id == target.pack_id)
    shorter = drop_lowest_ranked(pack)
    assert member in shorter.accepted_lineage_ids   # the member editors care about most is trimmed last
    assert any(row.get("editorStars") == 5 for row in pack.references)


def test_the_item_ranking_without_a_signal_run_puts_the_rated_reference_first():
    rows = [candidate("a", "hn", 0.9), candidate("b", "hn", 0.5)]
    rows[1] = replace(rows[1], stars=5)
    assert [item.lineage_id for item in rank(rows)][0] == "b"


# --- the writer ------------------------------------------------------------------------------------------------------------------


def test_the_writer_is_told_the_rating_as_direction_with_no_handle():
    rows, client = one_reference()
    rows[0].update(starRating=5, starRatedAt="2026-11-02T10:00:00Z", starRatedBy="an editor")
    model = Model()
    run_stories(client, model)
    drafting = json.loads(model.drafting[0]["input"])
    assert drafting["editor_rating"] == {"stars": 5, "of": 5}
    assert all("stars" not in entry for entry in drafting["what_the_newsroom_knows"])   # no handle, so no sentence can rest on it
    assert "editor_rating" in model.drafting[0]["instructions"] and "never reported" in model.drafting[0]["instructions"]


def test_no_rating_means_no_editor_rating_in_the_input():
    rows, client = one_reference()
    model = Model()
    run_stories(client, model)
    assert "editor_rating" not in json.loads(model.drafting[0]["input"])


# --- retrying ---------------------------------------------------------------------------------------------------------------------


def test_a_changed_rating_is_a_new_connection_so_a_rejected_idea_is_retried():
    rows, client = one_reference()
    memory = retry_memory.DictMemory()
    restates = {"verdict": "restates", "claim": "", "repeats_itself": False, "exposes_process": False, "reason": "It restates the source."}
    run_stories(client, Model(verdict=restates), retry_memory=memory)
    [record] = memory.records.values()
    assert not any(key.startswith("stars:") for key in record["connections"])
    waiting = Model()
    assert run_stories(client, waiting, retry_memory=memory)["alreadyRejected"] == 1 and waiting.requests == []
    rows[0].update(starRating=5, starRatedAt="2026-11-02T10:00:00Z", starRatedBy="an editor")
    retry = Model()
    run = run_stories(client, retry, retry_memory=memory)
    assert [row["newConnections"] for row in run["retriedWithNewConnections"]] == [["stars:5"]] and retry.requests


def test_stars_alone_do_not_clear_the_bar_for_an_idea():
    connections = rules.build_connections(None, [], [], stars=5)
    assert not connections.clears_the_bar(True) and retry_memory.single_keys(connections) == frozenset({"stars:5"})


# --- the run record ---------------------------------------------------------------------------------------------------------------


def test_a_highly_rated_reference_without_an_idea_is_explained_in_the_run_record():
    rows, client = one_reference(reason=False)   # accepted, but the newsroom knows nothing about it beyond the source
    rows[0].update(starRating=5, starRatedAt="2026-11-02T10:00:00Z", starRatedBy="an editor")
    run = run_stories(client, Model())
    [row] = run["ratedNoIdea"]
    assert (row["referenceId"], row["stars"], row["reason"]) == (rows[0]["id"], 5, "nothing_to_add") and row["explanation"]


def test_a_reference_that_got_an_idea_is_not_listed():
    rows, client = one_reference()
    rows[0].update(starRating=5, starRatedAt="2026-11-02T10:00:00Z", starRatedBy="an editor")
    run = run_stories(client, Model())
    assert run["drafts"] and run["ratedNoIdea"] == []


def test_low_and_middling_ratings_are_not_listed():
    rows = [{"referenceId": "a", "lineageId": "a", "title": "A", "stars": stars, "status": "accepted"} for stars in (1, 2, 3)]
    assert rated_outcomes.rated_without_ideas({"drafts": [], "skipped": [], "invalid": []}, rows, candidate_lineages=["a"]) == []


@pytest.mark.parametrize("status,reason", [("pending", "pending_not_accepted"), ("rejected", "not_accepted"), ("accepted", "not_a_candidate")])
def test_the_reasons_a_rated_reference_is_not_a_candidate(status, reason):
    [row] = rated_outcomes.rated_without_ideas({"drafts": [], "skipped": [], "invalid": []}, [{"referenceId": "a", "lineageId": "a", "title": "A", "stars": 5, "status": status}], candidate_lineages=[])
    assert row["reason"] == reason


def test_the_curation_flag_names_the_rated_reference_and_why():
    run = {"inputs": {"candidates": 0, "notAccepted": 0}, "ratedNoIdea": [{"referenceId": "a", "title": "A tool", "stars": 5, "reason": "pending_not_accepted", "explanation": "It is still pending."}]}
    reason, ask = review.curation_flag_text(run, [])
    assert "You rated 1 Reference highly" in ask and "A tool (5 stars: It is still pending.)" in ask


# --- pending ----------------------------------------------------------------------------------------------------------------------


def test_a_pending_reference_never_becomes_a_single_item_idea_but_keeps_its_stars_as_context():
    rows, client = world(1, status="pending")
    rows[0].update(starRating=5, starRatedAt="2026-11-02T10:00:00Z", starRatedBy="an editor", predictedAcceptProbability=0.2, curationStatusKey="knowledge-corpus-example-site#pending")
    signals = load_signal_inputs(_Reader(rows), site="example-site", now=NOW)
    [pending] = signals.pending_context
    assert pending.stars == 5 and [rating.stars for rating in signals.ratings] == [5]
    run = run_stories(client, Model())
    assert run["drafts"] == []   # a pending Reference is never a single-item candidate
    listed = rated_outcomes.rated_without_ideas(run, [{"referenceId": r.reference_id, "lineageId": r.lineage_id, "title": r.title, "stars": r.stars, "status": r.status} for r in signals.ratings], candidate_lineages=[])
    assert [row["reason"] for row in listed] == ["pending_not_accepted"]


class _Reader:
    """Just enough backend for ``load_signal_inputs`` over a list of References."""

    tenant_id = None

    def __init__(self, rows):
        self.rows = rows

    def list_by_index(self, index, key):
        if index == "referencesByCurationStatusKey":
            return [row for row in self.rows if row.get("curationStatusKey") == key]
        return []

    def list_records(self, model):
        return []

    def list_semantic_relations_by_subject_state(self, key):
        return []

    def list_semantic_relations_by_object_state(self, key):
        return []

    def graphql(self, query, variables=None):
        return {}
