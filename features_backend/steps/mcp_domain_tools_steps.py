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


@when('the editor decides a Reference without a conditional-write adapter')
def stale(context):
    context.staff.available_tools = frozenset()
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


@given('an editor connected to a site with a current Reference')
def reference_site(context):
    class ReferenceSite(Site):
        tenant_id = None
        def graphql(self, query, variables):
            if "AgentReviewReference" in query:
                self.decision = variables
                return {"agentReviewReferenceCuration": {"ok": True, "action": variables["action"], "referenceId": variables["referenceId"], "status": "accepted"}}
            return {"listReferencesByLineageAndVersion": {"items": [
                {"id": "ref-v1", "lineageId": "ref", "versionState": "superseded", "updatedAt": "old"},
                {"id": "ref-v2", "lineageId": "ref", "versionState": "current", "updatedAt": "revision"}], "nextToken": None}}
    context.principal = Principal("staff", "editor")
    context.staff = StaffReads(ReferenceSite())


@given('an editor connected to a shared site with a current Reference')
def shared_reference_site(context):
    reference_site(context)
    context.staff.client.tenant_id = "account"


@when('the editor opens the Reference by its lineage')
def open_reference(context):
    try:
        context.result = call_tool(context.principal, "reference_get", {"lineageId": "ref"}, staff=context.staff)
    except PermissionError as error:
        context.error = error


@then('the Reference card identifies the current version and revision')
def reference_card(context):
    assert context.result["reference"]["id"] == "ref-v2"
    assert context.result["reference"]["updatedAt"] == "revision"


@then('the Reference read is refused')
def reference_refused(context):
    assert context.error


@when('the agent accepts the Reference shown on the card')
def accept_reference(context):
    context.result = call_tool(context.principal, "reference_decide", {"lineageId": "ref", "expectedCurrentVersionId": "ref-v2", "expectedRevision": "revision", "decision": "accept"}, staff=context.staff)


@then('the site receives the current version and revision for an agent decision')
def decision_result(context):
    assert context.result["decision"]["ok"]
    assert context.staff.client.decision["referenceId"] == "ref-v2"
    assert context.staff.client.decision["expectedRevision"] == "revision"


@when('the agent accepts an outdated Reference card')
def stale_reference(context):
    try:
        call_tool(context.principal, "reference_decide", {"lineageId": "ref", "expectedCurrentVersionId": "ref-v1", "expectedRevision": "old", "decision": "accept"}, staff=context.staff)
    except ValueError as error:
        context.error = error


@then('the Reference decision is refused')
def decision_refused(context):
    assert context.error
    assert not hasattr(context.staff.client, "decision")
