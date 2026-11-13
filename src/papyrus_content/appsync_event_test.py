import pytest

from papyrus_content.appsync_event import NO_OPERATION_MESSAGE, NoOperation, amplify_function_event, operation_name, user_pool_identity


def test_the_operation_is_the_top_level_field_amplify_sends():
    event = amplify_function_event("Mutation", "announcementsPause", {"input": "{}"}, user_pool_identity("ryan", ["admin"]))
    assert set(event) == {"typeName", "fieldName", "arguments", "identity", "source", "request", "prev"}
    assert "info" not in event
    assert operation_name(event) == "announcementsPause"


@pytest.mark.parametrize("event", [{}, {"fieldName": ""}, {"fieldName": None}, {"info": {"fieldName": "announcementsSettings"}}])
def test_a_request_with_no_field_is_refused_in_plain_words(event):
    with pytest.raises(NoOperation) as raised:
        operation_name(event)
    assert str(raised.value) == NO_OPERATION_MESSAGE
