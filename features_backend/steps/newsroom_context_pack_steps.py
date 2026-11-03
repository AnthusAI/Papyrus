import copy
import json
from collections import defaultdict
from unittest import mock

from behave import given, then, when

from papyrus_content import multi_search_research as ms
from papyrus_content import newsroom_context_pack as pack_module
from papyrus_content import story_commands
from papyrus_content.model_defaults import DEFAULT_LLM_MODEL
from papyrus_content.newsroom_context_pack import build_context_pack
from papyrus_content.story_reporting import STORY_REFERENCE_RELATION_FIELDS, story_thread_id
from papyrus_content.web_search import SearchHit, SearchResponse

TENANT = "example"
SECTION_ID = f"{TENANT}#law-policy"
OTHER_SECTION_ID = f"{TENANT}#culture"
ENDPOINT = "https://example.invalid/graphql"
DIRECTION = "Find the court rulings on model output"
DRAFT_MARKER = "DRAFT-MARKER the opening paragraph of the Story."
QUERY = "model output rulings"


def moment(day, hour=9):
    return f"2026-10-{day:02d}T{hour:02d}:00:00Z"


class FakeNewsroom:
    """A tenant-scoped store with only the reads and writes the pack, the commands and the run use. Nothing touches a network."""

    def __init__(self):
        self.tenant_id = TENANT
        self.records = defaultdict(dict)
        self.relations = []
        self.items = []
        self.doctrine = {}
        self.threads = []
        self.messages = defaultdict(list)
        self.published = defaultdict(list)
        self.attachments = {}
        self.writes = []
        self.corpora = [{"id": "knowledge-corpus-example", "name": "Example", "role": "canonical"}]

    def get_record(self, model, record_id):
        row = self.records[model].get(record_id)
        if row is None and model == "NewsroomSection":
            row = self.records[model].get(f"{TENANT}#{record_id}")
        return self._bare(model, row)

    def _bare(self, model, row):
        if row is None:
            return None
        row = copy.deepcopy(row)
        if model == "NewsroomSection":
            row["storedId"], row["id"] = row["id"], row["id"].split("#", 1)[-1]
        return row

    def safe_list_records(self, model):
        return [self._bare(model, row) for row in self.records[model].values()]

    def list_by_index(self, index, key, **_):
        if index == "knowledgeCorporaByRoleAndName":
            return copy.deepcopy(self.corpora)
        if index == "itemBySlug":
            return copy.deepcopy(self.doctrine.get(key, []))
        if index == "itemsByLineageAndVersion":
            return copy.deepcopy([row for row in self.items if row["lineageId"] == key])
        if index == "semanticRelationsBySubjectState":
            return copy.deepcopy([row for row in self.relations if row.get("subjectStateKey") == key])
        if index == "referencesByCurationStatusKey":
            return copy.deepcopy([row for row in self.records["Reference"].values() if row.get("curationStatusKey") == key])
        if index == "referencesByLineageAndVersion":
            return copy.deepcopy([row for row in self.records["Reference"].values() if row.get("lineageId") == key])
        if index == "assignmentsByItemLineageAndCreatedAt":
            return copy.deepcopy([row for row in self.records["Assignment"].values() if row.get("itemLineageId") == key])
        if index == "itemsBySectionStatus":
            return copy.deepcopy([row for row in self.items
                                  if f"{TENANT}#{row.get('section')}#{'published' if row.get('status') == 'published' else 'draft'}" == key])
        if index == "messageThreadsByAnchor":
            return copy.deepcopy([row for row in self.threads if row.get("primaryAnchorKey") == key])
        if index == "messagesByThreadAndSequence":
            return copy.deepcopy(self.messages[key])
        raise AssertionError(f"the fake store does not serve index {index}")

    def get_records_by_id(self, model, ids):
        return {record_id: copy.deepcopy(self.records[model][record_id]) for record_id in ids if record_id in self.records[model]}

    def list_semantic_relations_by_subject_state(self, key):
        return self.list_by_index("semanticRelationsBySubjectState", key)

    def list_semantic_relations_by_object_state(self, key):
        return copy.deepcopy([row for row in self.relations if row.get("objectStateKey") == key])

    def list_reference_attachments_by_lineage(self, lineage):
        return copy.deepcopy(self.attachments.get(lineage, []))

    def iterate_newest_first(self, index, key):
        assert index == "publishedItemsBySectionStatus"
        self.reads = getattr(self, "reads", []) + [key]
        yield from sorted(copy.deepcopy(self.published.get(key, [])), key=lambda row: row["publishedAt"], reverse=True)

    def create_record(self, model, payload):
        self.writes.append(("create", model, copy.deepcopy(payload)))
        self.records[model][payload["id"]] = copy.deepcopy(payload)
        if model == "MessageThread":
            self.threads.append(copy.deepcopy(payload))

    def update_record(self, model, payload):
        self.writes.append(("update", model, copy.deepcopy(payload)))
        if payload["id"] in self.records[model]:
            self.records[model][payload["id"]].update(payload)
        if model == "Item":
            for row in self.items:
                if row["id"] == payload["id"]:
                    row.update(payload)

    def upsert(self, model, payload):
        known = payload["id"] in self.records[model]
        self.writes.append(("update" if known else "create", model, copy.deepcopy(payload)))
        self.records[model][payload["id"]] = copy.deepcopy(payload)
        if model == "SemanticRelation":
            self.relations.append(copy.deepcopy(payload))
        return "updated" if known else "created"

    def add_reference(self, reference_id, title, *, status="accepted", section=SECTION_ID, human=True, stars=None, reason=None, day=1, summary=None):
        row = {
            "id": reference_id, "lineageId": reference_id, "versionState": "current", "versionNumber": 1, "title": title,
            "sourceUri": f"https://example.org/{reference_id}", "sourcePublishedAt": moment(day), "createdAt": moment(day),
            "curationStatus": status, "curationStatusKey": f"knowledge-corpus-example#{status}", "curationActorKind": "human" if human else "machine",
            "curationStatusUpdatedAt": moment(day, 12), "curationStatusReason": reason, "curationSectionId": section,
            "starRating": stars, "starRatedAt": moment(day) if stars else None, "starRatedBy": "An Editor" if stars else None,
        }
        self.records["Reference"][reference_id] = row
        if summary:
            self.attachments[reference_id] = [{"role": "curation", "metadata": json.dumps({"summary": {"text": summary}})}]
        return row

    def link_reference(self, reference_id, role, note=None):
        self.relations.append({
            "id": f"relation-{reference_id}", "relationState": "current", "predicate": "uses_evidence", **STORY_REFERENCE_RELATION_FIELDS,
            "subjectKind": "item", "subjectLineageId": "story-1", "objectKind": "reference", "objectLineageId": reference_id,
            "subjectStateKey": "item#story-1#current", "objectStateKey": f"reference#{reference_id}#current",
            "metadata": json.dumps({"role": role, "note": note} if note else {"role": role}),
        })

    def add_published(self, lineage, title, section, day, *, tenant=TENANT, stage=None, item_type="article"):
        key = f"{tenant}#{section}#published"
        self.published[key].append({
            "id": f"published-{lineage}", "itemLineageId": lineage, "tenantId": tenant, "type": item_type, "status": "published",
            "slug": lineage, "section": section, "title": title, "headline": title, "deck": f"Deck of {title}", "publishedAt": moment(day),
            **({"stage": stage} if stage else {}),
        })


def build_newsroom():
    store = FakeNewsroom()
    for kind, text in (("mission", "Explain how machines affect public life. PUBLICATION-MISSION"),
                       ("policy", "Distinguish evidence from inference. PUBLICATION-POLICY")):
        slug = f"editorial-doctrine-{kind}"
        store.doctrine[slug] = [{"id": f"doctrine-{kind}", "lineageId": f"doctrine-{kind}", "versionNumber": 1, "versionState": "current",
                                 "type": "doctrine", "status": "private", "tenantId": TENANT, "body": [text]}]
    for section_id, title in ((SECTION_ID, "Law and Policy"), (OTHER_SECTION_ID, "Culture")):
        store.records["NewsroomSection"][section_id] = {
            "id": section_id, "tenantId": TENANT, "title": title, "updatedAt": moment(1),
            "editorialMission": f"{title} MISSION", "editorialPolicy": f"{title} POLICY",
            "assignmentGuidance": f"{title} GUIDANCE", "killCriteria": f"{title} KILL",
        }
    store.items.append({
        "id": "story-1-v2", "lineageId": "story-1", "versionNumber": 2, "versionState": "current", "tenantId": TENANT, "type": "article",
        "status": "draft", "stage": "idea", "section": "law-policy", "title": "Courts and model output", "headline": "Courts and model output",
        "deck": "What judges say about text a model wrote", "bodyMarkus": DRAFT_MARKER, "metadata": "{}",
    })
    store.records["Item"]["story-1-v2"] = store.items[0]
    store.records["Assignment"]["assignment-1"] = {
        "id": "assignment-1", "itemLineageId": "story-1", "assignmentTypeKey": "research.multi", "title": "Research: courts and model output",
        "instructions": DIRECTION, "createdBy": "An Editor", "queueKey": "research:law-policy:exploratory", "status": "open",
        "metadata": json.dumps({"contextProfile": "reporter", "direction": DIRECTION, "researchMode": "source_discovery", "corpusKey": "example",
                                "researchBackend": "multi_search"}),
    }
    store.add_reference("ref-attached", "The attached ruling", status="accepted", day=3, summary="A court held the text was the user's.")
    store.add_reference("ref-url", "https://example.org/ref-url", status="accepted", day=3, summary="A notice about disclosure. It has more.")
    store.link_reference("ref-url", "consulted")
    store.items.append({"id": "story-2-v1", "lineageId": "story-2", "versionNumber": 1, "versionState": "current", "tenantId": TENANT, "type": "article",
                        "status": "draft", "stage": "idea", "section": "law-policy", "title": "A sibling idea"})
    store.add_reference("law-evidence", "Evidence of a sibling Story", human=False, day=6, summary="A study of court filings. It counts them.")
    store.relations.append({"id": "relation-story-2", "relationState": "current", "predicate": "uses_evidence", "subjectKind": "item", "subjectLineageId": "story-2",
                            "objectKind": "reference", "objectLineageId": "law-evidence", "subjectStateKey": "item#story-2#current",
                            "objectStateKey": "reference#law-evidence#current", "metadata": json.dumps({"role": "consulted"})})
    def edge(edge_id, subject, obj, *, state="current", score=None, person=False, note=None):
        metadata = {"provenance": "human" if person else "suggested"}
        if person:
            metadata.update({"decision": "accepted", "decidedBy": "An Editor", "note": note})
        store.relations.append({
            "id": edge_id, "relationState": state, "predicate": "related_to", "subjectKind": "reference", "objectKind": "reference",
            "subjectLineageId": subject, "objectLineageId": obj, "subjectStateKey": f"reference#{subject}#{state}", "objectStateKey": f"reference#{obj}#{state}",
            "score": score, "metadata": json.dumps(metadata)})

    store.add_reference("rel-accepted", "Accepted by an editor as related", day=2, summary="A ruling the editor linked. It has detail.")
    store.add_reference("rel-high", "Suggested, strongest", status="pending", section=None, human=False, day=2, summary="A strongly similar case. Details follow.")
    store.add_reference("rel-low", "Suggested, weaker", human=False, day=2, summary="A weaker match. Details follow.")
    store.add_reference("rel-turned-down", "A related Reference that was rejected", status="rejected", day=2)
    store.add_reference("rel-by-declined-edge", "Only a rejected edge connects it", day=2, summary="Should not be related.")
    edge("edge-accepted", "ref-attached", "rel-accepted", person=True, note="Same court, same week.", score=0.5)
    edge("edge-high", "rel-high", "ref-url", state="suggested", score=0.9)
    edge("edge-low", "ref-attached", "rel-low", state="suggested", score=0.6)
    edge("edge-low-stronger", "ref-url", "rel-low", state="suggested", score=0.7)
    edge("edge-rejected-reference", "ref-attached", "rel-turned-down", state="suggested", score=0.95)
    edge("edge-rejected", "ref-attached", "rel-by-declined-edge", state="rejected", score=0.99)
    edge("edge-between-attached", "ref-attached", "ref-url", state="suggested", score=0.99)
    store.add_reference("law-url-title", "https://example.org/law-url-title", human=True, day=4, summary="Opens with the ruling. More text follows.")
    store.records["Assignment"]["assignment-0"] = {
        "id": "assignment-0", "itemLineageId": "story-1", "assignmentTypeKey": "research.multi", "title": "Earlier research", "instructions": "Look at appeals first",
        "metadata": json.dumps({"direction": "Look at appeals first"})}
    store.records["Message"]["message-packet-0"] = {
        "id": "message-packet-0", "messageKind": "research_packet", "createdAt": moment(2),
        "metadata": json.dumps({"research": {"summary": "Two appeals were found.", "claims": [{"claim": "An appeal was filed.", "sources": [1]}],
                                             "openQuestions": ["Who ruled?"], "researchMode": "source_discovery"}})}
    store.relations.append({"id": "produces-0", "relationState": "current", "predicate": "produces", "subjectKind": "assignment", "subjectId": "assignment-0",
                            "objectKind": "message", "objectId": "message-packet-0", "subjectStateKey": "assignment#assignment-0#current",
                            "objectStateKey": "message#message-packet-0#current"})
    store.link_reference("ref-attached", "consulted", note="the primary ruling")
    store.add_reference("ref-linked", "A commentary on the ruling", status="accepted", day=4, summary="Commentary.")
    store.relations.append({
        "id": "edge-1", "relationState": "current", "predicate": "related_to", "subjectKind": "reference", "objectKind": "reference",
        "subjectLineageId": "ref-attached", "objectLineageId": "ref-linked", "subjectStateKey": "reference#ref-attached#current",
        "objectStateKey": "reference#ref-linked#current",
        "metadata": json.dumps({"decision": "accepted", "decidedBy": "An Editor", "note": "The commentary answers the ruling."}),
    })
    store.threads.append({"id": "thread-1", "threadKind": "story_reporting", "primaryAnchorKey": "item#story-1"})
    for number, (day, who, text) in enumerate([(1, "An Editor", "Start with the Delaware case."), (2, "A Reporter", "Found two more rulings."),
                                               (3, "An Editor", "Check the appeal.")], start=1):
        store.messages["thread-1"].append({"id": f"message-{number}", "status": "active", "role": "human", "authorLabel": who, "content": text,
                                           "createdAt": moment(day), "sequenceNumber": number, "messageKind": "note"})
    for number, (day, title) in enumerate([(5, "Judges weigh machine text"), (6, "A statute on disclosure"), (7, "Fair use and training"),
                                           (8, "Liability for output")], start=1):
        store.add_published(f"law-{number}", title, "law-policy", day)
    for number, (day, title) in enumerate([(5, "Novels written with models"), (6, "Museums and generated art"), (7, "Music and licences")], start=1):
        store.add_published(f"culture-{number}", title, "culture", day)
    store.add_published("wiki-1", "A wiki page", "law-policy", 9, item_type="wiki_page")
    store.add_published("law-retired", "A retired story", "law-policy", 10, stage="retired")
    store.add_published("story-1", "The Story itself", "law-policy", 11)
    store.add_reference("law-human-stars", "Edited by hand, rated", human=True, stars=5, reason="the key ruling", day=2, summary="Rated summary.")
    store.add_reference("law-human-reason", "Edited by hand, explained", human=True, reason="primary source", day=3, summary="Reason summary.")
    store.add_reference("law-auto", "Accepted by a rule, newest", human=False, day=9, summary="Auto summary.")
    store.add_reference("law-pending", "Waiting for a decision", status="pending", day=8)
    store.add_reference("law-rejected", "Turned down", status="rejected", day=8)
    store.add_reference("culture-human", "A human choice in culture", human=True, stars=4, section=OTHER_SECTION_ID, day=2, summary="Culture summary.")
    store.add_reference("culture-auto", "A rule's choice in culture", human=False, section=OTHER_SECTION_ID, day=7, summary="Culture auto.")
    store.add_reference("culture-pending", "Culture still pending", status="pending", section=OTHER_SECTION_ID, day=7)
    store.add_reference("culture-rejected", "Culture turned down", status="rejected", section=OTHER_SECTION_ID, day=7)
    return store


def pack_for(context, **kwargs):
    with mock.patch.object(pack_module, "graphql_endpoint", return_value=ENDPOINT):
        return build_context_pack(context.store, profile="reporter", assignment="assignment-1", story_lineage_id="story-1", **kwargs)


def layer(context, name):
    return next(row for row in context.pack["layers"] if row["name"] == name)


def entry_ids(context, name):
    return [entry["id"] for entry in layer(context, name)["entries"]]


def core_room(pack):
    return sum(row["characters"] + 2 * len(row["entries"]) for row in pack["layers"] if row["name"] in pack_module.CORE_LAYERS)


def build(context, **kwargs):
    context.error = None
    try:
        context.pack = pack_for(context, **kwargs)
    except (ValueError, PermissionError) as error:
        context.error = str(error)
        context.pack = None


@given('a newsroom with a publication policy, a section "law-policy" and a Story "story-1" in it')
def step_newsroom(context):
    context.store = build_newsroom()


@given('the editor\'s assignment "assignment-1" on the Story with the direction "{direction}"')
def step_assignment(context, direction):
    assert context.store.records["Assignment"]["assignment-1"]["instructions"] == direction


@given("the section has no mission and no policy")
def step_no_doctrine(context):
    section = context.store.records["NewsroomSection"][SECTION_ID]
    section["editorialMission"] = ""
    section["editorialPolicy"] = ""


@given("the section has an accepted, a pending and a rejected Reference")
def step_statuses(context):
    assert {"law-pending", "law-rejected", "law-auto"} <= set(context.store.records["Reference"])


@given("the section has an auto-accepted Reference that is newer than every Reference an editor voted on")
def step_auto_newer(context):
    assert context.store.records["Reference"]["law-auto"]["curationStatusUpdatedAt"] > context.store.records["Reference"]["law-human-reason"]["curationStatusUpdatedAt"]


@given("another tenant has a Story published in the same section and an accepted Reference there")
def step_other_tenant(context):
    context.store.add_published("beta-story", "BETA-TENANT-STORY", "law-policy", 12, tenant="beta")
    context.store.add_reference("beta-ref", "BETA-TENANT-REFERENCE", day=12)
    context.store.records["Reference"]["beta-ref"]["curationStatusKey"] = "knowledge-corpus-beta#accepted"


@given("the Story belongs to another tenant")
def step_story_other_tenant(context):
    context.store.items[0]["tenantId"] = "beta"


@given("the Story has no section")
def step_no_section(context):
    context.store.items[0]["section"] = None


@given('the Story is at the "{stage}" stage')
def step_stage(context, stage):
    context.store.items[0]["stage"] = stage
    context.store.records["Item"]["story-1-v2"]["stage"] = stage


@given("the Story already cites a Reference that the run finds again")
def step_cited(context):
    context.store.add_reference("ref-cited", "A source the Story cites", day=5)
    context.store.link_reference("ref-cited", "cited")
    context.found_references = ["ref-cited", "ref-found"]


@given("the assignment is a plain multi-search assignment with no Story")
def step_plain(context):
    context.store.records["Assignment"]["assignment-1"] = {
        "id": "assignment-1", "assignmentTypeKey": "research.multi", "queueKey": "research:x:exploratory", "title": "Assess GLiDE",
        "status": "open", "metadata": json.dumps({"researchMode": "source_discovery", "corpusKey": "example"}),
    }


@when("the reporter context pack is built for the Story and the assignment")
def step_build(context):
    build(context)


@when("the reporter context pack is built with a budget of {budget:d} characters")
def step_build_tiny(context, budget):
    context.unbounded = pack_for(context)
    build(context, max_characters=budget)


@when("the reporter context pack is built with room for the first five layers and {more:d} more characters")
def step_build_room(context, more):
    context.unbounded = pack_for(context)
    context.more = more
    build(context, max_characters=len(context.unbounded["system"]) + core_room(context.unbounded) + more)


@when("the reporter context pack is built with room for the assignment and the Story only")
def step_build_core_only(context):
    context.unbounded = pack_for(context)
    layers = context.unbounded["layers"]
    needed = len(context.unbounded["system"]) + sum(layers[index]["characters"] + 2 * len(layers[index]["entries"]) for index in (0, 1))
    build(context, max_characters=needed + 10)


@when("the reporter context pack is built twice")
def step_build_twice(context):
    context.first = pack_for(context)
    context.second = pack_for(context)


@when("the publication policy is edited")
def step_edit_policy(context):
    context.first = getattr(context, "first", None) or context.second
    context.store.doctrine["editorial-doctrine-policy"][0]["body"] = ["A changed policy."]


@then('the layers are, in order, "{names}"')
def step_order(context, names):
    assert [row["name"] for row in context.pack["layers"]] == [name.strip() for name in names.split(",")]


@then("every layer holds at least one entry")
def step_every_layer(context):
    empty = [row["name"] for row in context.pack["layers"] if not row["entries"]]
    assert not empty, empty


@then("the user text shows the editor's direction before the Story's draft and the Story's draft before the section's published record")
def step_text_order(context):
    user = context.pack["user"]
    assert user.index(DIRECTION) < user.index(DRAFT_MARKER) < user.index("Judges weigh machine text"), user


@then("the system text carries the role, the publication policy and the section mission")
def step_system(context):
    system = context.pack["system"]
    assert "reporter" in system and "PUBLICATION-POLICY" in system and "Law and Policy MISSION" in system, system


@then("the system text is the same as without a budget")
def step_system_same(context):
    assert context.pack["system"] == context.unbounded["system"]


@then("no outer layer holds an entry")
def step_no_outer(context):
    assert all(not layer(context, name)["entries"] for name in (*pack_module.SHARED_LAYERS, *pack_module.OUTER_LAYERS))


@then("the assignment and the Story are still complete")
def step_core_complete(context):
    assert DIRECTION in context.pack["user"] and DRAFT_MARKER in context.pack["user"]
    assert context.pack["layers"][0]["entries"] and context.pack["layers"][1]["entries"]


@then("the warnings say that the section has no {kind}")
def step_warning_kind(context, kind):
    assert any(f"no {kind}" in warning for warning in context.pack["warnings"]), context.pack["warnings"]


@then('the system text does not contain the words "{words}"')
def step_not_in_system(context, words):
    assert words not in context.pack["system"].lower()


@then("the Reference layers show the accepted Reference")
def step_accepted_shown(context):
    assert "law-auto" in entry_ids(context, "desk_references")


@then("the Reference layers do not show the {status} Reference")
def step_status_hidden(context, status):
    shown = entry_ids(context, "desk_references") + entry_ids(context, "publication_references") + entry_ids(context, "story_references")
    assert not [name for name in shown if status in name], shown
    assert f"culture-{status}" not in context.pack["user"] and f"Culture {'still pending' if status == 'pending' else 'turned down'}" not in context.pack["user"]


@then("in the section's Reference layer the editor-rated Reference comes first")
def step_rated_first(context):
    assert entry_ids(context, "desk_references")[0] == "law-human-stars", entry_ids(context, "desk_references")


@then("the editor-voted Reference with a written reason comes before the auto-accepted Reference")
def step_reason_before_auto(context):
    ids = entry_ids(context, "desk_references")
    assert ids.index("law-human-reason") < ids.index("law-auto"), ids


@then("the auto-accepted Reference comes last")
def step_auto_last(context):
    ids = entry_ids(context, "desk_references")
    assert set(ids[-2:]) == {"law-auto", "law-evidence"} and ids[-2] == "law-auto", ids


@then("the assignment, the Story, its References, its conversation and its earlier research are all complete")
def step_first_five(context):
    for name in ("assignment", "story", "story_references", "story_conversation", "prior_research"):
        assert [row["id"] for row in layer(context, name)["entries"]] == [row["id"] for row in next(l for l in context.unbounded["layers"] if l["name"] == name)["entries"]]
        assert layer(context, name)["droppedCount"] == 0


@then("each outer layer holds at least one entry")
def step_each_outer(context):
    missing = [name for name in (*pack_module.SHARED_LAYERS, *pack_module.OUTER_LAYERS) if not layer(context, name)["entries"]]
    assert not missing, (missing, [(row["name"], row["characters"], row["droppedCount"]) for row in context.pack["layers"]])


@then("the section's published layer used no more than half of the {more:d} characters")
def step_half(context, more):
    row = layer(context, "desk_published")
    assert row["characters"] + 2 * len(row["entries"]) <= more // 2, row["characters"]


@then("the section's Reference layer holds at least one entry")
def step_desk_references_present(context):
    assert entry_ids(context, "desk_references")


@then("every entry in the user text is complete")
def step_whole(context):
    for row in context.pack["layers"]:
        for entry in row["entries"]:
            assert entry["characters"] > 0
    unbounded_text = context.unbounded["user"]
    for block in context.pack["user"].split("\n\n"):
        if block.startswith("## "):
            continue
    assert all(chunk in unbounded_text for chunk in context.pack["user"].split("\n\n"))


@then("at least one outer layer reports a dropped count above zero with a reason")
def step_dropped(context):
    dropped = [row for row in context.pack["layers"] if row["droppedCount"] > 0]
    assert dropped and all(row["droppedReason"] for row in dropped), context.pack["layers"]


@then("a layer that dropped nothing reports a dropped count of zero")
def step_none_dropped(context):
    clean = [row for row in context.pack["layers"] if not row["droppedReason"]]
    assert clean and all(row["droppedCount"] == 0 for row in clean)


@then("the conversation reports that its oldest messages were dropped")
def step_conversation_dropped(context):
    row = layer(context, "story_conversation")
    assert row["droppedCount"] > 0 and "oldest" in row["droppedReason"], row


@then("the References report that their summaries were dropped")
def step_summaries_dropped(context):
    row = layer(context, "story_references")
    assert row["droppedCount"] > 0 and "summaries" in row["droppedReason"], row
    assert "A court held the text was the user's." not in context.pack["user"]


@then("both packs have the same context hash")
def step_same_hash(context):
    assert context.first["contextHash"] == context.second["contextHash"]
    assert context.first["editorialContextHash"] == context.second["editorialContextHash"]


@then("the context hash changed")
def step_hash_changed(context):
    assert context.pack["contextHash"] != context.first["contextHash"]


@then("the editorial context hash changed")
def step_editorial_hash_changed(context):
    assert context.pack["editorialContextHash"] != context.first["editorialContextHash"]


@then("nothing from the other tenant appears in the user text")
def step_no_beta(context):
    assert "BETA-TENANT" not in context.pack["user"], context.pack["user"]


@then("building the pack fails because the tenant does not match")
def step_tenant_error(context):
    assert context.error and "tenant" in context.error, context.error


@then("the section layers are empty and say the Story has no section")
def step_section_layers_empty(context):
    for name in ("desk_published", "desk_references"):
        row = layer(context, name)
        assert not row["entries"] and row["emptyReason"] == "the Story has no section", row


@then("the warnings say that the Story has no section")
def step_warning_no_section(context):
    assert any("no section" in warning for warning in context.pack["warnings"]), context.pack["warnings"]


@then("the publication layers still hold entries")
def step_publication_layers(context):
    assert entry_ids(context, "publication_published") and entry_ids(context, "publication_references")


def assign(context, extra=None):
    options = {"story": "story-1", "direction": DIRECTION, **(extra or {})}
    flags = [part for key, value in options.items() for part in ((f"--{key}",) if value is True else (f"--{key}", str(value)))]
    changes = []
    context.changes = changes
    with mock.patch.object(story_commands, "create_authoring_client", return_value=(context.store, {})), \
         mock.patch("papyrus_content.assignments_workflow.publication_corpus_key", return_value="example"), \
         mock.patch("papyrus_content.assignments_workflow.build_record_changes", side_effect=lambda client, records: records), \
         mock.patch("papyrus_content.assignments_workflow.apply_record_changes", side_effect=lambda client, rows: changes.extend(rows)), \
         mock.patch("papyrus_content.assignments_workflow.update_newsroom_summary_after_assignment_creates"):
        story_commands.stories_assign_research(flags)
    context.assignment = next((row["expected"] for row in changes if row["modelName"] == "Assignment"), None)


@when('an editor assigns research on the Story with the direction "{direction}"')
def step_assign(context, direction):
    assign(context, {"direction": direction})


@when("an editor previews assigning research on the Story")
def step_assign_preview(context):
    assign(context, {"dry-run": True})


@then('an assignment of type "{kind}" works on the Story\'s lineage in the Story\'s section')
def step_assignment_type(context, kind):
    assert context.assignment["assignmentTypeKey"] == kind
    assert context.assignment["itemLineageId"] == "story-1"
    assert context.assignment["sectionKey"] == "law-policy" and context.assignment["sectionId"] == "law-policy"


@then("an assignment works on the Story's lineage")
def step_assignment_lineage(context):
    assert context.assignment["itemLineageId"] == "story-1"


@then("the assignment's instructions and metadata hold the direction")
def step_direction(context):
    assert context.assignment["instructions"] == DIRECTION
    assert json.loads(context.assignment["metadata"])["direction"] == DIRECTION


@then('the assignment\'s context profile is "{profile}" and its status is "{status}"')
def step_profile(context, profile, status):
    assert json.loads(context.assignment["metadata"])["contextProfile"] == profile and context.assignment["status"] == status


@then("the assignment records a created event")
def step_event(context):
    events = [row["expected"] for row in context.changes if row["modelName"] == "AssignmentEvent"]
    assert [event["eventType"] for event in events] == ["created"]


@then('the Story moved to the "{stage}" stage')
def step_moved(context, stage):
    updates = [payload for op, model, payload in context.store.writes if model == "Item" and payload.get("stage")]
    assert updates and updates[-1]["stage"] == stage
    assert json.loads(updates[-1]["metadata"])["stageMoves"][-1]["to"] == stage


@then("the Story did not move")
def step_not_moved(context):
    assert not [payload for op, model, payload in context.store.writes if model == "Item"]


@then("the preview wrote no record")
def step_nothing_written(context):
    assert context.changes == [] and context.store.writes == []


class RecordingLlm:
    def __init__(self):
        self.calls = []

    def __call__(self, system, user, schema):
        self.calls.append((schema["name"], system, user))
        if schema["name"] == "search_plan":
            return {"queries": [{"query": QUERY, "purpose": "rulings"}]}
        return {"summary": "Courts differ.", "recommended_angle": "Compare the rulings.", "claims": [{"claim": "A court ruled.", "sources": [1]}],
                "disagreements": [], "open_questions": ["Is there an appeal?"]}


class OneHitProvider:
    name = "gemini"

    def credential(self):
        return "not-a-key"

    def run(self, request):
        return SearchResponse([SearchHit("https://example.org/ruling", "A ruling", "A snippet.")], self.name)


@when("the multi-search run is made for the assignment")
def step_run(context):
    store = context.store
    try:
        context.expected_pack = pack_for(context, max_characters=ms.SYNTHESIS_INPUT_CHARACTERS // 2)
    except (ValueError, KeyError):
        context.expected_pack = None
    context.story_before = copy.deepcopy(store.items)
    context.llm = RecordingLlm()
    found = getattr(context, "found_references", ["ref-found"])
    if "ref-found" in found:
        store.add_reference("ref-found", "A source the run found", status="pending", section=None, human=False, day=10)
    references = [{"referenceId": reference_id} for reference_id in found]
    with mock.patch.object(pack_module, "graphql_endpoint", return_value=ENDPOINT), \
         mock.patch.object(ms, "apply_research_packet", return_value={"messageId": "message-packet-1"}) as packet, \
         mock.patch.object(ms, "intake_research_packet_proposals", return_value={"registeredReferenceCount": len(references), "references": references}), \
         mock.patch.object(ms, "build_record_changes", side_effect=lambda client, records: records), \
         mock.patch.object(ms, "apply_record_changes"), \
         mock.patch.object(ms, "update_newsroom_summary_after_research_packet_creates"):
        context.result = ms.research_multi(store, {"assignment": "assignment-1"}, llm=context.llm, providers={"gemini": OneHitProvider()})
    context.packet = json.loads(packet.call_args.args[1]["research-json"])


@then("the planning and the synthesis were given the role and the policy as their system text")
def step_systems(context):
    assert context.expected_pack, "the pack could not be built before the run"
    systems = {name: system for name, system, _ in context.llm.calls}
    assert systems["search_plan"] == context.expected_pack["system"].rstrip() + "\n\n" + ms.PLAN_SYSTEM
    assert systems["research_synthesis"] == context.expected_pack["system"].rstrip() + "\n\n" + ms.SYNTH_SYSTEM
    assert "PUBLICATION-POLICY" in systems["search_plan"]


@then("the planning brief is the pack's user text")
def step_brief(context):
    plan = next(user for name, _, user in context.llm.calls if name == "search_plan")
    assert plan == context.expected_pack["user"] and DIRECTION in plan
    synthesis = next(user for name, _, user in context.llm.calls if name == "research_synthesis")
    assert synthesis.startswith("Assignment brief:\n" + context.expected_pack["user"])


@then("the packet records the context hash, the editorial context hash and the size of each layer")
def step_packet_hashes(context):
    record = context.packet["multiSearch"]["contextPack"]
    assert record["contextHash"] == context.expected_pack["contextHash"] and record["editorialContextHash"] == context.expected_pack["editorialContextHash"]
    assert list(record["layers"]) == [row["name"] for row in context.expected_pack["layers"]]
    assert all({"entries", "characters", "droppedCount"} == set(size) for size in record["layers"].values())
    assert "PUBLICATION-POLICY" not in json.dumps(record)


@then("the packet is on no message thread")
def step_no_thread(context):
    written = [(model, payload["id"]) for op, model, payload in context.store.writes if model in ("Message", "MessageThread")]
    assert not written, written


def story_links(context):
    return [payload for op, model, payload in context.store.writes if model == "SemanticRelation" and payload.get("subjectLineageId") == "story-1"]


@then("the sources the run found are linked to the Story as consulted and not as cited")
def step_consulted(context):
    links = story_links(context)
    assert [json.loads(link["metadata"])["role"] for link in links] == ["consulted"], links
    assert links[0]["objectLineageId"] == "ref-found" and links[0]["predicate"] == "uses_evidence"


@then("the Story's text is unchanged")
def step_story_unchanged(context):
    assert context.store.items == context.story_before
    assert not [model for op, model, payload in context.store.writes if model == "Item"]


@then("the model is the default model")
def step_model(context):
    assert DEFAULT_LLM_MODEL == "gpt-6-luna" and context.packet["multiSearch"]["model"] == DEFAULT_LLM_MODEL


@then("that Reference is still linked to the Story as cited")
def step_still_cited(context):
    relation = next(row for row in context.store.relations if row.get("objectLineageId") == "ref-cited")
    assert json.loads(relation["metadata"])["role"] == "cited"
    assert "ref-cited" not in [link["objectLineageId"] for link in story_links(context)]
    assert [link["objectLineageId"] for link in story_links(context)] == ["ref-found"]


@then("the planning brief is the assignment's own brief text")
def step_plain_brief(context):
    plan = next(user for name, _, user in context.llm.calls if name == "search_plan")
    assert plan == ms.brief_text(context.store.records["Assignment"]["assignment-1"], json.loads(context.store.records["Assignment"]["assignment-1"]["metadata"]))


@then("the planning system text is the plain planning prompt")
def step_plain_system(context):
    assert next(system for name, system, _ in context.llm.calls if name == "search_plan") == ms.PLAN_SYSTEM
    assert next(system for name, system, _ in context.llm.calls if name == "research_synthesis") == ms.SYNTH_SYSTEM


@then("the packet has no context pack record")
def step_no_record(context):
    assert "contextPack" not in context.packet["multiSearch"] and not context.store.writes


@then("the earlier research appears after the conversation with its direction, summary, claims and open questions")
def step_prior_research(context):
    names = [row["name"] for row in context.pack["layers"]]
    assert names.index("prior_research") == names.index("story_conversation") + 1
    user = context.pack["user"]
    for text in ("Look at appeals first", "Two appeals were found.", "An appeal was filed.", "Who ruled?"):
        assert text in user, text
    assert user.index("Check the appeal.") < user.index("Look at appeals first") < user.index("Judges weigh machine text")


@then("the section's Reference layer holds the Reference that another Story in the section uses as evidence")
def step_section_evidence(context):
    assert "law-evidence" in entry_ids(context, "desk_references")
    assert "law-evidence" not in entry_ids(context, "publication_references")


def outer_blocks(context):
    user = context.pack["user"]
    blocks = []
    for name in pack_module.OUTER_LAYERS:
        heading = f"## {pack_module.HEADINGS[name]}\n\n"
        if heading in user:
            body = user.split(heading, 1)[1].split("\n\n## ", 1)[0]
            blocks += [entry for entry in body.split("\n\n") if entry]
    return blocks


@then("every entry in the outer layers is one line with its title, date and address")
def step_compact(context):
    blocks = outer_blocks(context)
    assert blocks and all("\n" not in block and "Title:" not in block and "Summary:" not in block for block in blocks), blocks
    assert any("Liability for output | 2026-10-08" in block and "law-4" in block for block in blocks)


@then("the first sentence of the summary or deck follows and the rest of it does not")
def step_first_sentence(context):
    user = context.pack["user"]
    assert "Deck of Liability for output" in user
    outer = "\n".join(outer_blocks(context))
    assert "A study of court filings" in outer and "It counts them." not in outer


@then("an editor's reason and stars stay on an outer entry when present")
def step_reason_stars(context):
    outer = "\n".join(outer_blocks(context))
    assert "accepted because the key ruling" in outer and "5 stars" in outer


@then("a Reference whose title is only its address shows no title line in the Story's References")
def step_no_url_title(context):
    section = context.pack["user"].split("## References already attached to the Story", 1)[1].split("\n\n## ", 1)[0]
    assert "Title: https://" not in section and "https://example.org/ref-url" in section and "A notice about disclosure. It has more." in section


@then("in the outer layers such a Reference leads with the first sentence of its summary")
def step_url_title_lead(context):
    outer = outer_blocks(context)
    line = next(block for block in outer if "law-url-title" in block)
    assert line.startswith("Opens with the ruling.") and "More text follows." not in line, line


def related(context):
    return layer(context, "related_references")["entries"]


@then("the layer of related References comes right after the Story's References")
def step_related_placed(context):
    names = [row["name"] for row in context.pack["layers"]]
    assert names.index("related_references") == names.index("story_references") + 1


@then("it holds the other end of edges in both directions, each once, and none already on the Story")
def step_related_both(context):
    ids = [entry["id"] for entry in related(context)]
    assert {"rel-accepted", "rel-high", "rel-low"} <= set(ids), ids
    assert len(ids) == len(set(ids)) and not {"ref-attached", "ref-url"} & set(ids), ids
    assert next(entry for entry in related(context) if entry["id"] == "rel-low")["score"] == 0.7


@then("the edge an editor accepted comes first, with the editor's note and the Reference it connects to")
def step_related_person_first(context):
    assert related(context)[0]["id"] == "rel-accepted" and related(context)[0]["connection"] == "accepted"
    user = context.pack["user"]
    assert "Editor's note on the connection: Same court, same week." in user and "Connects to: The attached ruling" in user
    assert "A ruling the editor linked. It has detail." in user


@then("the suggested edges follow by descending score and are labelled with their score and curation status")
def step_related_scores(context):
    ids = [entry["id"] for entry in related(context)]
    assert ids.index("rel-high") < ids.index("rel-low") and ids.index("rel-accepted") == 0, ids
    user = context.pack["user"]
    assert "suggested, score 0.90" in user and "Curation status: pending" in user and "Curation status: accepted" in user


@then("a rejected edge and a rejected Reference never appear in the related layer")
def step_related_rejected(context):
    ids = [entry["id"] for entry in related(context)]
    assert "rel-by-declined-edge" not in ids and "rel-turned-down" not in ids, ids
    assert "A related Reference that was rejected" not in context.pack["user"]


@then("no related Reference appears again in another layer")
def step_related_once(context):
    related_ids = {entry["id"] for entry in related(context)}
    elsewhere = {entry["id"] for row in context.pack["layers"] if row["name"] != "related_references" for entry in row["entries"]}
    assert not related_ids & elsewhere, related_ids & elsewhere


@then("a Reference only a rejected edge connects is not in the related layer")
def step_edge_rejected_only(context):
    assert "rel-by-declined-edge" not in [entry["id"] for entry in related(context)]
