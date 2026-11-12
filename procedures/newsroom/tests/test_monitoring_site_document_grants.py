"""The roles that file an idea or follow a Story's checklist can read the site's saved documents (its Story procedure), so nothing files a checklist from a guess.

The fields come from the code: a recording client counts what reading one saved document asks AppSync for. The grants come from the monitoring template.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from field_recorder import FieldRecorder
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles
from papyrus_content.guidelines.store import GuidelineStore

TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "monitoring" / "papyrus-monitoring.yaml"
FIELD = re.compile(r"apis/(\$\{\w+\}|\*)/types/(Query|Mutation)/fields/(\w+)\"")
SITE_APIS = ("AnthUs", "Papyrus", "ThreatIntel", "DataParade", "Pilobolus", "Shipped", "Distinctive", "MachinesOnMachines")


def resources() -> dict[str, str]:
    parts = re.split(r"\n(?=  \w+:\n    Type: )", TEMPLATE.read_text())
    return {re.match(r"\s*(\w+):", part).group(1): part for part in parts[1:]}


def grants_of(role: str) -> set[tuple[str, str, str]]:
    """(API, kind, field) for every AppSync grant in the role's own policy and in every managed policy attached to it. API is ``*`` or the site's parameter name."""
    found = set()
    for name, body in resources().items():
        if name == role or f"Roles: [!Ref {role}]" in body:
            found |= {(api, kind, field) for api, kind, field in FIELD.findall(body)}
    return found


def can(grants, api: str, kind: str, field: str) -> bool:
    return (api, kind, field) in grants or ("*", kind, field) in grants


class DownloadingBackend(FakeBackend):
    """The slot a download asks for is a local file, so the real download code runs."""

    def __init__(self, directory: Path, **options):
        super().__init__(**options)
        self.directory = directory

    def create_model_attachment_download(self, attachment_id: str) -> dict:
        attachment = next(row for row in self.attachments if row["id"] == attachment_id)
        path = self.directory / attachment_id
        path.write_bytes(self.bodies[attachment["storagePath"]])
        return {"downloadUrl": path.as_uri(), "method": "GET", "requiredHeaders": {}}


def site_document_reads(tmp_path) -> set[tuple[str, str]]:
    backend = DownloadingBackend(tmp_path)
    GuidelineStore(backend, FakeFiles(backend)).save("procedure", {"schemaVersion": 1, "steps": [{"key": "choose"}, {"key": "publish"}]}, actor="test", reason="test",
                                                       expected_current_version_id="none")
    recorder = FieldRecorder(backend)
    found = GuidelineStore(recorder).read("procedure")   # the real download: a slot, then the file
    assert found is not None
    return recorder.fields


def test_reading_a_saved_site_document_asks_for_three_fields(tmp_path):
    assert site_document_reads(tmp_path) == {("Query", "itemBySlug"), ("Query", "listModelAttachmentsByOwnerRoleAndSortKey"), ("Mutation", "createModelAttachmentDownload")}


@pytest.mark.parametrize("role", ["StoryWorkerRole", "ResearchWorkerRole"])
def test_the_story_worker_and_the_research_worker_can_read_the_sites_documents(tmp_path, role):
    grants = grants_of(role)
    missing = [(kind, field) for kind, field in site_document_reads(tmp_path) if not can(grants, "*", kind, field)]
    assert not missing, missing


@pytest.mark.parametrize("api", SITE_APIS)
def test_the_router_can_read_the_documents_of_every_site(tmp_path, api):
    grants = grants_of("RouterRole")
    missing = [(kind, field) for kind, field in site_document_reads(tmp_path) if not can(grants, f"${{{api}ApiId}}", kind, field)]
    assert not missing, missing


def test_the_research_workers_checklist_sync_has_no_quiet_path(monkeypatch):
    from papyrus_content import assignments_workflow, story_checklist

    def refused(*_args, **_options):
        raise story_checklist.ChecklistError("The site's procedure could not be read.")

    monkeypatch.setattr(story_checklist, "sync_checklist", refused)
    with pytest.raises(story_checklist.ChecklistError, match="could not be read"):
        assignments_workflow._sync_checklist_of_assignment(object(), {"itemLineageId": "story-1"})
