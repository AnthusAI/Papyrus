from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from papyrus_content import editorial_checks as editorial  # noqa: E402
from papyrus_newsroom import tactus_tools  # noqa: E402
from test_story_reporting import LINEAGE, client_with_one_story  # noqa: E402


class SiteEditorialStore:
    """The editorial models of one site in memory, with the story client's Item table as the item store."""

    def __init__(self, client) -> None:
        self.client = client
        self.policies: dict[str, dict] = {}
        self.settings: dict | None = None
        self.check_runs: dict[str, dict] = {}

    def list_policies(self):
        return [dict(record) for record in self.policies.values()]

    def get_editorial_context(self, section):
        from papyrus_content.editorial_context import build_context

        entries = [
            {"scope": "publication", "kind": "mission", "text": "Synthetic mission", "source": {"id": "synthetic-mission"}},
            {"scope": "publication", "kind": "policy", "text": "Synthetic private guidance", "source": {"id": "synthetic-policy"}},
        ]
        return build_context({"key": "synthetic"}, {"sectionId": section}, entries, mode="cloud", missing_publication_doctrine=[], missing_section_configuration=[])

    def publication_key(self):
        return "synthetic"

    def get_item(self, item_id):
        return self.client.get_record("Item", item_id)

    def put_check_run(self, record):
        self.check_runs[record["id"]] = json.loads(json.dumps(record))

    def get_check_run(self, item_id):
        return self.check_runs.get(item_id)

    def list_check_runs_by_lineage(self, lineage_id, limit):
        runs = [run for run in self.check_runs.values() if run["lineageId"] == lineage_id]
        return sorted(runs, key=lambda run: -run["versionNumber"])[:limit]

    def get_settings(self):
        return self.settings

    def list_feedback(self):
        return []


def site_graphql(context):
    """What AppSync does for the two operations the tool calls: route checkItemVersion to the function, read the stored run."""

    def graphql(query, variables=None):
        if "checkItemVersion" in query:
            if getattr(context, "checks_fail", False):
                raise RuntimeError("The language-model provider did not respond.")
            services = editorial.Services(store=context.store, decision_model=None, generator=None)
            result = editorial.handle("checkItemVersion", variables, services)
            context.function_asked_humanus = getattr(context, "function_asked_humanus", 0) + (1 if services.last_check_request else 0)
            for extra in getattr(context, "whole_document_findings", []):
                run = context.store.check_runs[variables["itemId"]]
                run["findings"].append(extra)
                run["reviews"] = int(run.get("reviews") or 0) + 1
            return {"checkItemVersion": json.dumps(json.dumps(result))}
        run = context.store.check_runs.get(variables["id"])
        if run is None:
            return {"getEditorialCheckRun": None}
        return {"getEditorialCheckRun": {**run, "findings": json.dumps(run["findings"]), "lanes": json.dumps(run["lanes"])}}

    return graphql


def run_tool(context, **kwargs):
    context.tool_error = None
    context.tool_result = None
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(context.client, None)), mock.patch("time.sleep"):
        try:
            context.tool_result = tactus_tools.papyrus_check_story_version(wait_seconds=0, **kwargs)
        except ValueError as error:
            context.tool_error = error


@given('a site with a story whose first draft reads "{body}"')
def step_site(context, body):
    context.client = client_with_one_story()
    context.client.tables["Item"][LINEAGE]["bodyMarkus"] = body
    context.client.tables["Item"][LINEAGE]["contentHash"] = f"hash-of:{body}"
    context.store = SiteEditorialStore(context.client)
    context.client.graphql = site_graphql(context)


@given('the publication has an enabled policy "{key}" that flags "{phrase}"')
def step_policy(context, key, phrase):
    policy = {
        "id": key, "version": 1, "title": key, "guidance": f"Avoid {phrase}.", "severity": "warn", "enabled": True,
        "detectors": [{"id": f"{key}-phrase", "lane": "rules", "kind": "phrase", "phrases": [phrase]}],
    }
    record = editorial.record_from_policy(policy, scope="publication", source="test")
    context.store.policies[record["id"]] = json.loads(json.dumps(editorial.policy_input(record)))


@given('the stored check also holds a review finding for rule "{rule}" that quotes nothing')
def step_whole_document(context, rule):
    context.whole_document_findings = [{"id": f"{rule}-1", "policyId": rule, "severity": "info", "status": "review",
                                        "message": "The first paragraph should state the meaning.", "excerpt": "", "probability": 0.6}]


@given("the publication turned editorial checks off")
def step_off(context):
    context.store.settings = {"id": "settings", "settings": json.dumps({"enabled": False})}


@when("the procedure checks the story's first version")
def step_check_first(context):
    run_tool(context, story=LINEAGE, version_number=1)


@when("the procedure checks the story's newest version")
def step_check_newest(context):
    run_tool(context, story=LINEAGE)


@when('the procedure checks the version "{version}"')
def step_check_named(context, version):
    run_tool(context, version=version)


@when('the procedure saves a fixed version reading "{body}"')
def step_save(context, body):
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(context.client, None)):
        context.saved = tactus_tools.papyrus_save_story_version(LINEAGE, body, "Fix the copy-edit findings", "Copy editor")


@then('the check status is "{status}" and the version is {clean}')
def step_status(context, status, clean):
    assert context.tool_error is None, context.tool_error
    assert context.tool_result["status"] == status, context.tool_result
    assert context.tool_result["clean"] is (clean == "clean"), context.tool_result


@then('there is 1 finding for rule "{rule}" quoting "{quote}"')
def step_finding(context, rule, quote):
    findings = context.tool_result["findings"]
    assert [(f["rule"], f["quote"]) for f in findings] == [(rule, quote)], findings
    assert findings[0]["id"] and findings[0]["message"] and findings[0]["severity"], findings


@then('the finding for rule "{rule}" is marked as about the whole document')
def step_document_scope(context, rule):
    found = {f["rule"]: f for f in context.tool_result["findings"]}
    assert found[rule]["scope"] == "document" and not found[rule]["quote"], found[rule]


@then('the finding for rule "{rule}" is marked as a quote finding')
def step_quote_scope(context, rule):
    found = {f["rule"]: f for f in context.tool_result["findings"]}
    assert found[rule]["scope"] == "quote" and found[rule]["quote"], found[rule]


@then("the result names version {number:d} and the policy pack version that was used")
def step_names_pack(context, number):
    assert context.tool_result["versionNumber"] == number
    assert context.tool_result["versionId"] == LINEAGE
    assert context.tool_result["packVersion"], context.tool_result
    assert context.tool_result["lanes"]["rules"], context.tool_result


@then("the result names version {number:d} and there are no findings")
def step_names_none(context, number):
    assert context.tool_result["versionNumber"] == number
    assert context.tool_result["versionId"] == context.saved["versionId"]
    assert context.tool_result["findings"] == []


@then("the first version still has its stored findings")
def step_first_kept(context):
    assert context.store.check_runs[LINEAGE]["violations"] == 1


@then('the check is refused as "{message}"')
def step_refused(context, message):
    assert context.tool_error is not None and message in str(context.tool_error), context.tool_error


@given("checking a saved version will fail")
def step_checks_fail(context):
    context.checks_fail = True


@then("the save reports an editorial check of version {number:d} with no violations")
def step_save_checked(context, number):
    check = context.saved["editorialCheck"]
    assert check["versionNumber"] == number and check["violations"] == 0 and "notChecked" not in check, context.saved


@then("version {number:d} has a stored check")
def step_has_stored_check(context, number):
    assert context.store.get_check_run(f"{LINEAGE}-v{number}") is not None, list(context.store.check_runs)


@then("the save succeeded as version {number:d} and reports that the version was not checked")
def step_save_survived(context, number):
    assert context.saved["versionNumber"] == number and context.saved["editorialCheck"].get("notChecked"), context.saved


@then("the function checked the first version only once")
def step_checked_once(context):
    assert context.function_asked_humanus == 1, context.function_asked_humanus
