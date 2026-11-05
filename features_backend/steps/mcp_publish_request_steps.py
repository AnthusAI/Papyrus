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
