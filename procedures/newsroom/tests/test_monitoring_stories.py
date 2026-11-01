"""The daily monitor-stories task of the monitoring router (src/papyrus_content/monitoring_stories.py, features_backend/monitoring-daily-stories.feature).
The model, the pages, the backends and the clock are fakes; nothing here reaches the network."""
from __future__ import annotations

import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from functools import partial
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_monitoring_router as tr  # noqa: E402
from fake_idea_store import FakeIdeaStore  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from test_monitor_stories import StoryModel, pages, provenance, world  # noqa: E402
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402
from papyrus_content.monitoring_router import MIN_REMAINING_SECONDS, run_router, validate_router_config  # noqa: E402
from papyrus_content.monitoring_stories import lambda_story_transport, run_publication, validate_monitor_stories  # noqa: E402

PUBLICATION = "example-site"   # the fixtures' corpus is knowledge-corpus-example-site


@pytest.fixture(autouse=True)
def iam_auth(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")   # the router Lambda's setting: earlier drafts are read through listStoryDrafts


@pytest.fixture(autouse=True)
def fake_idea_sink(monkeypatch):
    """The router files ideas through ``ItemStore``; these tests read what was filed from the fake backend, so the sink is its recording double (ItemStore itself: test_idea_items.py)."""
    monkeypatch.setattr("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client))


def router(publications=(PUBLICATION,), settings=None):
    """A router store whose publications are `publications`, each with its own AppSync endpoint (`monitorStories` from `settings`)."""
    table = tr.FakeTable()
    table.put_item(tr.COLLECTOR_CONFIG)
    run_collection(DynamoStore(table), "hn", fetch=lambda url: tr.FEED, now=1000)
    store, _ = tr.setup_router(table)
    config = table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]
    config["publications"] = [{"publicationId": p, "site": f"{p}.example", "appsyncEndpoint": tr.ENDPOINT.replace("abc123", f"api{n}"),
                               "corpusId": "knowledge-corpus-example-site",   # the fixtures' References all live in this corpus
                               **({"monitorStories": settings[p]} if settings and p in settings else {})} for n, p in enumerate(publications)]
    table.put_item(config)
    return table, store


def run_task(store, clients, model, *, time_left=lambda: 1e9, fetch=None, mode_table=None):
    """Runs the monitor-stories task; `clients` maps a publication id to its backend. Returns (result, log lines by publication)."""
    endpoints = {tr.ENDPOINT.replace("abc123", f"api{n}"): client for n, client in enumerate(clients.values())}
    out = io.StringIO()
    with redirect_stdout(out):
        result = run_router(store, "hn", now=NOW.timestamp(), task="monitor-stories", appsync=lambda endpoint: endpoints[endpoint],
                            deliver=tr.Delivery(), time_left=time_left, story_transport=model,
                            story_drafter=partial(run_publication, fetch=fetch or pages(*range(1, 60)), explorer=None))
    lines = {line["publicationId"]: line for line in map(json.loads, (l for l in out.getvalue().splitlines() if l.startswith('{"monitorStories"')))}
    return result, lines


def stories_filed(client):
    return [row for row in client.filed]


def test_the_daily_run_drafts_each_accepted_undrafted_monitored_reference_once():
    table, store = router()
    _, client = world(3)
    model = StoryModel()
    result, lines = run_task(store, {PUBLICATION: client}, model)
    assert len(stories_filed(client)) == 3
    assert {k: lines[PUBLICATION][k] for k in ("status", "drafted", "candidates", "notAccepted", "skipped", "stoppedBy")} == {
        "status": "complete", "drafted": 3, "candidates": 3, "notAccepted": 0, "skipped": 0, "stoppedBy": None}
    assert result["monitorStories"][PUBLICATION]["drafted"] == 3
    second, lines = run_task(store, {PUBLICATION: client}, model)
    assert len(stories_filed(client)) == 3 and lines[PUBLICATION]["drafted"] == 0 and lines[PUBLICATION]["candidates"] == 0
    assert len(model.requests) == 3   # nothing was asked of the model on the second run


def test_there_is_no_fixed_number_of_drafts_a_run_writes():
    table, store = router()
    _, client = world(7)
    _, lines = run_task(store, {PUBLICATION: client}, StoryModel())
    assert lines[PUBLICATION]["drafted"] == 7 and len(stories_filed(client)) == 7   # the old limit was 3


def test_pending_references_are_not_drafted_and_are_counted():
    table, store = router()
    _, client = world(4)
    client.references[0]["curationStatus"] = client.references[1]["curationStatus"] = "pending"
    _, lines = run_task(store, {PUBLICATION: client}, StoryModel())
    assert lines[PUBLICATION]["drafted"] == 2 and lines[PUBLICATION]["notAccepted"] == 2
    assert {json.loads(row["evidence"])["source"].split(": ")[1] for row in client.filed} == {"https://www.example3.org/post", "https://www.example4.org/post"}


def test_a_publication_with_monitor_stories_disabled_is_skipped():
    table, store = router(("example-site", "other-site"), {"other-site": {"enabled": False}})
    _, first = world(2)
    _, second = world(2)
    model = StoryModel()
    _, lines = run_task(store, {"example-site": first, "other-site": second}, model)
    assert lines["other-site"]["status"] == "disabled" and lines["other-site"]["drafted"] == 0
    assert len(first.filed) == 2 and not second.filed and not any(call[0] == "incoming" for call in second.calls)


def test_a_dry_run_router_writes_nothing():
    table, store = router()
    config = table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]
    table.put_item({**config, "mode": "dry-run"})
    _, client = world(2)
    result, lines = run_task(store, {PUBLICATION: client}, StoryModel())
    assert not client.filed and lines == {} and result["monitorStories"] == {}


def test_without_a_model_key_every_publication_logs_the_typed_skip():
    table, store = router()
    _, client = world(2)
    _, lines = run_task(store, {PUBLICATION: client}, None)
    assert lines[PUBLICATION]["status"] == "skipped" and lines[PUBLICATION]["reason"] == "openai_not_configured" and not client.filed


def test_running_out_of_time_stops_cleanly_and_the_next_run_continues_with_the_rest():
    table, store = router()
    _, client = world(5)
    model = StoryModel()
    asked = {"n": 0}

    def clock():   # plenty of time until two drafts have been asked for, then none
        return 1e9 if len(model.requests) < 2 else MIN_REMAINING_SECONDS - 1

    _, lines = run_task(store, {PUBLICATION: client}, model, time_left=clock)
    assert lines[PUBLICATION]["stoppedBy"] == "time" and lines[PUBLICATION]["status"] == "stopped"
    assert lines[PUBLICATION]["drafted"] == 2 and lines[PUBLICATION]["candidates"] == 5 and len(client.filed) == 2
    _, lines = run_task(store, {PUBLICATION: client}, model)
    assert lines[PUBLICATION]["stoppedBy"] is None and lines[PUBLICATION]["candidates"] == 3 and lines[PUBLICATION]["drafted"] == 3
    assert len(client.filed) == 5 and len({row["title"] for row in client.filed}) == 5   # each Reference exactly once


def test_the_best_ranked_items_go_first_when_time_runs_out():
    table, store = router()
    _, client = world(4, verdicts={1: 0.2, 2: 0.9, 3: 0.4, 4: 0.7})
    model = StoryModel()
    clock = lambda: 1e9 if len(model.requests) < 2 else 0   # noqa: E731
    run_task(store, {PUBLICATION: client}, model, time_left=clock)
    drafted = [json.loads(row["evidence"])["source"] for row in client.filed]
    assert [re.search(r"example(\d+)", source).group(1) for source in drafted] == ["2", "4"]


class SlowModel:
    """A model whose every call takes `seconds` of the Lambda's time (`left` is the clock)."""

    def __init__(self, seconds, start=600.0):
        self.seconds, self.left, self.model = seconds, start, StoryModel()

    def __call__(self, url, headers, payload):
        self.left -= self.seconds
        return self.model(url, headers, payload)


def test_each_publication_gets_an_equal_share_of_the_time_that_is_left():
    table, store = router(("example-site", "other-site"))
    _, first = world(8)
    _, second = world(2)
    slow = SlowModel(60)
    _, lines = run_task(store, {"example-site": first, "other-site": second}, slow, time_left=lambda: slow.left)
    assert lines["example-site"]["stoppedBy"] == "time" and 0 < lines["example-site"]["drafted"] < 8
    assert lines["other-site"]["drafted"] == 2 and lines["other-site"]["stoppedBy"] is None   # the big backlog did not starve it


def test_a_publication_the_time_stopped_gets_another_turn_while_time_is_left_and_reports_one_line():
    table, store = router(("example-site", "other-site"))
    _, big = world(8)
    _, nothing = world(0)
    slow = SlowModel(60)
    _, lines = run_task(store, {"example-site": big, "other-site": nothing}, slow, time_left=lambda: slow.left)
    assert lines["example-site"]["drafted"] == 8 and lines["example-site"]["stoppedBy"] is None and lines["example-site"]["candidates"] == 8
    assert len(big.filed) == 8 and len({row["title"] for row in big.filed}) == 8   # each Reference exactly once, over two passes
    reviews = [row for row in big.reviews.values()] if hasattr(big, "reviews") else []
    assert len(reviews) == 2 and sum(len(json.loads(r["links"]) if isinstance(r.get("links"), str) else r.get("links") or []) for r in reviews) == 8   # a review per pass, every draft linked


TTAB_AUTOMATION = {"id": "automation-ttab", "enabled": True, "procedureKey": "ttab.story", "trigger": json.dumps({"kind": "monitor", "config": {"monitorId": "ttab", "publicationId": PUBLICATION}})}


def trigger_row(table, reference, status, **fields):
    table.put_item({"pk": "MONITOR#ttab", "sk": f"TRIGGER#{PUBLICATION}#ttab.story#src-{reference['id']}", "referenceId": reference["id"], "status": status,
                    "createdAt": "2026-10-23T11:59:00Z", **fields})


def test_a_ttab_reference_an_automation_is_making_a_story_for_is_not_drafted():
    table, store = router()
    rows, client = world(4, monitor="ttab")
    provenance(rows[3], "hn")
    client.automations = [TTAB_AUTOMATION]
    trigger_row(table, rows[0], "running", runId="run-1")
    trigger_row(table, rows[1], "completed", runId="run-2")
    _, lines = run_task(store, {PUBLICATION: client}, StoryModel())
    assert lines[PUBLICATION]["drafted"] == 2 and lines[PUBLICATION]["handledByAutomation"] == 2
    assert [json.loads(row["evidence"])["source"] for row in client.filed].count("hn monitor: https://www.example4.org/post") == 1


def test_a_ttab_reference_whose_automation_never_ran_or_failed_is_drafted_like_any_other():
    table, store = router()
    rows, client = world(3, monitor="ttab")
    client.automations = [TTAB_AUTOMATION]   # configured for the monitor, but a run was only ever started for none of them
    trigger_row(table, rows[0], "failed", runId="run-1", runError="boom")
    trigger_row(table, rows[1], "startFailed")
    trigger_row(table, rows[2], "started", startedAt="2026-10-01T00:00:00Z")   # in flight for weeks: its outcome was never recorded
    _, lines = run_task(store, {PUBLICATION: client}, StoryModel())
    assert lines[PUBLICATION]["drafted"] == 3 and lines[PUBLICATION]["handledByAutomation"] == 0


def test_a_ttab_reference_nothing_started_for_is_drafted_with_an_automation_configured():
    table, store = router()
    _, client = world(2, monitor="ttab")
    client.automations = [TTAB_AUTOMATION]
    _, lines = run_task(store, {PUBLICATION: client}, StoryModel())
    assert lines[PUBLICATION]["drafted"] == 2 and lines[PUBLICATION]["handledByAutomation"] == 0


def test_a_filing_error_stops_the_publication_before_more_money_is_spent_and_the_others_go_on():
    table, store = router(("example-site", "other-site"))
    _, broken = world(4)
    _, fine = world(2)
    original = broken.graphql
    broken.graphql = lambda query, variables=None: (_ for _ in ()).throw(RuntimeError("not authorized")) if "fileProposal" in query else original(query, variables)
    model = StoryModel()
    _, lines = run_task(store, {"example-site": broken, "other-site": fine}, model)
    assert lines["example-site"]["stoppedBy"] == "file_error" and lines["example-site"]["drafted"] == 0
    assert len(model.requests) == 1 + 2   # one wasted call on the broken publication, then the other publication's two
    assert lines["other-site"]["drafted"] == 2


def test_a_publication_that_fails_is_logged_and_the_others_go_on():
    table, store = router(("example-site", "other-site"))
    _, fine = world(2)

    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("backend unavailable")

    _, lines = run_task(store, {"example-site": Broken(), "other-site": fine}, StoryModel())
    assert lines["example-site"]["status"] == "failed" and lines["other-site"]["drafted"] == 2


def test_the_log_line_names_what_the_run_did():
    table, store = router()
    _, client = world(2)
    client.references[1]["curationStatus"] = "pending"
    _, lines = run_task(store, {PUBLICATION: client}, StoryModel())
    assert {"drafted", "candidates", "notAccepted", "skipped", "stoppedBy"} <= set(lines[PUBLICATION])


def test_the_task_does_not_route_collect_or_give_feedback():
    table, store = router()
    _, client = world(1)
    result, _ = run_task(store, {PUBLICATION: client}, StoryModel())
    assert result["status"] == "skipped" and result["feedback"] == {"status": "skipped"} and result["autoAccept"] == {}


# --- packaging ---------------------------------------------------------------------------------------------------------------


def test_the_router_zip_can_run_the_drafting_with_nothing_but_the_standard_library(tmp_path):
    """The Lambda has boto3 and the zip's own pure-Python packages, nothing else: import everything the task uses from the built zip alone."""
    import importlib.util
    import subprocess
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("monitoring_build", root / "infra/monitoring/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    archive = tmp_path / "router.zip"
    build.build_router(archive)
    assert archive.stat().st_size < 2_000_000   # a sensible size: the drafting adds a handful of small modules
    script = ("import sys; sys.path.insert(0, sys.argv[1]); import papyrus_content.monitoring_router; "
              "from papyrus_content import monitoring_stories as m; from papyrus_content.ideas import monitor_stories, context, store, synthesis, review; "
              "from papyrus_content import link_exploration; print('imported')")
    done = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(archive)], capture_output=True, text=True, cwd=tmp_path,
                          env={"PAPYRUS_ROOT": str(tmp_path)})
    assert done.stdout.strip() == "imported", done.stderr[-800:]


# --- reading many References at a time ---------------------------------------------------------------------------------------


def test_reading_with_several_workers_gives_the_same_items_and_counts_as_reading_one_by_one():
    from papyrus_content.ideas import monitor_stories as library
    rows, client = world(12, verdicts={3: ("exclude", 0.1)})
    del rows[4]["discoveredByMonitorId"]   # not monitored
    one = library.collect_monitored_items(client, site=PUBLICATION, now=NOW)
    many = library.collect_monitored_items(client, site=PUBLICATION, now=NOW, workers=4)
    assert [i.lineage_id for i in many[0]] == [i.lineage_id for i in one[0]] and many[1] == one[1]
    assert one[1]["notMonitored"] == 1 and one[1]["judgedNotRelevant"] == 1


def test_a_read_that_runs_out_of_time_leaves_the_rest_unread_and_says_so():
    from papyrus_content.ideas import monitor_stories as library
    _, client = world(6)
    items, counts = library.collect_monitored_items(client, site=PUBLICATION, now=NOW, workers=2, out_of_time=lambda: True)
    assert items == [] and counts["readStopped"] == 6


# --- configuration -------------------------------------------------------------------------------------------------------


def test_monitor_stories_is_on_by_default_and_the_setting_is_validated():
    assert validate_monitor_stories("p", None) == {"enabled": True, "store": "items"}   # ideas are Items at the idea stage by default
    assert validate_monitor_stories("p", {}) == {"enabled": True, "store": "items"}
    assert validate_monitor_stories("p", {"enabled": False}) == {"enabled": False, "store": "items"}
    assert validate_monitor_stories("p", {"store": "items"}) == {"enabled": True, "store": "items"}
    assert validate_monitor_stories("p", {"store": "proposals"}) == {"enabled": True, "store": "items"}   # a router entry written before ideas became Items still validates
    for bad in ({"enabled": "no"}, {"limit": 3}, {"store": "files"}, "off", []):
        with pytest.raises(ValueError):
            validate_monitor_stories("p", bad)


def test_the_router_config_carries_the_setting():
    config = tr.router_config()
    config["publications"][1]["monitorStories"] = {"enabled": False}
    publications = validate_router_config(config)["publications"]
    assert [p["monitorStories"]["enabled"] for p in publications] == [True, False, True]


def test_the_model_key_is_read_from_the_enrichment_parameter_only_when_asked():
    class Ssm:
        def __init__(self):
            self.names = []

        def get_parameter(self, Name, WithDecryption):
            self.names.append((Name, WithDecryption))
            return {"Parameter": {"Value": " sk-test-value \n"}}

    ssm = Ssm()
    assert lambda_story_transport({}, ssm=ssm) is None and ssm.names == []
    assert callable(lambda_story_transport({"ENRICHMENT_OPENAI_KEY_PARAMETER": "/papyrus/shipped/openai-api-key"}, ssm=ssm))
    assert ssm.names == [("/papyrus/shipped/openai-api-key", True)]

    class Failing:
        def get_parameter(self, **kwargs):
            raise RuntimeError("denied")

    assert lambda_story_transport({"ENRICHMENT_OPENAI_KEY_PARAMETER": "/x"}, ssm=Failing()) is None


# --- IAM: the grant covers everything the drafting asks of a publication's API ----------------------------------------------

PUBLICATION_APIS = ("AnthUsApiId", "PapyrusApiId", "ThreatIntelApiId", "DataParadeApiId", "PilobolusApiId", "ShippedApiId")   # the six the hn monitor lists
GRAPHQL_ROOT = re.compile(r"^\s*(?:query|mutation)\b[^{]*\{\s*(\w+)", re.S)


def used_fields():
    """The AppSync root fields one full drafting run (reading, filing, raising the review) asks of a publication's API, recorded by
    running it on the real GraphQL client with its transport replaced."""
    assert os.environ["PAPYRUS_GRAPHQL_AUTH"] == "iam"   # the Lambda's setting: earlier drafts are read with listStoryDrafts, not listProposals
    rows, fake = world(2)
    recorded: list[tuple[str, str]] = []

    def respond(query, variables=None):
        kind, field = ("Mutation" if query.lstrip().startswith("mutation") else "Query"), GRAPHQL_ROOT.match(query).group(1)
        recorded.append((kind, field))
        variables = variables or {}
        if field == "listStoryDrafts":
            return {field: {"status": "ok", "drafts": []}}
        if field == "fileProposal":
            return {field: {"status": "ok", "id": f"proposal-{len(recorded)}"}}
        if kind == "Mutation":
            return {field: {"id": "x"}}
        if field.startswith("get"):
            return {field: None}
        # a list or an index query: answer from the fake backend by the name of the index the client asked for
        for index, definition in __import__("papyrus_content.graphql_authoring", fromlist=["INDEX_DEFINITIONS"]).INDEX_DEFINITIONS.items():
            if definition["field"] == field:
                if index == "referencesByCurationStatusKey":
                    return {field: {"items": [r for r in fake.references if variables.get("curationStatusKey", "").endswith("#accepted")], "nextToken": None}}
                if index == "semanticRelationsByObjectState":
                    lineage = variables[definition["partitionKey"]].split("#")[1]
                    return {field: {"items": fake.incoming.get(lineage, []), "nextToken": None}}
                if index == "semanticRelationsBySubjectState":
                    lineage = variables[definition["partitionKey"]].split("#")[1]
                    return {field: {"items": fake.relations.get(lineage, []), "nextToken": None}}
                return {field: {"items": [], "nextToken": None}}
        return {field: {"items": [], "nextToken": None}}

    client = PapyrusGraphQLAuthoringClient(endpoint=tr.ENDPOINT, header_factory=lambda body: {})
    client.graphql = respond
    publication = {"publicationId": PUBLICATION, "corpusKey": PUBLICATION}
    line = run_publication(client, publication, transport=StoryModel(), now=NOW, out_of_time=lambda: False, fetch=pages(1, 2), explorer=None)
    assert line["drafted"] == 2, line   # the recording covers filing and the review request too
    return set(recorded)


def granted_fields(api):
    """Every (Query|Mutation, field) the template grants the router role on `api`, from its managed policies and its inline policy."""
    template = _template()
    resources = template["Resources"]
    statements = []
    for resource in resources.values():
        props = resource.get("Properties") or {}
        if resource["Type"] == "AWS::IAM::ManagedPolicy" and ("Ref", "RouterRole") in (props.get("Roles") or []):
            statements += props["PolicyDocument"]["Statement"]
    statements += resources["RouterRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    granted = set()
    for statement in statements:
        for entry in statement["Resource"] if isinstance(statement.get("Resource"), list) else [statement.get("Resource")]:
            arn = entry[1] if isinstance(entry, tuple) else entry
            match = re.search(r"apis/\$\{" + api + r"\}/types/(Query|Mutation)/fields/(\w+)$", str(arn))
            if match:
                granted.add((match.group(1), match.group(2)))
    return granted


_template = tr._template


def test_monitor_stories_grant_covers_every_publication_api_the_hn_monitor_lists():
    resources_of = lambda name: [r[1] for r in _template()["Resources"][name]["Properties"]["PolicyDocument"]["Statement"][0]["Resource"]]   # noqa: E731
    template = _template()["Resources"]
    halves = ("RouterMonitorStoriesPolicy", "RouterMonitorStoriesSharedSitesPolicy", "RouterMonitorStoriesDistinctivePolicy")
    for name in halves:
        assert template[name]["Properties"]["Roles"] == [("Ref", "RouterRole")]
        assert len(template[name]["Properties"]["PolicyDocument"]["Statement"]) == 1
    resources = [r for name in halves for r in resources_of(name)]
    assert {r.split("apis/")[1].split("/")[0] for r in resources} == {"${" + api + "}" for api in (*PUBLICATION_APIS, "DistinctiveApiId")}
    assert "*" not in "".join(resources)
    needed = used_fields()
    assert {("Mutation", "fileProposal"), ("Query", "listStoryDrafts"), ("Mutation", "createReviewRequest"), ("Query", "getReviewRequest")} <= needed
    for api in (*PUBLICATION_APIS, "DistinctiveApiId"):
        granted_here = {tuple(r.split("types/")[1].split("/fields/")) for r in resources if f"apis/${{{api}}}/" in r}
        assert granted_here == needed, (api, sorted(needed ^ granted_here))   # explicit, complete and nothing more
        assert needed <= granted_fields(api), (api, sorted(needed - granted_fields(api)))


def test_every_managed_policy_of_the_router_fits_the_6144_character_limit():
    """IAM counts the characters of a managed policy without whitespace. Each AppSync ARN is measured with a real-length account and API id."""
    def measured(value):
        if isinstance(value, tuple):
            text = re.sub(r"\$\{(?:AWS::Partition)\}", "aws", value[1])
            text = re.sub(r"\$\{AWS::Region\}", "us-east-1", text)
            text = re.sub(r"\$\{AWS::AccountId\}", "712236451410", text)
            return re.sub(r"\$\{\w+\}", "x" * 26, text)
        if isinstance(value, dict):
            return {key: measured(item) for key, item in value.items()}
        if isinstance(value, list):
            return [measured(item) for item in value]
        return value
    for name, resource in _template()["Resources"].items():
        if resource["Type"] == "AWS::IAM::ManagedPolicy":
            document = json.dumps(measured(resource["Properties"]["PolicyDocument"]), separators=(",", ":"))
            assert len(re.sub(r"\s", "", document)) <= 6144, (name, len(document))


def test_distinctive_has_its_own_daily_monitor_stories_schedule():
    # The hn router does not list Distinctive Mark, so its web monitor runs the same task on its own schedule, at the same hour.
    resources = _template()["Resources"]
    hn, distinctive = resources["MonitorStoriesSchedule"]["Properties"], resources["DistinctiveMonitorStoriesSchedule"]["Properties"]
    assert json.loads(distinctive["Target"]["Input"]) == {"task": "monitor-stories", "monitorId": "web-distinctive"}
    assert distinctive["ScheduleExpression"] == hn["ScheduleExpression"]
    assert distinctive["Target"]["RetryPolicy"] == hn["Target"]["RetryPolicy"] == {"MaximumEventAgeInSeconds": 3600, "MaximumRetryAttempts": 0}
