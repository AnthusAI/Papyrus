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


def dated_vote(lineage: str, accepted_days_ago: float, added_days_ago: float, published_days_ago: float | None) -> HumanVote:
    published = moment(published_days_ago) if published_days_ago is not None else None
    return HumanVote(f"{lineage}-v1", lineage, f"Title {lineage}", f"https://example.org/{lineage}", "accepted", moment(accepted_days_ago), "someone", None, None, None,
                     moment(added_days_ago), published, ("concept-voice",))


def ordinary_votes(count: int = 120) -> list[HumanVote]:
    return [dated_vote(f"plain-{number}", 2 + number * 0.5, 3 + number * 0.5, 4 + number * 0.5) for number in range(count)]


def test_an_old_source_getting_new_attention_yields_a_resurfaced_pack_on_publication_basis():
    old = dated_vote("old-source", 0.4, 200, 600)
    asked = [message(1, 0.2, thread="thread-old", anchor="reference#old-source")]
    packs = build_packs(inputs(votes=[*ordinary_votes(), old], messages=asked), LOOKUPS, now=NOW)
    resurfaced = [pack for pack in packs if pack.signal_type == "resurfaced"]
    assert [pack.anchor for pack in resurfaced] == ["reference#old-source"]
    shown = resurfaced[0].as_json()
    assert shown["signal"]["dateBasis"] == "publication"
    assert shown["signal"]["publicationGapDays"] == 400 and shown["signal"]["gapPercentile"] > 0.99
    assert shown["signal"]["correctedPValue"] <= 0.01
    assert [row["kind"] for row in shown["signal"]["pointedAttentionAt"]] == ["human accept", "message"]
    assert shown["signal"]["pointedAttentionAt"][1]["handle"] == shown["messages"][0]["handle"]
    assert shown["references"][0]["published"] == moment(600)[:10] and shown["references"][0]["added"] == moment(200)[:10]


def test_an_old_source_nobody_attends_to_now_yields_no_resurfaced_pack():
    forgotten = dated_vote("old-source", 150, 200, 600)
    packs = build_packs(inputs(votes=[*ordinary_votes(), forgotten]), LOOKUPS, now=NOW)
    assert not [pack for pack in packs if pack.signal_type == "resurfaced"]


def test_a_reference_with_an_unknown_publication_date_has_no_gap_and_stays_null():
    unknown = dated_vote("unknown-date", 0.4, 200, None)
    packs = build_packs(inputs(votes=[*ordinary_votes(), unknown]), LOOKUPS, now=NOW)
    assert not [pack for pack in packs if pack.signal_type == "resurfaced"]
    rows = [row for pack in packs for row in pack.as_json()["references"] if row["title"] == "Title unknown-date"]
    assert all(row["published"] is None and row["orderedBy"] == "added" for row in rows)


def test_references_in_an_acceptance_pack_are_ordered_by_publication_date_with_the_fallback_flagged():
    early_published = dated_vote("published-early", 1.0, 0.9, 400)
    late_published = dated_vote("published-late", 1.1, 0.8, 5)
    no_date = dated_vote("no-date", 1.2, 0.7, None)
    packs = build_packs(inputs(votes=[*acceptance_votes(), early_published, late_published, no_date]), LOOKUPS, now=NOW)
    shown = next(pack for pack in packs if pack.signal_type == "acceptance").as_json()
    rows = {row["title"]: (position, row) for position, row in enumerate(shown["references"])}
    assert rows["Title published-late"][0] < rows["Title published-early"][0]
    assert rows["Title no-date"][1]["published"] is None and rows["Title no-date"][1]["orderedBy"] == "added"
    assert rows["Title published-late"][1]["orderedBy"] == "published"


import logging
import math
import random

from papyrus_content.ideas.signal_inputs import AcceptedReference, ReferenceEdge
from papyrus_knowledge_query.vector_index import reference_summary_vector_key

DIMENSIONS = 48


def accepted_reference(lineage: str, days_ago: float, concepts=(), by="machine") -> AcceptedReference:
    return AcceptedReference(f"{lineage}-v1", lineage, f"Title {lineage}", f"https://example.org/{lineage}", moment(days_ago + 1), moment(days_ago + 3), moment(days_ago), by, tuple(concepts))


def edge(subject: str, other: str, predicate: str = "related_to", days_ago: float = 1) -> ReferenceEdge:
    return ReferenceEdge(subject, other, predicate, moment(days_ago))


def noisy_unit(rng: random.Random, base=None, noise: float = 1.0) -> list[float]:
    vector = [rng.gauss(0, 1) * noise + (base[index] if base else 0.0) for index in range(DIMENSIONS)]
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


class FakeVectors:
    """A stand-in for the S3 Vectors provider: stored vectors by key, brute-force cosine, the filter ignored but recorded."""

    def __init__(self, vectors: dict[str, list[float]], accepted: set[str] | None = None) -> None:
        self.by_lineage = vectors
        self.accepted = accepted if accepted is not None else set(vectors)
        self.keys = {reference_summary_vector_key(lineage): lineage for lineage in vectors}
        self.filters: list[dict] = []

    def get_vector(self, key: str):
        lineage = self.keys.get(key)
        return list(self.by_lineage[lineage]) if lineage else None

    def query_by_vector(self, vector, top_k, metadata_filter):
        self.filters.append(metadata_filter)
        scored = [(1 - sum(a * b for a, b in zip(vector, other)), lineage) for lineage, other in self.by_lineage.items() if lineage in self.accepted]
        scored.sort()
        return [{"key": reference_summary_vector_key(lineage), "distance": distance, "metadata": {"referenceLineageId": lineage}} for distance, lineage in scored[:top_k]]


def cold_site(topic_size: int = 4, others: int = 30, seed: int = 7, noise: float = 0.04):
    """A site five days old: References with no concept links and no edges, ``topic_size`` of them about one thing."""
    rng = random.Random(seed)
    topic = noisy_unit(rng)
    vectors, references = {}, []
    for number in range(topic_size):
        vectors[f"topic-{number}"] = noisy_unit(rng, topic, noise)
        references.append(accepted_reference(f"topic-{number}", 0.5 + number * 0.3))
    for number in range(others):
        vectors[f"other-{number:02d}"] = noisy_unit(rng)
        references.append(accepted_reference(f"other-{number:02d}", 0.2 + number * 0.12))
    return references, vectors


def cluster_inputs(references, edges=()):
    return SignalInputs("example", moment(0), (), (), (), (), (), (), edges=tuple(edges), accepted=tuple(references))


def lookups_with(vectors, accepted=None) -> PackLookups:
    return PackLookups(vector_provider=FakeVectors(vectors, accepted))


def test_cluster_forms_from_vectors_alone_on_a_cold_site_and_says_it_is_emerging():
    references, vectors = cold_site()
    provider_lookups = lookups_with(vectors)
    packs = sorted((pack for pack in build_packs(cluster_inputs(references), provider_lookups, now=NOW) if pack.signal_type == "cluster"),
                   key=lambda pack: -pack.surprise)
    assert packs, "the topic forms a cluster pack"
    shown = packs[0].as_json()
    assert {"topic-0", "topic-1", "topic-2", "topic-3"} <= set(packs[0].accepted_lineage_ids)
    assert shown["signal"]["emerging"] is True and shown["signal"]["new"] is True and shown["signal"]["correctedPValue"] <= 0.01
    assert all(other.surprise <= packs[0].surprise for other in packs[1:])
    assert shown["signal"]["anchor"].startswith("cluster#") and shown["signal"]["dateBasis"] == "ingestion"
    assert shown["signal"]["score"] > 0 and shown["edges"] and {row["provenance"] for row in shown["edges"]} == {"suggested"}
    assert all(0 < row["similarity"] <= 1 for row in shown["edges"])
    assert provider_lookups.vector_provider.filters[0]["$and"][1] == {"curationStatus": {"$eq": "accepted"}}


def test_pack_edges_tell_confirmed_from_suggested():
    references, vectors = cold_site()
    packs = build_packs(cluster_inputs(references, [edge("topic-0", "topic-1")]), lookups_with(vectors), now=NOW)
    shown = [pack for pack in packs if pack.signal_type == "cluster"][0].as_json()
    by_pair = {(row["from"], row["to"]): row for row in shown["edges"]}
    handle = {row["title"]: row["handle"] for row in shown["references"]}
    confirmed = by_pair[(handle["Title topic-0"], handle["Title topic-1"])]
    assert confirmed["provenance"] == "confirmed" and confirmed["type"] == "related_to" and "similarity" not in confirmed
    assert any(row["provenance"] == "suggested" and "similarity" in row for row in shown["edges"])
    assert len([row for row in shown["edges"] if {row["from"], row["to"]} == {handle["Title topic-0"], handle["Title topic-1"]}]) == 1


def test_a_uniform_cold_site_yields_no_hub_and_no_cold_start_pack_and_no_significant_cluster():
    """Clusters are ranked, not gated (a small site never clears a corrected test): a uniform site may offer loose pairs as emerging cluster
    packs, which the citation check, the gate and the editors' spikes (the idea-pack-fit labels) then judge; it offers nothing else."""
    references, vectors = cold_site(topic_size=0, others=30)
    packs = build_packs(cluster_inputs(references), lookups_with(vectors), now=NOW)
    assert {pack.signal_type for pack in packs} <= {"cluster"}
    assert all(pack.as_json()["signal"].get("emerging") for pack in packs)
    threads = [message(number, 0.2 + number * 0.1, thread=f"thread-{name}", anchor=f"item#story-{name}") for name in "abcdef" for number in range(1, 4)]
    assert build_packs(inputs(messages=threads), LOOKUPS, now=NOW) == []


def test_cold_start_compares_a_young_thread_with_the_other_threads_and_marks_it_emerging():
    quiet = [message(number, 0.2 + number * 0.1, thread=f"thread-{name}", anchor=f"item#story-{name}") for name in "bcdefg" for number in range(1, 3)]
    loud = [message(100 + number, 0.1 + number * 0.05, thread="thread-a") for number in range(20)]
    packs = build_packs(inputs(messages=quiet + loud), LOOKUPS, now=NOW)
    conversation = [pack for pack in packs if pack.signal_type == "conversation"]
    assert [pack.anchor for pack in conversation] == ["thread-a"]
    signal = conversation[0].as_json()["signal"]
    assert signal["emerging"] is True and "cross-sectional" in signal["comparison"] and signal["correctedPValue"] <= 0.01
    assert conversation[0].scan["tested"] == 7


def test_cold_start_compares_a_young_concept_with_the_other_concepts():
    votes = [vote(f"ref-{n}", 0.1 + n * 0.1) for n in range(12)]
    votes += [vote(f"other-{c}-{n}", 0.2 + n * 0.1, concepts=(f"concept-{c}",)) for c in range(5) for n in range(2)]
    packs = build_packs(inputs(votes=votes), LOOKUPS, now=NOW)
    assert [(pack.signal_type, pack.anchor, pack.signal["emerging"]) for pack in packs] == [("acceptance", "concept-voice", True)]


def test_cluster_is_skipped_without_a_vector_provider_and_says_why(caplog):
    references, _ = cold_site()
    with caplog.at_level(logging.INFO):
        assert build_packs(cluster_inputs(references), PackLookups(), now=NOW) == []
    assert any("cluster signal skipped: no vector provider" in record.message for record in caplog.records)


def test_a_vector_failure_skips_the_cluster_signal_and_not_the_run(caplog):
    class Broken:
        def get_vector(self, key):
            raise RuntimeError("no s3vectors client")

    references, _ = cold_site()
    with caplog.at_level(logging.INFO):
        assert build_packs(cluster_inputs(references), PackLookups(vector_provider=Broken()), now=NOW) == []
    assert any("reading the vector index failed" in record.message for record in caplog.records)


def hub_site(neighbours: int = 6, population: int = 150):
    references = [accepted_reference(f"ref-{number:03d}", population - number + 0.5) for number in range(population)]
    hub = references[-1].lineage_id
    edges = [edge(hub, references[number].lineage_id) for number in range(neighbours)]
    return references, edges, hub


def test_a_recent_reference_with_far_more_connections_than_the_site_is_a_hub_with_its_percentile():
    references, edges, hub = hub_site()
    packs = [pack for pack in build_packs(cluster_inputs(references, edges), PackLookups(), now=NOW) if pack.signal_type == "hub"]
    assert [pack.anchor for pack in packs] == ["hub#" + hub]
    signal = packs[0].as_json()["signal"]
    assert signal["degree"] == 6 and signal["degreeShare"] == round(1 / 150, 3) and signal["count"] == 6
    assert signal["correctedPValue"] == float(f"{1 / 150:.3g}") and "emerging" not in signal
    shown = packs[0].as_json()
    assert shown["references"][0]["title"] == f"Title {hub}" and len(shown["references"]) == 7
    assert [row["relation"] for row in shown["references"][1:]] == ["linked"] * 6
    assert len(shown["edges"]) == 6 and {row["provenance"] for row in shown["edges"]} == {"confirmed"}


def test_shared_concepts_add_weighted_degree_and_a_site_where_everyone_has_the_same_degree_has_no_hub():
    references = [accepted_reference(f"ref-{number:03d}", 30 - number + 0.5, concepts=("concept-voice",)) for number in range(30)]
    assert [pack for pack in build_packs(cluster_inputs(references), LOOKUPS, now=NOW) if pack.signal_type == "hub"] == []
    sharing = [accepted_reference("ref-a", 0.5, concepts=("concept-rare",)), accepted_reference("ref-b", 40.5, concepts=("concept-rare",))] + [accepted_reference(f"ref-{n}", 1 + n) for n in range(5, 40)]
    from papyrus_content.ideas.context_packs import context_of, degree_of, concept_frequency
    from papyrus_content.knowledge_snapshot.trends import TrendConfig
    context = context_of(cluster_inputs(sharing), LOOKUPS, NOW, TrendConfig())
    degree, edge_neighbours, shared = degree_of(context, "ref-a", concept_frequency(context))
    assert edge_neighbours == {} and shared == {"ref-b": 1 / math.sqrt(2)} and degree == 1 / math.sqrt(2)


def test_a_conversation_pack_adds_the_references_linked_to_its_anchor_by_a_current_edge_marked_linked():
    anchor = vote("ref-1", 3, concepts=())
    linked = accepted_reference("ref-9", 20)
    base = inputs(messages=lit_thread_messages(), votes=[anchor])
    with_edge = SignalInputs(base.site, base.loaded_at, base.messages, base.votes, base.concept_links, base.pending_context, base.published, base.ideas,
                             edges=(edge("ref-9", "ref-1", "cites"),), accepted=(accepted_reference("ref-1", 3), linked))
    pack = [pack for pack in build_packs(with_edge, LOOKUPS, now=NOW) if pack.signal_type == "conversation"][0].as_json()
    assert [row["title"] for row in pack["references"]] == ["Title ref-1", "Title ref-9"]
    assert pack["references"][1]["relation"] == "linked" and pack["references"][1]["acceptedBy"] == "machine"
    assert pack["edges"] == [{"from": "R2", "to": "R1", "type": "cites", "provenance": "confirmed"}]


def test_a_component_with_earlier_arrivals_is_scanned_against_the_sites_arrivals_and_is_not_new():
    rng = random.Random(11)
    topic = noisy_unit(rng)
    references, vectors = [], {}
    for number in range(60):
        references.append(accepted_reference(f"old-{number:02d}", 80 - number))
        vectors[f"old-{number:02d}"] = noisy_unit(rng)
    for number in range(2):
        references.append(accepted_reference(f"early-{number}", 50 - number))
        vectors[f"early-{number}"] = noisy_unit(rng, topic, 0.1)
    for number in range(30):
        references.append(accepted_reference(f"busy-{number:02d}", 0.1 + number * 0.03))
        vectors[f"busy-{number:02d}"] = noisy_unit(rng)
    for number in range(8):
        references.append(accepted_reference(f"fresh-{number}", 0.2 + number * 0.05))
        vectors[f"fresh-{number}"] = noisy_unit(rng, topic, 0.1)
    packs = sorted((pack for pack in build_packs(cluster_inputs(references), lookups_with(vectors), now=NOW) if pack.signal_type == "cluster"),
                   key=lambda pack: -pack.surprise)
    assert packs
    signal = packs[0].as_json()["signal"]
    assert "new" not in signal and "emerging" not in signal and signal["correctedPValue"] <= 0.01
    assert {f"fresh-{n}" for n in range(8)} <= set(packs[0].accepted_lineage_ids)
