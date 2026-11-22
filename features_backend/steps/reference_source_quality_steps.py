import json

from behave import given, then, when

from papyrus_newsroom import reference_curation_signals

THE_TIME_OF_THE_RATING = "2026-11-20T12:00:00Z"


class KnowledgeGraphHeldInMemory:
    def __init__(self):
        self.relations_out_of_the_reference = []
        self.ratings_with_no_concept_yet = set()

    def list_outgoing(self, subject_kind, subject_lineage_id):
        return {"relations": list(self.relations_out_of_the_reference)}

    def get_semantic_object(self, object_kind, object_id):
        for rating in self.ratings_with_no_concept_yet:
            if object_id == reference_curation_signals.quality_node_id(rating):
                raise ValueError(f"{object_kind} {object_id} was not found")
        return {"id": object_id}


@given('a Reference titled "{title}" with no source quality rating yet')
def reference_with_no_source_quality_rating(context, title):
    context.reference_to_rate = {
        "id": "reference-a-v1",
        "lineageId": "reference-a",
        "versionNumber": 1,
        "corpusId": "knowledge-corpus-test",
        "title": title,
        "sourceUri": "https://example.org/teens-and-ai-companions",
        "importRunId": "import-1",
    }
    context.knowledge_graph = KnowledgeGraphHeldInMemory()
    context.quality_plan = None
    context.quality_refusal = None
    context.publication_policies = {"records": []}


@given("the knowledge graph has no concept for {rating:d} star quality yet")
def knowledge_graph_has_no_concept_for_rating(context, rating):
    context.knowledge_graph.ratings_with_no_concept_yet.add(rating)


@given("the Reference already has a source quality of {rating:d}")
def reference_already_has_source_quality(context, rating):
    context.knowledge_graph.relations_out_of_the_reference.append({
        "id": "quality-relation-earlier",
        "relationState": "current",
        "relationTypeKey": reference_curation_signals.QUALITY_RELATION_TYPE_KEY,
        "objectLineageId": reference_curation_signals.quality_node_lineage_id(rating),
        "score": rating,
        "metadata": {"qualityRating": rating},
    })


def plan_the_source_quality(context, rating, *, refresh=False, note="", actor_label="papyrus"):
    try:
        context.quality_plan = reference_curation_signals.build_reference_quality_plan(
            reference=context.reference_to_rate,
            rating=rating,
            note=note,
            actor_label=actor_label,
            refresh=refresh,
            now=THE_TIME_OF_THE_RATING,
            semantic_client=context.knowledge_graph,
        )
    except ValueError as refusal:
        context.quality_refusal = str(refusal)


@when("the Reference is given a source quality of {rating:d} afresh")
def reference_is_given_source_quality_afresh(context, rating):
    plan_the_source_quality(context, rating, refresh=True)


@when("the Reference is given a source quality of {rating}")
def reference_is_given_source_quality(context, rating):
    plan_the_source_quality(context, rating)


@when('"{rater}" gives the Reference a source quality of {rating:d} with the note "{note}"')
def rater_gives_source_quality_with_note(context, rater, rating, note):
    plan_the_source_quality(context, rating, note=note, actor_label=rater)


def records_of_the_quality_plan(context, *, model_name, action):
    assert context.quality_refusal is None, context.quality_refusal
    return [
        record["input"]
        for record in context.quality_plan["records"]
        if record["modelName"] == model_name and record["action"] == action
    ]


def the_new_quality_relation(context) -> dict:
    new_relations = records_of_the_quality_plan(context, model_name="SemanticRelation", action="create")
    assert len(new_relations) == 1, new_relations
    return new_relations[0]


@then('the plan writes one new quality relation scored {rating:d} that points at the concept "{concept_key}"')
def plan_writes_one_new_quality_relation(context, rating, concept_key):
    relation = the_new_quality_relation(context)
    assert relation["score"] == rating, relation
    assert reference_curation_signals.QUALITY_RELATION_TYPE_KEY in (relation.get("relationTypeKey"), relation.get("predicate")), relation
    assert relation["subjectLineageId"] == context.reference_to_rate["lineageId"], relation
    assert reference_curation_signals.quality_node_key(rating) == concept_key
    assert relation["objectLineageId"] == reference_curation_signals.quality_node_lineage_id(rating), relation


@then("the plan supersedes {count:d} earlier quality relations")
def plan_supersedes_earlier_quality_relations(context, count):
    superseded = records_of_the_quality_plan(context, model_name="SemanticRelation", action="update")
    assert len(superseded) == count, superseded
    assert all(relation["relationState"] == "superseded" for relation in superseded), superseded
    assert not [record for record in context.quality_plan["records"] if record["action"] == "delete"]


@then("the superseded relation records that a rating of {rating:d} replaced it")
def superseded_relation_records_replacement(context, rating):
    superseded = records_of_the_quality_plan(context, model_name="SemanticRelation", action="update")[0]
    assert superseded["id"] == "quality-relation-earlier", superseded
    assert superseded["metadata"]["supersededByRating"] == rating, superseded
    assert superseded["metadata"]["supersededAt"] == THE_TIME_OF_THE_RATING, superseded


@then('the plan also writes the concept "{display_name}"')
def plan_also_writes_the_concept(context, display_name):
    concepts = records_of_the_quality_plan(context, model_name="SemanticNode", action="create")
    assert len(concepts) == 1, concepts
    assert display_name in concepts[0].values(), concepts[0]


@then("the plan writes no concept")
def plan_writes_no_concept(context):
    assert records_of_the_quality_plan(context, model_name="SemanticNode", action="create") == []


@then("the quality plan writes no records at all")
def quality_plan_writes_no_records(context):
    assert context.quality_refusal is None, context.quality_refusal
    assert context.quality_plan["action"] == "noop", context.quality_plan
    assert context.quality_plan["records"] == []


@then("the plan names the relation that already holds the rating")
def plan_names_the_relation_that_holds_the_rating(context):
    assert context.quality_plan["existingRelationId"] == "quality-relation-earlier", context.quality_plan


@then('the new quality relation records the rater "{rater}", the note "{note}" and the time of the rating')
def new_quality_relation_records_rater_note_and_time(context, rater, note):
    metadata = the_new_quality_relation(context)["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    assert metadata["actorLabel"] == rater, metadata
    assert metadata["note"] == note, metadata
    assert metadata["ratedAt"] == THE_TIME_OF_THE_RATING, metadata


@then('the quality rating is refused with "{reason}"')
def quality_rating_is_refused(context, reason):
    assert context.quality_plan is None, context.quality_plan
    assert context.quality_refusal == reason, context.quality_refusal


@given('the publication has the policy "{label}" that says "{paragraph}"')
def publication_has_the_policy(context, label, paragraph):
    context.publication_policies = {"records": [{"label": label, "body": [paragraph]}]}


@when("the instructions for a model's quality assessment are written")
def instructions_for_quality_assessment_are_written(context):
    context.quality_assessment_instructions = reference_curation_signals.build_quality_assessment_prompt(
        "A national survey of 1,060 teenagers asked how often they talk to AI companions.",
        reference=context.reference_to_rate,
        rubric=reference_curation_signals.QUALITY_ASSESSMENT_RUBRIC,
        doctrine_context=context.publication_policies,
    )


@then('the instructions show the model the policy "{paragraph}"')
def instructions_show_the_policy(context, paragraph):
    assert paragraph in context.quality_assessment_instructions, context.quality_assessment_instructions


@then('the instructions say "{sentence}"')
def instructions_say(context, sentence):
    assert sentence in context.quality_assessment_instructions, context.quality_assessment_instructions


@then('the instructions ask for a rating that is "{wording}"')
def instructions_ask_for_a_rating(context, wording):
    assert wording in context.quality_assessment_instructions, context.quality_assessment_instructions


@given('a model rated the Reference {rating:d} because "{rationale}" with {evidence_count:d} pieces of evidence and {caveat_count:d} caveats')
def model_rated_the_reference(context, rating, rationale, evidence_count, caveat_count):
    context.model_quality_assessment = {
        "rating": rating,
        "rationale": rationale,
        "evidence": [f"Evidence {number}" for number in range(1, evidence_count + 1)],
        "caveats": [f"Caveat {number}" for number in range(1, caveat_count + 1)],
        "model": "gpt-5.4-mini",
        "promptVersion": reference_curation_signals.QUALITY_ASSESSMENT_PROMPT_VERSION,
    }


@when("the model's assessment is turned into the note for the rating")
def assessment_is_turned_into_the_note(context):
    context.quality_note = reference_curation_signals._quality_assessment_note(context.model_quality_assessment)


@then('the note gives the reason "{rationale}"')
def note_gives_the_reason(context, rationale):
    assert rationale in context.quality_note.splitlines()[0], context.quality_note


@then("the note lists {evidence_count:d} pieces of evidence and {caveat_count:d} caveats")
def note_lists_evidence_and_caveats(context, evidence_count, caveat_count):
    lines_by_heading = {line.split(": ", 1)[0]: line.split(": ", 1)[1] for line in context.quality_note.splitlines()[1:]}
    assert len(lines_by_heading["Evidence"].split("; ")) == evidence_count, context.quality_note
    assert len(lines_by_heading["Caveats"].split("; ")) == caveat_count, context.quality_note
