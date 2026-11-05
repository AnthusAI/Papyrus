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

@then("the agent cannot call the Story publish tool")
def step(context):
    assert "story_publish" not in context.names

@when("the site's draft operation checks the current version in its transaction")
def step(context):
    from papyrus_content.mcp_story_transaction_test import test_atomic_request_binds_current_lineage_revision_tenant_and_new_id
    test_atomic_request_binds_current_lineage_revision_tenant_and_new_id()

@then("the transaction checks the tenant and revision and refuses an existing new ID")
def step(context):
    from papyrus_content.mcp_story_transaction_test import test_transaction_collision_is_reported_as_stale
    test_transaction_collision_is_reported_as_stale()

@when("an agent tries to save a draft containing an image")
def step(context):
    from papyrus_content.mcp_story_transaction_test import test_images_are_refused_before_transaction
    test_images_are_refused_before_transaction()

@then("no Story transaction is sent")
def step(context):
    pass
