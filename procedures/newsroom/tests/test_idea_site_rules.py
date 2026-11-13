"""A site's idea rules (PPY-10a5e5): the minimum count of References, the verdicts that pass, and the premise-led mode. The scenarios of
features_backend/idea-site-rules.feature call these helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import monitoring_stories  # noqa: E402
from papyrus_content.ideas import monitor_stories as stories, pack_stories, point_check  # noqa: E402
from papyrus_content.ideas.rules import DEFAULT, IdeaRules, rules_of, validate_idea_rules  # noqa: E402
from test_idea_more_than_summary import LinkedClient, Model, editor_accepted, run_stories, story  # noqa: E402
from test_idea_pack_stories import ADDS as PACK_ADDS, acceptance_pack, backend, joined, run as run_pack, sentence, summarised, transport_of  # noqa: E402
from test_monitor_stories import world  # noqa: E402


def write_pack(rules, idea, verdict=PACK_ADDS, summaries=("R1", "R2", "R3", "R4")):
    """Writes the acceptance pack with the site's rules; returns (result, transport)."""
    from papyrus_content.ideas.items import ItemStore
    from test_idea_pack_stories import Gate, support

    pack = summarised(acceptance_pack(), *summaries)
    transport = transport_of(idea, verdict=verdict)
    result = pack_stories.draft_pack_ideas(
        backend(pack), pack, store=ItemStore(backend(pack)), gate=Gate(), transport=transport, cost_meter=pack_stories.CostMeter(), existing_titles=(), run_id="run-1",
        dry_run=False, concept_nodes={}, now=support.NOW, rules=rules)
    return result, transport


def apart(headline="Synthetic voices spread"):
    idea = joined(headline)
    idea["dek"] = sentence("Both sources describe voice cloning.", "R1")
    idea["paragraphs"] = [{"sentences": [sentence("The first source describes voice cloning.", "R1"), sentence("The second source describes voice cloning in newsrooms.", "R2")]}]
    return idea


def three_together():
    idea = joined("Synthetic voices spread", ("R1", "R2", "R3"))
    return idea


PREMISE = "A newsroom hires a chatbot as its editor-in-chief and the chatbot demands a corner office."


def premise_story():
    return {
        "premise": PREMISE,
        "headline": sentence("Foo checks claims against sources", "I1"), "dek": sentence("Foo is an open tool that checks claims against their sources.", "I1"), "section": "Tools",
        "paragraphs": [{"sentences": [sentence("Foo checks each claim against the page it came from.", "I1"), sentence("Foo is an open tool.", "I1")]}],
    }


def premise_run(answer, *, mode="premise-led", reason=True):
    rows, client = world(1)
    if reason:
        editor_accepted(rows[0])
    client = LinkedClient(references=rows, relations=client.relations, incoming=client.incoming, sections=("Analysis", "Tools"))
    model = Model(answer)
    run = run_stories(client, model, rules=IdeaRules(mode=mode))
    return run, client, model


# --- the setting -------------------------------------------------------------------------------------------------------------------


def test_the_defaults_are_the_standard_rules_and_a_site_that_sets_nothing_is_unchanged():
    assert validate_idea_rules("p", None) == DEFAULT.as_setting()
    assert monitoring_stories.validate_monitor_stories("p", None)["ideaRules"] == DEFAULT.as_setting()
    assert monitoring_stories.validate_monitor_stories("p", {"singleItem": True})["ideaRules"] == DEFAULT.as_setting()
    assert rules_of(None) is DEFAULT and DEFAULT.minimum_references == 2 and DEFAULT.passing_verdicts == ("adds",) and not DEFAULT.premise_led


@pytest.mark.parametrize("raw", [{"minimumReferences": 0}, {"minimumReferences": "2"}, {"minimumReferences": True}, {"passingVerdicts": []}, {"passingVerdicts": ["fine"]},
                                  {"passingVerdicts": ["adds", "adds"]}, {"mode": "satire"}, {"requireJointSentence": "yes"}, {"unknown": 1}, "adds"])
def test_a_wrong_setting_is_refused_with_the_name_of_the_setting(raw):
    with pytest.raises(ValueError, match="monitorStories.ideaRules"):
        monitoring_stories.validate_monitor_stories("p", {"ideaRules": raw})


def test_a_site_setting_becomes_the_rules():
    rules = rules_of(validate_idea_rules("p", {"minimumReferences": 3, "passingVerdicts": ["adds", "unsupported"], "mode": "premise-led", "checkRepeats": False}))
    assert rules == IdeaRules(3, True, ("adds", "unsupported"), False, True, "premise-led") and rules.premise_led


# --- the point check's verdicts ----------------------------------------------------------------------------------------------------


def test_only_the_verdicts_the_site_lets_through_pass():
    restates = {"verdict": "restates", "claim": "", "repeats_itself": False, "exposes_process": False}
    unsupported = {**restates, "verdict": "unsupported"}
    assert point_check.failures(restates) == ["no_point_beyond_source"] and point_check.failures(unsupported) == ["point_unsupported"]
    assert point_check.failures(restates, IdeaRules(passing_verdicts=("adds", "restates"))) == []
    assert point_check.failures(unsupported, IdeaRules(passing_verdicts=("unsupported",))) == []
    assert point_check.failures({**restates, "repeats_itself": True}, IdeaRules(passing_verdicts=("restates",), check_repeats=False)) == []
    assert point_check.failures({**restates, "exposes_process": True}, IdeaRules(passing_verdicts=("restates",))) == ["exposes_process"]


# --- context packs ------------------------------------------------------------------------------------------------------------------


def test_a_pack_idea_citing_one_reference_per_sentence_is_dropped_by_default_and_filed_when_the_site_asks_only_for_one():
    result, _ = write_pack(DEFAULT, apart())
    assert result.filed_count == 0
    result, _ = write_pack(IdeaRules(minimum_references=2, require_joint_sentence=False), apart())
    assert result.filed_count == 1


def test_a_site_that_wants_three_references_refuses_an_idea_citing_two():
    result, _ = write_pack(IdeaRules(minimum_references=3), joined("Synthetic voices spread"))
    assert result.filed_count == 0
    assert [problem["reason"] for problem in result.dropped[0]["citationCheck"]["problems"]] == ["fewer_than_3_accepted_references_cited", "no_joint_sentence"]
    result, _ = write_pack(IdeaRules(minimum_references=3), three_together())
    assert result.filed_count == 1


def test_the_pack_prompt_states_the_sites_count_only_when_it_differs():
    result, transport = write_pack(DEFAULT, joined("Synthetic voices spread"))
    assert transport.calls[0]["instructions"] == pack_stories.SYSTEM_PROMPT
    result, transport = write_pack(IdeaRules(minimum_references=3), three_together())
    assert "at least 3 different accepted References" in transport.calls[0]["instructions"]


def test_a_pack_idea_that_restates_its_sources_is_filed_when_the_site_lets_restates_through():
    restates = {**PACK_ADDS, "verdict": "restates", "claim": ""}
    result, _ = write_pack(DEFAULT, joined("Synthetic voices spread"), verdict=restates)
    assert result.filed_count == 0
    result, _ = write_pack(IdeaRules(passing_verdicts=("adds", "restates")), joined("Synthetic voices spread"), verdict=restates)
    assert result.filed_count == 1


# --- premise-led ideas ---------------------------------------------------------------------------------------------------------------


def test_a_premise_led_idea_starts_from_one_real_reference_and_states_the_premise_apart():
    run, client, model = premise_run(premise_story(), reason=False)   # no editor reason or comment: the item alone is enough
    assert len(run["drafts"]) == 1 and model.checks == []
    filed = client.filed[0]
    evidence = json.loads(filed["evidence"])
    assert evidence["mode"] == "premise-led" and evidence["premise"] == PREMISE and "minimumStandard" not in evidence
    assert "## Invented premise" in filed["body"] and "This premise is invented" in filed["body"] and PREMISE in filed["body"]
    sent = model.drafting[0]
    assert sent["instructions"] == stories.PREMISE_PROMPT and "premise" in sent["text"]["format"]["schema"]["properties"] and "point" not in sent["text"]["format"]["schema"]["properties"]


def test_a_premise_led_run_without_a_premise_files_nothing():
    run, client, model = premise_run({**premise_story(), "premise": " "})
    assert run["drafts"] == [] and client.filed == []
    assert [row["reason"] for row in run["skipped"]] == [stories.NO_PREMISE_OFFERED]


def test_the_default_mode_still_needs_a_point_and_never_mentions_a_premise():
    rows, client = world(1)
    editor_accepted(rows[0])
    client = LinkedClient(references=rows, relations=client.relations, incoming=client.incoming, sections=("Analysis", "Tools"))
    model = Model(story())
    run = run_stories(client, model)
    assert len(run["drafts"]) == 1 and len(model.checks) == 1 and model.drafting[0]["instructions"] == stories.SYSTEM_PROMPT
    assert "premise" not in json.loads(client.filed[0]["evidence"])
