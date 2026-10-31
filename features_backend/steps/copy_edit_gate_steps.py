from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from papyrus_content import editorial_checks as editorial  # noqa: E402
from papyrus_content.copy_edit import copy_edit_version  # noqa: E402
from test_story_reporting import LINEAGE, client_with_one_story  # noqa: E402



class SiteEditorialStore:
    """The editorial models of one site in memory, with the story client's Item table as the item store."""

    def __init__(self, client) -> None:
        self.client = client
        self.policies: dict[str, dict] = {}
        self.settings = None
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
        return sorted((run for run in self.check_runs.values() if run["lineageId"] == lineage_id), key=lambda run: -run["versionNumber"])[:limit]

    def get_settings(self):
        return self.settings

    def list_feedback(self):
        return []


class FakeGenerator:
    """Stands in for the rewrite model: two options for whatever sentence it is asked about."""

    def __init__(self) -> None:
        self.unavailable = False
        self.calls = 0

    def generate(self, **_kwargs):
        import humanus

        self.calls += 1
        if self.unavailable:
            raise humanus.SuggestUnavailableError("No provider key is configured.")
        return {"options": [
            {"replacement": "This is a release.", "rationale": "Plain.", "factVerificationRequired": False, "unresolvedQuestions": []},
            {"replacement": "This release ships.", "rationale": "Concrete.", "factVerificationRequired": False, "unresolvedQuestions": []},
        ]}


def _phrase_policy(key, phrase, severity, replacement=None):
    detector = {"id": f"{key}-phrase", "lane": "rules", "kind": "phrase", "phrases": [phrase]}
    if replacement:
        detector["replacement"] = replacement
    policy = {"id": key, "version": 1, "title": key, "guidance": f"Avoid {phrase}.", "severity": severity, "enabled": True, "detectors": [detector]}
    return editorial.record_from_policy(policy, scope="publication", source="test")


def _put(context, record):
    context.store.policies[record["id"]] = json.loads(json.dumps(editorial.policy_input(record)))


def _services(context):
    return editorial.Services(store=context.store, decision_model=None, generator=context.generator)


def _item(context, number):
    return next(row for row in context.client.tables["Item"].values() if row["versionNumber"] == number)


@given('a newsroom with a story drafted as "{body}"')
def step_site(context, body):
    context.client = client_with_one_story()
    context.client.tables["Item"][LINEAGE]["bodyMarkus"] = body
    context.client.tables["Item"][LINEAGE]["contentHash"] = f"hash-of:{body}"
    context.client.tables["Item"][LINEAGE]["stage"] = "copywriting"
    context.store = SiteEditorialStore(context.client)
    context.generator = FakeGenerator()
    context.results = []


@given('the story is redrafted as "{body}"')
def step_redraft(context, body):
    context.client.tables["Item"][LINEAGE]["bodyMarkus"] = body
    context.client.tables["Item"][LINEAGE]["contentHash"] = f"hash-of:{body}"


@given("the site policies are:")
def step_policies(context):
    for row in context.table:
        _put(context, _phrase_policy(row["key"], row["phrase"], row["severity"], row["replacement"] or None))


@given('the site has a policy "{key}" that wants contractions')
def step_contractions(context, key):
    policy = {"id": key, "version": 1, "title": key, "guidance": "Use contractions.", "severity": "warn", "enabled": True,
              "detectors": [{"id": f"{key}-check", "lane": "rules", "kind": "builtin", "check": "uncontracted_forms"}]}
    _put(context, editorial.record_from_policy(policy, scope="publication", source="test"))


@given("rewrite options cannot be produced because no provider key is configured")
def step_no_key(context):
    context.generator.unavailable = True


def _run(context, **options):
    outcome = copy_edit_version(context.client, _services(context), story=LINEAGE, **options)
    context.results.append(outcome)
    context.outcome = outcome


@when("the copy-edit step runs on the story")
def step_run(context):
    _run(context)


@when("the copy-edit step runs on the story and raises review requests")
def step_run_review(context):
    _run(context, raise_review=True)


@when("the copy-edit step runs on the story again")
def step_run_again(context):
    context.generator.calls = 0
    _run(context)


@when("the copy-edit step previews the story")
def step_preview(context):
    _run(context, dry_run=True)


@then('a new version 2 exists by "{author}" with the reason "{reason}"')
def step_version2(context, author, reason):
    row = _item(context, 2)
    assert row["versionCreatedBy"] == author and row["changeReason"] == reason, row


@then('version 2 reads "{body}"')
def step_reads(context, body):
    assert _item(context, 2)["bodyMarkus"] == body, _item(context, 2)["bodyMarkus"]


@then('the first version still reads "{body}"')
def step_first_reads(context, body):
    assert _item(context, 1)["bodyMarkus"] == body


def _run_findings(context):
    run = context.store.check_runs[_item(context, 2)["id"]]
    return run, run["findings"]


@then('the check of version 2 lists the finding for "{policy}" with {count:d} rewrite options')
def step_options(context, policy, count):
    _, findings = _run_findings(context)
    found = [f for f in findings if f["policyId"] == policy]
    assert len(found) == 1 and len(found[0]["suggest"]) == count, findings
    assert all(option["replacement"] for option in found[0]["suggest"]), found
    assert "This is a game-changing release." in _item(context, 2)["bodyMarkus"]  # options are stored, never applied


@then('the check of version 2 does not list a finding for "{policy}"')
def step_not_listed(context, policy):
    _, findings = _run_findings(context)
    assert all(f["policyId"] != policy for f in findings), findings


@then('the result holds the story because of "{policy}"')
def step_holds(context, policy):
    assert context.outcome["hold"] is True and policy in context.outcome["reason"], context.outcome


@then("the result does not hold the story")
def step_no_hold(context):
    assert context.outcome["hold"] is False, context.outcome


@then("one open flag review request about the story names version 2")
def step_flag(context):
    (request,) = context.client.tables["ReviewRequest"].values()
    subject = json.loads(request["subject"])
    assert request["mode"] == "flag" and request["state"] == "open" and subject == {"type": "story", "id": LINEAGE}, request
    assert _item(context, 2)["id"] in request["links"], request


@then("the story has only version 1")
def step_only_one(context):
    assert len(context.client.tables["Item"]) == 1


@then("the story has exactly {count:d} versions")
def step_exact(context, count):
    assert len(context.client.tables["Item"]) == count


@then("the second run is skipped as already copy-edited")
def step_skipped(context):
    assert context.results[-1].get("skipped") == "already copy-edited" and context.generator.calls == 0, context.results[-1]


@then('the preview lists a fix from "{old}" to "{new}"')
def step_preview_lists(context, old, new):
    fixes = context.outcome["mechanicalFixes"]
    assert context.outcome["dryRun"] and [(f["from"], f["to"]) for f in fixes] == [(old, new)], context.outcome


@then("the result says rewrite options are unavailable")
def step_unavailable(context):
    assert "unavailable" in context.outcome["rewriteOptions"], context.outcome


@then("version 2 has the stage of version 1 and is not published")
def step_stage(context):
    row = _item(context, 2)
    assert row["stage"] == _item(context, 1)["stage"] and row["status"] == "draft", row
    assert "PublishedItem" not in context.client.tables or not context.client.tables["PublishedItem"]
