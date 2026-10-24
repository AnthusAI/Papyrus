"""Cloud procedure runner, site procedure registration, and monitor-triggered procedure runs."""
import json
from pathlib import Path

import pytest

from papyrus_content import model_attachments, procedure_runner as pr, site_procedures as sp
from papyrus_content.monitoring_cloud import DynamoStore
from papyrus_content.monitoring_router import Router, RouterStore, run_router, validate_router_config

from test_monitoring_router import ENDPOINT, Delivery, FakeTable
from test_monitoring_ttab import NOW, collected_table, direct_router_config

PROCEDURE = """Procedure {
    input = {
        proceeding = field.string{required = true, description = "Proceeding number"},
        opinion_url = field.string{required = true},
        corpus = field.string{default = "knowledge-corpus-example"}
    },
    output = {
        title = field.string{required = true}
    },
    function(input)
        return {title = input.proceeding}
    end
}
"""
PROCEDURE_WITH_SKILL = PROCEDURE.replace("Procedure {", """analyst = Agent {
    provider = "openai",
    model = "gpt-6-luna",
    system_prompt = "Follow the skill.",
    skills = {".claude/skills/example-skill"},
    skills_mode = "full"
}

Procedure {""")
KEY_PARAMETER = "/amplify/shared/app123/OPENAI_API_KEY"
TRIGGER = {"procedureKey": "distinctive.ttab.ruling-analysis",
           "input": {"proceeding": "{sourceIdPrefix}", "opinion_url": "{documentUrl}"}}


# --- monitor triggers --------------------------------------------------------------------------------

class TriggerTable(FakeTable):
    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues, **_):
        item = self.items[(Key["pk"], Key["sk"])]
        for assignment in UpdateExpression.removeprefix("SET ").split(", "):
            name, value = assignment.split(" = ")
            item[ExpressionAttributeNames.get(name, name)] = ExpressionAttributeValues[value]


def triggered_table(**publication):
    table = TriggerTable()
    table.items.update(collected_table().items)
    distinctive = {"publicationId": "distinctive", "site": "distinctive-mark.com", "appsyncEndpoint": ENDPOINT,
                   "openaiKeyParameter": KEY_PARAMETER, "procedureTriggers": [TRIGGER], **publication}
    table.put_item(direct_router_config(publications=[distinctive]))
    return table


def route(table, delivery, started, now=NOW + 60):
    return run_router(RouterStore(table), "ttab", now=now, cyclotron=None, deliver=delivery,
                      appsync=lambda endpoint: object(), start_procedure=started.append,
                      context_receipt=lambda client, publication: {"contextHash": "h", "reason": None})


def test_triggers_need_a_key_parameter_and_only_known_placeholders():
    base = {"publicationId": "distinctive", "site": "d.example", "appsyncEndpoint": ENDPOINT, "procedureTriggers": [TRIGGER]}
    with pytest.raises(ValueError, match="openaiKeyParameter"):
        validate_router_config(direct_router_config(publications=[base]))
    bad = {**base, "openaiKeyParameter": KEY_PARAMETER,
           "procedureTriggers": [{"procedureKey": "k", "input": {"proceeding": "{secret}"}}]}
    with pytest.raises(ValueError, match="input proceeding"):
        validate_router_config(direct_router_config(publications=[bad]))
    good = validate_router_config(direct_router_config(publications=[{**base, "openaiKeyParameter": KEY_PARAMETER}]))
    assert good["publications"][0]["procedureTriggers"] == [TRIGGER]


def test_a_new_reference_starts_its_procedure_once_with_mapped_input():
    table, delivery, started = triggered_table(), Delivery(), []

    first = route(table, delivery, started)
    router = Router(RouterStore(table), validate_router_config(table.items[("MONITOR#ttab", "CONFIG#router")]),
                    monitor_id="ttab", now=NOW + 120, run_id="run-2", cyclotron=None, appsync=lambda e: object(),
                    start_procedure=started.append)
    disc = DynamoStore._clean(table.by_prefix("DISC#97752244-EXA_26#")[0])
    router.start_procedures(router.publications["distinctive"], disc, {"referenceId": "reference-again"})
    second = {"counts": router.counts}
    assert first["counts"]["proceduresStarted"] == 2 and second["counts"]["proceduresStarted"] == 0
    assert len(started) == 2
    wemby = next(request for request in started if request["trigger"]["sourceId"] == "97752244-EXA_26")
    assert wemby["input"] == {"proceeding": "97752244", "opinion_url":
                              "https://ttab-reading-room.uspto.gov/ttab-document//legal-proceeding/97752244/decision/EXA_26.pdf"}
    assert wemby["openaiKeyParameter"] == KEY_PARAMETER and wemby["procedureKey"] == TRIGGER["procedureKey"]
    row = table.by_prefix("TRIGGER#distinctive#distinctive.ttab.ruling-analysis#97752244-EXA_26")[0]
    assert row["status"] == "started" and wemby["trigger"]["sk"] == row["sk"]


def test_a_reused_reference_does_not_start_a_procedure():
    table, started = triggered_table(), []

    class ReusingDelivery(Delivery):
        def __call__(self, *args):
            return {**super().__call__(*args), "referenceReused": True}

    result = route(table, ReusingDelivery(), started)

    assert started == [] and result["counts"]["procedureNotTriggered"] == 2 and result["counts"]["delivered"] == 2
    assert {row["status"] for row in table.by_prefix("TRIGGER#")} == {"notTriggered"}


def test_a_failed_start_is_recorded_and_never_fails_the_delivery():
    table, delivery = triggered_table(), Delivery()

    def unavailable(request):
        raise RuntimeError("lambda throttled")

    result = run_router(RouterStore(table), "ttab", now=NOW + 60, cyclotron=None, deliver=delivery,
                        appsync=lambda endpoint: object(), start_procedure=unavailable,
                        context_receipt=lambda client, publication: {"contextHash": "h", "reason": None})

    assert result["counts"]["delivered"] == 2 and result["counts"]["procedureStartFailed"] == 2
    assert result["counts"]["routed"] == 2
    assert {row["status"] for row in table.by_prefix("TRIGGER#")} == {"startFailed"}


# --- the runner --------------------------------------------------------------------------------------

class NewsroomClient:
    def __init__(self, *, status="published", source="attachment://code.tac", skills=()):
        self.version = {"id": "version-1", "status": status, "isCurrent": True, "versionNumber": 1, "tactusSource": source}
        self.attachments = [{"id": "a-code", "role": "code", "sortKey": "code", "status": "active", "body": PROCEDURE.encode()}]
        self.attachments = [{"id": f"a-{n}", "role": "code", "sortKey": f"skill:{path}", "status": "active", "body": body}
                            for n, (path, body) in enumerate(skills)] + self.attachments
        self.started, self.updates = [], []

    def graphql(self, query, variables):
        if "getNewsroomProcedureDefinition" in query:
            return {"getNewsroomProcedureDefinition": json.dumps(
                {"id": "procedure-1", "enabled": True, "currentVersionId": "version-1", "currentVersion": self.version})}
        if "startNewsroomProcedureRun" in query:
            self.started.append(variables)
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "runId": "run-1"})}
        if "updateProcedureRun" in query:
            self.updates.append(variables["input"])
            return {"updateProcedureRun": variables["input"]}
        raise AssertionError(query)

    def list_by_index(self, index, key, limit=100):
        assert index == "modelAttachmentsByOwnerRoleAndSortKey" and key == "version-1"
        return self.attachments


@pytest.fixture(autouse=True)
def attachment_bodies(monkeypatch):
    monkeypatch.setattr(model_attachments, "download_attachment_buffer", lambda client, entry, **_: entry["body"])


REQUEST = {"appsyncEndpoint": ENDPOINT, "procedureKey": "distinctive.ttab.ruling-analysis",
           "openaiKeyParameter": KEY_PARAMETER, "input": {"proceeding": "97752244", "opinion_url": "https://x/a.pdf"}}


def test_the_runner_materializes_skills_records_the_run_and_its_output(tmp_path):
    client = NewsroomClient(skills=[(".claude/skills/example-skill/SKILL.md", b"# Example")])
    seen = {}

    def execute(workdir, source_path, inputs, *, timeout_seconds, environment):
        seen.update(skill=(workdir / ".claude/skills/example-skill/SKILL.md").read_text(), source=source_path.read_text(),
                    inputs=inputs, timeout=timeout_seconds)
        return {"success": True, "output": {"title": "Wemby"}, "seconds": 42}

    result = pr.run_procedure_request(REQUEST, client=client, execute=execute, seconds_available=900,
                                      environment={}, workroot=tmp_path)

    assert result == {"runId": "run-1", "procedureKey": REQUEST["procedureKey"], "versionId": "version-1",
                      "runStatus": "completed", "seconds": 42, "error": None, "costUsd": None, "costRecorded": False,
                      "output": {"title": "Wemby"}}
    assert seen["skill"] == "# Example" and "Procedure {" in seen["source"] and seen["timeout"] == 840
    assert json.loads(client.started[0]["input"])["__papyrusExecutionMode"] == "external_cli"
    assert client.updates[0]["runStatus"] == "completed" and json.loads(client.updates[0]["output"]) == {"title": "Wemby"}
    assert "title: Wemby" in client.updates[0]["resultSummary"]
    assert list(tmp_path.iterdir()) == []


def run_with(request, outcome, *, client=None, seconds_available=900, tmp_path=None, **kwargs):
    client = client or NewsroomClient()
    seen = {}

    def execute(workdir, source_path, inputs, *, timeout_seconds, environment):
        seen["timeout"] = timeout_seconds
        return outcome

    result = pr.run_procedure_request({**REQUEST, **request}, client=client, execute=execute, seconds_available=seconds_available,
                                      environment={}, workroot=tmp_path, **kwargs)
    return result, client, seen


@pytest.mark.parametrize("requested, available, expected", [
    (None, 900, 840),        # no limit in the request: what the Lambda has left, less the recording margin (as before)
    (300, 900, 300),         # the automation's timeout is shorter
    (5000, 900, 840),        # asked for more than the Lambda has: capped at the Lambda's limit
    (840, 400, 340),         # the Lambda's own remaining time still wins
])
def test_the_automations_timeout_is_the_childs_deadline_capped_at_the_lambdas_limit(tmp_path, requested, available, expected):
    request = {} if requested is None else {"timeoutSeconds": requested}
    _, _, seen = run_with(request, {"success": True, "output": {}, "seconds": 1}, seconds_available=available, tmp_path=tmp_path)
    assert seen["timeout"] == expected


@pytest.mark.parametrize("bad", [0, -5, "300", True, 1.5])
def test_a_timeout_that_is_not_a_positive_whole_number_is_not_runnable(bad):
    with pytest.raises(pr.ProcedureNotRunnable, match="timeoutSeconds"):
        pr.validate_request({**REQUEST, "timeoutSeconds": bad})


CALLS = [{"agent": "analyst", "model": "gpt-6-luna", "provider": "openai", "promptTokens": 100_000, "completionTokens": 10_000, "cachedTokens": 0},
         {"agent": "analyst", "model": "gpt-6-luna", "provider": "openai", "promptTokens": 100_000, "completionTokens": 0, "cachedTokens": 50_000}]


def test_the_usage_and_an_estimated_cost_are_stored_on_the_procedure_run(tmp_path):
    result, client, _ = run_with({}, {"success": True, "output": {"title": "x"}, "seconds": 5, "usage": CALLS}, tmp_path=tmp_path)
    update = client.updates[0]
    assert update["costUsd"] == pytest.approx(0.015 + 0.0055) and result["costUsd"] == pytest.approx(0.0205) and result["costRecorded"] is True
    usage = json.loads(update["usage"])
    assert (usage["calls"], usage["promptTokens"], usage["completionTokens"], usage["complete"]) == (2, 200_000, 10_000, True)
    assert usage["models"] == {"gpt-6-luna": 2} and usage["perCall"] == CALLS


def test_a_failed_run_still_records_the_cost_of_the_calls_it_made(tmp_path):
    result, client, _ = run_with({}, {"success": False, "error": "boom", "usage": CALLS[:1]}, tmp_path=tmp_path)
    assert result["runStatus"] == "failed" and client.updates[0]["runStatus"] == "failed" and client.updates[0]["costUsd"] == pytest.approx(0.015)


def test_an_unpriced_model_is_recorded_as_usage_without_a_cost(tmp_path):
    odd = [{**CALLS[0], "model": "mystery-1"}]
    result, client, _ = run_with({}, {"success": True, "output": {}, "usage": odd}, tmp_path=tmp_path)
    usage = json.loads(client.updates[0]["usage"])
    assert client.updates[0]["costUsd"] is None and usage["complete"] is False and usage["unpricedModels"] == ["mystery-1"]
    assert result["costRecorded"] is True and result["costUsd"] is None


def test_a_run_with_no_model_call_sends_no_usage_fields(tmp_path):
    _, client, _ = run_with({}, {"success": True, "output": {}, "usage": []}, tmp_path=tmp_path)
    assert "usage" not in client.updates[0] and "costUsd" not in client.updates[0]


def test_a_backend_without_the_usage_fields_still_gets_the_outcome(tmp_path):
    class OldBackend(NewsroomClient):
        def graphql(self, query, variables):
            if "updateProcedureRun" in query and "usage" in variables["input"]:
                raise RuntimeError("Validation error: The variables input contains a field name 'usage' that is not defined")
            return super().graphql(query, variables)
    client = OldBackend()
    result, _, _ = run_with({}, {"success": True, "output": {"title": "x"}, "usage": CALLS}, client=client, tmp_path=tmp_path)
    assert result["runStatus"] == "completed" and result["costRecorded"] is False and result["costUsd"] == pytest.approx(0.0205)
    assert client.updates[0]["runStatus"] == "completed" and "usage" not in client.updates[0]


def test_a_failure_to_record_that_is_not_about_usage_still_raises(tmp_path):
    class Down(NewsroomClient):
        def graphql(self, query, variables):
            if "updateProcedureRun" in query:
                raise RuntimeError("AppSync is down")
            return super().graphql(query, variables)
    with pytest.raises(RuntimeError, match="down"):
        run_with({}, {"success": True, "output": {}}, client=Down(), tmp_path=tmp_path)


def test_the_trigger_row_names_its_run_while_it_runs_and_a_failure_to_say_so_does_not_stop_the_run(tmp_path):
    seen = []
    result, _, _ = run_with({}, {"success": True, "output": {}}, run_started=seen.append, tmp_path=tmp_path)
    assert seen == ["run-1"] and result["runStatus"] == "completed"

    def failing(run_id):
        raise RuntimeError("AccessDenied")
    result, _, _ = run_with({}, {"success": True, "output": {}}, run_started=failing, tmp_path=tmp_path)
    assert result["runStatus"] == "completed"


def test_record_trigger_run_marks_the_row_running_with_the_run_id():
    table = TriggerTable()
    table.put_item({"pk": "MONITOR#ttab", "sk": "MANUAL#a#1", "status": "starting"})
    pr.record_trigger_run(table, {"pk": "MONITOR#ttab", "sk": "MANUAL#a#1"}, "run-7")
    row = table.items[("MONITOR#ttab", "MANUAL#a#1")]
    assert row["status"] == "running" and row["runId"] == "run-7" and row["runStartedAt"].endswith("Z")
    pr.record_trigger_run(None, {"pk": "p", "sk": "s"}, "run-8")           # no table: nothing to do
    pr.record_trigger_run(table, None, "run-8")                            # no trigger: nothing to do


def test_the_automation_id_in_the_request_survives_validation():
    request = pr.validate_request({**REQUEST, "timeoutSeconds": 300, "trigger": {"kind": "manual", "automationId": "distinctive.ttab"}})
    assert request["timeoutSeconds"] == 300 and request["trigger"]["automationId"] == "distinctive.ttab"


def test_a_failed_run_is_recorded_as_failed_with_its_error(tmp_path):
    client = NewsroomClient()

    result = pr.run_procedure_request(REQUEST, client=client, workroot=tmp_path, seconds_available=900, environment={},
                                      execute=lambda *a, **k: {"success": False, "error": "timed out after 840 s", "seconds": 840})

    assert result["runStatus"] == "failed" and client.updates[0]["errorSummary"] == "timed out after 840 s"


def test_only_a_published_version_runs_and_skills_cannot_escape_the_workdir(tmp_path):
    with pytest.raises(pr.ProcedureNotRunnable, match="published"):
        pr.run_procedure_request(REQUEST, client=NewsroomClient(status="draft"), execute=None, seconds_available=900, environment={})
    escaping = NewsroomClient(skills=[("../outside/SKILL.md", b"x")])
    result = pr.run_procedure_request(REQUEST, client=escaping, workroot=tmp_path, seconds_available=900, environment={},
                                      execute=lambda *a, **k: {"success": True})
    assert result["runStatus"] == "failed" and "escapes" in result["error"]


def test_the_child_process_runs_real_tactus_with_input_defaults(tmp_path):
    pytest.importorskip("tactus")
    source_path = tmp_path / "procedure.tac"
    source_path.write_text(PROCEDURE)

    outcome = pr.execute_in_child(tmp_path, source_path, {"proceeding": "91287216", "opinion_url": "https://x/b.pdf"},
                                  timeout_seconds=120, environment=pr.child_environment(
                                      {"appsyncEndpoint": ENDPOINT}, None) | {"PYTHONPATH": str(Path(pr.__file__).parents[1])})

    assert outcome["success"] is True and outcome["output"] == {"title": "91287216"}


# --- registration ------------------------------------------------------------------------------------

def site(tmp_path, source=PROCEDURE_WITH_SKILL):
    (tmp_path / "procedures").mkdir(parents=True)
    (tmp_path / "procedures" / "example.tac").write_text(source)
    skill = tmp_path / ".claude" / "skills" / "example-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: example-skill\ndescription: An example.\n---\n# Example\n")
    return tmp_path / "procedures" / "example.tac"


def test_a_registration_plan_carries_the_input_schema_and_every_skill_file(tmp_path):
    pytest.importorskip("tactus")
    plan = sp.registration_plan(site(tmp_path), root=tmp_path, procedure_key="example.procedure", title="Example")

    assert plan["parameterSchema"]["required"] == ["proceeding", "opinion_url"]
    assert plan["defaults"] == {"corpus": "knowledge-corpus-example"}
    assert [path for path, _ in plan["skills"]] == [".claude/skills/example-skill/SKILL.md"]
    assert plan["versionId"] == sp.registration_plan(site(tmp_path / "again"), root=tmp_path / "again",
                                                     procedure_key="example.procedure")["versionId"]


def test_a_skill_directory_without_a_skill_file_is_refused(tmp_path):
    pytest.importorskip("tactus")
    source = site(tmp_path)
    (tmp_path / ".claude" / "skills" / "example-skill" / "SKILL.md").unlink()
    with pytest.raises(ValueError, match="no SKILL.md"):
        sp.registration_plan(source, root=tmp_path, procedure_key="example.procedure")


class RegistryClient:
    def __init__(self):
        self.records, self.uploads = {}, []

    def get_record(self, model, record_id):
        return self.records.get((model, record_id))

    def create_record(self, model, payload):
        assert (model, payload["id"]) not in self.records
        self.records[(model, payload["id"])] = dict(payload)

    def owner_exists(self, attachment):
        return ("ProcedureVersion", attachment["ownerId"]) in self.records

    def update_record(self, model, payload):
        self.records[(model, payload["id"])].update(payload)

    def list_by_index(self, index, key, limit=100):
        return [record for (model, _), record in self.records.items()
                if model == "ProcedureVersion" and record["procedureId"] == key]


def test_registering_publishes_a_version_and_archives_the_previous_one(tmp_path, monkeypatch):
    pytest.importorskip("tactus")
    client = RegistryClient()
    monkeypatch.setattr(model_attachments, "upload_attachment_body",
                        lambda client_, attachment, body: client.owner_exists(attachment)
                        and client.uploads.append((attachment["sortKey"], body)) or attachment)
    first_plan = sp.registration_plan(site(tmp_path), root=tmp_path, procedure_key="example.procedure")

    first = sp.register_site_procedure(client, first_plan, now="2026-10-21T00:00:00Z")
    again = sp.register_site_procedure(client, first_plan, now="2026-10-21T00:01:00Z")
    (tmp_path / "procedures" / "example.tac").write_text(PROCEDURE_WITH_SKILL.replace("Follow the skill.", "Follow it."))
    second = sp.register_site_procedure(client, sp.registration_plan(
        tmp_path / "procedures" / "example.tac", root=tmp_path, procedure_key="example.procedure"), now="2026-10-21T00:02:00Z")

    assert first["status"] == "registered" and again["status"] == "unchanged" and second["versionNumber"] == 2
    definition = client.records[("ProcedureDefinition", "procedure-example-procedure")]
    assert definition["currentVersionId"] == second["versionId"]
    assert client.records[("ProcedureVersion", first["versionId"])]["status"] == "archived"
    assert client.records[("ProcedureVersion", second["versionId"])]["status"] == "published"
    assert ("skill:.claude/skills/example-skill/SKILL.md", client.uploads[0][1]) == client.uploads[0]
    assert {sort_key for sort_key, _ in client.uploads} == {"code", "skill:.claude/skills/example-skill/SKILL.md"}
    assert len(client.uploads) == 4


# --- templates ---------------------------------------------------------------------------------------

def cloudformation(path):
    import yaml

    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, suffix, node: (
        suffix, loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node)))
    return yaml.load(path.read_text(), Loader=Loader)


INFRA = Path(__file__).resolve().parents[3] / "infra"


def test_the_runner_never_retries_and_stops_inside_its_lambda_timeout():
    resources = cloudformation(INFRA / "procedures" / "papyrus-procedure-runner.yaml")["Resources"]
    function = resources["RunnerFunction"]["Properties"]
    assert function["PackageType"] == "Image" and function["Timeout"] == 900
    assert resources["RunnerInvokeConfig"]["Properties"]["MaximumRetryAttempts"] == 0
    assert pr.SECONDS_KEPT_FOR_RECORDING < function["Timeout"]
    statements = resources["RunnerRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert {statement["Sid"] for statement in statements} == {
        "Logs", "FailedInvocations", "PublicationOpenAiKeys", "TriggerOutcomes", "StageTriggerRows",
        "StartNextStage", "PublicationNewsrooms"}
    assert all("*" != statement["Resource"] for statement in statements)
    by_sid = {statement["Sid"]: statement for statement in statements}
    rows = by_sid["StageTriggerRows"]
    assert set(rows["Action"]) == {"dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"}
    assert rows["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"] == ["MONITOR#*"]
    invoke = by_sid["StartNextStage"]
    assert invoke["Action"] == "lambda:InvokeFunction" and invoke["Resource"][1].endswith(":function:papyrus-procedure-runner")


def test_the_router_may_start_only_the_named_runner():
    template = cloudformation(INFRA / "monitoring" / "papyrus-monitoring.yaml")
    policy = template["Resources"]["RouterProcedureRunnerPolicy"]
    assert policy["Condition"] == "HasProcedureRunner"
    statement = policy["Properties"]["PolicyDocument"]["Statement"][0]
    assert statement["Action"] == "lambda:InvokeFunction" and statement["Resource"][1].endswith(":function:${ProcedureRunnerFunctionName}")


def test_the_runner_hook_never_raises_when_delivery_fails(monkeypatch, capsys):
    from papyrus_content import graphql_authoring, procedure_runner, story_triggers

    monkeypatch.setattr(graphql_authoring, "PapyrusGraphQLAuthoringClient", lambda: object())

    def boom(*args, **kwargs):
        raise RuntimeError("no table")

    monkeypatch.setattr(story_triggers, "deliver_after_run", boom)
    procedure_runner.fire_story_triggers_after_run(object(), None, {"runStatus": "completed", "output": {"story": "s"}})
    assert "could not be delivered" in capsys.readouterr().out
