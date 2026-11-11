"""The head stage key rule and the backfill planner (features_backend/story-head-stage-index.feature has the narrative scenarios)."""

from __future__ import annotations

from papyrus_content import graphql_authoring
from papyrus_content.content_item_lifecycle import build_new_content_item_version, head_stage_fields, head_stage_key, with_stage
from papyrus_content.records import build_record_change_from_current, records_equal_for_model
from papyrus_content.story_head_index import head_of, plan_head_index
from papyrus_content.tenancy import tenant_scoped_index, tenant_stamped_payload


def row(number: int, state: str, stage: str = "copywriting", lineage: str = "story-a", **extra):
    return {"id": f"{lineage}-v{number}", "lineageId": lineage, "versionNumber": number, "versionState": state, "stage": stage,
            "versionCreatedAt": f"2026-11-0{number}T00:00:00Z", "updatedAt": f"2026-11-0{number}T01:00:00Z", **extra}


def test_the_key_is_the_stage_of_a_row_that_is_not_superseded():
    assert head_stage_key({"versionState": "current", "stage": "published"}) == "published"
    assert head_stage_key({"versionState": "draft", "stage": "reporting"}) == "reporting"
    assert head_stage_key({"stage": "idea"}) == "idea"
    assert head_stage_key({"versionState": "superseded", "stage": "published"}) is None
    assert head_stage_key({"versionState": "current"}) is None
    assert head_stage_fields({"versionState": "current", "stage": "idea"}, head=False) == {"headStageKey": None}
    assert with_stage({"versionState": "current", "stage": "idea"}, "assignment") == {"versionState": "current", "stage": "assignment", "headStageKey": "assignment"}


def test_a_new_story_is_born_with_its_head_key():
    item = build_new_content_item_version(lineage_id="l", title="T", summary=None, section_key=None, stage="idea", actor_label="a", now="2026-11-09T00:00:00Z", item_type="article")
    assert item["headStageKey"] == "idea"


def test_the_record_change_path_derives_the_key_and_never_counts_it_as_a_difference():
    current = row(1, "current")
    moved = build_record_change_from_current("Item", {**current, "stage": "illustration"}, current)
    assert moved["action"] == "update" and moved["expected"]["headStageKey"] == "illustration"
    superseded = build_record_change_from_current("Item", {**current, "versionState": "superseded"}, current)
    assert superseded["expected"]["headStageKey"] is None
    # A row read from a site that has no headStageKey must not look changed only because the key is derived.
    same = build_record_change_from_current("Item", dict(current), current)
    assert same["action"] == "noop"
    assert records_equal_for_model("Item", current, {**current, "headStageKey": "copywriting"})
    created = build_record_change_from_current("Item", {"id": "x", "lineageId": "x", "versionState": "current"}, None)
    assert "headStageKey" not in created["expected"], "a create with no stage names no key"


def test_the_key_is_tenant_scoped_and_so_is_a_query_of_the_head_index():
    stamped = tenant_stamped_payload("Item", "mom", {"id": "a", "stage": "idea", "headStageKey": "idea"})
    assert stamped["headStageKey"] == "mom#idea" and stamped["stage"] == "idea"
    assert tenant_stamped_payload("Item", "mom", {"id": "a", "headStageKey": None})["headStageKey"] is None
    assert tenant_scoped_index("mom", "itemsByHeadStage", "idea") == ("itemsByHeadStage", "mom#idea")
    assert tenant_scoped_index(None, "itemsByHeadStage", "idea") == ("itemsByHeadStage", "idea")
    assert tenant_scoped_index("mom", "itemsByStage", "idea") == ("itemsByStage", "idea"), "the old stage index is not tenant-prefixed"


def test_the_head_is_the_current_row_else_the_one_not_superseded_else_none():
    assert head_of([row(1, "superseded"), row(2, "current"), row(3, "draft")])["id"] == "story-a-v2"
    assert head_of([row(1, "superseded"), row(2, "draft")])["id"] == "story-a-v2"
    assert head_of([row(1, "current"), row(2, "current")])["id"] == "story-a-v2", "the most recently created of a muddled pair"
    assert head_of([row(1, "superseded")]) is None


def test_the_plan_writes_only_what_differs():
    rows = [
        row(1, "superseded"), row(2, "current", headStageKey="copywriting"),                     # already right
        row(1, "superseded", lineage="b"), row(2, "current", "published", lineage="b"),         # head to set
        row(1, "current", lineage="c", headStageKey="copywriting"), row(2, "current", lineage="c"),  # muddled: move the key to v2
        row(1, "superseded", lineage="d", headStageKey="idea"),                                 # superseded with a key, no head: reported only
    ]
    plan = plan_head_index(rows)
    assert plan.counts() == {"rows read": 7, "stories": 4, "heads to set": 2, "keys to remove": 1, "already right": 1, "muddled": 1, "no head": 1, "superseded with key": 1}
    assert [(change["id"], change["key"], change["updatedAt"]) for change in plan.sets] == [("b-v2", "published", "2026-11-02T01:00:00Z"), ("c-v2", "copywriting", "2026-11-02T01:00:00Z")]
    assert [change["id"] for change in plan.removals] == ["c-v1"]


def test_the_plan_compares_tenant_prefixed_keys_and_treats_an_unreadable_key_as_missing():
    rows = [row(1, "current", headStageKey="mom#copywriting")]
    assert plan_head_index(rows, tenant_id="mom").counts()["already right"] == 1
    assert plan_head_index(rows, tenant_id="mom", keys_readable=False).counts()["heads to set"] == 1


class _Transport(graphql_authoring.PapyrusGraphQLAuthoringClient):
    def __init__(self, fields, endpoint):
        super().__init__(endpoint=endpoint, header_factory=lambda body: {})
        self.fields, self.sent, self.checks = fields, [], 0

    def _send_graphql(self, query, variables=None):
        if "PapyrusSchemaCheck" in query:
            self.checks += 1
            if self.fields is None:
                raise graphql_authoring.GraphQLRequestError("introspection is off")
            return {"__type": {"name": "Item", "fields": [{"name": name} for name in self.fields]}}
        if "headStageKey" in str((variables or {}).get("input")) and "headStageKey" not in (self.fields or []):
            raise graphql_authoring.GraphQLRequestError("GraphQL request failed: The variables input contains a field name 'headStageKey' that is not defined for input object type 'UpdateItemInput'")
        self.sent.append(variables)
        return {}


def test_a_site_that_cannot_be_asked_is_written_with_the_key_and_a_refusal_is_sent_again_without_it(capsys):
    client = _Transport(None, "https://cannot-ask.example.test/graphql")
    client.update_record_unscoped("Item", {"id": "a", "headStageKey": "idea", "stage": "idea"})
    assert client.sent == [{"input": {"id": "a", "stage": "idea"}}]
    assert "has no headStageKey yet" in capsys.readouterr().err
    client.update_record_unscoped("Item", {"id": "b", "headStageKey": "idea"})
    assert client.sent[-1] == {"input": {"id": "b"}} and client.checks == 1


def test_the_field_is_kept_for_a_site_that_has_it():
    client = _Transport(["id", "headStageKey"], "https://has-it.example.test/graphql")
    client.update_record_unscoped("Item", {"id": "a", "headStageKey": None})
    client.update_record_unscoped("Reference", {"id": "r", "feedStateKey": None})
    assert client.sent[0] == {"input": {"id": "a", "headStageKey": None}} and client.checks == 1
