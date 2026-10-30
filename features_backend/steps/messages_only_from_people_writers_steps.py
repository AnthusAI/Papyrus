import json
from pathlib import Path
import sys

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_newsroom_tools as tools  # noqa: E402
import test_ontology_enrichment as ontology_tests  # noqa: E402
from papyrus_content import form_submissions_commands as forms  # noqa: E402
from papyrus_content import ontology_enrichment as ontology  # noqa: E402
from papyrus_newsroom import coverage_theme, email_submission_replies, tactus_runtime  # noqa: E402

NOW = "2026-05-21T12:00:00Z"


def _reference(index, title):
    return {
        "id": f"reference-{index}", "lineageId": f"reference-{index}", "versionState": "current",
        "corpusId": "knowledge-corpus-ai-ml-research", "title": title, "sourceUri": f"https://example.com/{index}",
        "sourcePublishedAt": "2026-05-20T12:00:00Z", "curationStatus": "accepted",
    }


@given("accepted references about a topic in a corpus")
def trend_references(context):
    context.references = [_reference(1, "AI tools reshape video game design workflows"), _reference(2, "Studios test generative NPC behavior in games")]


@when("I build an edition trend report for that topic")
def build_trend(context):
    context.report = coverage_theme.signals_trend_report(
        corpus_key="AI-ML-research", topic="AI in video games", coverage_key="coverage.ai-in-video-games",
        references=context.references, semantic_nodes=[], newsroom_sections=[], now=NOW)


@then("the report ranks at least one signal")
def ranks(context):
    assert context.report["signals"]


@then("the report carries no records to write")
def no_records(context):
    assert "records" not in context.report and "apply" not in context.report


@given("accepted references that mention concepts in a corpus")
def concept_fixture(context):
    context.fixture = tools.NewsroomToolTests()._concept_report_fixture()


@when("I build a concept report of every type")
def build_concepts(context):
    context.report = coverage_theme.signals_concept_report(
        corpus_key="AI-ML-research", report_type="all", limit=3, trend_window_days=7, now=NOW,
        references=context.fixture["references"], semantic_nodes=context.fixture["semantic_nodes"],
        semantic_relations=context.fixture["semantic_relations"])


@then("the report has popularity, trending and pagerank sections")
def sections(context):
    assert {section["reportType"] for section in context.report["reports"]} == {"popularity", "trending", "pagerank"}


@given("an ontology relation between two concepts")
def ontology_relation(context):
    suite = ontology_tests.OntologyEnrichmentTests()
    context.state = suite.build_state()
    context.relation = context.state["models"]["SemanticRelation"][0]


@when("the relationship explainer records its explanation")
def explain(context):
    fingerprint = ontology.relation_explanation_fingerprint(context.state, context.relation)
    built = ontology.build_relation_context(context.state, context.relation, input_fingerprint=fingerprint)
    context.records = ontology.build_relation_explanation_records(
        context.relation, built, {"meaning": "Alpha is mentioned.", "confidence": 0.9, "model": "test-model"}, now=NOW)


@then("the only record to write is a model attachment owned by the relation")
def only_attachment(context):
    assert [record["modelName"] for record in context.records] == ["ModelAttachment"]
    assert context.records[0]["expected"]["ownerId"] == context.relation["id"]


@then("no Message and no link relation are written")
def no_message(context):
    assert not [record for record in context.records if record["modelName"] in {"Message", "SemanticRelation"}]


class _FormClient:
    def __init__(self):
        self.messages = [{"id": "form-1", "messageKind": "form_submission", "messageType": "form_submission", "status": "active",
                          "summary": "contact from Ada", "authorLabel": "Ada", "metadata": json.dumps({"formId": "contact"}),
                          "createdAt": "2026-10-21T12:00:00Z"}]
        self.created = []

    def graphql(self, query, variables):
        return {"listMessagesByKindAndCreatedAt": {"items": list(self.messages), "nextToken": None}}

    def get_record(self, model, record_id):
        return next((m for m in self.messages if m["id"] == record_id), None)

    def create_record(self, model, payload):
        self.created.append(payload)

    def update_record(self, model, payload):
        self.get_record(model, payload["id"]).update(payload)


@given("a public form submission that is open")
def open_submission(context):
    context.client = _FormClient()
    context.original_factory = forms.create_authoring_client
    forms.create_authoring_client = lambda: (context.client, None)
    context.add_cleanup(lambda: setattr(forms, "create_authoring_client", context.original_factory))


@when("an operator marks the submission handled with a note")
def handle(context):
    forms.messages_handle(["--message-id", "form-1", "--note", "answered by email"])


@then("the submission's own status is handled and its metadata keeps the note")
def handled(context):
    row = context.client.messages[0]
    assert row["status"] == "handled"
    assert json.loads(row["metadata"])["handledNote"] == "answered by email"


@then("no new Message is created")
def none_created(context):
    assert context.client.created == [] and len(context.client.messages) == 1


@then("the submission no longer lists as open")
def not_open(context):
    rows = [forms.submission_row(m) for m in context.client.messages]
    assert [r["status"] for r in rows] == ["handled"]


@given("the Tactus tools the newsroom agents can call")
def tactus_tools(context):
    context.tools = set(tactus_runtime.API_METHODS) if hasattr(tactus_runtime, "API_METHODS") else None
    assert context.tools is not None, "tactus_runtime must expose its tool table"


@then("the tools include listing Reference notes")
def has_list(context):
    assert ("reference", "note_list") in context.tools


@then("the tools do not include creating a Reference note")
def no_create(context):
    assert ("reference", "note_create") not in context.tools


@then("the email agent is told that notes come only from people")
def email_prompt(context):
    prompt = email_submission_replies._email_agent_instructions()
    assert "note_create" not in prompt and "Messages come only from people" in prompt
