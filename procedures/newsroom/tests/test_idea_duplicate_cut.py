from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.ideas import dedupe, duplicate_cut  # noqa: E402


def test_scorer_matches_similarity():
    corpus = ["alpha beta gamma", "alpha beta delta", "epsilon zeta"]
    assert dedupe.WordScorer(corpus)(corpus[0], corpus[1]) == dedupe.similarity(corpus[0], corpus[1], corpus)


def test_learned_cut_is_the_smallest_similarity_reaching_the_precision():
    votes = [(0.1 + 0.01 * n, False) for n in range(20)] + [(0.7 + 0.005 * n, True) for n in range(60)]
    cut = duplicate_cut.learn_duplicate_cut(votes)
    assert cut.learned and cut.threshold < 0.75 and cut.record()["lowerBound"] >= 0.9


def test_too_few_decisions_keep_the_fallback():
    cut = duplicate_cut.learn_duplicate_cut([(0.9, True), (0.1, False)])
    assert cut.threshold == dedupe.FALLBACK_THRESHOLD and not cut.learned and cut.reason == "no learned cut: too few decisions"


def test_duplication_is_named_by_code_note_or_move_reason():
    assert duplicate_cut.names_duplication({"decision": {"reasonCode": "duplicate"}}, "")
    assert duplicate_cut.names_duplication({"decision": {"note": "A duplicate of Monday's piece"}}, "")
    assert duplicate_cut.names_duplication({}, "Duplicates the earlier story")
    assert not duplicate_cut.names_duplication({"decision": {"reasonCode": "off_topic"}}, "Not for us")


def test_a_site_with_many_stories_yields_a_prompt_under_the_bound():
    import json
    from papyrus_content.ideas import synthesis
    stories = [{"id": f"s{n}", "title": f"Story number {n} " + "word " * 40, "summary": "summary " * 40, "date": "2026-10-01"} for n in range(5000)]
    context = {"stories": stories, "sections": [], "drafts": []}
    model_input = {"source": {"page_text": "x" * 50_000}}
    model_input["recent_and_in_flight_stories"] = synthesis.fit_stories(model_input, context)
    size = len(json.dumps(model_input, ensure_ascii=False, separators=(",", ":")))
    assert size <= synthesis.MAXIMUM_INPUT_CHARACTERS
    assert 0 < context["promptStories"] < len(stories) and model_input["recent_and_in_flight_stories"][0]["title"].startswith("Story number 0")
    assert len(context["stories"]) == 5000
