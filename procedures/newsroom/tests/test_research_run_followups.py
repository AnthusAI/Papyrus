"""Five faults found on the first real worker run of research.multi (features_backend/research-run-followups.feature and the fact-check and worker features).
Invented content only. No network, no AWS, no model."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import assignments_commands as commands  # noqa: E402
from papyrus_content import assignments_workflow as aw  # noqa: E402
from papyrus_content import fact_check as fc  # noqa: E402
from papyrus_content import multi_search_research as ms  # noqa: E402
from papyrus_content.story_reporting import link_reference_to_story, story_references  # noqa: E402
from test_multi_search_research import FakeLlm, FakeProvider, hit  # noqa: E402
from test_research_assignments_worker import Backend, Research, assignment, run  # noqa: E402
from test_story_reporting import LINEAGE, NOW, FakeAuthoringClient, client_with_one_story  # noqa: E402


# --- 1. the intake writes under PAPYRUS_RUNS_DIR; an unwritable root without it is an error ------------------------------------------------

@pytest.fixture
def unwritable_root(tmp_path, monkeypatch):
    root = tmp_path / "code"
    root.mkdir()
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    monkeypatch.setattr(aw, "PAPYRUS_ROOT", root)
    monkeypatch.delenv("PAPYRUS_RUNS_DIR", raising=False)
    yield root
    root.chmod(stat.S_IRWXU)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_an_unwritable_root_is_an_error_that_names_the_setting(unwritable_root):
    with pytest.raises(OSError, match="PAPYRUS_RUNS_DIR"):
        aw.writable_run_dir("run-1")


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_the_configured_directory_is_used_when_the_root_cannot_be_written(unwritable_root, tmp_path, monkeypatch):
    monkeypatch.setenv("PAPYRUS_RUNS_DIR", str(tmp_path / "configured"))
    run_dir = aw.writable_run_dir("run-1")
    assert run_dir == tmp_path / "configured" / "run-1" and run_dir.is_dir()


def test_a_run_directory_stays_under_the_root_when_it_can_be_written(tmp_path, monkeypatch):
    monkeypatch.setattr(aw, "PAPYRUS_ROOT", tmp_path)
    assert aw.writable_run_dir("run-2") == tmp_path / ".papyrus-runs" / "run-2"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_the_intake_writes_its_catalog_under_the_configured_directory(unwritable_root, tmp_path, monkeypatch):
    monkeypatch.setenv("PAPYRUS_RUNS_DIR", str(tmp_path / "configured"))
    packet = {"summary": "Nothing found.", "proposedReferences": []}
    entry = {"assignment": {"id": "assignment-1"}, "message": {"id": "message-1", "createdAt": "2026-11-03T12:00:00Z"}, "packet": packet}
    client = mock.Mock()
    client.get_record.return_value = {"id": "assignment-1", "metadata": json.dumps({"corpusKey": "example"})}
    client.list_records.return_value = []
    with mock.patch.object(aw, "load_assignment_research_packet_entries", return_value=[entry]):
        result = aw.intake_research_packet_proposals(client, {"assignment": "assignment-1", "corpus-key": "example", "dry-run": True})
    assert result["catalogPath"].startswith(str(tmp_path / "configured")) and Path(result["catalogPath"]).is_file()


# --- 2. process-proposals --cited-only finishes the job ------------------------------------------------------------------------------

def story_client():
    client = client_with_one_story()
    client.tables["Reference"]["reference-held-v1"] = {"id": "reference-held-v1", "lineageId": "reference-held", "versionNumber": 1, "versionState": "current"}
    client.tables["Assignment"] = {"assignment-1": {"id": "assignment-1", "itemLineageId": LINEAGE, "metadata": json.dumps({"contextProfile": "reporter"})}}
    return client


INTAKE = {"assignmentId": "assignment-1", "citedOnly": True,
          "references": [{"referenceId": "reference-pwn-ai-v1", "action": "create"}, {"referenceId": "reference-held-v1", "action": "held"}]}


def test_taking_in_links_both_and_curates_only_the_taken_in(monkeypatch):
    client = story_client()
    curated = []
    monkeypatch.setattr(ms, "curate_found_references", lambda c, assignment_id, ids, services=None: curated.append(list(ids)) or {"curated": list(ids), "failed": []})
    result = ms.take_in_found_references(client, "assignment-1", LINEAGE, INTAKE, actor_label="tester")
    assert sorted(result["linked"]) == ["reference-held", "reference-pwn-ai"]
    assert curated == [["reference-pwn-ai-v1"]]
    assert {row["role"] for row in story_references(client, LINEAGE)} == {"consulted"}


def test_taking_in_twice_adds_no_link_and_does_not_downgrade_a_role(monkeypatch):
    client = story_client()
    monkeypatch.setattr(ms, "curate_found_references", lambda *a, **k: {"curated": [], "failed": []})
    link_reference_to_story(client, LINEAGE, "reference-pwn-ai-v1", role="cited", actor="editor", note="kept note", now=NOW)
    first = ms.take_in_found_references(client, "assignment-1", LINEAGE, INTAKE, actor_label="tester")
    second = ms.take_in_found_references(client, "assignment-1", LINEAGE, INTAKE, actor_label="tester")
    rows = {row["referenceLineageId"]: row for row in story_references(client, LINEAGE)}
    assert first["linked"] == ["reference-held"] and second["linked"] == []
    assert len(rows) == 2 and rows["reference-pwn-ai"]["role"] == "cited" and rows["reference-pwn-ai"]["note"] == "kept note"


def test_the_command_does_the_same_as_the_research_run(monkeypatch, capsys):
    client = story_client()
    monkeypatch.setattr(commands, "create_authoring_client", lambda: (client, None))
    monkeypatch.setattr(commands, "intake_research_packet_proposals", lambda c, options: dict(INTAKE))
    monkeypatch.setattr(ms, "curate_found_references", lambda c, assignment_id, ids, services=None: {"curated": list(ids), "failed": []})
    commands.assignments_intake_proposals(["--assignment", "assignment-1", "--cited-only", "true", "--json"])
    printed = json.loads(capsys.readouterr().out)
    assert sorted(printed["linkedToStory"]) == ["reference-held", "reference-pwn-ai"] and printed["curation"]["curated"] == ["reference-pwn-ai-v1"]
    assert len(story_references(client, LINEAGE)) == 2


def test_the_command_leaves_an_assignment_without_a_reporter_profile_alone(monkeypatch, capsys):
    client = story_client()
    client.tables["Assignment"]["assignment-1"]["metadata"] = json.dumps({"contextProfile": "none"})
    monkeypatch.setattr(commands, "create_authoring_client", lambda: (client, None))
    monkeypatch.setattr(commands, "intake_research_packet_proposals", lambda c, options: dict(INTAKE))
    commands.assignments_intake_proposals(["--assignment", "assignment-1", "--cited-only", "true", "--json"])
    assert "linkedToStory" not in json.loads(capsys.readouterr().out) and story_references(client, LINEAGE) == []


# --- 3. the status after a failed intake ---------------------------------------------------------------------------------------------

class IntakeFailed(Research):
    def __call__(self, client, options, **_):
        self.asked.append(options)
        return {"action": "completed", "intakeError": "OSError: [Errno 30] Read-only file system: '/var/task/.papyrus-runs'"}


def test_a_failed_intake_is_said_plainly_in_the_note_and_the_pass_result():
    backend = Backend([assignment(1)])
    result = run(backend, IntakeFailed())
    note = [event["note"] for event in backend.events if event["eventType"] == "research.completed"][0]
    assert backend.rows["assignment-1"]["status"] == "completed"
    assert "sources were not added" in note and "could not write a working file" in note and "Errno" not in note and "OSError" not in note
    assert result["intakeFailed"] == {"assignment-1": "OSError: [Errno 30] Read-only file system: '/var/task/.papyrus-runs'"}


def test_a_clean_run_keeps_its_plain_note_and_reports_no_intake_failure():
    backend = Backend([assignment(1)])
    result = run(backend, Research())
    assert [e["note"] for e in backend.events if e["eventType"] == "research.completed"] == ["Research finished; the packet is on the assignment."]
    assert result["intakeFailed"] == {}


def test_the_other_failure_reasons_lose_their_exception_names():
    assert "boom happened" in ms.finished_note("ValueError: boom happened") and "ValueError" not in ms.finished_note("ValueError: boom happened")


# --- 4. the summary and angle checks --------------------------------------------------------------------------------------------------

def names(text, *sources, prose=False, hosts=()):
    return [row["term"] for row in fc.literal_check(text, list(sources), list(hosts), prose=prose)]


def test_an_ordinary_word_that_opens_a_sentence_is_not_a_name_in_a_summary_or_angle():
    assert names("Examine the records. Two claims rest on one source.", "records and sources", prose=True) == []
    assert names("Examine the records.", "records") == ["Examine"]


def test_an_invented_person_is_still_caught_in_a_summary():
    assert names("Jordan Quill signed it.", "A clerk signed it.", prose=True) == ["Jordan", "Quill"]
    assert names("The clerk met Quill.", "A clerk signed it.", prose=True) == ["Quill"]


def test_a_sentence_opening_word_the_sources_capitalize_elsewhere_is_checked():
    assert names("Quill signed it.", "He met Quill there. Quill is clerk.", prose=True) == []
    assert names("Quill signed it.", "The record has a quill pen.", prose=True) == []


def test_possessives_match_on_both_sides():
    assert names("The Harbor County State's Attorney's Office said so.", "Harbor County State’s Attorney’s Office said so.") == []
    assert names("The Harbor County State Attorney Office said so.", "Harbor County State's Attorney's Office said so.") == []
    assert names("The Harbor County State's Attorney's Office said so.", "Harbor County State Attorney Office said so.") == []
    assert names("The Harbor County State's Attorney's Office said so.", "The State of Harbor County said so.") == ["Attorney", "Office"]


def verified(claim="Councilor Marlow spoke on Tuesday.", number=1):
    return [{"claim": claim, "sources": [str(number)]}]


def test_a_summary_with_a_sentence_opening_verb_is_kept():
    texts = {"1": "Councilor Marlow spoke on Tuesday."}
    llm = lambda system, user, schema: {"summary": "Examine the speech. Councilor Marlow spoke on Tuesday.", "recommended_angle": "Watch the next vote."}
    summary, angle, note = ms.verified_summary(verified(), texts, {"1": "https://a.example.org/x"}, {"verified": 1, "total": 1}, llm, "")
    assert note is None and summary.startswith("Examine") and angle == "Watch the next vote."


def test_a_failed_summary_leaves_the_angle_empty_not_a_copy():
    texts = {"1": "Councilor Marlow spoke on Tuesday."}
    llm = lambda system, user, schema: {"summary": "Councilor Marlow spoke in Ohio.", "recommended_angle": "Follow Ohio."}
    summary, angle, note = ms.verified_summary(verified(), texts, {"1": "https://a.example.org/x"}, {"verified": 1, "total": 1, "needs_check": 0}, llm, "")
    assert note.startswith("summary_failed_literal_check") and angle == "" and summary.startswith("1 of 1 claims")


def test_the_packet_angle_is_empty_when_there_is_none():
    packet = ms.build_packet([{"query": "q"}], [], {}, {"summary": "A plain summary.", "recommendedAngle": "", "claims": [], "disagreements": [],
                                                       "openQuestions": [], "droppedClaims": []})
    assert packet["recommended_angle"] == ""


# --- 5. the editor's direction is covered ---------------------------------------------------------------------------------------------

DIRECTION = "Look into Dana Woodruff, Councilor Marlow and Alder Vance. Find court records on Pell County."


def research(direction, pages, claims, open_questions=()):
    synthesis = {"summary": "The pages were read.", "recommended_angle": "", "claims": claims, "disagreements": [], "open_questions": list(open_questions)}
    llm = FakeLlm(synthesis=synthesis)
    hits = [hit(f"https://page{n}.example.org/a", f"Page {n}", text) for n, text in enumerate(pages, start=1)]
    provider = FakeProvider("gemini", {query["query"]: hits for query in llm.plan["queries"]})
    return ms.run_multi_search("brief", llm=llm, providers={"gemini": provider}, direction=direction)["packet"]


def test_a_name_with_sources_and_no_claim_is_a_gap_with_an_open_question():
    packet = research(DIRECTION, ["Dana Woodruff filed a court record in Pell County.", "Councilor Marlow spoke. Alder Vance was held."],
                      [{"claim": "Councilor Marlow spoke.", "sources": [2]}, {"claim": "Alder Vance was held.", "sources": [2]},
                       {"claim": "Pell County has records.", "sources": [1]}])
    gaps = packet["factCheck"]["directionGaps"]
    assert [(gap["name"], gap["inSources"]) for gap in gaps] == [("Dana Woodruff", True)]
    assert "The run has sources that mention Dana Woodruff but wrote nothing on Dana Woodruff." in packet["open_questions"]


def test_a_name_in_no_source_is_found_nothing_and_a_covered_name_is_not_a_gap():
    packet = research("Look into Councilor Marlow and Rowan Tesk.", ["Councilor Marlow spoke."], [{"claim": "Councilor Marlow spoke.", "sources": [1]}])
    assert [(gap["name"], gap["inSources"]) for gap in packet["factCheck"]["directionGaps"]] == [("Rowan Tesk", False)]
    assert "The run found nothing on Rowan Tesk." in packet["open_questions"]


def test_a_name_in_an_open_question_or_an_unverified_claim_is_covered():
    packet = research("Look into Councilor Marlow and Alder Vance.", ["Councilor Marlow spoke. Alder Vance was held."],
                      [{"claim": "Councilor Marlow spoke.", "sources": [1]}], open_questions=["Why was Alder Vance held?"])
    assert "directionGaps" not in packet["factCheck"]


def test_generic_words_and_sentence_openers_in_a_direction_are_not_names():
    assert fc.direction_gaps("Find the cases. Look into records. Compare the sources.", ["nothing"], ["nothing"]) == []


def test_no_direction_means_no_check():
    packet = research("", ["Councilor Marlow spoke."], [{"claim": "Councilor Marlow spoke.", "sources": [1]}])
    assert "directionGaps" not in packet["factCheck"]


def test_the_packet_body_lists_the_gaps():
    packet = research(DIRECTION, ["Dana Woodruff filed a court record in Pell County."], [{"claim": "Pell County has records.", "sources": [1]}])
    bundle = aw.normalize_research_packet_bundle(packet, assignment={"corpusId": "c"}, assignment_meta={}, research_mode="source_discovery")
    body = aw.research_packet_body(bundle)
    assert "Named in the direction, not covered:" in body and "- Dana Woodruff: The run has sources that mention Dana Woodruff" in body


REAL_DIRECTION = (Path(__file__).resolve().parents[3] / "features_backend" / "fixtures" / "research" / "non-interference-direction.txt").read_text(encoding="utf-8")


def test_a_real_direction_does_not_ask_about_a_venue_citation_or_a_described_document_label():
    names = [gap["name"] for gap in fc.direction_gaps(REAL_DIRECTION, ["nothing"], ["NeurIPS Gemini Bob Alice GibberLink"])]
    assert "NeurIPS" not in names and "Gemini" not in names and "Bob" not in names and "GibberLink" not in names
    assert "Zdancewic" in names and "Goldwasser" in names


def test_the_venue_year_and_described_label_rules_stay_narrow():
    assert "NeurIPS" not in fc.subjects_text("Unilateral steganography (NeurIPS 2026).")
    assert "Smith" in fc.subjects_text("The bound (Smith 2019).")
    assert "Gemini" not in fc.subjects_text("The Gemini deep-research documents are leads.")
    assert "Gemini" in fc.subjects_text("Gemini has a deep-research mode, and the documents are leads.")
