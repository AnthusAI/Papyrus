import copy
import io
import json
import os
import tempfile
import urllib.request
from contextlib import redirect_stdout
from unittest.mock import patch

from behave import given, then, when

from papyrus_content.editorial_context import hosted_publication


class BackendClient:
    """An in-memory authoring client: just the calls the operator commands make."""

    tenant_id = None
    endpoint = "https://publication.example.test/graphql"

    def __init__(self):
        self.tables = {}
        self.summaries = []

    def list_by_index(self, index, key):
        assert index == "knowledgeCorporaByRoleAndName"
        return copy.deepcopy([row for row in self.tables.get("KnowledgeCorpus", {}).values() if row.get("role") == key])

    def list_records(self, model):
        return copy.deepcopy(list(self.tables.get(model, {}).values()))

    def get_record(self, model, record_id):
        return copy.deepcopy(self.tables.get(model, {}).get(record_id))

    def create_record(self, model, record):
        self.tables.setdefault(model, {})[record["id"]] = copy.deepcopy(record)

    update_record = create_record

    def upsert(self, model, record):
        self.create_record(model, record)

    def update_newsroom_summary(self, delta, **kwargs):
        self.summaries.append(delta)

    def corpora(self):
        return list(self.tables.get("KnowledgeCorpus", {}).values())


def _canonical(context, key):
    context.backend.tables.setdefault("KnowledgeCorpus", {})[f"knowledge-corpus-{key}"] = {
        "id": f"knowledge-corpus-{key}", "name": key.title(), "role": "canonical"}


@given("a fresh backend with no canonical corpus")
def fresh_backend(context):
    context.backend = BackendClient()
    context.error = None


@given('a backend whose canonical corpus is "{key}"')
def backend_with_corpus(context, key):
    fresh_backend(context)
    _canonical(context, key)


def _run(context, action):
    context.error = None
    context.output = io.StringIO()
    try:
        with redirect_stdout(context.output):
            action()
    except Exception as error:  # noqa: BLE001 - scenarios assert on the operator-facing message
        context.error = str(error)


@when('the operator runs publication init for key "{key}" named "{name}"')
def run_init(context, key, name):
    from papyrus_content.publication import publication_init_command

    with patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(context.backend, {})):
        _run(context, lambda: publication_init_command(["--key", key, "--name", name]))


@then('the backend has one canonical corpus "{key}" named "{name}"')
def one_corpus_named(context, key, name):
    assert [(row["id"], row["name"]) for row in context.backend.corpora()] == [(f"knowledge-corpus-{key}", name)], context.backend.corpora()
    assert context.backend.corpora()[0]["role"] == "canonical"


@then('the backend still has one canonical corpus "{key}"')
def still_one_corpus(context, key):
    assert [row["id"] for row in context.backend.corpora()] == [f"knowledge-corpus-{key}"]


@then('editorial context resolves the publication "{key}"')
def context_resolves(context, key):
    assert hosted_publication(context.backend)["key"] == key


@then("the command reports the publication already exists")
def reports_exists(context):
    assert context.error is None, context.error
    assert "\texists\t" in context.output.getvalue()


@then('the command fails saying the backend already serves "{key}"')
def fails_serves(context, key):
    assert context.error and f"already serves publication {key}" in context.error, context.error


@when("editorial context is requested")
def request_context(context):
    _run(context, lambda: hosted_publication(context.backend))


@then('the error mentions "{text}"')
def error_mentions(context, text):
    assert context.error and text in context.error, context.error


@when('a deploy runs with the brand corpus key "{key}" and name "{name}"')
def deploy_ensures(context, key, name):
    from papyrus_content.publication import ensure_publication_from_environment

    _run(context, lambda: ensure_publication_from_environment(
        context.backend, {"PAPYRUS_PUBLICATION_CORPUS_KEY": key, "PAPYRUS_PUBLICATION_NAME": name}))
    assert context.error is None, context.error


def _write_catalog(context, items):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"items": items}, handle)
    handle.close()
    context.add_cleanup(os.unlink, handle.name)
    context.catalog_path = handle.name


@given("a catalog with an item that has an item_id and an item that has none")
def catalog_two_items(context):
    _write_catalog(context, [
        {"item_id": "first-item", "title": "First", "source_uri": "https://example.test/first", "media_type": "text/html",
         "ingestion_rationale": "Why it matters"},
        {"title": "Second", "source_uri": "https://example.test/second", "media_type": "text/html",
         "ingestion_rationale": "Why it matters too"},
    ])


@given("a catalog with an item that has no item_id and no source URL")
def catalog_no_id(context):
    _write_catalog(context, [{"title": "Nothing to key on", "ingestion_rationale": "Why"}])


def _unreachable(*args, **kwargs):
    import urllib.error

    raise urllib.error.URLError("network unreachable")


def _register(context, extra):
    from papyrus_content.cli import references_register_catalog

    # No repo steering file exists in a data-driven publication.
    with patch("papyrus_content.cli.create_authoring_client", return_value=(context.backend, {})), \
            patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam", "PAPYRUS_STEERING_CONFIG": ""}), \
            patch("papyrus_content.steering.resolve_topics_steering_config_path", return_value="/nonexistent/papyrus-steering.yml"), \
            patch("papyrus_content.records.upload_attachment_body"), \
            patch("urllib.request.urlopen", _unreachable if getattr(context, "offline", False) else urllib.request.urlopen):
        _run(context, lambda: references_register_catalog(
            ["--catalog", context.catalog_path, "--status", "pending", *extra]))


@when("the operator registers the catalog as pending with no steering file and no corpus key")
def register_plain(context):
    _register(context, [])


@then("the registration succeeds")
def registration_succeeds(context):
    assert context.error is None, context.error


@when('the operator registers the catalog as pending with corpus key "{key}"')
def register_with_key(context, key):
    _register(context, ["--corpus-key", key])


@then('both references exist in corpus "{key}"')
def both_exist(context, key):
    references = context.backend.tables.get("Reference", {})
    assert len(references) == 2, references
    assert {ref["corpusId"] for ref in references.values()} == {f"knowledge-corpus-{key}"}
    assert {ref["curationStatus"] for ref in references.values()} == {"pending"}


@then("the computed item_id of the second reference is derived from its source URL")
def computed_id(context):
    from papyrus_content.catalog import catalog_item_with_external_item_id

    expected = catalog_item_with_external_item_id({"source_uri": "https://example.test/second"})["item_id"]
    assert expected in {ref["externalItemId"] for ref in context.backend.tables["Reference"].values()}


@then("the registration fails with a publication binding mismatch")
def binding_mismatch(context):
    assert context.error and "publication binding mismatch" in context.error, context.error
    assert not context.backend.tables.get("Reference")


@then("the registration fails saying catalog item 1 has no item_id and no source_uri")
def no_id(context):
    assert context.error and "Catalog item 1 has no item_id and no source_uri" in context.error, context.error


@when("a caller without an editor session requests pending reference intake")
def intake_refused(context):
    from procedures.newsroom.tests.test_reference_intake import ENV, IDENTITY, payload
    from papyrus_content.reference_intake import intake_references

    reader = copy.deepcopy(IDENTITY)
    reader["claims"]["cognito:groups"] = ["reader"]
    with patch.dict(os.environ, ENV):
        _run(context, lambda: intake_references(BackendClient(), payload(), reader))
    assert context.error, "intake should be refused"


@then('the refusal mentions "{first}" and "{second}"')
def refusal_mentions(context, first, second):
    assert first in context.error and second in context.error, context.error


@given("a signed-in session for a different publication endpoint")
def other_publication_session(context):
    from papyrus_content.cli_user_auth import AuthConfig, SiteSession
    from procedures.newsroom.tests.test_cli_user_auth import MemoryStore, Provider

    config = AuthConfig(
        publication="https://news.example.test", issuer="https://cognito-idp.us-east-1.amazonaws.com/pool",
        client_id="native-client", oauth_domain="https://news.auth.us-east-1.amazoncognito.com",
        graphql_endpoint="https://abc.appsync-api.us-east-1.amazonaws.com/graphql",
        callback_uri="http://127.0.0.1:5182/oauth/callback", refresh_lifetime_seconds=172800)
    clock = [1000.0]
    context.session = SiteSession(config, store=MemoryStore(), provider=Provider(clock), clock=lambda: clock[0],
                              receive=lambda *args: "unused")


@when("GraphQL headers are requested for this endpoint")
def headers_for_other_endpoint(context):
    _run(context, lambda: context.session.headers("https://other.appsync-api.us-east-1.amazonaws.com/graphql"))


@given("the network is unreachable")
def offline(context):
    context.offline = True


@then("the registration output has no traceback")
def no_traceback(context):
    assert "Traceback" not in context.output.getvalue() and "URLError" not in context.output.getvalue()


@given('a backend with section "{section}" and canonical corpus "{key}"')
def backend_with_section(context, section, key):
    backend_with_corpus(context, key)
    context.backend.tables["NewsroomSection"] = {section: {"id": section, "title": section.title()}}


def _hide_steering():
    return patch("papyrus_content.steering.resolve_topics_steering_config_path", return_value="/nonexistent/papyrus-steering.yml")


def _run_cli(context, args):
    from papyrus_content import cli as content_cli

    with patch("papyrus_content.story_commands.create_authoring_client", return_value=(context.backend, {})), \
            patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(context.backend, {})), \
            patch("papyrus_content.cli.create_authoring_client", return_value=(context.backend, {})), \
            patch("papyrus_content.assignments_commands.create_authoring_client", return_value=(context.backend, {})), \
            patch("papyrus_content.records.upload_attachment_body"), _hide_steering():
        _run(context, lambda: content_cli.dispatch(args[0], args[1], args[2:]))
    assert context.error is None, context.error


@when('the operator creates a story titled "{title}" in section "{section}" at stage "{stage}"')
def create_story(context, title, section, stage):
    _run_cli(context, ["stories", "create", "--title", title, "--section", section, "--stage", stage])


@when('the operator creates a story titled "{title}" in section "{section}" at stage "{stage}" with an assignment')
def create_story_with_assignment(context, title, section, stage):
    _run_cli(context, ["stories", "create", "--title", title, "--section", section, "--stage", stage, "--with-assignment"])


@then('one content item exists at stage "{stage}" and no assignment exists')
def item_no_assignment(context, stage):
    items = list(context.backend.tables.get("Item", {}).values())
    assert [item["stage"] for item in items] == [stage], items
    assert not context.backend.tables.get("Assignment")


@then("one content item exists at stage \"{stage}\" and the assignment works on it")
def item_with_assignment(context, stage):
    items = list(context.backend.tables.get("Item", {}).values())
    assert [item["stage"] for item in items] == [stage], items
    assignments = list(context.backend.tables.get("Assignment", {}).values())
    assert [a["itemLineageId"] for a in assignments] == [items[0]["lineageId"]]


@when('the operator creates a reporting assignment titled "{title}" in section "{section}" with no corpus key')
def create_reporting(context, title, section):
    _run_cli(context, ["assignments", "create-reporting", "--title", title, "--section", section])


@then('the assignment is for corpus "{key}"')
def assignment_corpus(context, key):
    assignments = list(context.backend.tables.get("Assignment", {}).values())
    assert [a["corpusId"] for a in assignments] == [f"knowledge-corpus-{key}"]
