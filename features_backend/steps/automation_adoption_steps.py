from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import automations as au  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore  # noqa: E402
from papyrus_content.automation_adoption import adopt  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

CALLERS = {"admin": Caller(kind="person", subject="ada", is_admin=True), "editor": Caller(kind="person", subject="ed"),
           "agent": Caller(kind="agent", subject="rating-agent", is_admin=True)}


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


@given('a site with the automation "{automation_id}" and no agent policy')
def site(context, automation_id):
    context.site, context.error, context.result = Site(), None, None
    record = au.build_record({"id": automation_id, "title": "TTAB ruling analysis", "enabled": True, "procedureKey": "distinctive.ttab.ruling-analysis",
                              "trigger": {"kind": "monitor", "config": {"monitorId": "ttab", "publicationId": "distinctive"}}}, actor="seed")
    context.site.rows[automation_id] = au.stored_payload(record)


@given('"{automation_id}" is adopted as "{responsibility}"')
def adopted(context, automation_id, responsibility):
    adopt(context.site, CALLERS["admin"], automation_id, responsibility, apply=True)
    context.site.writes = 0


def attempt(context, who, automation_id, responsibility, apply=True):
    context.error = None
    try:
        context.result = adopt(context.site, CALLERS[who], automation_id, responsibility, apply=apply)
    except au.AutomationError as error:
        context.error = error


@when('an admin adopts "{automation_id}" as "{responsibility}"')
def admin_adopts(context, automation_id, responsibility):
    attempt(context, "admin", automation_id, responsibility)


@when('an admin adopts "{automation_id}" as "{responsibility}" with a dry run')
def admin_dry_run(context, automation_id, responsibility):
    attempt(context, "admin", automation_id, responsibility, apply=False)


@when('an editor adopts "{automation_id}" as "{responsibility}"')
def editor_adopts(context, automation_id, responsibility):
    attempt(context, "editor", automation_id, responsibility)


@when('an agent adopts "{automation_id}" as "{responsibility}"')
def agent_adopts(context, automation_id, responsibility):
    attempt(context, "agent", automation_id, responsibility)


@when('an admin changes the title of "{automation_id}"')
def retitle(context, automation_id):
    au.update_automation(context.site, automation_id, {"title": "Renamed"}, actor="ada")


@then('the result says it would adopt "{automation_id}" as "{responsibility}"')
def would_adopt(context, automation_id, responsibility):
    assert context.error is None
    assert context.result["automationId"] == automation_id and context.result["responsibility"] == responsibility
    assert context.result["changed"] is True and context.result["applied"] is False


@then("the automation has no responsibility")
def none(context):
    (row,) = context.site.rows.values()
    assert not row.get("responsibility") and context.site.writes == 0


@then('the automation\'s responsibility is "{responsibility}"')
def has(context, responsibility):
    (row,) = context.site.rows.values()
    assert row["responsibility"] == responsibility


@then("the agent policy is still version 0")
def policy_untouched(context):
    assert context.site.policy.read("alpha").version == 0 and context.site.table.writes == []


@then("the result says there is nothing to change")
def nothing(context):
    assert context.error is None and context.result["changed"] is False and context.site.writes == 0


@then('the adoption is refused saying it is already adopted as "{responsibility}"')
def already(context, responsibility):
    assert context.error is not None and f"already adopted as {responsibility}" in str(context.error)


@then("the adoption is refused saying only an admin who is a person adopts")
def only_admin(context):
    assert context.error is not None and "only an admin who is a person adopts" in str(context.error)


@then('the adoption is refused saying "{name}" is not a responsibility')
def not_responsibility(context, name):
    assert context.error is not None and f"{name!r} is not a responsibility" in str(context.error)


@then("the adoption is refused saying automation {automation_id} does not exist")
def missing(context, automation_id):
    assert context.error is not None and f"automation {automation_id} does not exist" in str(context.error)
