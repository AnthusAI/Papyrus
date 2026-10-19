"""Credential-free behavior of the supported user-session intake boundary."""
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from papyrus_content.reference_intake import intake_references, IntakeError
from procedures.newsroom.tests.test_story_reporting import client_with_one_story, LINEAGE
from papyrus_content.story_reporting import link_reference_to_story, story_references

ENDPOINT = "https://publication.appsync-api.us-east-1.amazonaws.com/graphql"
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/publication-pool"
ENV = {"PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT, "PAPYRUS_USER_POOL_ISSUER": ISSUER, "PAPYRUS_TENANT_ID": ""}
IDENTITY = {"sub": "editor-sub", "issuer": ISSUER, "claims": {"sub": "editor-sub", "iss": ISSUER, "cognito:groups": ["editor"]}}


def payload(url="https://example.test/report#section", **changes):
    return {"publicationEndpoint": ENDPOINT, "corpusId": "corpus-one", "items": [{"source_uri": url, "item_id": "lead", "title": "Source", "media_type": "text/html", "ingestion_rationale": "Primary reporting source"}], **changes}


class IntakeClient:
    def __init__(self):
        self.story = client_with_one_story()
        self.story.tables["Reference"] = {}
        self.story.tables["KnowledgeCorpus"] = {"corpus-one": {"id": "corpus-one"}}
        self.tables = self.story.tables
        self.lock = threading.Lock()
        self.uploads = {}
        self.fail_upload = False

    def __getattr__(self, name):
        if name == "list_records":
            return lambda model: copy.deepcopy(list(self.tables.get(model, {}).values()))
        return getattr(self.story, name)

    def create_record(self, model, record):
        with self.lock:
            table = self.tables.setdefault(model, {})
            if record["id"] in table:
                raise RuntimeError("ConditionalCheckFailedException")
            table[record["id"]] = copy.deepcopy(record)

    def upload(self, client, attachment, body):
        if self.fail_upload:
            self.fail_upload = False
            raise RuntimeError("interrupted provenance upload")
        self.tables.setdefault("ModelAttachment", {})[attachment["id"]] = attachment
        self.uploads[attachment["id"]] = body


def submit(client, data=None, identity=None):
    with patch.dict("os.environ", ENV), patch("papyrus_content.reference_intake.upload_attachment_body", client.upload):
        return intake_references(client, payload() if data is None else data, IDENTITY if identity is None else identity)


def test_editor_intake_and_link_preserve_story():
    c = IntakeClient()
    previous = c.tables["Item"][LINEAGE]
    previous["versionState"] = "superseded"
    c.tables["Item"][f"{LINEAGE}-v2"] = {**previous, "id": f"{LINEAGE}-v2", "versionNumber": 2, "versionState": "current"}
    c.tables["Message"] = {"existing-note": {"id": "existing-note", "summary": "Prior reporting"}}
    before = copy.deepcopy(c.tables["Item"])
    prior_messages = copy.deepcopy(c.tables["Message"])
    result = submit(c)
    ref = c.tables["Reference"][result["references"][0]["id"]]
    assert ref["curationStatus"] == "pending"
    assert ref["versionCreatedBy"] == "user:editor-sub"
    provenance = json.loads(next(iter(c.uploads.values())))
    assert provenance["actorSub"] == "editor-sub"
    assert provenance["sourceUri"] == "https://example.test/report"
    assert provenance["rationale"] == "Primary reporting source"
    link_reference_to_story(c, LINEAGE, ref["id"], role="consulted", actor="ChatGPT")
    assert story_references(c, LINEAGE)[0]["role"] == "consulted"
    assert c.tables["Item"] == before
    assert c.tables["Message"] == prior_messages
    assert not c.tables.get("PublishedItem")


@pytest.mark.parametrize("violation", ["no identity", "a reader role", "another issuer", "another publication", "another corpus", "a caller selected tenant"])
def test_rejects_before_writes(violation):
    c = IntakeClient(); identity = copy.deepcopy(IDENTITY); data = payload()
    if violation == "no identity": identity = {}
    if violation == "a reader role": identity["claims"]["cognito:groups"] = ["reader"]
    if violation == "another issuer": identity["claims"]["iss"] = "https://other/pool"
    if violation == "another publication": data["publicationEndpoint"] = "https://other/graphql"
    if violation == "another corpus": data["corpusId"] = "foreign-corpus"
    if violation == "a caller selected tenant": data["tenantId"] = "foreign"
    before = copy.deepcopy(c.tables)
    with pytest.raises(IntakeError): submit(c, data, identity)
    assert c.tables == before
    assert not c.uploads


def test_repeat_and_parallel_intake_preserve_first_actor_and_payload():
    c = IntakeClient(); first = submit(c)
    original = copy.deepcopy(c.tables)
    data = payload("HTTPS://EXAMPLE.TEST:443/report#another")
    data["items"][0].update(title="Overwrite", ingestion_rationale="Overwrite")
    identity = copy.deepcopy(IDENTITY); identity["sub"] = identity["claims"]["sub"] = "another-editor"
    assert submit(c, data, identity)["references"] == first["references"]
    assert c.tables == original
    # Patch process globals once: worker-local patch contexts can restore another
    # worker's environment/helper while its intake is still executing.
    with patch.dict("os.environ", ENV), patch("papyrus_content.reference_intake.upload_attachment_body", c.upload):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: intake_references(c, payload(), IDENTITY), range(8)))
    assert all(r["references"] == first["references"] for r in results)
    assert len(c.tables["Reference"]) == len(c.tables["KnowledgeImportRun"]) == len(c.uploads) == 1


def test_partial_intake_is_recoverable_without_overwrite():
    c = IntakeClient(); c.fail_upload = True
    with pytest.raises(RuntimeError, match="interrupted"): submit(c)
    before = copy.deepcopy(c.tables["Reference"])
    result = submit(c)
    assert result["ok"]
    assert c.tables["Reference"] == before
    assert len(c.uploads) == 1


def test_batch_validation_is_complete_before_writes_and_no_status_or_actor_override():
    c = IntakeClient(); data = payload(); data["items"].append({"source_uri": "file:///secret", "title": "bad", "ingestion_rationale": "bad"})
    with pytest.raises(IntakeError): submit(c, data)
    assert not c.tables["Reference"]
    for key, value in [("status", "accepted"), ("actorSub", "human"), ("actorLabel", "Ryan")]:
        with pytest.raises(IntakeError): submit(c, payload(**{key: value}))


def test_legacy_reference_deduplicated_without_recuration():
    c = IntakeClient()
    legacy = {"id": "legacy-v3", "lineageId": "legacy", "versionNumber": 3, "versionState": "current", "sourceUri": "https://EXAMPLE.TEST:443/report#old", "corpusId": "corpus-one", "curationStatus": "accepted"}
    c.tables["Reference"][legacy["id"]] = legacy
    result = submit(c)
    assert result["references"][0]["id"] == "legacy-v3"
    assert c.tables["Reference"] == {legacy["id"]: legacy}
    assert not c.uploads


def test_simultaneous_first_intake_uses_conditional_create():
    c = IntakeClient()
    gate = threading.Barrier(4)
    normal_list = c.list_records
    def synchronized_list(model):
        result = normal_list(model)
        gate.wait(timeout=5)
        return result
    c.list_records = synchronized_list
    with patch.dict("os.environ", ENV), patch("papyrus_content.reference_intake.upload_attachment_body", c.upload):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: intake_references(c, payload(), IDENTITY), range(4)))
    assert len({r["references"][0]["id"] for r in results}) == 1
    assert len(c.tables["Reference"]) == len(c.tables["KnowledgeImportRun"]) == len(c.uploads) == 1


def test_handler_uses_validated_identity_and_returns_denials():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("intake_actions", Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py")
    handler = importlib.util.module_from_spec(spec); spec.loader.exec_module(handler)
    c = IntakeClient()
    with patch.dict("os.environ", ENV), patch.object(handler, "create_authoring_client", return_value=(c, {})), patch("papyrus_content.reference_intake.upload_attachment_body", c.upload):
        e = {"fieldName": "intakePendingReferences", "arguments": {"input": json.dumps(payload())}, "identity": IDENTITY}
        assert handler.handler(e, None)["ok"]
        before = copy.deepcopy(c.tables)
        e["identity"] = {}
        assert handler.handler(e, None)["errors"][0]["code"] == "intake-rejected"
        assert c.tables == before


def test_cli_routes_user_catalog_to_scoped_action_without_generic_writes(tmp_path):
    from papyrus_content.cli import references_register_catalog
    catalog = tmp_path / "catalog.json"; catalog.write_text(json.dumps({"items": payload()["items"]}))
    steering = {"corpora": [{"key": "one", "name": "One", "role": "source"}]}
    class ActionClient:
        endpoint = ENDPOINT
        def graphql(self, query, variables):
            assert "intakePendingReferences" in query
            data = json.loads(variables["input"])
            assert data["publicationEndpoint"] == ENDPOINT
            assert set(data) == {"publicationEndpoint", "corpusId", "items"}
            self.calls.append(data)
            return {"intakePendingReferences": json.dumps({"ok": True, "references": [{"id": "actual-record-id"}]})}
        def __init__(self): self.calls = []
    c = ActionClient()
    with patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "user"}), patch("papyrus_content.cli.create_authoring_client", return_value=(c, {})), patch("papyrus_content.reference_intake_cli.require_steering_config", return_value=steering):
        flags = ["--config", "ignored", "--corpus-key", "one", "--catalog", str(catalog), "--status", "pending"]
        references_register_catalog(flags + ["--dry-run"])
        assert not c.calls
        references_register_catalog(flags)
        assert len(c.calls) == 1
        with pytest.raises(ValueError, match="pending only"):
            references_register_catalog(flags[:-1] + ["accepted"])


def test_schema_preserves_read_only_models_and_scoped_group_action():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    for file in ("schema.ts", "resource.ts"):
        source = (root / "amplify/data" / file).read_text()
        action = source.split("  intakePendingReferences: a", 1)[1].split("  saveItemDraft:", 1)[0]
        assert "allow.groups(contentWriteGroups)" in action
        assert "identityPool" not in action
        for model in ("KnowledgeCorpus", "KnowledgeImportRun", "Reference"):
            block = source.split(f"  {model}:", 1)[1].split(".authorization", 1)[1].split("\n    ]),", 1)[0]
            assert '.to(["read"])' in block
    roles = (root / "amplify/functions/model-attachment-upload/handler.ts").read_text().split("ALLOWED_ROLES", 1)[1].split("]);", 1)[0]
    assert '"metadata"' in roles


def test_intake_provenance_does_not_collide_with_normal_reference_metadata():
    from papyrus_content.model_attachments import build_json_model_payload_attachment
    c = IntakeClient()
    ref_id = submit(c)["references"][0]["id"]
    provenance = next(iter(c.tables["ModelAttachment"].values()))
    normal = build_json_model_payload_attachment({
        "ownerKind": "reference", "ownerId": ref_id, "role": "metadata", "sortKey": "metadata",
        "content": {"title": "Enrichment"}, "now": "2026-10-19T00:00:00Z",
    })["attachment"]
    assert provenance["id"] != normal["id"]
    assert provenance["storagePath"] != normal["storagePath"]
    assert provenance["filename"] == "editorial-intake.json"


def test_real_handler_executes_upload_protocol_without_external_credentials():
    import importlib.util
    import hashlib
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("intake_upload_actions", Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py")
    handler = importlib.util.module_from_spec(spec); spec.loader.exec_module(handler)
    c = IntakeClient()
    slots = []; completions = []; requests = []
    def slot(attachment):
        assert attachment["role"] == "metadata"
        assert attachment["filename"] == "editorial-intake.json"
        assert c.get_record("Reference", attachment["ownerId"]) is not None
        slots.append(copy.deepcopy(attachment))
        return {"uploadId": attachment["id"], "uploadUrl": "https://upload.example.test/slot", "requiredHeaders": {"content-type": "application/json"}, "storagePath": attachment["storagePath"], "method": "PUT"}
    def complete(upload_id, attachment):
        assert upload_id == slots[-1]["id"]
        assert hashlib.sha256(requests[-1].data).hexdigest() == attachment["sha256"]
        completions.append(upload_id)
        c.tables.setdefault("ModelAttachment", {})[attachment["id"]] = copy.deepcopy(attachment)
        return attachment
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def put(request):
        assert request.get_method() == "PUT"
        assert request.full_url == "https://upload.example.test/slot"
        requests.append(request)
        return Response()
    c.create_model_attachment_upload = slot
    c.complete_model_attachment_upload = complete
    e = {"fieldName": "intakePendingReferences", "arguments": {"input": json.dumps(payload())}, "identity": IDENTITY}
    # Only the managed API client and network boundary are faked. The actual
    # handler, intake service, attachment builder and upload/complete helper run.
    with patch.dict("os.environ", ENV), patch.object(handler, "create_authoring_client", return_value=(c, {})), patch("urllib.request.urlopen", put):
        first = handler.handler(e, None)
        assert first["ok"]
        second = handler.handler(e, None)
        assert second["references"] == first["references"]
    assert len(slots) == len(completions) == len(requests) == 1
    assert json.loads(requests[0].data)["actorSub"] == "editor-sub"
