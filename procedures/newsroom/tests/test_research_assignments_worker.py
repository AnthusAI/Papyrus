"""The router's research-assignments task (features_backend/monitoring-research-assignments.feature). The backend, the clock and the research run are fakes."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.research_assignments_worker import WORKER_LABEL, run_research_assignments, validate_research_assignments  # noqa: E402

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
PUBLICATION = {"publicationId": "example-site", "corpusKey": "example-site"}


class Backend:
    """An in-memory backend with the four calls the worker makes."""

    def __init__(self, rows):
        self.rows = {row["id"]: dict(row) for row in rows}
        self.events = []
        self.relations, self.history = {}, {}

    def list_semantic_relations_by_subject_state(self, state_key):
        return self.relations.get(state_key, [])

    def list_assignment_events_by_assignment_and_created_at(self, assignment_id):
        return self.history.get(assignment_id, [])

    def list_assignments_by_type_status_and_created_at(self, type_key):
        return [dict(row) for row in self.rows.values() if row["assignmentTypeKey"] == type_key]

    def update_record(self, model, payload):
        assert model == "Assignment"
        self.rows[payload["id"]].update(payload)

    def create_record(self, model, payload):
        assert model == "AssignmentEvent"
        self.events.append(payload)


def assignment(number, *, status="open", story="story-1", profile="reporter", type_key="research.multi", expires=None):
    return {"id": f"assignment-{number}", "assignmentTypeKey": type_key, "queueKey": "research:world:exploratory", "status": status, "title": f"Research {number}",
            "createdAt": f"2026-11-03T0{number}:00:00.000Z", "itemLineageId": story, "sectionKey": "world", "claimExpiresAt": expires,
            "metadata": json.dumps({"contextProfile": profile, "direction": f"Look into {number}"})}


class Research:
    def __init__(self, fail=(), raises=()):
        self.asked, self.fail, self.raises = [], set(fail), set(raises)

    def __call__(self, client, options, **_):
        self.asked.append(options)
        if options["assignment"] in self.raises:
            raise RuntimeError("search is down")
        if options["assignment"] in self.fail:
            return {"action": "failed", "error": "no search provider answered"}
        return {"action": "completed"}


def run(backend, research, *, out_of_time=lambda: False, time_left=None):
    return run_research_assignments(backend, PUBLICATION, now=NOW, out_of_time=out_of_time, research=research, clock=lambda: NOW, time_left=time_left)


def test_open_research_assignments_with_a_story_run_oldest_first_and_finish():
    backend, research = Backend([assignment(2), assignment(1)]), Research()
    result = run(backend, research)
    assert [asked["assignment"] for asked in research.asked] == ["assignment-1", "assignment-2"]
    assert research.asked[0]["corpus-key"] == "example-site" and research.asked[0]["actor-label"] == WORKER_LABEL
    assert {row["status"] for row in backend.rows.values()} == {"completed"} and result["ran"] == ["assignment-1", "assignment-2"]
    assert [event["eventType"] for event in backend.events if event["assignmentId"] == "assignment-1"] == ["claim", "research.completed"]


def produces_relation(number):
    return {"relationTypeKey": "produces", "subjectKind": "assignment", "subjectId": f"assignment-{number}", "objectKind": "message", "objectId": "message-1", "relationState": "current"}


@pytest.mark.parametrize("evidence", ["relation", "event", "intake_failed_event"])
def test_an_open_assignment_that_already_has_a_packet_is_completed_with_a_note_and_not_researched(evidence):
    backend, research = Backend([assignment(1), assignment(2)]), Research()
    if evidence == "relation":
        backend.relations["assignment#assignment-1#current"] = [produces_relation(1)]
    else:
        backend.history["assignment-1"] = [{"eventType": "research.multi.completed" if evidence == "event" else "research.multi.intake_failed"}]
    result = run(backend, research)
    assert [asked["assignment"] for asked in research.asked] == ["assignment-2"]
    assert backend.rows["assignment-1"]["status"] == "completed" and "completedAt" in backend.rows["assignment-1"] and result["alreadyDone"] == ["assignment-1"]
    note = next(event["note"] for event in backend.events if event["assignmentId"] == "assignment-1")
    assert "packet already exists" in note and result["ran"] == ["assignment-2"]


def test_a_superseded_packet_relation_does_not_count():
    backend, research = Backend([assignment(1)]), Research()
    backend.relations["assignment#assignment-1#current"] = [{**produces_relation(1), "relationState": "superseded"}]
    run(backend, research)
    assert [asked["assignment"] for asked in research.asked] == ["assignment-1"]


def test_the_worker_tells_the_research_to_leave_the_status_to_it():
    backend, research = Backend([assignment(1)]), Research()
    run(backend, research)
    assert research.asked[0]["leave-status"] is True


def test_a_failure_note_keeps_the_real_reason_and_drops_the_terminal_sign_in_advice():
    backend = Backend([assignment(1), assignment(2)])

    def research(client, options, **_):
        if options["assignment"] == "assignment-1":
            return {"action": "failed", "error": "GraphQL request failed: 401 Unauthorized: Permission denied\nYour AWS session may have expired or lack access. Run `aws sso login --profile <profile>` and retry."}
        raise RuntimeError("Check your newsroom identity/publication permissions with `papyrus auth status`; renew with `papyrus login` if needed.")

    run(backend, research)
    notes = {event["assignmentId"]: event["note"] for event in backend.events if event["eventType"] == "research.failed"}
    assert notes["assignment-1"] == "GraphQL request failed: 401 Unauthorized: Permission denied"
    assert notes["assignment-2"] == "The research did not finish."
    assert "aws sso login" not in " ".join(notes.values()) and "papyrus login" not in " ".join(notes.values())


def test_the_assignment_is_marked_running_before_the_research_starts():
    backend, seen = Backend([assignment(1)]), []

    def research(client, options, **_):
        row = backend.rows[options["assignment"]]
        seen.append((row["status"], row["assigneeKey"], row["claimExpiresAt"]))
        return {"action": "completed"}

    run(backend, research)
    assert seen == [("claimed", WORKER_LABEL, "2026-11-03T12:16:00.000Z")]


@pytest.mark.parametrize("other", [assignment(1, story=None), assignment(1, profile="researcher"), assignment(1, status="completed"), assignment(1, type_key="research.candidate")])
def test_assignments_without_a_story_or_the_reporter_profile_or_not_open_are_left_alone(other):
    backend, research = Backend([other]), Research()
    run(backend, research)
    assert research.asked == [] and backend.events == []


def test_a_failed_run_is_failed_with_its_reason_and_the_others_still_run():
    backend, research = Backend([assignment(1), assignment(2), assignment(3)]), Research(fail={"assignment-1"}, raises={"assignment-2"})
    result = run(backend, research)
    assert [backend.rows[f"assignment-{n}"]["status"] for n in (1, 2, 3)] == ["failed", "failed", "completed"]
    notes = {event["assignmentId"]: event["note"] for event in backend.events if event["eventType"] == "research.failed"}
    assert notes == {"assignment-1": "no search provider answered", "assignment-2": "RuntimeError: search is down"}
    assert result["failed"] == ["assignment-1", "assignment-2"]


def test_it_stops_before_the_deadline_and_leaves_the_rest_open():
    backend, research = Backend([assignment(1), assignment(2), assignment(3)]), Research()
    calls = iter([False, True])
    result = run(backend, research, out_of_time=lambda: next(calls, True))
    assert [row["status"] for row in backend.rows.values()] == ["completed", "open", "open"]
    assert result["stoppedBy"] == "time" and result["leftOpen"] == 2 and result["status"] == "stopped"


def test_a_run_is_not_started_with_less_time_than_a_search_and_synthesis_need():
    backend, research = Backend([assignment(1)]), Research()
    result = run(backend, research, time_left=lambda: 400)
    assert research.asked == [] and backend.rows["assignment-1"]["status"] == "open" and result["stoppedBy"] == "time" and result["leftOpen"] == 1
    result = run(backend, research, time_left=lambda: 800)
    assert backend.rows["assignment-1"]["status"] == "completed"


def test_the_research_is_told_to_stop_judging_when_less_than_the_judge_reserve_is_left():
    left, told = [800], []

    def research(client, options, out_of_time):
        told.append(out_of_time())
        left[0] = 200
        told.append(out_of_time())
        return {"action": "completed"}

    run(Backend([assignment(1)]), research, time_left=lambda: left[0])
    assert told == [False, True]


def test_a_judge_that_is_out_of_time_leaves_claims_unchecked_and_the_run_still_makes_a_packet():
    from papyrus_content.fact_check import check_claims
    from papyrus_content.multi_search_research import stop_judging_when_short_of_time

    asked = []
    short = [False]

    def judge(claim, cited, info):
        asked.append(claim)
        short[0] = True
        return {"verdict": "supported", "quotes": [], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}

    texts = {"1": "Alpha beta gamma. Delta epsilon."}
    claims = [{"claim": "Alpha beta gamma.", "sources": ["1"]}, {"claim": "Delta epsilon.", "sources": ["1"]}]
    report = check_claims(claims, texts, judge=stop_judging_when_short_of_time(judge, lambda: short[0]), urls={"1": "https://a.example/x"})
    verdicts = [claim["verdict"] for claim in report["claims"]]
    assert "unchecked" in verdicts and report["counts"]["total"] == 2
    assert all("ran short of time" in claim["reasons"][0] for claim in report["claims"] if claim["verdict"] == "unchecked")


def test_a_claim_past_its_lease_is_failed_with_a_reason_and_not_run_again():
    stale, live = (NOW - timedelta(minutes=1)).isoformat(), (NOW + timedelta(minutes=5)).isoformat()
    backend, research = Backend([assignment(1, status="claimed", expires=stale), assignment(2, status="claimed", expires=live)]), Research()
    result = run(backend, research)
    assert backend.rows["assignment-1"]["status"] == "failed" and backend.rows["assignment-2"]["status"] == "claimed"
    assert "time ran out" in backend.events[0]["note"] and result["expired"] == ["assignment-1"] and research.asked == []


def test_the_policy_is_off_unless_a_publication_turns_it_on():
    assert validate_research_assignments("x", None) == {"enabled": False}
    assert validate_research_assignments("x", {"enabled": True}) == {"enabled": True}
    for bad in ("yes", {"enabled": "yes"}, {"budget": 5}):
        with pytest.raises(ValueError):
            validate_research_assignments("x", bad)


# --- the router task and the fields its run asks for -------------------------------------------------------------------------------------

import test_monitoring_router as tr  # noqa: E402
import test_monitoring_stories as tms  # noqa: E402
from ideas_fixtures import NOW as ROUTER_NOW  # noqa: E402
from papyrus_content import monitoring_router as mr  # noqa: E402


def router_with(settings):
    from _pytest.monkeypatch import MonkeyPatch

    table, store = tms.router(tuple(settings), None)
    config = table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]
    for entry in config["publications"]:
        if settings[entry["publicationId"]] is not None:
            entry["researchAssignments"] = settings[entry["publicationId"]]
    table.put_item(config)
    return table, store


def run_task(store, backends, *, publication_id=None, fan_out=None, research=None, time_left=lambda: 900):
    endpoints = {tr.ENDPOINT.replace("abc123", f"api{n}"): backend for n, backend in enumerate(backends.values())}
    original = mr.run_research_assignments
    mr.run_research_assignments = lambda client, publication, **options: original(client, publication, **{**options, "research": research or Research()})
    try:
        return mr.run_router(store, "hn", now=ROUTER_NOW.timestamp(), task="research-assignments", appsync=lambda endpoint: endpoints[endpoint], deliver=tr.Delivery(),
                             time_left=time_left, publication_id=publication_id, fan_out=fan_out)
    finally:
        mr.run_research_assignments = original


def test_with_no_publication_named_the_task_only_starts_a_run_for_each_publication_that_turned_it_on(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    table, store = router_with({"a-site": {"enabled": True}, "off-site": None, "b-site": {"enabled": True}})
    started = []
    result = run_task(store, {}, fan_out=started.append)
    assert started == ["a-site", "b-site"] and result["status"] == "fanned-out"
    assert not [key for key in table.items if key[1].startswith(("LOCK#", "ROUTERUN#"))]


def test_a_run_for_one_publication_runs_its_assignments_under_its_own_lock_and_leaves_the_routing_lock_free(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    table, store = router_with({"a-site": {"enabled": True}})
    backend, research = Backend([assignment(1)]), Research()
    result = run_task(store, {"a-site": backend}, publication_id="a-site", research=research)
    assert backend.rows["assignment-1"]["status"] == "completed" and result["researchAssignments"]["a-site"]["ran"] == ["assignment-1"]
    assert store.acquire_router_lock("hn", "route", now=ROUTER_NOW.timestamp())
    assert store.acquire_router_lock("hn", "again", now=ROUTER_NOW.timestamp(), sk="LOCK#research-assignments#a-site")


def test_a_publication_that_did_not_turn_it_on_runs_nothing(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    _, store = router_with({"a-site": None})
    backend, research = Backend([assignment(1)]), Research()
    result = run_task(store, {"a-site": backend}, publication_id="a-site", research=research)
    assert research.asked == [] and result["researchAssignments"]["a-site"]["status"] == "skipped"


def worker_grants():
    """Every (Query|Mutation, field) the template grants the research worker's own role, on any publication API."""
    import re

    statements = tr._template()["Resources"]["ResearchWorkerRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    found = set()
    for statement in statements:
        for entry in statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]:
            match = re.search(r"apis/\*/types/(Query|Mutation)/fields/(\w+)$", str(entry[1] if isinstance(entry, tuple) else entry))
            if match:
                found.add((match.group(1), match.group(2)))
    return found


def recorded_fields_of_a_full_run(monkeypatch, tenant_id=None):
    """The fields one assignment's whole run asks of the publication API, on the real client with its transport replaced: the pass, the claim, the context pack, the
    two model calls, the packet and its intake. The backend answers like a small real one (what is created can be read back)."""
    import functools
    import re
    import urllib.request

    import test_multi_search_research as multi
    from papyrus_content import multi_search_research as research_module
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

    recorded, stored = set(), {}
    story = {"id": "item-1", "lineageId": "story-1", "versionState": "current", "versionNumber": 1, "type": "post", "stage": "assignment", "headline": "A story",
             "section": None, "bodyMarkus": "Body", "status": "draft", "tenantId": tenant_id}
    corpus = {"id": "knowledge-corpus-example-site", "role": "canonical", "name": "Example"}
    doctrine = {"id": "d", "lineageId": "d", "versionNumber": 1, "versionState": "current", "type": "doctrine", "status": "private", "body": ["Doctrine"], "tenantId": tenant_id}
    row = assignment(1)
    stored.setdefault("Assignment", {})[row["id"]] = row

    bodies, pending = {}, []
    partition_models = {"listSemanticRelationsByObjectState": ("SemanticRelation", "objectStateKey"),
                        "listSemanticRelationsBySubjectState": ("SemanticRelation", "subjectStateKey"),
                        "listModelAttachmentsByOwnerRoleAndSortKey": ("ModelAttachment", "ownerId")}

    def respond(query, variables=None):
        variables = variables or {}
        if query.lstrip().startswith("query BatchGet"):   # several gets as aliased fields: IAM and the recorder see the real field names
            fields = re.findall(r"\br\d+:\s*(get\w+)\(", query)
            recorded.update(("Query", name) for name in fields)
            return {f"r{n}": stored.get(name[3:], {}).get(variables.get(f"k{n}")) for n, name in enumerate(fields)}
        kind, field = ("Mutation" if query.lstrip().startswith("mutation") else "Query"), tms.GRAPHQL_ROOT.match(query).group(1)
        recorded.add((kind, field))
        write = re.match(r"(create|update)(\w+)$", field)
        if kind == "Mutation" and write and "input" in variables:
            stored.setdefault(write.group(2), {}).setdefault(variables["input"]["id"], {}).update(variables["input"])
        if field == "createModelAttachmentUpload":
            pending.append(f"https://s3.example/payload-{len(bodies) + len(pending)}")
            return {field: {"uploadId": f"u{len(pending)}", "uploadUrl": pending[-1], "method": "PUT", "requiredHeaders": {}, "storagePath": pending[-1]}}
        if field == "completeModelAttachmentUpload":
            attachment = {**variables, "id": f"attachment-{len(stored.get('ModelAttachment', {}))}", "storagePath": pending.pop(0), "status": "active"}
            stored.setdefault("ModelAttachment", {})[attachment["id"]] = attachment
            return {field: attachment}
        if field == "createModelAttachmentDownload":
            return {field: {"downloadUrl": stored["ModelAttachment"][variables["attachmentId"]]["storagePath"], "method": "GET", "requiredHeaders": {}}}
        if kind == "Mutation":
            return {field: {"id": "x"}}
        served = {"listAssignmentsByTypeStatusAndCreatedAt": [row], "listItemsByLineageAndVersion": [story], "itemBySlug": [doctrine], "itemByTenantSlug": [doctrine],
                  "listKnowledgeCorporaByRoleAndName": [corpus]}
        if field in served:
            return {field: {"items": served[field], "nextToken": None}}
        if field in partition_models:
            model, key = partition_models[field]
            return {field: {"items": [entry for entry in stored.get(model, {}).values() if entry.get(key) == variables[key]], "nextToken": None}}
        if field.startswith("get"):
            return {field: stored.get(field[3:], {}).get(variables.get("id"))}
        return {field: {"items": [], "nextToken": None}}

    class Upload:
        status = 200

        def __init__(self, body=b""):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *failure):
            return False

        def read(self):
            return self.body

    def transport(request):
        if request.data is not None:
            bodies[request.full_url] = request.data
            return Upload()
        return Upload(bodies[request.full_url])

    monkeypatch.setattr(urllib.request, "urlopen", transport)
    client = PapyrusGraphQLAuthoringClient(endpoint=tr.ENDPOINT, tenant_id=tenant_id, header_factory=lambda body: {})
    client.graphql = respond
    done = functools.partial(research_module.research_multi, llm=multi.FakeLlm(), providers=multi.two_providers())
    result = run_research_assignments(client, {**PUBLICATION, "appsyncEndpoint": tr.ENDPOINT}, now=NOW, out_of_time=lambda: False, research=done, clock=lambda: NOW)
    assert result["ran"] == ["assignment-1"], (result, stored.get("AssignmentEvent"))
    assert "research.multi.intake_failed" not in [event["eventType"] for event in stored["AssignmentEvent"].values()]
    assert stored["Reference"] and ("Mutation", "createSemanticRelation") in recorded and ("Mutation", "updateReference") in recorded
    return recorded


@pytest.mark.parametrize("tenant_id", [None, "example-tenant"])
def test_every_field_a_full_run_asks_for_is_granted_to_the_research_workers_role(monkeypatch, tenant_id):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    asked = recorded_fields_of_a_full_run(monkeypatch, tenant_id)
    granted = worker_grants()
    assert {("Mutation", "updateAssignment"), ("Mutation", "createAssignmentEvent"), ("Mutation", "createMessage")} <= asked
    print(sorted(asked)); assert asked <= granted, sorted(asked - granted)


def test_the_worker_may_read_what_a_context_pack_reads_for_a_story_past_the_idea_stage():
    """The full-run test above uses a fake Story, so it does not reach these. A live run on a Story in copywriting failed with a 401 without them."""
    assert {("Query", "getItem"), ("Query", "listItemsByStageAndUpdatedAt")} <= worker_grants()


def test_the_worker_has_its_own_function_and_schedule_and_the_key_policies_name_its_role():
    resources = tr._template()["Resources"]
    assert resources["ResearchAssignmentsSchedule"]["Properties"]["Target"]["Arn"] == ("GetAtt", "ResearchWorkerFunction.Arn") or "ResearchWorkerFunction" in str(resources["ResearchAssignmentsSchedule"]["Properties"]["Target"]["Arn"])
    assert json.loads(resources["ResearchAssignmentsSchedule"]["Properties"]["Target"]["Input"]) == {"task": "research-assignments", "monitorId": "hn"}
    for name in ("ResearchWorkerOpenAiSearchKeyPolicy", "ResearchWorkerPerplexitySearchKeyPolicy", "ResearchWorkerGeminiSearchKeyPolicy", "ResearchWorkerTavilyKeyPolicy"):
        assert resources[name]["Properties"]["Roles"] == [("Ref", "ResearchWorkerRole")], name
        assert resources[name]["Condition"] == resources[name.replace("ResearchWorker", "Router")]["Condition"], name
        assert resources[name]["Properties"]["PolicyDocument"] == resources[name.replace("ResearchWorker", "Router")]["Properties"]["PolicyDocument"], name
    for name in ("RouterOpenAiSearchKeyPolicy", "RouterTavilyKeyPolicy"):
        assert resources[name]["Properties"]["Roles"] == [("Ref", "RouterRole")], name
    function = resources["ResearchWorkerFunction"]["Properties"]
    assert function["Handler"] == resources["RouterFunction"]["Properties"]["Handler"] and function["Timeout"] == 900
    from papyrus_content.monitoring_router import TASK_LEASE_SECONDS
    from papyrus_content.research_assignments_worker import CLAIM_LEASE_SECONDS

    assert TASK_LEASE_SECONDS["research-assignments"] > function["Timeout"] and CLAIM_LEASE_SECONDS > function["Timeout"]


def test_the_router_role_keeps_its_twenty_policies_and_gains_none():
    resources = tr._template()["Resources"]
    attached = [name for name, resource in resources.items() if resource["Type"] == "AWS::IAM::ManagedPolicy" and ("Ref", "RouterRole") in (resource["Properties"].get("Roles") or [])]
    assert len(attached) <= 20, len(attached)


def test_an_idle_tick_lists_once_and_writes_no_receipt(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    table, store = router_with({"a-site": {"enabled": True}})
    backend = Backend([])
    listed = []
    original = backend.list_assignments_by_type_status_and_created_at
    backend.list_assignments_by_type_status_and_created_at = lambda type_key: listed.append(type_key) or original(type_key)
    run_task(store, {"a-site": backend}, publication_id="a-site")
    assert listed == ["research.multi"] and backend.events == []
    assert not [key for key in table.items if key[1].startswith("ROUTERUN#")]
    backend.rows["assignment-1"] = assignment(1)
    run_task(store, {"a-site": backend}, publication_id="a-site")
    assert [key for key in table.items if key[1].startswith("ROUTERUN#")]


def test_the_router_zip_can_load_everything_a_research_run_uses_with_nothing_but_the_zip(tmp_path):
    """The Lambda has boto3 and the zip's own packages. The first live run failed with a missing module that tests with the full repository could not see."""
    import importlib.util
    import subprocess
    import sys
    import zipfile
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("monitoring_build", root / "infra/monitoring/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    archive = tmp_path / "router.zip"
    build.build_router(archive, target="host")
    unpacked = tmp_path / "task"
    zipfile.ZipFile(archive).extractall(unpacked)
    script = ("import sys; sys.path.insert(0, sys.argv[1]); "
              "from papyrus_content import multi_search_research, research_assignments_worker, newsroom_context_pack, fact_check; "
              "from papyrus_content import assignments_workflow, reference_curation, steering, catalog, ids, web_search; "
              "import pypdf; assert sys.argv[1] in pypdf.__file__; "   # a research run reads PDFs; without this every PDF silently reads as no text
              "assert sys.argv[1] in multi_search_research.__file__; print('loaded')")
    done = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(unpacked)], capture_output=True, text=True, cwd=tmp_path,
                          env={"PAPYRUS_ROOT": str(unpacked)})
    assert done.stdout.strip() == "loaded", done.stderr[-800:]


def test_the_desk_lookup_of_a_section_s_stories_is_granted():
    """The pack finds the desk's Stories through this query. A recording with a fake store never reached it, and the first live run on a tenant site was refused."""
    assert ("Query", "listItemsBySectionStatusAndPublishedAt") in worker_grants()

