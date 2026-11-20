from behave import given, when, then
from papyrus_content import mcp_publish_request_test as checks

@given("a site requires human publication approval")
@given("a site does not require publication approval")
def step(context): pass

@when("an agent requests publication of its current draft")
def step(context): pass

@then("the version-bound review is opened or reused and the Story stays unpublished")
def step(context): checks.test_gate_opens_and_reuses_exact_version_request_without_publishing()

@when("the Story changes before the request is recorded")
def step(context): pass

@then("the request is refused and nothing is published")
def step(context): checks.test_stale_and_conflicting_requests_never_publish()

@when("a person approves the version")
def step(context): pass

@then("the agent is directed to the staff console and nothing is published")
def step(context): checks.test_gate_opens_and_reuses_exact_version_request_without_publishing()

@then("it receives a staff console handoff and no record is written")
def step(context): checks.test_no_gate_returns_console_handoff_without_any_write()

@when("an agent answers a previous approval request")
def step(context): pass

@then("another person must still approve the version")
def step(context): checks.test_agent_approval_cannot_satisfy_person_gate()

@when("the current draft cannot be published at its placeholder address")
def step(context): pass

@then("no approval request is created")
def step(context): checks.test_invalid_publish_preflight_does_not_open_approval()

@given("a site excludes its review and editorial model groups")
def step(context): pass

@when("the site configures Story publication requests")
def step(context):
    import subprocess
    subprocess.run(["npx", "tsx", "scripts/test-mcp-story-availability.ts"], check=True, capture_output=True, text=True)

@then("it omits the operation from discovery and direct requests fail closed")
def step(context):
    from unittest.mock import patch
    from papyrus_content import mcp_publish_request_test as suite
    class EnvPatch:
        def setenv(self, key, value):
            self.stack.enter_context(patch.dict("os.environ", {key: value}))
        def delenv(self, key, raising=False):
            import os
            self.stack.enter_context(patch.dict("os.environ", {k: v for k, v in os.environ.items() if k != key}, clear=True))
    from contextlib import ExitStack
    with ExitStack() as stack:
        helper = EnvPatch(); helper.stack = stack
        suite.test_action_fails_closed_when_review_models_are_excluded(helper)
