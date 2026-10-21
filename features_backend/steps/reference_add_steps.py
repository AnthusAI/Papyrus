"""Adding a reference by importing: leaving a preview saves nothing, and a web page keeps its details.

These scenarios drive Papyrus's real curation host and its real web preparation
path (`PapyrusPrimingCuration`) through the same routes the References view uses.
Only the network, the model and the page extraction are the curation-review
harness's offline fixtures (`scripts/curation-review/fixtures.py`).
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

import httpx
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "scripts" / "curation-review"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

WEB_ADDRESS = "https://example.invalid/web"
IN_PROGRESS = ("queued", "running", "starting")


class ImportSession:
    """One editor's References session against the harness's curation host."""
    def __init__(self, behave_context, execution_mode):
        from fixtures import ACCOUNTS, ReviewAuthority

        directory = tempfile.TemporaryDirectory()
        behave_context.add_cleanup(directory.cleanup)
        self.authority = ReviewAuthority(directory.name)
        self.authority.mode = execution_mode
        behave_context.add_cleanup(self.authority.close)
        self.account = ACCOUNTS[0]
        self.draft_id = str(uuid.uuid4())
        self.draft = None

    def run(self, steps):
        """Run `steps(command, bootstrap)` against a fresh host client."""
        from papyrus_content.curation_host import create_curation_host

        async def session():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_curation_host(self.authority.context)),
                                         base_url="http://papyrus.offline") as client:
                bootstrap = (await client.get("/api/newsroom/curation/context")).json()
                scope = bootstrap["scope"]
                headers = {"X-Cyclotron-Account": scope["accountId"], "X-Papyrus-Publication": scope["publicationId"],
                           "X-Papyrus-Binding": scope["bindingRevision"]}

                async def command(action, payload):
                    response = await client.post("/api/newsroom/curation/priming", headers=headers, json={
                        "query": "mutation($action:String!,$payload:JSON!){primingCommand(action:$action,payload:$payload)}",
                        "variables": {"action": action, "payload": payload}})
                    assert response.status_code == 200, response.text
                    return response.json()
                return await steps(command, bootstrap)
        return asyncio.run(session())

    def saved_references(self):
        return self.authority.proof()[self.account]["acceptedExamples"]


@given("a References workspace that prepares web pages offline using {execution_mode} execution")
def step_workspace_prepares_web_pages(context, execution_mode):
    context.import_session = ImportSession(context, execution_mode)


@when("the editor previews a reference from a web address")
def step_editor_previews_web_address(context):
    session = context.import_session

    async def preview(command, bootstrap):
        started = await command("transform", {
            "identifier": session.draft_id, "list_id": bootstrap["priming"]["listId"], "refs": bootstrap["priming"]["classifiers"],
            "transformer_id": "papyrus", "inputs": {"url": WEB_ADDRESS}})
        assert not started.get("errors"), started
        draft = started["data"]["primingCommand"]
        for _ in range(100):
            if draft["status"] not in IN_PROGRESS:
                break
            await asyncio.sleep(0.02)
            draft = (await command("poll", {"identifier": session.draft_id}))["data"]["primingCommand"]
        return draft
    session.draft = session.run(preview)
    assert session.draft["status"] == "preview", session.draft


@when("the editor cancels the import")
def step_editor_cancels_import(context):
    session = context.import_session

    async def cancel(command, _bootstrap):
        return await command("cancel", {"identifier": session.draft_id})
    result = session.run(cancel)
    assert not result.get("errors"), result
    assert result["data"]["primingCommand"]["status"] == "cancelled", result


@when("the editor rejects the preview and asks for a revision")
def step_editor_rejects_preview(context):
    session = context.import_session

    async def reject(command, _bootstrap):
        return await command("feedback", {"identifier": session.draft_id, "version": session.draft["version"],
                                          "request_id": str(uuid.uuid4()), "reason": "The summary is wrong.", "inputs": {}})
    result = session.run(reject)
    assert not result.get("errors"), result
    assert result["data"]["primingCommand"]["status"] != "accepted", result


@then("no reference has been added")
def step_no_reference_added(context):
    assert context.import_session.saved_references() == 0


@then("a draft that was left cannot be saved afterwards")
def step_left_draft_cannot_be_saved(context):
    session = context.import_session

    async def try_to_save(command, _bootstrap):
        current = (await command("poll", {"identifier": session.draft_id}))["data"]["primingCommand"]
        return await command("accept", {"identifier": session.draft_id, "version": current["version"],
                                        "labels": [{"editorial": {"label": "publish"}}]})
    refused = session.run(try_to_save)
    assert refused.get("errors"), refused
    assert session.saved_references() == 0


@then("the preview lists the exact details used to make suggestions")
def step_preview_lists_exact_details(context):
    row = context.import_session.draft["rows"][0]
    details = row["model_representation"]["editorial"]
    assert details, row
    for field in ("title", "text", "abstract", "source_uri", "domain"):
        assert details[field] == row["item"]["values"][field], (field, details)
    assert details["source_uri"] == WEB_ADDRESS
    assert details["title"].strip() and details["abstract"].strip()


@then("the preview keeps where the page came from and how it was prepared")
def step_preview_keeps_provenance(context):
    provenance = context.import_session.draft["rows"][0]["item"]["provenance"]
    assert provenance["source_url"] == WEB_ADDRESS
    prepared = provenance["papyrus"]
    assert prepared["processing_path"] == "web"
    assert prepared["preparation"] == "existing_pipeline"
    assert prepared["reference_id"] and prepared["external_item_id"]
    assert prepared["artifact_roles"] == ["extracted_text_raw", "extracted_text"]
