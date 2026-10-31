"""Editor review stage bot: the records and the contract (no model calls anywhere)."""
from __future__ import annotations

import asyncio
import json
from unittest import mock

import pytest

import test_story_triggers as t
from fake_client import FakeAuthoringClient
from papyrus_content import editor_review as er
from papyrus_content.story_reporting import latest_story_version

BODY = "Intro.\n\n| Control | Status |\n| --- | --- |\n| Identity | Have |\n\nClose.\n"
CONTEXT = {"text": "Synthetic mission and policy.", "contextHash": "ctx-hash-1", "warnings": []}


def passing(**changes):
    findings = [{"criterion": key, "status": "pass", "severity": "info", "note": "ok"} for key in er.CRITERION_KEYS]
    review = {"verdict": "approve", "summary": "Meets the criteria.", "findings": findings, "revisionNotes": [],
              "illustrationPlan": {"needed": False}, "typesettingPlan": {"tables": "cards under 640px"}}
    review.update(changes)
    return review


def failing_finding(criterion, note="Rows link to nothing.", severity="error"):
    return {"criterion": criterion, "status": "fail", "severity": severity, "quote": "Every row links back to code", "note": note}


def with_findings(*overrides, **changes):
    review = passing(**changes)
    keyed = {finding["criterion"]: finding for finding in review["findings"]}
    for override in overrides:
        keyed[override["criterion"]] = override
    review["findings"] = list(keyed.values())
    return review


def world(body=BODY, **metadata):
    world = t.World(stage="copywriting", metadata=metadata or None)
    world.client.update_record("Item", {"id": t.LINEAGE, "bodyMarkus": body})
    return world


def record(world, raw, check=None, version=t.LINEAGE):
    return er.record_review(world.client, t.LINEAGE, version, raw, model="gpt-6-luna", context_hash="ctx-hash-1", check=check, at=t.NOW)


def stored(world, version=t.LINEAGE):
    return json.loads(world.client.tables["Item"][version]["metadata"])["editorReview"]


def test_find_tables_returns_pipe_tables_with_their_first_line():
    tables = er.find_tables(BODY)
    assert len(tables) == 1 and tables[0]["startLine"] == 3 and tables[0]["text"].count("|") == 9
    assert er.find_tables("A | b in prose.\n| lone line\n") == []


def test_an_approving_review_is_stored_on_the_version_and_does_not_hold():
    w = world()
    outcome = record(w, passing())
    assert outcome == {"version": t.LINEAGE, "hold": False, "reason": "", "verdict": "approve"}
    review = stored(w)
    assert review["verdict"] == "approve" and review["model"] == "gpt-6-luna" and review["contextHash"] == "ctx-hash-1" and review["at"] == t.NOW
    assert review["versionId"] == t.LINEAGE and {f["criterion"] for f in review["findings"]} == set(er.CRITERION_KEYS)
    assert review["illustrationPlan"] == {"needed": False} and "downgradedFrom" not in review


def test_the_review_keeps_the_rest_of_the_versions_metadata_and_changes_nothing_else():
    w = world(botChain={"hops": 1})
    before = {key: value for key, value in w.client.tables["Item"][t.LINEAGE].items() if key != "metadata"}
    record(w, passing())
    row = w.client.tables["Item"][t.LINEAGE]
    metadata = json.loads(row["metadata"])
    assert metadata["botChain"] == {"hops": 1} and metadata["frontMatterYaml"] and "editorReview" in metadata
    assert {key: value for key, value in row.items() if key != "metadata"} == before   # state, stage, status, body untouched
    assert not w.client.tables.get("Message") and not w.client.tables.get("PublishedItem")


def test_a_revise_review_holds_with_the_notes_as_the_reason():
    w = world()
    raw = with_findings(failing_finding("promises-kept"), verdict="revise", revisionNotes=["Link every row to its file.", "Cite the original source."])
    outcome = record(w, raw)
    assert outcome["hold"] is True and outcome["verdict"] == "revise" and outcome["version"] == t.LINEAGE
    assert outcome["reason"].startswith("Editor review: revise.") and "Link every row to its file." in outcome["reason"]
    assert stored(w)["revisionNotes"] == ["Link every row to its file.", "Cite the original source."]


def test_a_reframe_review_holds():
    outcome = record(world(), passing(verdict="reframe", revisionNotes=["The evidence supports a smaller story."]))
    assert outcome["hold"] is True and outcome["verdict"] == "reframe" and "smaller story" in outcome["reason"]


def test_revision_notes_default_to_the_failed_findings_and_the_reason_is_bounded():
    w = world()
    raw = with_findings(failing_finding("dates-sourced", "Dates are inferred." + " x" * 500), verdict="revise")
    outcome = record(w, raw)
    assert "dates-sourced: Dates are inferred." in stored(w)["revisionNotes"][0] and len(outcome["reason"]) <= er.REASON_LIMIT


def test_approve_cannot_stand_over_an_error_level_failure():
    w = world()
    outcome = record(w, with_findings(failing_finding("claims-attributed-and-linked")))
    assert outcome["hold"] is True and outcome["verdict"] == "revise" and outcome["downgradedFrom"] == "approve"
    assert any("claims-attributed-and-linked" in note for note in stored(w)["revisionNotes"])


def test_a_warning_level_failure_does_not_stop_an_approval():
    outcome = record(world(), with_findings(failing_finding("doctrine-fit", "Soft phrase.", severity="warn")))
    assert outcome["hold"] is False and outcome["verdict"] == "approve"


def test_a_criterion_the_reviewer_did_not_assess_counts_as_failed():
    w = world()
    raw = passing()
    raw["findings"] = [f for f in raw["findings"] if f["criterion"] != "dates-sourced"]
    outcome = record(w, raw)
    assert outcome["verdict"] == "revise" and any(f["criterion"] == "dates-sourced" and f["status"] == "fail" for f in stored(w)["findings"])


def test_tables_cannot_be_not_applicable_when_the_version_has_one():
    w = world()
    outcome = record(w, with_findings({"criterion": "tables-verified", "status": "na", "severity": "info", "note": "none"}))
    assert outcome["verdict"] == "revise"
    plain = world(body="No table here.\n")
    assert record(plain, with_findings({"criterion": "tables-verified", "status": "na", "severity": "info", "note": "none"}))["verdict"] == "approve"


def test_an_error_level_editorial_check_violation_blocks_approval_and_review_findings_do_not():
    check = {"status": "checked", "violations": 1, "reviews": 1, "packVersion": "v1", "findings": [
        {"rule": "no-hype", "severity": "error", "status": "violation", "message": "hype"},
        {"rule": "voice", "severity": "warn", "status": "violation", "message": "passive"},
        {"rule": "maybe", "severity": "error", "status": "review", "message": "unsure", "probability": 0.5}]}
    w = world()
    outcome = record(w, passing(), check=check)
    assert outcome["verdict"] == "revise" and stored(w)["editorialCheck"]["blocking"] == ["no-hype"]
    clean = {"status": "checked", "violations": 0, "reviews": 1, "findings": [{"rule": "maybe", "severity": "error", "status": "review"}]}
    assert record(world(), passing(), check=clean)["verdict"] == "approve"


def test_a_skipped_or_missing_check_does_not_block():
    assert record(world(), passing(), check={"status": "skipped", "findings": []})["verdict"] == "approve"
    assert record(world(), passing(), check=None)["verdict"] == "approve"


@pytest.mark.parametrize("raw", [{"verdict": "publish"}, {"verdict": ""}, {}, "approve"])
def test_an_answer_that_is_not_a_review_is_refused_and_nothing_is_stored(raw):
    w = world()
    with pytest.raises(ValueError):
        record(w, raw)
    assert "editorReview" not in json.loads(w.client.tables["Item"][t.LINEAGE]["metadata"])


def test_the_review_is_refused_for_a_version_of_another_story():
    w = world()
    with pytest.raises(ValueError, match="not a version of story"):
        er.record_review(w.client, "other-story", t.LINEAGE, passing(), model="m", context_hash="h", check=None, at=t.NOW)


# --- the inputs --------------------------------------------------------------------------------------------


def inputs_for(w, **kwargs):
    kwargs.setdefault("run_check", lambda version_id: {"status": "checked", "violations": 0, "reviews": 0, "findings": []})
    kwargs.setdefault("read_context", lambda lineage: CONTEXT)
    kwargs.setdefault("read_attachment", lambda client, attachment: b"Angle: show the audit trail.")
    return er.gather_review_inputs(w.client, t.LINEAGE, t.LINEAGE, **kwargs)


def add_assignment(w, **fields):
    w.client.tables.setdefault("Assignment", {})["assignment-1"] = {
        "id": "assignment-1", "assignmentTypeKey": "copywriting.article-draft", "itemLineageId": t.LINEAGE, "createdAt": t.NOW, "status": "open", **fields}


def test_without_a_brief_the_doctrine_is_the_brief():
    gathered = inputs_for(world())
    assert gathered["brief"] == {"source": "none", "assignmentId": None, "text": ""} and "doctrine" in gathered["briefFallback"]
    assert gathered["editorialContext"] == {"text": CONTEXT["text"], "hash": "ctx-hash-1", "warnings": []}
    assert gathered["tables"] and gathered["version"]["bodyMarkus"] == BODY and [c["key"] for c in gathered["criteria"]] == list(er.CRITERION_KEYS)


def test_a_brief_in_the_versions_metadata_wins():
    w = world(editorBrief="Angle from metadata.")
    add_assignment(w)
    assert inputs_for(w)["brief"] == {"source": "story-metadata", "assignmentId": None, "text": "Angle from metadata."}


def test_the_copywriting_assignments_brief_attachment_is_the_brief_then_its_summary():
    w = world()
    add_assignment(w, summary="Summary brief.")
    w.client.tables["ModelAttachment"] = {"att-1": {"id": "att-1", "ownerId": "assignment-1", "role": "assignment_brief", "sortKey": "a", "status": "active"}}
    assert inputs_for(w)["brief"] == {"source": "assignment-attachment", "assignmentId": "assignment-1", "text": "Angle: show the audit trail."}
    w.client.tables["ModelAttachment"] = {}
    assert inputs_for(w)["brief"]["source"] == "assignment-summary"


def test_other_assignments_and_cancelled_ones_are_not_the_brief():
    w = world()
    add_assignment(w, assignmentTypeKey="reporting.packet", summary="Not a copywriting brief.")
    assert inputs_for(w)["brief"]["source"] == "none"
    add_assignment(w, summary="Cancelled.", canceledAt=t.NOW)
    assert inputs_for(w)["brief"]["source"] == "none"


def test_linked_references_carry_their_source_and_date():
    w = world()
    w.client.tables["Reference"] = {"reference-1-v1": {"id": "reference-1-v1", "lineageId": "reference-1", "versionNumber": 1, "versionState": "current",
                                                       "title": "A guide", "sourceUri": "https://example.test/guide", "sourcePublishedAt": "2026-02-19"}}
    w.client.tables["SemanticRelation"] = {"r1": {"id": "r1", "predicate": "story_reference", "objectKind": "reference", "objectLineageId": "reference-1",
                                                  "subjectStateKey": f"item#{t.LINEAGE}#current", "metadata": json.dumps({"role": "cited"})}}
    with mock.patch("papyrus_content.story_reporting.STORY_REFERENCE_PREDICATE", "story_reference"):
        (reference,) = inputs_for(w)["references"]
    assert reference["title"] == "A guide" and reference["sourceUri"] == "https://example.test/guide" and reference["role"] == "cited"


def test_the_inputs_refuse_a_version_of_another_story_or_a_missing_one():
    w = world()
    with pytest.raises(ValueError, match="not found"):
        er.gather_review_inputs(w.client, t.LINEAGE, "nope", run_check=lambda v: {}, read_context=lambda s: CONTEXT)
    with pytest.raises(ValueError, match="not a version of story"):
        er.gather_review_inputs(w.client, "other", t.LINEAGE, run_check=lambda v: {}, read_context=lambda s: CONTEXT)


# --- the engine and the procedure -------------------------------------------------------------------------


def started(w):
    (outcome,) = w.deliver()
    assert outcome["status"] == "started"
    return w.invoked[0]


def test_an_approval_advances_the_story_and_a_revision_raises_a_flag_with_the_story_still_in_copywriting():
    approved = world()
    request = started(approved)
    result = approved.finish(request, output=record(approved, passing()))
    assert result["status"] == "moved" and approved.stage() == "typesetting" and approved.reviews() == []
    assert latest_story_version(approved.client, t.LINEAGE)["versionState"] == "current"

    revised = world()
    request = started(revised)
    result = revised.finish(request, output=record(revised, with_findings(failing_finding("promises-kept"), verdict="revise", revisionNotes=["Link the rows."])))
    assert result["status"] == "held" and revised.stage() == "copywriting"
    (review,) = revised.reviews()
    assert review["mode"] == "flag" and "Link the rows." in review["reason"] and not revised.client.tables.get("Message")


def run_procedure(tmp_path, review, client, check=None):
    """Run editor_review.tac through Tactus: the model is faked (an agent mock), the tools are the real ones over a fake backend."""
    pytest.importorskip("tactus")
    from tactus.adapters.memory import MemoryStorage
    from tactus.core import TactusRuntime
    from tactus.core.mocking import MockManager, set_current_mock_manager
    from tactus.protocols.result import TactusResult

    from pathlib import Path
    source = Path(__file__).resolve().parents[3] / "procedures/newsroom/editor_review.tac"
    runtime = TactusRuntime(procedure_id="papyrus-procedure-newsroom", storage_backend=MemoryStorage(), openai_api_key="unused", source_file_path=str(source))
    runtime.dependency_mode = "none"
    manager = MockManager()
    manager.disable_mock()
    runtime.mock_manager = manager
    set_current_mock_manager(manager)
    runtime.external_agent_mocks = {"editor_reviewer": [{"data": review}]}
    client.graphql = lambda *args, **kwargs: {}
    run = check or {"status": "checked", "clean": True, "violations": 0, "reviews": 0, "findings": []}
    stored_run = {"id": t.LINEAGE, "lineageId": t.LINEAGE, "versionNumber": 1, "violations": run["violations"], "reviews": run["reviews"],
                  "findings": [{"policyId": f["rule"], **{k: v for k, v in f.items() if k != "rule"}} for f in run["findings"]], "lanes": {}}
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)), \
            mock.patch("papyrus_newsroom.tactus_tools.papyrus_check_story_version", return_value=run), \
            mock.patch("papyrus_newsroom.tactus_tools.papyrus_editorial_context", return_value=CONTEXT), \
            mock.patch("papyrus_content.model_attachments.download_attachment_buffer", return_value=None), \
            mock.patch("papyrus_content.editorial_commands.read_item_check_run", return_value=stored_run):
        result = asyncio.run(runtime.execute(source.read_text(encoding="utf-8"), {"story": t.LINEAGE, "version": t.LINEAGE}, format="lua"))
    output = result.get("result")
    return result, output.output if isinstance(output, TactusResult) else output


def test_the_procedure_runs_through_tactus_and_answers_with_the_contract(tmp_path):
    w = world()
    result, output = run_procedure(tmp_path, passing(), w.client)
    assert result.get("success"), result.get("error")
    assert output == {"version": t.LINEAGE, "hold": False, "reason": "", "verdict": "approve"}
    assert stored(w)["verdict"] == "approve" and stored(w)["contextHash"] == "ctx-hash-1" and stored(w)["model"] == "gpt-6-luna"


def test_the_procedure_holds_on_revise_and_cannot_approve_over_a_check_violation(tmp_path):
    w = world()
    result, output = run_procedure(tmp_path, with_findings(failing_finding("promises-kept"), verdict="revise", revisionNotes=["Link the rows."]), w.client)
    assert result.get("success") and output["hold"] is True and output["verdict"] == "revise" and "Link the rows." in output["reason"]

    w = world()
    violation = {"status": "checked", "clean": False, "violations": 1, "reviews": 0, "findings": [{"rule": "no-hype", "severity": "error", "status": "violation", "message": "hype"}]}
    result, output = run_procedure(tmp_path, passing(), w.client, check=violation)
    assert result.get("success") and output["hold"] is True and stored(w)["downgradedFrom"] == "approve"
    assert not w.client.tables.get("Message")
