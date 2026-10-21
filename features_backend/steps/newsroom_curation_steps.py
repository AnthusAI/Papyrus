"""Account-scoped curation through the Papyrus curation host, in embedded and remote modes.

Every scenario composes the real Papyrus host and BFF over Cyclotron's publication
lab and priming service. Only the source transformer and classifier model are
offline fixtures. Cyclotron is optional, so its modules load inside the steps.
"""
from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import httpx
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

PUBLICATION_ID = "demo-publication"
ACCOUNT_ID = "account-a"
PERSON_ID = "person-a"
BINDING_REVISION = "binding-1"
PRIMING_LIST_ID = "examples"
PRIMING_CLASSIFIER_REFERENCES = ({"id": "editor", "revision": 1},)
PRIMING_ITEM_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}, "text": {"type": "string", "minLength": 1}},
                       "required": ["title", "text"], "additionalProperties": False}
TRANSFORMED_SOURCE_EXAMPLE = {"id": "synthetic-paper", "occurred_at": "2026-10-14",
                              "values": {"title": "Synthetic paper", "text": "Synthetic research content"},
                              "provenance": {"source_url": "https://example.invalid/paper"}}
SOURCE_URL = "https://example.invalid/paper"
GRANTED_PUBLICATION_CAPABILITIES = ("read", "decide", "review", "steer")
SCOPE_HEADERS = {"x-cyclotron-account": ACCOUNT_ID, "x-papyrus-publication": PUBLICATION_ID,
                 "x-papyrus-binding": BINDING_REVISION}


@dataclass
class CentralAccountState:
    """What the account service currently says about the original session."""
    selection: object
    publication_access_allowed: bool = True
    access_resolution_started: asyncio.Event | None = None
    protected_engine_reads: list = field(default_factory=list)


class OfflineSourceTransformer:
    """Source transformer that turns a bare URL into one candidate example."""
    def __init__(self):
        self.received_inputs = []

    def handle(self, request):
        if request.method == "POST":
            import json
            self.received_inputs.append(json.loads(request.content)["inputs"])
            return httpx.Response(200, json={"job_id": "job", "status": "running"})
        return httpx.Response(200, json={"job_id": "job", "status": "complete", "candidate": TRANSFORMED_SOURCE_EXAMPLE})


class CurationWorkspace:
    """One publication workspace whose host is composed fresh inside each event loop."""
    def __init__(self, behave_context, execution_mode):
        from decision_flywheel import Cyclotron
        from decision_flywheel.priming import HTTPTransformer, PrimingService
        from decision_flywheel.publication_lab import PublicationActor, PublicationBinding, PublicationLab
        from decision_flywheel.publication_lab_test import DEFINITION, OfflineModel
        from decision_flywheel.web_store import WebStore
        from papyrus_content.publication_bff import PublicationSelection

        self.execution_mode = execution_mode
        temporary_directory = tempfile.TemporaryDirectory()
        behave_context.add_cleanup(temporary_directory.cleanup)
        workspace_root = Path(temporary_directory.name)
        resources = contextlib.ExitStack()
        behave_context.add_cleanup(resources.close)

        self.classifier_model = OfflineModel()
        self.engine = resources.enter_context(Cyclotron.open(workspace_root / "engine", DEFINITION, self.classifier_model))
        self.publication_lab = PublicationLab(self.engine, account_id=ACCOUNT_ID, bindings=(PublicationBinding(PUBLICATION_ID, outputs=("intel",), revision=BINDING_REVISION),))
        self.publication_actor = PublicationActor(ACCOUNT_ID, PERSON_ID, frozenset(
            (PUBLICATION_ID, capability) for capability in GRANTED_PUBLICATION_CAPABILITIES))
        self.original_selection = PublicationSelection(ACCOUNT_ID, PERSON_ID, PUBLICATION_ID, BINDING_REVISION)
        self.central_account = CentralAccountState(self.original_selection)

        self.priming_store = WebStore(workspace_root / "priming")
        self.priming_store.save_item_list(PRIMING_LIST_ID, "Examples")
        self.priming_store.save_classifier("editor", "editor", {
            "question": "Publish?", "classes": [{"label": "publish"}, {"label": "not publish"}],
            "item_schema": PRIMING_ITEM_SCHEMA})
        self.source_transformer = OfflineSourceTransformer()
        transformer_client = resources.enter_context(httpx.Client(transport=httpx.MockTransport(self.source_transformer.handle)))
        self.priming_service = PrimingService(self.priming_store, transformers=[HTTPTransformer(
            "papyrus", "Papyrus", "https://transformer.invalid", ({"name": "url", "label": "Source URL", "required": True},))],
            client=transformer_client)

    def publication_bff(self):
        from decision_flywheel.publication_lab import PublicationAccess
        from papyrus_content.publication_bff import PublicationBFF

        async def resolve_publication_access(_connection, _publication, _capability):
            if self.central_account.access_resolution_started is not None:
                self.central_account.access_resolution_started.set()
                await asyncio.sleep(0)
            if not self.central_account.publication_access_allowed:
                return None
            return PublicationAccess(self.publication_lab, self.publication_actor)

        return PublicationBFF(resolve_selection=lambda _connection: self.central_account.selection,
                              resolve_access=resolve_publication_access)

    async def authorize_original_session(self, _capability):
        from decision_flywheel.publication_lab import PublicationError
        if not self.central_account.publication_access_allowed:
            raise PublicationError("explicit publication access refused", 403)
        return self.central_account.selection

    def embedded_curation_context(self):
        from papyrus_content.curation_host import (CurationContext, EmbeddedPublicationTransport,
                                                   GuardedPrimingService)
        return CurationContext(self.original_selection, "embedded", self.authorize_original_session,
                               EmbeddedPublicationTransport(self.publication_bff(), None),
                               GuardedPrimingService(self.priming_service, self.engine.execution),
                               PRIMING_LIST_ID, PRIMING_CLASSIFIER_REFERENCES,
                               capabilities=GRANTED_PUBLICATION_CAPABILITIES)

    @contextlib.asynccontextmanager
    async def curation_host_client(self):
        from decision_flywheel.publication_lab import HTTPPublicationClient, create_publication_host
        from papyrus_content.curation_host import (CurationContext, RemotePrimingTransport,
                                                   RemotePublicationTransport, create_curation_host)

        async with contextlib.AsyncExitStack() as clients:
            def offline_client(app, base_url):
                return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)

            if self.execution_mode == "embedded":
                context = self.embedded_curation_context()
            else:
                central_publication_host = await clients.enter_async_context(
                    offline_client(create_publication_host(self.publication_bff()), "http://lab.offline"))
                central_priming_host = await clients.enter_async_context(
                    offline_client(create_curation_host(lambda _request: self.embedded_curation_context()), "http://lab.offline"))
                context = CurationContext(self.original_selection, "remote", self.authorize_original_session,
                                          RemotePublicationTransport(HTTPPublicationClient(central_publication_host, account_id=ACCOUNT_ID)),
                                          RemotePrimingTransport(central_priming_host, self.original_selection),
                                          PRIMING_LIST_ID, PRIMING_CLASSIFIER_REFERENCES,
                                          capabilities=GRANTED_PUBLICATION_CAPABILITIES)
            yield await clients.enter_async_context(
                offline_client(create_curation_host(lambda _request: context), "http://papyrus.offline"))


async def priming_graphql(curation_client, query, variables):
    response = await curation_client.post("/api/newsroom/curation/priming", headers=SCOPE_HEADERS,
                                          json={"query": query, "variables": variables})
    assert response.status_code == 200, response.text
    return response.json()


async def priming_command(curation_client, action, payload):
    return await priming_graphql(curation_client,
                                 "mutation($action:String!,$payload:JSON!){primingCommand(action:$action,payload:$payload)}",
                                 {"action": action, "payload": payload})


async def preview_example_from_source_url(curation_client, draft_identifier):
    started = await priming_command(curation_client, "transform", {
        "identifier": draft_identifier, "list_id": PRIMING_LIST_ID, "refs": list(PRIMING_CLASSIFIER_REFERENCES),
        "transformer_id": "papyrus", "inputs": {"url": SOURCE_URL}})
    assert not started.get("errors"), started
    polled = await priming_command(curation_client, "poll", {"identifier": draft_identifier})
    assert not polled.get("errors"), polled
    return polled["data"]["primingCommand"]


@given("an authorized publication workspace using {execution_mode} execution")
def step_authorized_publication_workspace(context, execution_mode):
    context.curation_workspace = CurationWorkspace(context, execution_mode)


@when("the editor opens References")
def step_editor_opens_references(context):
    async def open_references():
        if getattr(context, "unconfigured_curation_host", None) is not None:
            curation_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=context.unconfigured_curation_host),
                                                base_url="http://papyrus.offline")
            async with curation_client:
                return await curation_client.get("/api/newsroom/curation/context")
        async with context.curation_workspace.curation_host_client() as curation_client:
            return await curation_client.get("/api/newsroom/curation/context")
    context.references_context_response = asyncio.run(open_references())


@then("shared monitoring, human review and authorized proposal controls are available")
def step_shared_controls_available(context):
    workspace = context.curation_workspace
    assert context.references_context_response.status_code == 200, context.references_context_response.text
    references_context = context.references_context_response.json()
    assert references_context["mode"] == workspace.execution_mode
    assert references_context["scope"] == {"accountId": ACCOUNT_ID, "publicationId": PUBLICATION_ID,
                                           "bindingRevision": BINDING_REVISION}
    assert {"read", "review", "steer"} <= set(references_context["capabilities"])

    async def read_monitoring():
        async with workspace.curation_host_client() as curation_client:
            return [await curation_client.post("/api/newsroom/curation/publication", headers=SCOPE_HEADERS,
                                               json={"operation": operation, "payload": {}})
                    for operation in ("status", "history")]
    for monitoring_response in asyncio.run(read_monitoring()):
        assert monitoring_response.status_code == 200, monitoring_response.text
        assert monitoring_response.json()["accountId"] == ACCOUNT_ID


@then("optional example priming accepts a source URL without manual source fields")
def step_priming_accepts_source_url(context):
    workspace = context.curation_workspace

    async def contract_and_preview():
        async with workspace.curation_host_client() as curation_client:
            contract = await priming_graphql(curation_client,
                                             "query($list:ID!,$refs:JSON!){primingContract(listId:$list,classifiers:$refs)}",
                                             {"list": PRIMING_LIST_ID, "refs": list(PRIMING_CLASSIFIER_REFERENCES)})
            return contract, await preview_example_from_source_url(curation_client, "url-only-preview")
    contract, preview = asyncio.run(contract_and_preview())
    assert [source_field["name"] for transformer in contract["data"]["primingContract"]["transformers"]
            for source_field in transformer["fields"]] == ["url"]
    assert workspace.source_transformer.received_inputs == [{"url": SOURCE_URL}]
    assert preview["status"] == "preview"
    assert workspace.priming_store.list_items(PRIMING_LIST_ID) == []
    context.example_preview = preview


@then("a label must be chosen before accepting the example")
def step_label_required_before_acceptance(context):
    workspace = context.curation_workspace

    async def accept_without_label():
        async with workspace.curation_host_client() as curation_client:
            return await priming_command(curation_client, "accept", {
                "identifier": "url-only-preview", "version": context.example_preview["version"], "labels": [{}]})
    refused = asyncio.run(accept_without_label())
    assert refused.get("errors"), refused
    assert workspace.priming_store.list_items(PRIMING_LIST_ID) == []


@then("a classification explanation is optional")
def step_classification_explanation_optional(context):
    workspace = context.curation_workspace

    async def accept_label_without_explanation():
        async with workspace.curation_host_client() as curation_client:
            return await priming_command(curation_client, "accept", {
                "identifier": "url-only-preview", "version": context.example_preview["version"],
                "labels": [{"editor": {"label": "publish"}}]})
    accepted = asyncio.run(accept_label_without_explanation())
    assert not accepted.get("errors"), accepted
    assert accepted["data"]["primingCommand"]["status"] == "accepted"
    assert [item["id"] for item in workspace.priming_store.list_items(PRIMING_LIST_ID)] == [TRANSFORMED_SOURCE_EXAMPLE["id"]]


@given("a request pinned to a verified person, account, publication and binding")
def step_request_pinned_to_verified_scope(context):
    context.curation_workspace = CurationWorkspace(context, "embedded")
    context.scope_change_outcomes = {}


@when("the original session loses access or changes scope before ownership")
def step_session_changes_while_request_waits(context):
    from decision_flywheel.publication_lab_test import ITEM

    workspace = context.curation_workspace
    scope_changes = {
        "access revoked": lambda account: setattr(account, "publication_access_allowed", False),
        "account changed": lambda account: setattr(account, "selection", replace(account.selection, account_id="account-b")),
        "person changed": lambda account: setattr(account, "selection", replace(account.selection, person_id="person-b")),
        "binding changed": lambda account: setattr(account, "selection", replace(account.selection, binding_revision="binding-2")),
    }
    for engine_read_name in ("decision", "decision_log", "status"):
        original_engine_read = getattr(workspace.engine, engine_read_name)

        def recorded_engine_read(*arguments, _name=engine_read_name, _original=original_engine_read, **keywords):
            workspace.central_account.protected_engine_reads.append(_name)
            return _original(*arguments, **keywords)
        setattr(workspace.engine, engine_read_name, recorded_engine_read)

    async def decide_while_scope_changes(apply_scope_change):
        workspace.central_account = CentralAccountState(workspace.original_selection,
                                                        access_resolution_started=asyncio.Event())
        async with workspace.curation_host_client() as curation_client:
            async with workspace.engine.execution():
                waiting_request = asyncio.create_task(curation_client.post(
                    "/api/newsroom/curation/publication", headers=SCOPE_HEADERS,
                    json={"operation": "decide", "payload": {"bindingRevision": BINDING_REVISION, "item": ITEM}}))
                await workspace.central_account.access_resolution_started.wait()
                apply_scope_change(workspace.central_account)
            return await waiting_request, list(workspace.central_account.protected_engine_reads)

    for scope_change_name, apply_scope_change in scope_changes.items():
        context.scope_change_outcomes[scope_change_name] = asyncio.run(decide_while_scope_changes(apply_scope_change))


@then("the operation is refused before protected reads or writes")
def step_operation_refused_before_protected_access(context):
    workspace = context.curation_workspace
    for scope_change_name, (response, protected_engine_reads) in context.scope_change_outcomes.items():
        expected_status = 403 if scope_change_name == "access revoked" else 409
        assert response.status_code == expected_status, (scope_change_name, response.status_code, response.text)
        assert protected_engine_reads == [], (scope_change_name, protected_engine_reads)
    assert workspace.engine.labels() == [] and workspace.classifier_model.calls == 0


@then("the UI discards the old snapshot and draft state")
def step_refusal_gives_ui_nothing_stale_to_keep(context):
    for scope_change_name, (response, _protected_engine_reads) in context.scope_change_outcomes.items():
        refusal = response.json()
        assert set(refusal) == {"error", "code"}, (scope_change_name, refusal)
        if scope_change_name != "access revoked":
            assert refusal["code"] == "account_changed", (scope_change_name, refusal)


@given("no curation host has been configured")
def step_no_curation_host_configured(context):
    from decision_flywheel import Cyclotron
    from papyrus_content.curation_host import create_curation_host

    context.opened_curation_engines = []
    original_open = Cyclotron.open

    def recorded_open(*arguments, **keywords):
        context.opened_curation_engines.append(arguments)
        return original_open(*arguments, **keywords)
    Cyclotron.open = recorded_open
    context.add_cleanup(setattr, Cyclotron, "open", original_open)
    context.unconfigured_curation_host = create_curation_host(lambda _request: None)


@then("the existing reference workflows remain available")
def step_existing_reference_workflows_available(context):
    module_check = subprocess.run(
        [sys.executable, "-c",
         "import sys; import papyrus_newsroom.reference_curation_signals; "
         "sys.exit(any(name.startswith(('papyrus_content.curation_host', 'decision_flywheel')) for name in sys.modules))"],
        cwd=REPO_ROOT, env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": ""}, capture_output=True, text=True)
    assert module_check.returncode == 0, module_check.stderr


@then("no curation backend is activated automatically")
def step_no_curation_backend_activated(context):
    assert context.references_context_response.status_code == 401, context.references_context_response.text
    assert context.opened_curation_engines == []


@given("a central curation peer for the publication")
def step_central_curation_peer(context):
    context.curation_workspace = CurationWorkspace(context, "embedded")


async def run_routes_harness_against_peer(workspace, role):
    """Serve the real curation host on loopback and drive the Next routes against it."""
    import json
    import socket

    import uvicorn
    from papyrus_content.curation_host import create_curation_host

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    peer = create_curation_host(lambda _request: workspace.embedded_curation_context())
    server = uvicorn.Server(uvicorn.Config(peer, host="127.0.0.1", port=port, log_level="error"))
    serving = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        process = await asyncio.create_subprocess_exec(
            "npx", "tsx", "scripts/curation-routes-bdd-harness.ts", str(port), role,
            cwd=REPO_ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        assert process.returncode == 0, stderr.decode()
        return json.loads(stdout)
    finally:
        server.should_exit = True
        await serving


@when("a member and a viewer of the account open References through the Papyrus routes")
def step_member_and_viewer_open_references(context):
    workspace = context.curation_workspace
    context.route_outcomes = {}
    for role in ("member", "viewer"):
        context.route_outcomes[role] = asyncio.run(run_routes_harness_against_peer(workspace, role))
        if role == "member":
            context.inputs_after_member = list(workspace.source_transformer.received_inputs)


@then("the routes pass monitoring and a source URL preview to the peer for the member")
def step_routes_pass_member_requests(context):
    member = context.route_outcomes["member"]
    assert member["context"]["status"] == 200, member["context"]
    assert member["context"]["body"]["scope"] == {"accountId": ACCOUNT_ID, "publicationId": PUBLICATION_ID,
                                                  "bindingRevision": BINDING_REVISION}
    assert set(member["context"]["body"]["capabilities"]) == {"read", "review", "decide"}, "capped at the member role"
    assert member["status"]["status"] == 200 and member["status"]["body"]["accountId"] == ACCOUNT_ID
    assert member["contract"]["status"] == 200
    assert member["importAttempt"]["status"] == 200, member["importAttempt"]
    assert context.inputs_after_member == [{"url": SOURCE_URL}]


@then("the viewer can read monitoring but cannot start an import")
def step_viewer_reads_but_cannot_import(context):
    viewer = context.route_outcomes["viewer"]
    assert viewer["context"]["body"]["capabilities"] == ["read"]
    assert viewer["status"]["status"] == 200 and viewer["contract"]["status"] == 200
    assert viewer["importAttempt"]["status"] == 403, viewer["importAttempt"]
    assert viewer["importAttempt"]["body"]["code"] == "capability_refused"


@then("the peer never receives the viewer's import")
def step_peer_never_receives_viewer_import(context):
    assert context.curation_workspace.source_transformer.received_inputs == context.inputs_after_member
