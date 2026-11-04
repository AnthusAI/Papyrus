import contextlib
import io
import json
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

from papyrus_content import newsroom_context_pack as pack_module
from papyrus_content import section_concepts
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.newsroom_context_pack import build_context_pack
from papyrus_content.section_concepts import build_editor_concept_node, concept_slug

from newsroom_context_pack_steps import ENDPOINT, SECTION_ID, TENANT, build_newsroom, layer, moment, give_core_concepts

FIXTURE = "scripts/fixtures/editor-concept-vectors.json"


def node_row(name, *, aliases=(), status="accepted", description=None):
    slug = concept_slug(name)
    return {"id": f"concept-{slug}-v1", "lineageId": f"concept-{slug}", "versionState": "current", "versionNumber": 1,
            "nodeKey": f"editor_concept--{slug}", "nodeKind": "editor_concept", "displayName": name, "aliases": list(aliases),
            "status": status, "description": description}


def core(context):
    raw = context.store.records["NewsroomSection"][SECTION_ID].get("coreConcepts")
    return json.loads(raw) if raw else []


def run_command(context, flags):
    context.error = None
    out = io.StringIO()
    with mock.patch.object(section_concepts, "create_authoring_client", return_value=(context.store, None)), contextlib.redirect_stdout(out):
        try:
            section_concepts.sections_concepts(flags)
        except ValueError as error:
            context.error = str(error)
    context.output = out.getvalue()


def pack(context, profile="reporter", **kwargs):
    with mock.patch.object(pack_module, "graphql_endpoint", return_value=ENDPOINT):
        return build_context_pack(context.store, profile=profile, story_lineage_id="story-1", **kwargs)


@given('a newsroom whose section "law-policy" has one core concept and a Story "story-1" in it')
def step_newsroom(context):
    context.store = build_newsroom()
    give_core_concepts(context.store)


@given('the newsroom knows a concept "{name}" with the alias "{alias}"')
def step_known_with_alias(context, name, alias):
    row = node_row(name, aliases=[alias])
    context.store.records["SemanticNode"][row["id"]] = row


@given('the newsroom knows a rejected concept "{name}"')
def step_known_rejected(context, name):
    row = node_row(name, status="rejected")
    context.store.records["SemanticNode"][row["id"]] = row


@given('the section has "{name}" as a core concept too')
def step_has_too(context, name):
    entries = core(context) + [{"conceptLineageId": f"concept-{concept_slug(name)}", "note": None, "addedBy": "An Editor", "addedAt": moment(2)}]
    context.store.records["NewsroomSection"][SECTION_ID]["coreConcepts"] = json.dumps(entries)


@given("the section has no core concepts")
def step_has_none(context):
    context.store.records["NewsroomSection"][SECTION_ID]["coreConcepts"] = None


@when("the editor lists the core concepts of the section")
def step_list(context):
    run_command(context, ["--section", "law-policy"])


@when('the editor adds the concept "{name}" with the note "{note}"')
def step_add_note(context, name, note):
    run_command(context, ["add", "--section", "law-policy", "--concept", name, "--note", note])


@when('the editor adds the concept "{name}" asking to create it')
def step_add_create(context, name):
    run_command(context, ["add", "--section", "law-policy", "--concept", name, "--create"])


@when('the editor adds the concept "{name}" as a dry run')
def step_add_dry(context, name):
    context.store.writes.clear()
    run_command(context, ["add", "--section", "law-policy", "--concept", name, "--dry-run"])


@when('the editor adds the concept "{name}"')
def step_add(context, name):
    run_command(context, ["add", "--section", "law-policy", "--concept", name])


@when('the editor removes the concept "{name}"')
def step_remove(context, name):
    run_command(context, ["remove", "--section", "law-policy", "--concept", name])


@when('the concept "{name}" is rejected')
def step_reject(context, name):
    row = next(row for row in context.store.records["SemanticNode"].values() if row["displayName"] == name)
    row["status"] = "rejected"


@then('the list shows the concept "{name}" as a core concept')
def step_list_shows(context, name):
    assert context.error is None, context.error
    assert name in context.output and "\tcore\t" in context.output, context.output


@then("the section has both core concepts in the order they were added")
def step_both(context):
    assert [entry["conceptLineageId"] for entry in core(context)] == ["concept-containment", "concept-confinement-problem"], core(context)


@then("the new entry holds the note, who added it and when")
def step_entry(context):
    entry = core(context)[-1]
    assert entry["note"] == "The sibling of containment" and entry["addedBy"] == "papyrus-cli" and entry["addedAt"], entry


@then('the section has the core concept "{name}"')
def step_has(context, name):
    assert context.error is None, context.error
    nodes = {row["lineageId"]: row for row in context.store.records["SemanticNode"].values()}
    assert name in [nodes[entry["conceptLineageId"]]["displayName"] for entry in core(context)], core(context)


@then('the command is refused saying "{text}"')
def step_refused(context, text):
    assert context.error and text in context.error, context.error


@then("the section still has one core concept")
def step_still_one(context):
    assert len(core(context)) == 1, core(context)


@then("the section has no core concepts")
def step_none(context):
    assert core(context) == [], core(context)


@then("the newsroom has written nothing")
def step_nothing_written(context):
    assert context.store.writes == [], context.store.writes


@then("the newsroom holds an editor concept written exactly as the shared fixture says")
def step_matches_fixture(context):
    case = next(case for case in json.load(open(FIXTURE))["cases"] if case["slug"] == "a" * 80)
    row = context.store.records["SemanticNode"]["semantic-node-editor_concept--the-sandbox-problem-v1"]
    made = build_editor_concept_node("the sandbox problem", "papyrus-cli", row["createdAt"])
    assert row == made, (row, made)
    assert set(row) == set(case["node"]), set(row) ^ set(case["node"])


@then("the Python writer produces every editor concept in the shared fixture")
def step_fixture(context):
    for case in json.load(open(FIXTURE))["cases"]:
        assert concept_slug(case["name"]) == case["slug"], case["name"]
        if case["node"] is None:
            try:
                build_editor_concept_node(case["name"], case["actor"], case["now"])
            except ValueError:
                continue
            raise AssertionError("an empty name must be refused")
        assert build_editor_concept_node(case["name"], case["actor"], case["now"]) == case["node"], case["name"]


# --- the pack ----------------------------------------------------------------------------------------------------------------------------

@given('the core concept has an alias, a description and the editor\'s note "{note}"')
def step_concept_details(context, note):
    node = context.store.records["SemanticNode"]["concept-containment-v1"]
    node.update(aliases=["the containment issue"], description="Keeping a capable system inside its limits.")
    entries = core(context)
    entries[0]["note"] = note
    context.store.records["NewsroomSection"][SECTION_ID]["coreConcepts"] = json.dumps(entries)


@given('the concept is linked to another concept by a suggestion and by a link an editor accepted with the note "{note}"')
def step_concept_links(context, note):
    for name in ("confinement problem", "alignment tax"):
        row = node_row(name)
        context.store.records["SemanticNode"][row["id"]] = row

    def link(relation_id, other, state, metadata):
        context.store.relations.append({
            "id": relation_id, "relationState": state, "predicate": "related_to", "subjectKind": "semanticNode", "objectKind": "semanticNode",
            "subjectLineageId": "concept-containment", "objectLineageId": other, "subjectStateKey": f"semanticNode#concept-containment#{state}",
            "objectStateKey": f"semanticNode#{other}#{state}", "metadata": json.dumps(metadata)})

    link("link-machine", "concept-alignment-tax", "current", {"provenance": "derived"})
    link("link-person", "concept-confinement-problem", "current", {"decision": "accepted", "decidedBy": "An Editor", "note": note})


@then('each pack\'s section concepts layer holds a card for "{name}"')
def step_each_card(context, name):
    for built in context.packs:
        rows = {row["name"]: row for row in built["layers"]}
        assert [entry["name"] for entry in rows["section_concepts"]["entries"]] == [name], built["layers"]
    context.pack = context.packs[0]


def card_text(context):
    heading = f"## {pack_module.HEADINGS['section_concepts']}\n\n"
    return context.pack["user"].split(heading, 1)[1].split("\n\n## ", 1)[0]


@then("the card shows the alias, the kind, the description and the editor's note")
def step_card_fields(context):
    text = card_text(context)
    for expected in ("Concept: containment problem", "Also called: the containment issue", "Kind: editor_concept",
                     "Description: Keeping a capable system inside its limits.", "Why it matters here"):
        assert expected in text, (expected, text)


@then("the card lists the accepted link with its note before the suggested one")
def step_card_links(context):
    text = card_text(context)
    accepted = text.index("related_to: confinement problem; accepted by an editor; the editor's note on the link: Two sides of one fence")
    assert accepted < text.index("related_to: alignment tax"), text
    context.sample_card = text


@then("the section concepts come before the section's published Stories in every pack")
def step_before_published(context):
    for built in context.packs:
        names = [row["name"] for row in built["layers"]]
        assert names.index("section_concepts") < names.index("concept_references") < names.index("desk_published"), names


@given("the section also has a core concept that no longer exists")
def step_gone(context):
    entries = core(context) + [{"conceptLineageId": "concept-vanished", "note": None, "addedBy": "An Editor", "addedAt": moment(2)}]
    context.store.records["NewsroomSection"][SECTION_ID]["coreConcepts"] = json.dumps(entries)


@given('the core concept "{name}" is rejected')
def step_core_rejected(context, name):
    step_reject(context, name)


@when("the reporter context pack is built for the Story")
def step_reporter(context):
    context.pack = pack(context, assignment="assignment-1")


@then("the section concepts layer holds no card")
def step_no_card(context):
    assert layer(context, "section_concepts")["entries"] == []


@then("the warnings name both concepts")
def step_warnings(context):
    joined = " ".join(context.pack["warnings"])
    assert "concept-vanished" in joined and "containment problem" in joined and "rejected" in joined, joined


def tag(context, relation_id, reference, predicate, *, status="accepted", human=True, stars=None, subject_kind="reference"):
    context.store.add_reference(reference, f"About {reference}", status=status, human=human, stars=stars, day=5, summary="A summary. More.")
    context.store.relations.append({
        "id": relation_id, "relationState": "current", "predicate": predicate, "subjectKind": subject_kind, "objectKind": "semanticNode",
        "subjectLineageId": reference, "objectLineageId": "concept-containment", "subjectStateKey": f"reference#{reference}#current",
        "objectStateKey": "semanticNode#concept-containment#current", "metadata": json.dumps({"decision": "accepted", "decidedBy": "An Editor"})})


@given("an accepted Reference mentions the core concept and an editor-rated Reference is tagged with it")
def step_ring(context):
    tag(context, "mention-1", "concept-mention", "mentions", human=False)
    tag(context, "tag-1", "concept-rated", "related_to", stars=5)
    tag(context, "tag-pending", "concept-pending", "related_to", status="pending")


@then('the concept References layer lists the editor-rated one first, labelled "{label}"')
def step_ring_first(context, label):
    entries = layer(context, "concept_references")["entries"]
    ids = [entry["id"] for entry in entries if entry["id"] in ("concept-rated", "concept-mention")]
    assert ids == ["concept-rated", "concept-mention"], [entry["id"] for entry in entries]
    heading = f"## {pack_module.HEADINGS['concept_references']}\n\n"
    context.ring_text = context.pack["user"].split(heading, 1)[1].split("\n\n## ", 1)[0]
    rated = next(line for line in context.ring_text.split("\n\n") if "About concept-rated" in line)
    assert label in rated, rated
    context.sample_ring_line = rated


@then('the mention is labelled "{label}"')
def step_mention_label(context, label):
    assert label in next(line for line in context.ring_text.split("\n\n") if "About concept-mention" in line)


@then("a pending Reference tagged with the concept is not listed")
def step_pending_absent(context):
    assert "concept-pending" not in [entry["id"] for entry in layer(context, "concept_references")["entries"]]


@given("the Story's own Reference is tagged with the core concept")
def step_own(context):
    context.store.relations.append({
        "id": "tag-own", "relationState": "current", "predicate": "related_to", "subjectKind": "reference", "objectKind": "semanticNode",
        "subjectLineageId": "ref-attached", "objectLineageId": "concept-containment", "subjectStateKey": "reference#ref-attached#current",
        "objectStateKey": "semanticNode#concept-containment#current", "metadata": "{}"})


@then("the concept References layer does not list the Story's own Reference")
def step_own_absent(context):
    ids = [entry["lineageId"] for entry in layer(context, "concept_references")["entries"]]
    assert "ref-attached" not in ids and "law-tagged" in ids, ids


@then('both concept layers are empty with the reason "{reason}"')
def step_empty_reason(context, reason):
    for name in ("section_concepts", "concept_references"):
        row = layer(context, name)
        assert row["entries"] == [] and row["emptyReason"] == reason, row


class SchemaWithoutCoreConcepts:
    def __init__(self):
        self.asked = 0

    def request(self, _method, _path, body=None, headers=None):
        self.last = json.loads(body)["query"]

    def getresponse(self):
        refused = "coreConcepts" in self.last
        self.asked += refused
        answer = ({"errors": [{"message": "Validation error of type FieldUndefined: Field 'coreConcepts' in type 'NewsroomSection' is undefined"}]}
                  if refused else {"data": {"listNewsroomSections": {"items": [{"id": "section-1"}]}}})
        return SimpleNamespace(status=200, reason="OK", read=lambda: json.dumps(answer).encode("utf-8"))

    def close(self):
        pass


@given("a site whose schema has no core concepts on a section")
def step_old_site(context):
    context.old_connection = SchemaWithoutCoreConcepts()
    context.old_client = PapyrusGraphQLAuthoringClient(endpoint="https://example.test/graphql", header_factory=lambda _payload: {}, tenant_id="old-site")
    context.old_client._connection = context.old_connection


@when("the router reads that site's sections twice")
def step_read_sections(context):
    query = "query { listNewsroomSections { items { id title coreConcepts } } }"
    context.old_reads = [context.old_client.graphql(query), context.old_client.graphql(query)]


@then("both reads return the sections and the field was asked for once")
def step_old_reads(context):
    assert [read["listNewsroomSections"]["items"] for read in context.old_reads] == [[{"id": "section-1"}]] * 2
    assert context.old_connection.asked == 1, context.old_connection.asked


# --- the budget -------------------------------------------------------------------------------------------------------------------------

@when("the reporter context pack is built with room for the core layers minus one character")
def step_tight_budget(context):
    from newsroom_context_pack_steps import core_room

    full = pack(context, assignment="assignment-1")
    context.pack = pack(context, assignment="assignment-1", max_characters=len(full["system"]) + core_room(full) - 1)


@then("the card still lists the accepted link with its note")
def step_accepted_kept(context):
    assert "related_to: confinement problem; accepted by an editor; the editor's note on the link: Two sides of one fence" in card_text(context), card_text(context)


@then("the card no longer lists the suggested link")
def step_machine_gone(context):
    assert "alignment tax" not in card_text(context), card_text(context)


@then("the section concepts layer records the dropped machine link")
def step_dropped_recorded(context):
    row = layer(context, "section_concepts")
    assert row["droppedCount"] == 1 and "machine links dropped" in row["droppedReason"], row
