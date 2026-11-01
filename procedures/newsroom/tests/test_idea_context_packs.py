"""Context packs: conversation and acceptance signals, ranking, trimming and anchor-based suppression (PPY-4f5cd3, PPY-1c3cf9)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from papyrus_content.ideas.context_packs import (
    ConceptInfo, PackLookups, build_packs, evidence_of, rank_packs, suppress_repeats, trim_pack,
)
from papyrus_content.ideas.signal_inputs import (
    ConceptLink, HumanVote, PendingReference, SignalInputs, SignalMessage, StoryRecord,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
LOOKUPS = PackLookups(
    concepts={"concept-voice": ConceptInfo("Voice cloning", "concept", "Synthetic voices.", "#voice-cloning")},
    summaries={"ref-1": "A short summary."}, mission="Cover audio AI.", policy="Be plain.", allowed_sections=("Analysis",),
)


def moment(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def message(number: int, days_ago: float, thread: str = "thread-a", anchor: str = "reference#ref-1") -> SignalMessage:
    return SignalMessage(f"m{thread}{number}", thread, "reference", anchor, moment(days_ago), "staff", f"Comment {number}")


def vote(lineage: str, days_ago: float, status: str = "accepted", concepts=("concept-voice",)) -> HumanVote:
    return HumanVote(f"{lineage}-v1", lineage, f"Title {lineage}", f"https://example.org/{lineage}", status, moment(days_ago), "someone", None, None, None,
                     moment(days_ago + 1), moment(days_ago + 2), tuple(concepts))


def inputs(messages=(), votes=(), links=(), pending=(), published=(), ideas=()) -> SignalInputs:
    return SignalInputs("example", moment(0), tuple(messages), tuple(votes), tuple(links), tuple(pending), tuple(published), tuple(ideas))


def lit_thread_messages() -> list[SignalMessage]:
    quiet = [message(number, 60 - number * 3, thread="thread-b", anchor="item#story-b") for number in range(1, 15)]
    burst = [message(100 + number, 0.5, thread="thread-a") for number in range(9)]
    return quiet + burst


def acceptance_votes() -> list[HumanVote]:
    steady = [vote(f"other-{number}", 70 - number * 3, concepts=("concept-other",)) for number in range(1, 22)]
    burst = [vote(f"ref-{number}", 1 + number * 0.1) for number in range(1, 10)]
    return steady + burst


def test_lit_up_thread_yields_a_conversation_pack_and_quiet_one_none():
    packs = build_packs(inputs(messages=lit_thread_messages(), links=[ConceptLink("ref-1", "concept-voice", "mentions")], votes=[vote("ref-1", 3)]), LOOKUPS, now=NOW)
    conversation = [pack for pack in packs if pack.signal_type == "conversation"]
    assert [pack.anchor for pack in conversation] == ["thread-a"]
    shown = conversation[0].as_json()
    assert shown["signal"]["dateBasis"] == "message"
    assert shown["signal"]["correctedPValue"] <= 0.01
    assert len(shown["messages"]) == 9 and shown["messages"][0]["handle"] == "M1" and shown["messages"][0]["about"] == "R1"
    assert shown["references"][0]["summary"] == "A short summary."
    assert shown["concepts"][0]["hashtag"] == "#voice-cloning"
    assert shown["packId"].startswith("pack-") and len(shown["packId"]) == len("pack-") + 12


def test_concept_at_its_own_baseline_yields_no_pack():
    steady = [vote(f"ref-{number}", 70 - number * 3) for number in range(1, 22)]
    assert build_packs(inputs(votes=steady), LOOKUPS, now=NOW) == []


def test_site_without_messages_still_yields_acceptance_packs_stating_the_date_basis():
    packs = build_packs(inputs(votes=acceptance_votes()), LOOKUPS, now=NOW)
    assert [pack.signal_type for pack in packs] == ["acceptance"]
    shown = packs[0].as_json()
    assert shown["signal"]["anchor"] == "concept-voice"
    assert shown["signal"]["dateBasis"] == "ingestion"
    assert [row["handle"] for row in shown["references"]] == [f"R{number}" for number in range(1, 10)]
    assert all(pack.as_json()["signal"]["dateBasis"] for pack in packs)


def test_pending_references_are_context_with_p_handles_and_never_evidence():
    held = PendingReference("pend-1", "pend-1", "Waiting", "https://example.org/w", moment(1), moment(2), 0.9, ("concept-voice",))
    pack = build_packs(inputs(votes=acceptance_votes(), pending=[held]), LOOKUPS, now=NOW)[0]
    pending = [row for row in pack.as_json()["references"] if row["status"] == "pending"]
    assert pending[0]["handle"] == "P1" and pending[0]["note"] == "not yet accepted"
    assert "pend-1" not in pack.accepted_lineage_ids


def test_published_stories_are_those_since_the_baseline_began_and_ideas_show_spiked():
    ideas = [StoryRecord("i1", "An idea", "", None, "draft", moment(2)[:10], "[]"), StoryRecord("i2", "A spiked one", "", None, "declined", moment(2)[:10], "[]")]
    published = [StoryRecord("s1", "Recent", "", "Analysis", "published", moment(5)[:10], "[]"), StoryRecord("s2", "Ancient", "", "Analysis", "published", "2020-01-01", "[]")]
    pack = build_packs(inputs(votes=acceptance_votes(), published=published, ideas=ideas), LOOKUPS, now=NOW)[0].as_json()
    assert [row["title"] for row in pack["recent_published_stories"]] == ["Recent"]
    assert [row["state"] for row in pack["existing_ideas"]] == ["idea", "spiked"]


def test_packs_from_different_signals_interleave_by_surprise():
    both = build_packs(inputs(messages=lit_thread_messages(), votes=acceptance_votes(), links=[ConceptLink("ref-1", "concept-voice", "mentions")]), LOOKUPS, now=NOW)
    assert {pack.signal_type for pack in both} == {"conversation", "acceptance"}
    triple = rank_packs([both[0], both[1], both[0].__class__(**{**both[0].__dict__, "pack_id": "pack-extra", "signal": {**both[0].signal, "surprise": 0.1}})])
    assert [pack.signal_type for pack in triple][:2] != [triple[0].signal_type] * 2
    assert triple[-1].pack_id == "pack-extra"


def test_a_pack_is_trimmed_lowest_ranked_first_and_only_to_the_limit():
    held = [PendingReference(f"p{n}", f"p{n}", "Waiting " * 20, "https://example.org", moment(1), None, 0.5, ("concept-voice",)) for n in range(5)]
    pack = build_packs(inputs(votes=acceptance_votes(), pending=held), LOOKUPS, now=NOW)[0]
    assert trim_pack(pack) is pack
    limit = pack.size() - 200
    trimmed = trim_pack(pack, limit)
    assert trimmed.size() <= limit
    assert len([row for row in trimmed.references if row["status"] == "accepted"]) == 9
    tight = trim_pack(pack, pack.size() // 2)
    assert len(tight.references) < len(pack.references)


def idea_from(pack, state="draft", day="2026-10-20", extra=None) -> StoryRecord:
    evidence = {**evidence_of(pack), **(extra or {})}
    return StoryRecord("idea-1", "T", "", None, state, day, "[]", json.dumps(evidence))


def test_an_anchor_already_drafted_yields_nothing_without_new_evidence():
    pack = build_packs(inputs(votes=acceptance_votes()), LOOKUPS, now=NOW)[0]
    result = suppress_repeats([pack], [idea_from(pack)])
    assert result.kept == () and result.packsSkippedNoNewEvidence == 1


def test_a_new_accepted_reference_or_materially_more_activity_yields_a_new_pack():
    pack = build_packs(inputs(votes=acceptance_votes()), LOOKUPS, now=NOW)[0]
    fewer = idea_from(pack, extra={"referenceLineageIds": list(pack.accepted_lineage_ids)[:-1]})
    assert suppress_repeats([pack], [fewer]).kept == (pack,)
    smaller = idea_from(pack, extra={"window": {"windowDays": pack.scan["windowDays"], "count": 0, "tested": pack.scan["tested"]}})
    assert suppress_repeats([pack], [smaller]).kept == (pack,)


def test_an_unrelated_anchor_is_kept_and_a_spiked_anchor_needs_both_conditions():
    pack = build_packs(inputs(votes=acceptance_votes()), LOOKUPS, now=NOW)[0]
    other = StoryRecord("i0", "T", "", None, "draft", "2026-10-20", "[]", json.dumps({"anchor": "concept-else"}))
    assert suppress_repeats([pack], [other]).kept == (pack,)
    only_reference = idea_from(pack, state="declined", extra={"referenceLineageIds": []})
    assert suppress_repeats([pack], [only_reference]).kept == ()
    both = idea_from(pack, state="declined", extra={"referenceLineageIds": [], "window": {"windowDays": pack.scan["windowDays"], "count": 0, "tested": pack.scan["tested"]}})
    assert suppress_repeats([pack], [both]).kept == (pack,)
