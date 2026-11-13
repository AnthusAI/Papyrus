"""The automation-view function runs the field Amplify names: `runAutomation` is never answered with the overview."""
from papyrus_content.appsync_event import NO_OPERATION_MESSAGE, amplify_function_event, user_pool_identity
from papyrus_content.automation_view import handle


def test_run_automation_is_the_field_amplify_names():
    editor = user_pool_identity("edie", ["editor"])
    assert handle(amplify_function_event("Mutation", "runAutomation", {}, editor), env={}) == {"error": "bad_request"}


def test_a_request_naming_no_field_says_so():
    event = amplify_function_event("Query", "automationOverview", {}, user_pool_identity("edie", ["editor"]))
    del event["fieldName"]
    assert handle(event, env={}) == {"error": "bad_request", "message": NO_OPERATION_MESSAGE}
