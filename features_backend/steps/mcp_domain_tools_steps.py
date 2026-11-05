from behave import given, when, then
from papyrus_content.mcp_tools import Principal, StaffReads, call_tool


class Site:
    def get_record(self, model, id):
        return None

    def list_by_index(self, index, key, **kwargs):
        if index == "itemsByLineageAndVersion":
            return [{"id": "story-v2", "lineageId": key, "versionNumber": 2, "versionState": "current"}]
        if index == "semanticRelationsBySubjectState":
            return [{"id": "relation", "predicate": "uses_evidence", "objectKind": "reference", "objectLineageId": "ref"}]
        return []


@given('an editor connected to a site with a Story and evidence')
def editor(context):
    context.principal = Principal("staff", "editor")
    context.staff = StaffReads(Site())


@given('a reader connected to a site with a verified site subject')
def reader(context):
    context.principal = Principal("reader", "reader", site_subject="site-subject")
    context.staff = StaffReads(Site())


@when('the editor asks for the Story and its evidence')
def read_story(context):
    context.story = call_tool(context.principal, "story_get", {"lineageId": "story"}, staff=context.staff)
    context.evidence = call_tool(context.principal, "story_evidence", {"lineageId": "story"}, staff=context.staff)


@then('the tools return the current Story version and the evidence lineage')
def story_result(context):
    assert context.story["story"]["id"] == "story-v2"
    assert context.evidence["evidence"][0]["referenceLineageId"] == "ref"


@when('the editor decides a Reference using an obsolete revision')
def stale(context):
    try:
        call_tool(context.principal, "reference_decide", {"lineageId": "ref", "expectedCurrentVersionId": "ref-v1", "expectedRevision": "old", "decision": "accept"}, staff=context.staff)
    except RuntimeError as error:
        context.error = error


@then('the decision is refused without changing the Reference')
def refused(context):
    assert context.error


@when('the reader asks for the Story')
def forbidden(context):
    try:
        call_tool(context.principal, "story_get", {"lineageId": "story"}, staff=context.staff)
    except PermissionError as error:
        context.error = error


@then('the staff tool is refused')
def forbidden_result(context):
    assert context.error


@when('the reader submits a link')
def submit(context):
    def handler(event):
        context.event = event
        return {"statusCode": 200}
    call_tool(context.principal, "reader_submit", {"url": "https://example.org/", "title": "Example"}, staff=context.staff, reader=handler)


@then("the site's reader policy receives the verified site subject")
def subject(context):
    assert context.event["siteSubject"] == "site-subject"
    assert context.event["isStaff"] is False
    assert context.event["action"] == "submit"
