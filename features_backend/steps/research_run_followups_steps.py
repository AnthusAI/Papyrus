"""Steps of features_backend/research-run-followups.feature and the scenarios in fact-check.feature and monitoring-research-assignments.feature that came with it.
They call the same code as procedures/newsroom/tests/test_research_run_followups.py, with invented content."""
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_research_run_followups as followups  # noqa: E402
from papyrus_content import assignments_commands as commands  # noqa: E402
from papyrus_content import assignments_workflow as aw  # noqa: E402
from papyrus_content import multi_search_research as ms  # noqa: E402
from papyrus_content.story_reporting import link_reference_to_story, story_references  # noqa: E402
from steps.monitoring_research_assignments_steps import state as worker_state  # noqa: E402


def stop_patch(context, patcher):
    patcher.start()
    context.add_cleanup(patcher.stop)


# --- the temporary directory ----------------------------------------------------------------------------------------------------

@given("a code directory that cannot be written and PAPYRUS_RUNS_DIR naming a writable directory")
def step_unwritable(context):
    base = Path(tempfile.mkdtemp())
    root = base / "code"
    root.mkdir()
    (base / "temporary").mkdir()
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    context.followups = SimpleNamespace(base=base, root=root)
    context.add_cleanup(lambda: (root.chmod(stat.S_IRWXU), shutil.rmtree(base, ignore_errors=True)))
    stop_patch(context, mock.patch.object(aw, "PAPYRUS_ROOT", root))
    stop_patch(context, mock.patch.dict(os.environ, {"PAPYRUS_RUNS_DIR": str(base / "temporary")}))


@when("the sources of a research packet are taken in")
def step_take_in_dir(context):
    packet = {"summary": "Nothing found.", "proposedReferences": []}
    entry = {"assignment": {"id": "assignment-1"}, "message": {"id": "message-1", "createdAt": "2026-11-03T12:00:00Z"}, "packet": packet}
    client = mock.Mock()
    client.get_record.return_value = {"id": "assignment-1", "metadata": json.dumps({"corpusKey": "example"})}
    client.list_records.return_value = []
    with mock.patch.object(aw, "load_assignment_research_packet_entries", return_value=[entry]):
        context.followups.result = aw.intake_research_packet_proposals(client, {"assignment": "assignment-1", "corpus-key": "example", "dry-run": True})


@then("the catalog was written under the configured run directory")
def step_catalog_dir(context):
    path = context.followups.result["catalogPath"]
    assert path.startswith(str(context.followups.base / "temporary")) and Path(path).is_file(), path


# --- the operator command ---------------------------------------------------------------------------------------------------------

@given("a Story whose reporter research assignment found one new Reference and one already held")
def step_story(context):
    context.followups = SimpleNamespace(client=followups.story_client(), curated=[])


@given("a Story whose research assignment has no reporter profile")
def step_story_without_profile(context):
    client = followups.story_client()
    client.tables["Assignment"]["assignment-1"]["metadata"] = json.dumps({"contextProfile": "none"})
    context.followups = SimpleNamespace(client=client, curated=[])


@given('the Story already cites the new Reference with the note "{note}"')
def step_cited(context, note):
    link_reference_to_story(context.followups.client, followups.LINEAGE, "reference-pwn-ai-v1", role="cited", actor="editor", note=note, now=followups.NOW)


@when("the sources are taken in by the operator command with cited-only")
def step_command(context):
    current = context.followups

    def curate(client, assignment_id, ids, services=None):
        current.curated.extend(ids)
        return {"curated": list(ids), "failed": []}

    with mock.patch.object(commands, "create_authoring_client", lambda: (current.client, None)), \
         mock.patch.object(commands, "intake_research_packet_proposals", lambda client, options: dict(followups.INTAKE)), \
         mock.patch.object(ms, "curate_found_references", curate), mock.patch("builtins.print"):
        commands.assignments_intake_proposals(["--assignment", "assignment-1", "--cited-only", "true", "--json"])


@then("both References are linked to the Story as consulted")
def step_both_linked(context):
    rows = story_references(context.followups.client, followups.LINEAGE)
    assert sorted(row["referenceLineageId"] for row in rows) == ["reference-held", "reference-pwn-ai"] and {row["role"] for row in rows} == {"consulted"}


@then("only the new Reference was summarized")
def step_only_new(context):
    assert context.followups.curated == ["reference-pwn-ai-v1"], context.followups.curated


@then("the Story has {count:d} References")
def step_count(context, count):
    assert len(story_references(context.followups.client, followups.LINEAGE)) == count


@then('the new Reference is still cited with the note "{note}"')
def step_still_cited(context, note):
    row = [r for r in story_references(context.followups.client, followups.LINEAGE) if r["referenceLineageId"] == "reference-pwn-ai"][0]
    assert row["role"] == "cited" and row["note"] == note


# --- the worker's note ------------------------------------------------------------------------------------------------------------

@given("the research for assignment {number:d} finishes but could not take its sources in because the server could not write a working file")
def step_intake_failed(context, number):
    current = worker_state(context)
    current.research = followups.IntakeFailed()


@then("its finished note says that its sources were not added because the server could not write a working file")
def step_note(context):
    notes = [event["note"] for event in worker_state(context).backend.events if event["eventType"] == "research.completed"]
    assert len(notes) == 1 and "sources were not added" in notes[0] and "could not write a working file" in notes[0] and "Errno" not in notes[0], notes


@then("the pass result lists assignment {number:d} as unable to take its sources in")
def step_listed(context, number):
    assert f"assignment-{number}" in worker_state(context).result["intakeFailed"]


# --- the fact check ---------------------------------------------------------------------------------------------------------------

@given('the editor\'s direction is "{text}"')
def step_direction(context, text):
    context.run.direction = text


@given('the editor\'s direction is the text of "{fixture}"')
def step_direction_from_fixture(context, fixture):
    context.run.direction = (Path(__file__).resolve().parent.parent / "fixtures" / "research" / fixture).read_text(encoding="utf-8")


@then("the packet angle is empty")
def step_angle_empty(context):
    assert context.packet["recommended_angle"] == "", context.packet["recommended_angle"]


def gap_named(context, name):
    return [gap for gap in (context.packet["factCheck"].get("directionGaps") or []) if gap["name"] == name]


@then('the packet names "{name}" as a direction gap and the sources mention it')
def step_gap_with_sources(context, name):
    assert [gap["inSources"] for gap in gap_named(context, name)] == [True]


@then('the packet names "{name}" as a direction gap and the sources do not mention it')
def step_gap_without_sources(context, name):
    assert [gap["inSources"] for gap in gap_named(context, name)] == [False]


@then('the packet\'s open questions include "{text}"')
def step_open_question(context, text):
    assert text in context.packet["open_questions"], context.packet["open_questions"]


@then('the packet names no direction gap for "{name}"')
def step_no_gap_for(context, name):
    names = [gap["name"] for gap in context.packet["factCheck"].get("directionGaps") or []]
    assert not any(name.lower() == entry.lower() or name.lower() in entry.lower().split() for entry in names), names


@then('the packet\'s open questions do not mention "{text}"')
def step_open_question_absent(context, text):
    assert not any(text in question for question in context.packet["open_questions"]), context.packet["open_questions"]


@then("the packet has no direction gaps")
def step_no_gaps(context):
    assert not context.packet["factCheck"].get("directionGaps")


# --- the corpus record ---------------------------------------------------------------------------------------------------------

OLD_CORPUS = {"id": "knowledge-corpus-example", "name": "Example", "role": "canonical", "itemCount": 5000, "createdAt": "2020-01-01T00:00:00Z"}


@given("a publication whose corpus record says it was created long ago and holds many items")
def step_old_corpus(context):
    context.corpus_client = mock.Mock()
    context.corpus_client.get_record.side_effect = lambda model, record_id: (dict(OLD_CORPUS) if model == "KnowledgeCorpus" else {"id": record_id})
    context.corpus_client.list_records.return_value = []


@when("a research packet's cited sources are taken in")
def step_take_in_keeping_corpus(context):
    packet = {"proposedReferences": [{"url": "https://example.org/report", "title": "A report", "ingestion_rationale": "cited"}]}
    entry = {"assignment": {"id": "assignment-1"}, "message": {"id": "message-1", "createdAt": "2026-11-03T12:00:00Z"}, "packet": packet}
    captured = {}

    def changes(client, records):
        captured["models"] = [row["modelName"] for row in records]
        return []

    publication = {"key": "example", "corpusId": "knowledge-corpus-example", "name": "Example"}
    with mock.patch.object(aw, "load_assignment_research_packet_entries", return_value=[entry]), \
         mock.patch("papyrus_content.editorial_context.hosted_publication", return_value=publication), \
         mock.patch.object(aw, "build_record_changes", side_effect=changes):
        aw.intake_research_packet_proposals(context.corpus_client, {"assignment": "assignment-1", "corpus-key": "example", "dry-run": True,
                                                                    "config": "does-not-exist.yml"})
    context.corpus_models = captured["models"]


@then("the corpus record is unchanged")
def step_corpus_unchanged(context):
    assert "KnowledgeCorpus" not in context.corpus_models, context.corpus_models


@then("the cited sources are registered")
def step_registered(context):
    assert "Reference" in context.corpus_models, context.corpus_models
