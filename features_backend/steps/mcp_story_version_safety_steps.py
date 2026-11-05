from behave import given, when, then
from papyrus_content.mcp_story_atomic_test import test_two_same_version_saves_have_one_winner, test_conflicting_new_id_is_not_overwritten
from papyrus_content.mcp_tools import Principal, StaffReads, list_tools


@given("a Story has a single current version")
def step(context):
    pass

@when("two drafts are saved against that same expected version")
def step(context):
    test_two_same_version_saves_have_one_winner()

@then("only one becomes the new current version")
@then("the other is refused without changing the Story")
def step(context):
    pass

@when("another write claims the planned new version ID")
def step(context):
    test_conflicting_new_id_is_not_overwritten()

@then("the draft is refused without changing the Story")
def step(context):
    pass

@given("the site has no safe agent publishing operation")
def step(context):
    context.staff = StaffReads(object())

@when("an agent discovers the site's Story tools")
def step(context):
    context.names = {tool["name"] for tool in list_tools(Principal(kind="staff", subject="person", is_agent=True), staff=context.staff)}

@then("the agent cannot call a Story write tool")
def step(context):
    assert "story_publish" not in context.names
    assert "story_save_draft" not in context.names
