"""A deploy applies the agent definitions (features_backend/agent-definitions-on-release.feature). A fake site; no network."""
from __future__ import annotations

import copy
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import automations as au  # noqa: E402
from papyrus_content.agent_definitions import definition as agent_definition  # noqa: E402
from papyrus_content.agent_definitions import release  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore, decide_start  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

TENANT = "alpha"
ADMIN = Caller(kind="person", subject="ada", is_admin=True)
CORE_PROCEDURES = {"rate_items"}


class Site:
    """The site's Automation records as the API stores them (JSON fields as strings), and its agent policy document."""

    def __init__(self):
        self.rows, self.writes = {}, 0
        self.s3, self.table = FakeS3(), FakeTable()
        self.policy = AgentPolicyStore(SiteStore(self.s3, "bucket", self.table, now=lambda: "2026-11-17T00:00:00Z"))

    def list_tenant_rows(self, model, fields):
        assert model == "Automation"
        return [dict(row) for row in self.rows.values()]

    def get_record(self, model, record_id):
        return self.rows.get(record_id)

    def create_record(self, model, payload):
        assert payload["id"] not in self.rows, "created twice"
        self.writes += 1
        self.rows[payload["id"]] = dict(payload)

    def update_record(self, model, payload):
        self.writes += 1
        self.rows[payload["id"]] = {**self.rows[payload["id"]], **payload}


def _fresh(context):
    context.site, context.error, context.report = Site(), None, {}
    context.policy_before = (None, [], {})
    context.work = Path(tempfile.mkdtemp(prefix="agents-release-"))
    context.core_dir, context.site_dir = context.work / "core", context.work / "site"
    shutil.copytree(agent_definition.CORE_DIRECTORY, context.core_dir, ignore=shutil.ignore_patterns(".*"))
    context.site_dir.mkdir()
    context.procedures = set(CORE_PROCEDURES)
    context.tmp_dirs = getattr(context, "tmp_dirs", []) + [context.work]


def _write_site_definition(context, name, responsibility="rate", procedure="rate_items"):
    data = yaml.safe_load((agent_definition.CORE_DIRECTORY / "rate.yaml").read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    data.update(id=name, responsibility=responsibility, procedure=procedure)
    (context.site_dir / f"{name}.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _deploy(context, *, apply=True, check=False):
    context.error, context.report, context.writes_before = None, {}, context.site.writes
    try:
        definitions = release.load(context.site_dir, context.core_dir)
        if check:
            results = release.check_drift(context.site, definitions, context.procedures)
        else:
            results = release.apply_release(context.site, definitions, context.procedures, apply=apply, now="2026-11-17T04:00:00Z")
        context.report = {entry["definitionId"]: entry["status"] for entry in results}
    except release.ReleaseError as error:
        context.error = error


def _seed(context, automation_id, *, procedure="rate_items", **extra):
    record = au.build_record({"id": automation_id, "title": "Daily rating", "enabled": extra.pop("enabled", True), "procedureKey": procedure,
                              "trigger": {"kind": "schedule", "config": {}}, **extra}, actor="seed")
    context.site.rows[automation_id] = au.stored_payload(record)


def _row(context, automation_id):
    return au.read_record(context.site.rows[automation_id])


@given("a site with no automations and no agent policy")
def step_empty_site(context):
    _fresh(context)


@given('a site with the automation "{automation_id}" adopted as "{responsibility}" and enabled')
def step_adopted(context, automation_id, responsibility):
    _fresh(context)
    _seed(context, automation_id, responsibility=responsibility)


@given('a site with the automation "{automation_id}" that runs the procedure "{procedure}" and holds no definition')
def step_other_automation(context, automation_id, procedure):
    _fresh(context)
    _seed(context, automation_id, procedure=procedure)
    context.procedures.add(procedure)


@given('a site whose agent policy sets the responsibility "{responsibility}" to "{rung}", paused with a reason, and a weekly budget')
def step_policy(context, responsibility, rung):
    _fresh(context)
    policy = context.site.policy
    policy.set_rung(TENANT, ADMIN, responsibility, rung, reason="the rating policy")
    policy.pause(TENANT, ADMIN, reason="an audit", responsibility=responsibility)
    policy.set_value(TENANT, ADMIN, "budget", {"amountUsd": 10, "period": "week"}, reason="a budget")
    context.policy_before = (policy.read(TENANT), list(context.site.table.writes), dict(context.site.s3.objects))


@given('the site folder holds the complete definition "{name}" for the responsibility "{responsibility}"')
def step_site_definition(context, name, responsibility):
    _write_site_definition(context, name, responsibility)


@given('the site folder holds the definition "{name}" that runs the procedure "{procedure}" for the responsibility "{responsibility}"')
def step_site_definition_procedure(context, name, responsibility, procedure):
    _write_site_definition(context, name, responsibility, procedure)


@given('the site registers the procedure "{procedure}"')
def step_site_registers(context, procedure):
    context.procedures.add(procedure)


@given('the site folder holds a definition "{name}" with no must-never line')
def step_invalid(context, name):
    _write_site_definition(context, name)
    path = context.site_dir / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["template"]["mustNever"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@given('the deploy has applied the core definition "{name}"')
def step_given_core(context, name):
    _deploy(context)
    assert context.error is None, context.error
    context.site.writes = 0


@given("the deploy has applied the core and site definitions")
def step_given_both(context):
    _deploy(context)
    assert context.error is None, context.error
    context.site.writes = 0


@given('the site folder no longer holds the definition "{name}"')
def step_removed_given(context, name):
    (context.site_dir / f"{name}.yaml").unlink()


@given('the site folder no longer holds the definition "{name}" and the deploy has applied the definitions')
def step_removed_applied(context, name):
    (context.site_dir / f"{name}.yaml").unlink()
    _deploy(context)
    assert context.error is None, context.error
    context.site.writes = 0


@when('the deploy applies the core definition "{name}"')
def step_apply_core(context, name):
    _deploy(context)


@when("the deploy applies the core and site definitions")
def step_apply_both(context):
    _deploy(context)


@when("the deploy applies the definitions again")
def step_apply_again(context):
    _deploy(context)


@when('the deploy applies the core definition "{name}" with a changed template line')
def step_apply_changed(context, name):
    path = context.core_dir / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["template"]["measured"] += " It is read weekly."
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _deploy(context)


@when('the deploy applies the core definition "{name}" with a site must-never rule')
def step_apply_site_rule(context, name):
    (context.site_dir / f"{name}.yaml").write_text(
        yaml.safe_dump({"extends": name, "mustNever": ["Rate an item from a source the site has rejected"]}, sort_keys=False), encoding="utf-8")
    _deploy(context)


@when('the site folder no longer holds the definition "{name}" and the deploy applies the definitions')
def step_when_removed(context, name):
    (context.site_dir / f"{name}.yaml").unlink()
    _deploy(context)


@when('the site folder holds the complete definition "{name}" again and the deploy applies the definitions')
def step_when_returned(context, name):
    _write_site_definition(context, name)
    _deploy(context)


@when("the deploy plans the core and site definitions without applying them")
def step_plan(context):
    _deploy(context, apply=False)


@when("the agent drift check runs")
def step_check(context):
    _deploy(context, check=True)


@then('the automation "{automation_id}" exists and is disabled')
def step_exists_disabled(context, automation_id):
    assert _row(context, automation_id)["enabled"] is False


@then('the automation "{automation_id}" is disabled')
@then('the automation "{automation_id}" is still disabled')
def step_disabled(context, automation_id):
    assert _row(context, automation_id)["enabled"] is False


@then('the automation "{automation_id}" is marked retired')
def step_retired(context, automation_id):
    assert _row(context, automation_id)["definitionRetiredAt"]


@then('the automation "{automation_id}" is not marked retired')
def step_not_retired(context, automation_id):
    assert not _row(context, automation_id)["definitionRetiredAt"]


@then('the automation "{automation_id}" still holds the registered definition "{name}" at version {version:d}')
def step_holds(context, automation_id, name, version):
    record = _row(context, automation_id)
    assert (record["definitionId"], record["definitionVersion"]) == (name, version), record
    assert record["definition"]["id"] == name


@then('the automation "{automation_id}" is adopted as "{responsibility}" and is enabled')
def step_adopted_kept(context, automation_id, responsibility):
    record = _row(context, automation_id)
    assert (record["responsibility"], record["enabled"]) == (responsibility, True), record


@then('the automation "{automation_id}" has no adopted responsibility')
def step_not_adopted(context, automation_id):
    assert _row(context, automation_id)["responsibility"] is None


@then('the deploy reports "{definition_id}" as {status}')
def step_reports(context, definition_id, status):
    assert context.error is None, context.error
    assert context.report.get(definition_id) == status, context.report


@then("the deploy wrote nothing")
def step_no_writes(context):
    assert context.site.writes == context.writes_before, (context.site.writes, context.writes_before)


@then('the policy would not start a run of the responsibility "{responsibility}" and says it is off')
def step_off(context, responsibility):
    decision = decide_start(context.site.policy.read(TENANT), responsibility)
    assert not decision.start and decision.reason_code == "off", decision


@then("the agent policy document was not written")
def step_policy_untouched(context):
    assert context.site.table.writes == context.policy_before[1]
    assert context.site.s3.objects == context.policy_before[2]


@then("the agent policy document is at the same version with the same rung, pause and budget")
def step_policy_same(context):
    before = context.policy_before[0]
    after = context.site.policy.read(TENANT)
    assert (after.version, after.document) == (before.version, before.document)
    assert after.document["agents"]["rate"] == {"rung": "propose", "paused": True, "pausedReason": "an audit"}
    assert after.document["site"]["budget"] == {"amountUsd": 10, "period": "week"}


@then('the registered schedules are those of "{first}" and "{second}"')
def step_schedules_two(context, first, second):
    assert set(release.registered_schedules(list(context.site.rows.values()))) == {first, second}


@then('the registered schedules are those of "{only}" alone')
def step_schedules_one(context, only):
    found = release.registered_schedules(list(context.site.rows.values()))
    assert set(found) == {only} and found[only]["cron"], found


@then('the deploy stops and names the definition "{name}" and the line "{line}"')
def step_stops_named(context, name, line):
    assert context.error is not None and name in str(context.error) and line in str(context.error), context.error


@then('the deploy stops and says the procedure "{procedure}" of "{name}" is not registered')
def step_stops_procedure(context, procedure, name):
    text = str(context.error)
    assert context.error is not None and f"{name}: the procedure {procedure} is not registered" in text, text


@then('the deploy stops and says the automation "{automation_id}" runs the procedure "{procedure}" and is not an agent the deploy created')
def step_stops_other(context, automation_id, procedure):
    text = str(context.error)
    assert f"the automation {automation_id} runs the procedure {procedure}" in text and "not an agent the deploy created" in text, text


@then('the deploy stops and names the automation "{automation_id}"')
def step_stops_automation(context, automation_id):
    assert context.error is not None and f"automation {automation_id} is adopted as select" in str(context.error), context.error


@then("the agent check passes")
def step_check_passes(context):
    assert context.error is None, context.error


@then('the agent check fails and names "{definition_id}" as to be retired')
def step_check_fails(context, definition_id):
    assert isinstance(context.error, release.ReleaseDriftError), context.error
    assert f"{definition_id} is gone from Git and not yet retired" in str(context.error), context.error
