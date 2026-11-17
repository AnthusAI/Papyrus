"""The registered copy of a definition on the Automation record (features_backend/agent-definition-registered-copy.feature). A fake site; no network."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import automations as au  # noqa: E402
from papyrus_content.agent_definitions import definition as agent_definition  # noqa: E402
from papyrus_content.agent_definitions.registered import digest, register  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402


class Site:
    """The site's Automation records as the API stores them (JSON fields as strings), and its agent policy document."""

    def __init__(self):
        self.rows, self.writes = {}, 0
        self.table = FakeTable()
        self.policy = AgentPolicyStore(SiteStore(FakeS3(), "bucket", self.table))

    def get_record(self, model, record_id):
        return self.rows.get(record_id)

    def update_record(self, model, payload):
        self.writes += 1
        self.rows[payload["id"]] = {**self.rows[payload["id"]], **payload}


def _shipped(name: str):
    loaded = agent_definition.load_sets(agent_definition.CORE_DIRECTORY)
    assert not loaded.problems, loaded.problems
    return loaded.get(name)


def _seed(context, automation_id: str, **extra):
    context.site, context.error, context.result = Site(), None, None
    record = au.build_record({"id": automation_id, "title": "Daily rating", "enabled": True, "procedureKey": "papyrus.rate-items",
                              "trigger": {"kind": "monitor", "config": {"monitorId": "daily", "publicationId": "alpha"}}, **extra}, actor="seed")
    context.site.rows[automation_id] = au.stored_payload(record)
    context.before = dict(context.site.rows[automation_id])


@given('a site with the automation "{automation_id}" and no registered definition')
def step_site(context, automation_id):
    _seed(context, automation_id)


@given('a site with the automation "{automation_id}" adopted as "{responsibility}" and disabled')
def step_site_adopted(context, automation_id, responsibility):
    _seed(context, automation_id, responsibility=responsibility, enabled=False)


def _register(context, automation_id, definition, apply=True):
    context.error = None
    context.writes_before = context.site.writes
    try:
        context.result = register(context.site, automation_id, definition, actor="release", apply=apply)
    except au.AutomationError as error:
        context.error = error


def _changed(name: str):
    shipped = _shipped(name)
    data = copy.deepcopy(shipped.data)
    data["template"]["measured"] = data["template"]["measured"] + " It is read weekly."
    return agent_definition.Definition(name, data, "core")


def _with_site_rule(name: str):
    shipped = _shipped(name)
    data = agent_definition.merge(shipped.data, {"mustNever": ["Rate an item from a source the site has rejected"]})
    return agent_definition.Definition(name, data, "core", extended=True)


@given('the definition "{name}" is registered on "{automation_id}"')
def step_given_registered(context, name, automation_id):
    _register(context, automation_id, _shipped(name))
    assert context.error is None
    context.site.writes = 0


@when('the definition "{name}" is registered on "{automation_id}"')
def step_registered(context, name, automation_id):
    _register(context, automation_id, _shipped(name))


@when('the definition "{name}" is registered on "{automation_id}" with a dry run')
def step_dry_run(context, name, automation_id):
    _register(context, automation_id, _shipped(name), apply=False)


@when('the definition "{name}" is changed and registered on "{automation_id}"')
def step_changed(context, name, automation_id):
    context.changed = _changed(name)
    _register(context, automation_id, context.changed)


@when('the definition "{name}" with a site must-never rule is registered on "{automation_id}"')
def step_site_rule(context, name, automation_id):
    _register(context, automation_id, _with_site_rule(name))


@when('the definition "{name}" is registered on "{automation_id}" with its fields in another order')
def step_reordered(context, name, automation_id):
    data = _shipped(name).data
    reordered = {key: data[key] for key in reversed(list(data))}
    reordered["template"] = {key: data["template"][key] for key in reversed(list(data["template"]))}
    _register(context, automation_id, agent_definition.Definition(name, reordered, "core"))


def _row(context, automation_id):
    return au.read_record(context.site.rows[automation_id])


@then('the automation "{automation_id}" holds the registered definition "{name}" at version {version:d}')
def step_holds(context, automation_id, name, version):
    record = _row(context, automation_id)
    assert (record["definitionId"], record["definitionVersion"]) == (name, version), record


@then('the registered digest of "{automation_id}" is the digest of the definition "{name}"')
def step_digest(context, automation_id, name):
    assert _row(context, automation_id)["definitionDigest"] == digest(_shipped(name).data)


@then('the registered digest of "{automation_id}" is the digest of the changed definition')
def step_digest_changed(context, automation_id):
    assert _row(context, automation_id)["definitionDigest"] == digest(context.changed.data)


@then('the registered copy on "{automation_id}" is the definition "{name}"')
def step_copy(context, automation_id, name):
    assert _row(context, automation_id)["definition"] == _shipped(name).data


@then('the registered copy on "{automation_id}" is the changed definition')
def step_copy_changed(context, automation_id):
    assert _row(context, automation_id)["definition"] == context.changed.data


@then('the registration says "{action}"')
def step_action(context, action):
    assert context.error is None and context.result["action"] == action, (context.error, context.result)


@then('the registration says "{action}" and is not applied')
def step_not_applied(context, action):
    assert context.result["action"] == action and context.result["applied"] is False


@then("no record was written")
def step_no_write(context):
    assert context.site.writes == 0


@then('the automation "{automation_id}" holds no registered definition')
def step_none(context, automation_id):
    record = _row(context, automation_id)
    assert record["definitionId"] is None and record["definitionDigest"] is None and record["definition"] is None


@then('the automation "{automation_id}" is still adopted as "{responsibility}" and disabled')
def step_still(context, automation_id, responsibility):
    record = _row(context, automation_id)
    assert record["responsibility"] == responsibility and record["enabled"] is False


@then('the automation "{automation_id}" has its trigger and procedure as before')
def step_trigger(context, automation_id):
    now = context.site.rows[automation_id]
    assert all(now[key] == context.before[key] for key in ("trigger", "procedureKey", "title", "inputTemplate", "limits")), now


@then("the site's agent policy document was not touched")
def step_policy(context):
    assert context.site.policy.read("alpha").version == 0 and context.site.table.writes == []


@then('the registration is refused saying "{words}"')
def step_refused(context, words):
    assert context.error is not None and words in str(context.error), context.error


@then('the record read for "{automation_id}" shows the registered definition "{name}" at version {version:d} with its digest and copy')
def step_read(context, automation_id, name, version):
    record = au.read_record(json.loads(json.dumps(context.site.rows[automation_id])))
    assert record["definitionId"] == name and record["definitionVersion"] == version
    assert record["definitionDigest"] == digest(_shipped(name).data) and record["definition"] == _shipped(name).data
