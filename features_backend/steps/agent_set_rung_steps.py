from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.agent_definitions import cli as agents_cli  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore, decide_start  # noqa: E402
from papyrus_content.agent_policy.catalogue import SiteCatalogueTable  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3  # noqa: E402

TENANT, BUCKET = "alpha", "site-bucket"
PEOPLE = {"admin": Caller(kind="person", subject="ada", is_admin=True), "editor": Caller(kind="person", subject="ed"),
          "agent": Caller(kind="agent", subject="rating-agent"),
          # An agent running in a person's signed-in session: identify() gives it the session's label and whether the token is an admin's.
          "agent in ada's session": Caller(kind="agent", subject="ada", is_admin=True), "agent in ed's session": Caller(kind="agent", subject="ed")}
SITE_DEFINITIONS = REPO_ROOT / "src" / "papyrus_content" / "agent_definitions" / "core"


class SiteApi:
    """The site's GraphQL API as far as the site store's catalogue uses it: the two site-document models, with their conditions."""

    def __init__(self):
        self.rows = {"SiteDocument": {}, "SiteDocumentVersion": {}}
        self.before_save = None
        self.requests = []   # every request the store sent, as the real schema is asked to validate it (scripts/graphql-operations-contract.mts)

    def graphql(self, query, variables=None):
        variables = variables or {}
        self.requests.append({"query": query, "variables": variables})
        for model in ("SiteDocumentVersion", "SiteDocument"):
            if f"get{model}(" in query:
                return {f"get{model}": self.rows[model].get(variables["id"])}
        if "listSiteDocumentVersionsByDocument" in query:
            rows = [row for row in self.rows["SiteDocumentVersion"].values() if row["documentId"] == variables["documentId"]]
            assert "sortDirection: DESC" in query and "limit: 1" in query, "the latest version is one query, highest first"
            rows.sort(key=lambda row: -row["version"])
            return {"listSiteDocumentVersionsByDocument": {"items": rows[:1]}}
        match = re.search(r"mutation (Create|Update)(SiteDocumentVersion|SiteDocument)", query)
        assert match, query
        verb, model = match.groups()
        if self.before_save and model == "SiteDocumentVersion":
            hook, self.before_save = self.before_save, None
            hook()
        table, row = self.rows[model], variables["input"]
        if verb == "Create":
            assert "condition" not in variables, "a create names no condition: the model's create already refuses an existing key"
            if row["id"] in table:
                raise RuntimeError("The conditional request failed (ConditionalCheckFailed)")
            table[row["id"]] = dict(row)
        else:
            stored = table[row["id"]]
            if any(stored[name] != check["eq"] for name, check in (variables["condition"] or {}).items()):
                raise RuntimeError("The conditional request failed (ConditionalCheckFailed)")
            stored.update(row)
        return {}


class Client:
    tenant_id = TENANT

    def __init__(self, api):
        self.api = api

    def graphql(self, query, variables=None):
        return self.api.graphql(query, variables)


def _fresh(context):
    context.api, context.s3 = SiteApi(), FakeS3()
    clock = iter(f"2026-11-17T00:{minute:02d}:00Z" for minute in range(60))
    context.store = AgentPolicyStore(SiteStore(context.s3, BUCKET, SiteCatalogueTable(context.api), now=lambda: next(clock)))
    context.policy = context.store   # the steps of agent-policy.feature (a wake that starts nothing) read it from here
    context.refusal, context.skipped = None, []
    context.definitions_dir = None
    context.envelope = None
    context.exit_code = None


def _run(context, who, agent, rung, *, reason, apply=False, scope=None, extra=()):
    argv = ["--id", agent, "--rung", rung, *extra]
    if reason is not None:
        argv += ["--reason", reason]
    for item in (scope.split(",") if scope else []):
        argv += ["--scope", item]
    if apply:
        argv.append("--apply")
    if context.definitions_dir:
        argv += ["--dir", str(context.definitions_dir)]
    out = io.StringIO()
    context.exit_code = agents_cli.set_rung_command(
        argv, out, client_factory=lambda: Client(context.api), policy_factory=lambda client: context.store, caller_factory=lambda client, caller: PEOPLE[who])
    context.envelope = json.loads(out.getvalue())


def _state(context):
    return context.store.read(TENANT)


@given("a site with no agent policy saved yet")
def never_saved(context):
    _fresh(context)


@given('a site where "{agent}" was set to "{rung}" with the command')
def seeded(context, agent, rung):
    _fresh(context)
    _run(context, "admin", agent, rung, reason="Seed", apply=True)
    assert context.exit_code == 0, context.envelope


@given('a site definition "{name}" whose operations reach publish_auto')
def top_definition(context, name):
    folder = Path(tempfile.mkdtemp(prefix="set-rung-"))
    text = (SITE_DEFINITIONS / "rate.yaml").read_text(encoding="utf-8")
    text = text.replace("id: rate\n", f"id: {name}\n", 1).replace("ratings_set: draft", "ratings_set: publish_auto")
    (folder / f"{name}.yaml").write_text(text, encoding="utf-8")
    context.definitions_dir = folder


@given("another admin saves the policy while the change is being made")
def racing(context):
    context.api.before_save = lambda: context.store._store.save(
        TENANT, "agents", {"schemaVersion": 1, "site": {}, "agents": {"improve": {"rung": "draft"}}}, "bea", note="Somebody else")


@when('an admin runs set-rung for "{agent}" to "{rung}" because "{reason}"')
def admin_dry(context, agent, rung, reason):
    _run(context, "admin", agent, rung, reason=reason)


@when('an admin runs set-rung for "{agent}" to "{rung}" because "{reason}" and applies it')
def admin_apply(context, agent, rung, reason):
    _run(context, "admin", agent, rung, reason=reason, apply=True)


@when('an admin applies set-rung to "{rung}" for "{agent}" within the scope "{scope}" because "{reason}"')
def admin_scope(context, rung, agent, scope, reason):
    _run(context, "admin", agent, rung, reason=reason, apply=True, scope=scope)


@when('an admin runs set-rung for "{agent}" to "{rung}" with no reason')
def admin_no_reason(context, agent, rung):
    _run(context, "admin", agent, rung, reason=None, apply=True)


@when('an editor runs set-rung for "{agent}" to "{rung}" because "{reason}" and applies it')
def editor_apply(context, agent, rung, reason):
    _run(context, "editor", agent, rung, reason=reason, apply=True)


@when('an editor runs set-rung for "{agent}" to "{rung}" because "{reason}"')
def editor_dry(context, agent, rung, reason):
    _run(context, "editor", agent, rung, reason=reason)


@when('an agent runs set-rung for "{agent}" to "{rung}" because "{reason}" and applies it')
def agent_apply(context, agent, rung, reason):
    _run(context, "agent", agent, rung, reason=reason, apply=True)


def _refused(context, code):
    assert context.exit_code != 0 and context.envelope["ok"] is False, context.envelope
    assert context.envelope["error"]["code"] == code, context.envelope
    return context.envelope["error"]["message"]


@then("the command succeeds as a dry run")
def dry(context):
    assert context.exit_code == 0 and context.envelope["result"]["action"] == "dry-run" and not context.envelope["result"]["applied"], context.envelope


@then("the command succeeds and applied the change")
def applied(context):
    assert context.exit_code == 0 and context.envelope["result"]["applied"] and context.envelope["result"]["changed"], context.envelope


@then("the command succeeds and said nothing changed")
def unchanged(context):
    assert context.exit_code == 0 and not context.envelope["result"]["changed"] and not context.envelope["result"]["applied"], context.envelope
    assert context.envelope["warnings"], "it says nothing was written"


def _side(context, which, agent, version):
    side = context.envelope["result"][which]
    assert side["policyVersion"] == int(version), side
    return side["entry"]


@then('it shows "{agent}" before as not named at policy version {version:d}')
def before_unnamed(context, agent, version):
    assert _side(context, "before", agent, version) is None


@then('it shows "{agent}" before at "{rung}" as policy version {version:d}')
def before_at(context, agent, rung, version):
    assert _side(context, "before", agent, version)["rung"] == rung


@then('it shows "{agent}" after at "{rung}" as policy version {version:d}')
def after_at(context, agent, rung, version):
    assert _side(context, "after", agent, version)["rung"] == rung


@then("the site's policy is still version {version:d}")
def still(context, version):
    assert _state(context).version == version


@then('the site\'s policy is version {version:d} and "{agent}" is at "{rung}"')
def version_and_rung(context, version, agent, rung):
    state = _state(context)
    assert state.version == version and state.document["agents"][agent]["rung"] == rung, state


@then('version {version:d} records the admin "{who}" and the reason "{reason}"')
def recorded(context, version, who, reason):
    record = context.store.version_record(TENANT, version)
    assert record["by"] == who and record["reason"] == reason and record["at"], record


@then('version {version:d} of the policy still holds "{agent}" at "{rung}"')
def history(context, version, agent, rung):
    assert context.store._store.read_version(TENANT, "agents", version)["agents"][agent]["rung"] == rung


@then('"{agent}" is at "{rung}" for the section "{section}"')
def scoped(context, agent, rung, section):
    from papyrus_content.agent_policy import effective
    found = effective(_state(context), agent, {"section": section})
    assert (found.rung, found.source) == (rung, "override"), found


@then("the command is refused as invalid input saying the rung must be one of the ladder")
def bad_rung(context):
    message = _refused(context, "invalid_input")
    assert "must be one of: off, observe, propose, draft, prepare, publish_soft, publish_auto" in message, message


@then("the command is refused as invalid input naming the agents there are")
def bad_agent(context):
    message = _refused(context, "invalid_input")
    assert "poet is not an agent definition" in message and "rate" in message, message


@then('the command is refused as a constraint conflict saying the rating agent needs no more than "{rung}"')
def above_ceiling(context, rung):
    message = _refused(context, "constraint_conflict")
    assert f"needs more than {rung}" in message and f"Set it to {rung} or lower" in message, message


@then("the command is refused as a constraint conflict saying a hard floor forbids publish_auto")
def floor(context):
    message = _refused(context, "constraint_conflict")
    assert "hard floor" in message and "publish_auto" in message and "stops automatic publishing" in message, message


@then("the command is refused as invalid input asking for --reason")
def no_reason(context):
    assert "--reason" in _refused(context, "invalid_input")


@then("the command is refused as not authorized")
def not_authorized(context):
    _refused(context, "not_authorized")


@then("the command is refused as blocked")
def blocked(context):
    _refused(context, "blocked")


@then("the command is refused as a stale version")
def stale(context):
    _refused(context, "stale_version")


@then("the policy holds only the other admin's version")
def only_other(context):
    state = _state(context)
    assert state.version == 1 and "rate" not in state.document["agents"], state


@then('a wake for "{agent}" starts under policy version {version:d} at the rung "{rung}"')
def wake_starts(context, agent, version, rung):
    decision = decide_start(_state(context), agent, {})
    assert decision.start and (decision.policy_version, decision.rung) == (version, rung), decision


@then("every request the site store sent is accepted by the GraphQL schema Amplify generates from the data schema")
def requests_match_schema(context):
    assert context.api.requests, "the scenario sent no request"
    with tempfile.TemporaryDirectory() as folder:
        operations = Path(folder) / "operations.json"
        operations.write_text(json.dumps(context.api.requests))
        run = subprocess.run(["npx", "tsx", "scripts/graphql-operations-contract.mts", str(operations)], cwd=REPO_ROOT, capture_output=True, text=True)
    verdicts = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    assert len(verdicts) == len(context.api.requests), run.stderr[-2000:] or run.stdout[-2000:]
    rejected = [verdict for verdict in verdicts if verdict["problems"]]
    assert not rejected, "the schema refuses: " + json.dumps(rejected, indent=2)
    context.verdict_operations = {verdict["operation"] for verdict in verdicts}


@then("the requests include a conditional update, a create and a latest-version query")
def requests_cover_kinds(context):
    assert {"UpdateSiteDocumentIf", "CreateSiteDocument", "CreateSiteDocumentVersion", "LatestSiteDocumentVersion"} <= context.verdict_operations, context.verdict_operations


def _delegated(context, session, agent, rung, person, quote, *, name="Claude"):
    _run(context, f"agent in {session}'s session", agent, rung, reason="Test", apply=True, extra=["--on-instruction-of", person, "--quote", quote, "--agent", name])


@when('an agent in ada\'s session sets "{agent}" to "{rung}" on the instruction of "{person}" who said "{quote}"')
def delegated_ada(context, agent, rung, person, quote):
    _delegated(context, "ada", agent, rung, person, quote)


@when('an agent in ed\'s session sets "{agent}" to "{rung}" on the instruction of "{person}" who said "{quote}"')
def delegated_ed(context, agent, rung, person, quote):
    _delegated(context, "ed", agent, rung, person, quote)


@when('an agent in ada\'s session sets "{agent}" to "{rung}" without naming anyone')
def delegated_nobody(context, agent, rung):
    _run(context, "agent in ada's session", agent, rung, reason="Test", apply=True)


@then('the policy version {version:d} says it was saved by "{by}" and its reason holds "{words}"')
def saved_by(context, version, by, words):
    record = context.store.version_record(TENANT, version)
    assert record["by"] == by and words in record["reason"], record

