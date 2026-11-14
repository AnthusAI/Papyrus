"""A research assignment made in the newsroom (lib/assign-research.ts) must end in the stored shape `papyrus stories assign-research` makes, and the reporting
agent's context pack and the research run must read it (features_backend/browser-assign-research.feature). The TypeScript test writes what the browser path
writes to features_backend/fixtures/browser-assign-research.json; this test loads that file into the same fake newsroom the context pack specs use. The
Assignment model has no metadata or instructions column, so the direction reaches the pack only through the `metadata` ModelAttachment."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps", Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import newsroom_context_pack_steps as pack_steps  # noqa: E402
from papyrus_content import assignments as assignments_module  # noqa: E402
from papyrus_content import multi_search_research as research_module  # noqa: E402
from papyrus_content import newsroom_context_pack as pack_module  # noqa: E402
from papyrus_content.assignments_workflow import create_research_assignment  # noqa: E402
from papyrus_content.graphql_authoring import strip_unsupported_payload_fields  # noqa: E402

FIXTURE = REPO_ROOT / "features_backend" / "fixtures" / "browser-assign-research.json"


def written_by_the_browser() -> dict:
    return json.loads(FIXTURE.read_text())


class NewsroomWithTheBrowsersAssignment(pack_steps.FakeNewsroom):
    """The fake newsroom, with the assignment as the browser path stored it: the row without metadata or instructions, and the two ModelAttachments."""

    def __init__(self, written, *, attachments=True):
        super().__init__()
        self.payloads = {}
        row = dict(written["assignment"])
        self.assignment_id = row["id"]
        self.records["Assignment"] = {self.assignment_id: row}
        if attachments:
            self.payloads = {"metadata": json.dumps(written["metadata"]), "assignment_instructions": written["instructions"]}

    def list_by_index(self, index, key, **options):
        if index == "modelAttachmentsByOwnerRoleAndSortKey":
            return [{"id": f"{key}-{role}", "ownerKind": "assignment", "ownerId": key, "role": role, "sortKey": role, "status": "active", "updatedAt": "2026-11-03T12:00:00Z"}
                    for role in self.payloads]
        return super().list_by_index(index, key, **options)


def store_of(written, **options):
    store = NewsroomWithTheBrowsersAssignment(written, **options)
    for kind, text in (("mission", "Explain how machines affect public life."), ("policy", "Distinguish evidence from inference.")):
        store.doctrine[f"editorial-doctrine-{kind}"] = [{"id": f"doctrine-{kind}", "lineageId": f"doctrine-{kind}", "versionNumber": 1, "versionState": "current", "type": "doctrine",
                                                         "status": "private", "tenantId": pack_steps.TENANT, "body": [text]}]
    store.records["NewsroomSection"][pack_steps.SECTION_ID] = {"id": pack_steps.SECTION_ID, "tenantId": pack_steps.TENANT, "title": "Law and Policy", "editorialMission": "M", "editorialPolicy": "P"}
    store.items.append({"id": "story-1-v1", "lineageId": "story-1", "versionNumber": 1, "versionState": "current", "tenantId": pack_steps.TENANT, "type": "article", "status": "draft",
                        "stage": "idea", "section": "law-policy", "title": "Courts and model output", "headline": "Courts and model output", "bodyMarkus": "Draft."})
    return store


def download_from(store):
    def download(client, attachment, **_):
        return store.payloads[attachment["role"]].encode()

    return mock.patch.object(assignments_module, "download_attachment_buffer", side_effect=download)


def pack_of(store):
    with download_from(store), mock.patch.object(pack_module, "graphql_endpoint", return_value=pack_steps.ENDPOINT):
        return pack_module.build_context_pack(store, profile="reporter", assignment=store.assignment_id, story_lineage_id="story-1")


def test_the_pack_built_from_what_the_browser_wrote_carries_the_editors_direction():
    written = written_by_the_browser()
    pack = pack_of(store_of(written))
    assert written["metadata"]["direction"] in pack["user"]
    assert "Editor's direction (it outranks the Story)" in pack["user"]


def test_without_the_metadata_attachment_the_direction_never_reaches_the_pack():
    written = written_by_the_browser()
    pack = pack_of(store_of(written, attachments=False))
    assert written["metadata"]["direction"] not in pack["user"]


def test_the_assignment_row_has_only_columns_the_model_has():
    row = written_by_the_browser()["assignment"]
    assert strip_unsupported_payload_fields("Assignment", row) == row
    assert {"metadata", "instructions", "brief"}.isdisjoint(row)


def test_the_research_run_accepts_the_browser_assignment_and_records_a_packet_built_from_the_direction():
    import test_multi_search_research as multi

    written = written_by_the_browser()
    store = store_of(written)
    llm = multi.FakeLlm()
    with download_from(store), mock.patch.object(pack_module, "graphql_endpoint", return_value=pack_steps.ENDPOINT), \
         mock.patch.object(research_module, "apply_research_packet", return_value={"messageId": "m1"}) as packet, \
         mock.patch.object(research_module, "intake_research_packet_proposals", return_value={"registeredReferenceCount": 0}), \
         mock.patch.object(research_module, "build_record_changes", side_effect=lambda client, records: records), \
         mock.patch.object(research_module, "apply_record_changes"), \
         mock.patch.object(research_module, "update_newsroom_summary_after_research_packet_creates"):
        result = research_module.research_multi(store, {"assignment": store.assignment_id}, llm=llm, providers=multi.two_providers())
    assert result["action"] == "completed" and packet.called
    assert written["metadata"]["direction"] in llm.calls[0][1]


def test_the_browser_stores_what_the_command_stores():
    """The command's records, captured before they are written, against the browser's: the same Assignment columns, event fields and metadata keys."""
    written = written_by_the_browser()
    captured = []

    class Client:
        def get_record(self, model, record_id):
            return {"id": record_id, "type": "section"} if model == "NewsroomSection" else None

    with mock.patch("papyrus_content.assignments_workflow.build_record_changes", side_effect=lambda client, records: captured.extend(records) or records), \
         mock.patch("papyrus_content.assignments_workflow.apply_record_changes"), \
         mock.patch("papyrus_content.assignments_workflow.update_newsroom_summary_after_assignment_creates"):
        create_research_assignment(Client(), {"title": "Courts and model output", "type": "research.multi", "content-item": "story-1", "section": "law-policy", "corpus-key": "example",
                                              "instructions": written["instructions"], "direction": written["metadata"]["direction"], "context-profile": "reporter", "actor-label": "An Editor"})
    cli_assignment = next(record["expected"] for record in captured if record["modelName"] == "Assignment")
    cli_event = next(record["expected"] for record in captured if record["modelName"] == "AssignmentEvent")
    cli_metadata = json.loads(cli_assignment["metadata"])
    columns = strip_unsupported_payload_fields("Assignment", cli_assignment)
    browser = written["assignment"]
    assert set(browser) <= set(columns), sorted(set(browser) - set(columns))
    for key in ("assignmentTypeKey", "queueKey", "queueStatusKey", "status", "priority", "title", "summary", "sectionKey", "sectionStatusKey", "sectionQueueStatusKey", "newsroomFeedKey", "itemLineageId", "createdBy"):
        assert browser[key] == columns[key], key
    cli_event = {key: value for key, value in cli_event.items() if value is not None or key in written["event"]}   # actorSub is None unless a login names one
    assert set(written["event"]) == set(cli_event)
    assert {key: value for key, value in written["event"].items() if key not in ("id", "createdAt", "assignmentId")} == {key: value for key, value in cli_event.items() if key not in ("id", "createdAt", "assignmentId")}
    assert set(written["metadata"]) <= set(cli_metadata)
    for key in ("kind", "researchMode", "sectionKey", "contextProfile", "direction", "researchBackend", "topicScopeCategoryKeys"):
        assert written["metadata"][key] == cli_metadata[key], key
    assert cli_assignment["instructions"] == written["instructions"]
