from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, register_type, then, when
import parse

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.agent_policy import AgentPolicyStore, PolicyError, decide_start  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402



@parse.with_pattern(r"[a-z_]+")
def _name(text):
    return text


register_type(Name=_name)
TENANT = "alpha"
ADMIN = Caller(kind="person", subject="ada", is_admin=True)
EDITOR = Caller(kind="person", subject="ed", is_admin=False)
AGENT = Caller(kind="agent", subject="rating-agent", is_admin=False)
SCOPE_WORD = re.compile(r'(list|channel|kind|section|storyType) "([^"]+)"')


def _scope(text):
    return {("storyType" if word == "story type" else word): value for word, value in SCOPE_WORD.findall(text)}


def _policy(context):
    return context.policy


def _fresh(context):
    context.s3, context.catalogue = FakeS3(), FakeTable()
    clock = iter(f"2026-11-16T00:{minute:02d}:00Z" for minute in range(60))
    context.policy = AgentPolicyStore(SiteStore(context.s3, "bucket", context.catalogue, now=lambda: next(clock)))
    context.refusal = None
    context.skipped = []


def _try(context, action):
    context.refusal = None
    try:
        action()
    except PolicyError as error:
        context.refusal = error


def _wake(context, responsibility, **where):
    return decide_start(_policy(context).read(TENANT), responsibility, where)


@given("a site that has never saved an agent policy")
def never_saved(context):
    _fresh(context)


@given('a site where "{responsibility}" is at "{rung}"')
def seeded(context, responsibility, rung):
    _fresh(context)
    _policy(context).set_rung(TENANT, ADMIN, responsibility, rung, reason="Seed")


@given('a site where "{responsibility}" was set to "observe" and then to "draft"')
def two_changes(context, responsibility):
    _fresh(context)
    _policy(context).set_rung(TENANT, ADMIN, responsibility, "observe", reason="First look")
    _policy(context).set_rung(TENANT, ADMIN, responsibility, "draft", reason="Trusted now")


@given('a site with "{first}" at "{first_rung}" and "{second}" at "{second_rung}"')
def seeded_two(context, first, first_rung, second, second_rung):
    _fresh(context)
    _policy(context).set_rung(TENANT, ADMIN, first, first_rung, reason="Seed")
    _policy(context).set_rung(TENANT, ADMIN, second, second_rung, reason="Seed")


@given('an admin gave "{responsibility}" the rung "{rung}" for {scope} because "{why}"')
def gave_override(context, responsibility, rung, scope, why):
    _policy(context).set_rung(TENANT, ADMIN, responsibility, rung, reason=why, scope=_scope(scope))


@given('an admin paused "{responsibility}" because "{why}"')
def already_paused(context, responsibility, why):
    _policy(context).pause(TENANT, ADMIN, reason=why, responsibility=responsibility)


@given('three timed wakes for "{responsibility}" came and were each skipped')
def skipped_ticks(context, responsibility):
    context.skipped = [_wake(context, responsibility) for _ in range(3)]
    assert all(not decision.start for decision in context.skipped)
    context.writes_after_skips = len(context.catalogue.writes)


@when('an admin sets "{responsibility}" to "{rung}" because "{why}"')
def admin_sets(context, responsibility, rung, why):
    _try(context, lambda: _policy(context).set_rung(TENANT, ADMIN, responsibility, rung, reason=why))


@when('an editor tries to set "{responsibility}" to "{rung}" because "{why}"')
def editor_sets(context, responsibility, rung, why):
    _try(context, lambda: _policy(context).set_rung(TENANT, EDITOR, responsibility, rung, reason=why))


@when('an agent tries to set "{responsibility}" to "{rung}" because "{why}"')
def agent_sets(context, responsibility, rung, why):
    _try(context, lambda: _policy(context).set_rung(TENANT, AGENT, responsibility, rung, reason=why))


@when('an admin sets the rung of "{responsibility}" for {scope} to "{rung}" because "{why}"')
def admin_sets_override(context, responsibility, scope, rung, why):
    _try(context, lambda: _policy(context).set_rung(TENANT, ADMIN, responsibility, rung, reason=why, scope=_scope(scope)))


@when('an admin pauses "{responsibility}" because "{why}"')
def admin_pauses(context, responsibility, why):
    _policy(context).pause(TENANT, ADMIN, reason=why, responsibility=responsibility)


@when("an admin pauses the site because \"{why}\"")
def admin_pauses_site(context, why):
    _policy(context).pause(TENANT, ADMIN, reason=why)


@when('an admin resumes "{responsibility}" because "{why}"')
def admin_resumes(context, responsibility, why):
    _policy(context).resume(TENANT, ADMIN, reason=why, responsibility=responsibility)


@when('an admin sets a quiet window, a budget and the model tiers for the site because "{why}"')
def admin_sets_site_values(context, why):
    context.window = {"start": "22:00", "end": "06:00", "timeZone": "America/New_York"}
    context.budget = {"amountUsd": 25, "period": "week"}
    context.tiers = {"editorial": "model-a", "work": "model-b", "bulk": "model-c"}
    for field, value in (("quietWindow", context.window), ("budget", context.budget), ("tiers", context.tiers)):
        _policy(context).set_value(TENANT, ADMIN, field, value, reason=why)


@when('an admin sets the loop limit of "{responsibility}" to {limit:d} because "{why}"')
def admin_sets_loop_limit(context, responsibility, limit, why):
    _policy(context).set_value(TENANT, ADMIN, "loopLimit", limit, reason=why, responsibility=responsibility)


@when("the runner reads the policy five times")
def runner_reads(context):
    context.writes_before_reads = len(context.catalogue.writes)
    context.s3_before_reads = dict(context.s3.objects)
    for _ in range(5):
        _policy(context).read(TENANT)


@then('every responsibility is at "off" under policy version 0')
def all_off(context):
    for name in ("rate", "ideate", "improve", "translate", "announce", "anything_else"):
        decision = _wake(context, name)
        assert (decision.rung, decision.policy_version, decision.start) == ("off", 0, False), (name, decision)


@then('a wake for "{responsibility}" starts nothing and says "{message}"')
def wake_refused(context, responsibility, message):
    decision = _wake(context, responsibility)
    assert not decision.start and decision.reason == message, decision


@then('a wake for "{responsibility}" is not affected by that pause')
def wake_unaffected(context, responsibility):
    decision = _wake(context, responsibility)
    assert decision.reason == f"{responsibility} is off", decision   # never named, so off for its own reason, not for the pause


@then("the policy is version {version:d}")
def policy_version(context, version):
    assert _policy(context).read(TENANT).version == version


@then("the policy is still version {version:d}")
def policy_still_version(context, version):
    assert _policy(context).read(TENANT).version == version


@then('the policy is still version {version:d} and the rung of "{responsibility}" is "{rung}"')
def policy_still_and_rung(context, version, responsibility, rung):
    state = _policy(context).read(TENANT)
    assert state.version == version and state.document["agents"][responsibility]["rung"] == rung


@then('version {version:d} records the admin, a time and the reason "{why}"')
def version_record(context, version, why):
    record = _policy(context).version_record(TENANT, version)
    assert record["by"] == "ada" and record["at"] and record["reason"] == why, record


@then('the rung of "{responsibility:Name}" is "{rung}"')
def rung_is(context, responsibility, rung):
    assert _wake(context, responsibility).rung == rung


@then('version {version:d} still holds "{responsibility}" at "{rung}"')
def old_version_holds(context, version, responsibility, rung):
    document = context.policy._store.read_version(TENANT, "agents", version)
    assert document["agents"][responsibility]["rung"] == rung


@then("each of the two versions records who, when and why")
def both_recorded(context):
    for version, why in ((1, "First look"), (2, "Trusted now")):
        record = _policy(context).version_record(TENANT, version)
        assert record["by"] == "ada" and record["at"] and record["reason"] == why, record


@then("the change is refused as not authorized")
def refused_not_authorized(context):
    assert context.refusal is not None and context.refusal.code == "not_authorized"


@then("the change is blocked")
def refused_blocked(context):
    assert context.refusal is not None and context.refusal.code == "blocked"


@then("the change is refused as invalid")
def refused_invalid(context):
    assert context.refusal is not None and context.refusal.code == "invalid_input"


def _rung_for(context, responsibility, scope_text):
    return decide_start(_policy(context).read(TENANT), responsibility, _scope(scope_text))


@then('the rung of "{responsibility}" for {scope} is "{rung}", chosen by an override')
def rung_by_override(context, responsibility, scope, rung):
    decision = _rung_for(context, responsibility, scope)
    assert (decision.rung, decision.source) == (rung, "override"), decision


@then('the rung of "{responsibility}" for {scope} is "{rung}"')
def rung_for_scope(context, responsibility, scope, rung):
    assert _rung_for(context, responsibility, scope).rung == rung


@then('the rung of "{responsibility}" with nothing in view is "{rung}"')
def rung_nothing_in_view(context, responsibility, rung):
    assert decide_start(_policy(context).read(TENANT), responsibility, {}).rung == rung


@then('there is still one override for section "{section}" and it holds "{rung}"')
def one_override(context, section, rung):
    overrides = _policy(context).read(TENANT).document["agents"]["improve"]["overrides"]
    assert overrides == [{"section": section, "rung": rung}], overrides


@then("no run is started for the three skipped wakes")
def no_replay(context):
    assert len(context.catalogue.writes) == context.writes_after_skips + 2   # the resume itself: one version row and one pointer move
    assert all(not decision.start for decision in context.skipped)


@then('the next wake for "{responsibility}" starts under the new policy version')
def next_wake_starts(context, responsibility):
    decision = _wake(context, responsibility)
    assert decision.start and decision.policy_version == _policy(context).read(TENANT).version == 3, decision


@then('a wake for "{responsibility}" starts at the rung "{rung}"')
def wake_starts_at(context, responsibility, rung):
    decision = _wake(context, responsibility)
    assert decision.start and decision.rung == rung, decision


@then('a wake for "{responsibility}" starts, and its run record carries policy version {version:d} and rung "{rung}"')
def run_record(context, responsibility, version, rung):
    decision = _wake(context, responsibility)
    assert decision.start and decision.run_fields() == {"policyVersion": version, "rung": rung}, decision


@then("a skipped wake carries the policy version and rung it was decided under as well")
def skipped_record(context):
    decision = _wake(context, "translate")
    assert not decision.start and decision.run_fields() == {"policyVersion": 2, "rung": "off"}, decision


@then("the policy holds those values exactly as given")
def values_held(context):
    document = _policy(context).read(TENANT).document
    assert document["site"] == {"quietWindow": context.window, "budget": context.budget, "tiers": context.tiers}
    assert document["agents"]["improve"]["loopLimit"] == 3


@then("an invalid quiet window is refused naming the field")
def invalid_window(context):
    try:
        _policy(context).set_value(TENANT, ADMIN, "quietWindow", {"start": "25:00", "end": "06:00", "timeZone": "America/New_York"}, reason="Test")
    except PolicyError as error:
        assert error.code == "invalid_input" and "site.quietWindow.start" in error.message
    else:
        raise AssertionError("the invalid window was accepted")


@then("the policy store was not written to")
def nothing_written(context):
    assert len(context.catalogue.writes) == context.writes_before_reads
    assert context.s3.objects == context.s3_before_reads
