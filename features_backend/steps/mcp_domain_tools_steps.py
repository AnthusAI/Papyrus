from behave import given, when, then
from papyrus_content.mcp_tools import Principal, StaffReads, call_tool


class Site:
    def graphql(self, query, variables):
        if "StoryVersions" in query:
            return {"listItemsByLineageAndVersion": {"items": [{"id": "story-v2", "lineageId": variables["lineageId"], "versionNumber": 2, "versionState": "current"}], "nextToken": None}}
        if "StoryEvidence" in query:
            return {"listSemanticRelationsBySubjectState": {"items": [{"id": "relation", "predicate": "uses_evidence", "objectKind": "reference", "objectLineageId": "ref"}], "nextToken": None}}
        return {}

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


def private_handler():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "amplify/functions/mcp-tools/handler.py"
    spec = importlib.util.spec_from_file_location("papyrus_mcp_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@given('a reader connected to the private site-tools service')
def private_reader(context):
    context.handler = private_handler()


@given('a reader connected to the private site-tools service without a reader plugin')
def private_reader_no_plugin(context):
    import os
    private_reader(context)
    context.old_reader_function = os.environ.pop("PAPYRUS_READER_STEERING_FUNCTION", None)


@when('the reader includes an administrative role in a tool request')
def forge_role(context):
    context.result = context.handler.handler({"operation": "call", "principal": {"kind": "reader", "siteSubject": "ss1_" + "a" * 43},
        "name": "reader_submit", "arguments": {"url": "https://example.org", "title": "Example", "role": "admin"}}, None)


@then('the service refuses the forged role')
def forged_role_refused(context):
    assert context.result["isError"]


@when("the reader lists the site's tools")
def list_reader_tools(context):
    context.result = context.handler.handler({"operation": "list", "principal": {"kind": "reader", "siteSubject": "ss1_" + "a" * 43}}, None)
    if context.old_reader_function is not None:
        import os
        os.environ["PAPYRUS_READER_STEERING_FUNCTION"] = context.old_reader_function


@then('the reader sees no reader tools')
def no_reader_tools(context):
    assert context.result == {"tools": []}


@given("an editor connected to a shared site with an Assignment for another publication")
def foreign_assignment(context):
    class SharedSite(Site):
        tenant_id = "account-one"
        def get_record(self, model, id):
            return {"id": id, "itemLineageId": "foreign"} if model == "Assignment" else None
        def list_by_index(self, index, key, **kwargs):
            return [{"id": "foreign-v1", "lineageId": key, "versionNumber": 1, "versionState": "current", "tenantId": "account-two"}]
    context.principal = Principal("staff", "editor")
    context.staff = StaffReads(SharedSite())


@when('the editor opens that Assignment')
def open_foreign_assignment(context):
    try:
        call_tool(context.principal, "assignment_get", {"id": "assignment"}, staff=context.staff)
    except (ValueError, PermissionError) as error:
        context.error = error


@then('the Assignment read is refused')
def assignment_refused(context):
    assert context.error


@given('an editor connected to a site with a searchable Story')
def searchable_story(context):
    class SearchSite(Site):
        tenant_id = None
        def graphql(self, query, variables):
            assert variables["limit"] == 2
            return {"listItems": {"items": [{"id": "story-v1", "lineageId": "story", "type": "article", "title": "Example"}], "nextToken": "more"}}
    context.principal = Principal("staff", "editor")
    context.staff = StaffReads(SearchSite())


@when('the editor searches for the Story with a page size of two')
def search_story(context):
    context.result = call_tool(context.principal, "story_search", {"query": "Example", "limit": 2}, staff=context.staff)


@then('the result contains the Story and a continuation token')
def search_result(context):
    assert context.result["stories"][0]["lineageId"] == "story"
    assert context.result["nextToken"] == "more"


@given('an editor connected to a site with an open review')
def open_review(context):
    class ReviewSite(Site):
        tenant_id = None
        row = {"id": "review", "subject": '{"type":"story","id":"story"}', "mode": "hard_gate", "reason": "Check",
               "raisedBy": "procedure", "raisedAt": "2026-01-01T00:00:00Z", "state": "open", "updatedAt": "revision", "history": "[]"}
        def get_record(self, model, id):
            return dict(self.row) if model == "ReviewRequest" and id == "review" else None
        def graphql(self, query, variables):
            assert variables["condition"] == {"state": {"eq": "open"}, "updatedAt": {"eq": "revision"}}
            self.row.update(variables["input"])
            return {"updateReviewRequest": {"id": "review"}}
    context.principal = Principal("staff", "editor", is_agent=True)
    context.staff = StaffReads(ReviewSite())


@when('the agent answers the current review with feedback')
def answer_current_review(context):
    try:
        context.result = call_tool(context.principal, "review_answer", {"id": "review", "expectedRevision": "revision", "decision": "feedback", "feedback": "Revise the lead."}, staff=context.staff)
    except ValueError as error:
        context.error = error


@then('the saved answer names the agent and returns the updated revision')
def review_answer_result(context):
    assert context.result["review"]["answer"]["by"] == "agent:editor"
    assert context.result["review"]["updatedAt"] != "revision"


@when('the agent answers an outdated review')
def answer_old_review(context):
    try:
        call_tool(context.principal, "review_answer", {"id": "review", "expectedRevision": "old", "decision": "approve"}, staff=context.staff)
    except ValueError as error:
        context.error = error


@then('the review answer is refused as stale')
def stale_review_result(context):
    assert "stale_revision" in str(context.error)
    assert context.staff.client.row["state"] == "open"


@given('an editor connected to a site with a publish approval request')
def publish_review(context):
    open_review(context)
    context.staff.client.row["raisedBy"] = "publish-gate"


@when('the agent tries to approve the publish request')
def approve_publish_review(context):
    try:
        call_tool(context.principal, "review_answer", {"id": "review", "expectedRevision": "revision", "decision": "approve"}, staff=context.staff)
    except PermissionError as error:
        context.error = error


@then('the request remains open for a person')
def publish_review_still_open(context):
    assert context.error
    assert context.staff.client.row["state"] == "open"


@given("another answer wins before the agent's update")
def concurrent_review(context):
    from papyrus_content.operator_errors import GraphQLRequestError
    def conflict(query, variables):
        raise GraphQLRequestError("ConditionalCheckFailedException")
    context.staff.client.graphql = conflict


@given('an editor connected to a site with a rateable Story')
def rateable_story(context):
    class StarSite(Site):
        row = {"id": "story-v2", "lineageId": "story", "versionState": "current", "versionNumber": 2,
               "updatedAt": "2026-11-01T10:00:00Z", "starRevision": None, "starRating": None, "type": "article"}
        def graphql(self, query, variables):
            if "AgentStoryStars" in query:
                assert variables["expectedStarRevision"] is None
                self.row.update(starRating=variables["stars"], starRevision="new")
                return {"agentSetItemStars": {"ok": True}}
            return {"listItemsByLineageAndVersion": {"items": [dict(self.row)], "nextToken": None}}
    context.principal = Principal("staff", "editor")
    context.staff = StaffReads(StarSite())


@when('the agent gives that Story four stars')
def rate_story(context):
    card = context.staff.story_get(context.principal, lineageId="story")["story"]
    context.result = call_tool(context.principal, "story_star", {"lineageId": "story", "expectedCurrentVersionId": card["id"], "expectedRevision": card["revision"], "stars": 4}, staff=context.staff)
    context.previous_revision = card["revision"]


@then('the Story card shows four stars and a new revision')
def rated_story(context):
    assert context.result["story"]["starRating"] == 4
    assert context.result["story"]["revision"] != context.previous_revision


@when('the agent rates the Story from an outdated card')
def rate_old_story(context):
    try:
        call_tool(context.principal, "story_star", {"lineageId": "story", "expectedCurrentVersionId": "story-v1", "expectedRevision": '["2026-11-01T10:00:00Z",null]', "stars": 4}, staff=context.staff)
    except ValueError as error:
        context.error = error


@then('the Story rating is refused as stale')
def stale_story_rating(context):
    assert "stale_revision" in str(context.error)
    assert context.staff.client.row["starRating"] is None


@when('the reader tries to rate a Story')
def reader_rates_story(context):
    try:
        call_tool(context.principal, "story_star", {"lineageId": "story", "expectedCurrentVersionId": "story-v1", "expectedRevision": '["2026-11-01T10:00:00Z",null]', "stars": 4}, staff=context.staff)
    except PermissionError as error:
        context.error = error


@given('an editor connected to a site with the agent draft operation')
def draft_site(context):
    class DraftSite(Site):
        def graphql(self, query, variables):
            import json
            assert json.loads(variables["input"])["expectedCurrentVersionId"] == "story-v1"
            return {"agentSaveStoryDraft": {"ok": True, "item": {"id": "story-v2"}, "editorialCheck": {"notChecked": "Check unavailable"}}}
    context.principal = Principal("staff", "editor", is_agent=True)
    context.staff = StaffReads(DraftSite())


@when('the agent saves a new draft and its check is unavailable')
def save_draft_unchecked(context):
    context.result = call_tool(context.principal, "story_save_draft", {"lineageId": "story", "expectedCurrentVersionId": "story-v1", "body": "New draft.", "reason": "Revision"}, staff=context.staff)


@then('the tool reports both the saved draft and the check status')
def saved_draft_and_check(context):
    assert context.result["ok"] is True
    assert context.result["item"]["id"] == "story-v2"
    assert context.result["editorialCheck"]["notChecked"] == "Check unavailable"


@when('the editor asks for the next Story procedure steps')
def next_story_steps(context):
    context.result = call_tool(context.principal, "story_next", {"lineageId": "story"}, staff=context.staff)


@then('the direction and research steps are reported as unknown')
def unknown_story_steps(context):
    steps = {row["key"]: row["state"] for row in context.result["procedure"]["steps"]}
    assert steps["direction"] == "unknown"
    assert steps["research"] == "unknown"


@given('an editor connected to a site with a publish request operation')
def publish_request_site(context):
    class PublishSite(Site):
        def graphql(self, query, variables):
            import json
            assert json.loads(variables["input"]) == {"lineageId": "story", "expectedCurrentVersionId": "story-v1"}
            return {"agentRequestStoryPublish": {"status": "pending", "requestId": "review", "versionId": "story-v1"}}
    context.principal = Principal("staff", "editor", is_agent=True)
    context.staff = StaffReads(PublishSite())


@when('the agent requests publication for the current Story')
def request_story_publish(context):
    context.result = call_tool(context.principal, "story_request_publish", {"lineageId": "story", "expectedCurrentVersionId": "story-v1"}, staff=context.staff)


@then('the tool reports a pending human approval request')
def pending_publish_request(context):
    assert context.result == {"status": "pending", "requestId": "review", "versionId": "story-v1"}
