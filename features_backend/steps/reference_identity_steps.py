import copy
import json
from contextlib import redirect_stdout
from io import StringIO

from behave import given, when, then

from papyrus_content.reference_duplicates_report import build_duplicates_report
from papyrus_content.reference_identity import identity_keys
from procedures.newsroom.tests import reference_identity_support as support
from procedures.newsroom.tests.reference_identity_support import held_reference

PATHS = {
    "monitor delivery": support.through_monitor_delivery,
    "editor intake": support.through_editor_intake,
    "research intake": support.through_research_intake,
    "chat create": support.through_chat_create,
    "catalog import": support.through_catalog_import,
    "citation graph": support.through_citation_graph,
}
CORPUS_OF = {"same": support.FIRST_CORPUS, "other": support.SECOND_CORPUS}


@given('a Reference for the address "{address}"')
def a_reference_for_the_address(context, address):
    context.held_row = {"sourceUri": address}


@when('a source arrives as "{form}"')
def a_source_arrives(context, form):
    context.arriving_row = {"sourceUri": form}


@then('the two share an identity key')
def share_a_key(context):
    assert identity_keys(context.held_row) & identity_keys(context.arriving_row), (context.held_row, context.arriving_row)


@then('the two share no identity key')
def share_no_key(context):
    assert not (identity_keys(context.held_row) & identity_keys(context.arriving_row))


@given('a fully captured Reference whose text has a hash')
def captured_reference(context):
    context.held_row = {"sourceUri": "https://example.org/one", "capturedTextSha256": "c" * 64, "captureState": "full"}


@when('another fully captured Reference has text with the same hash')
def another_captured_reference(context):
    context.arriving_row = {"sourceUri": "https://mirror.example/one", "capturedTextSha256": "c" * 64, "captureState": "full"}


@then('a thinly captured Reference with that hash shares none')
def thin_reference(context):
    thin = {"capturedTextSha256": "c" * 64, "captureState": "thin"}
    assert not (identity_keys(context.held_row) & identity_keys(thin))


@given('a Reference titled "{title}" at "{address}"')
def a_titled_reference(context, title, address):
    context.held_row = held_reference(address, title=title, number=1)


@when('a source titled "{title}" arrives at "{address}"')
def a_titled_source(context, title, address):
    context.arriving_row = held_reference(address, title=title, number=2)


@then('the report counts them as a same-title candidate and not as a duplicate')
def title_candidate(context):
    report = build_duplicates_report([context.held_row, context.arriving_row])
    assert report["identity"]["groups"] == 0 and report["sameTitleCandidates"]["groups"] == 1


@given('a publication that holds an accepted Reference for "{address}"')
def a_publication_holding(context, address):
    context.address = address
    context.holding = address


@when('the {path} brings "{address}" to the {corpus} corpus')
def a_path_brings(context, path, address, corpus):
    context.client = support.publication_holding(context.holding, corpus=CORPUS_OF[corpus], held_in=support.FIRST_CORPUS, status="accepted")
    context.held_before = copy.deepcopy(context.client.references())
    context.client.writes.clear()
    printed = StringIO()
    with redirect_stdout(printed):
        context.path_result = PATHS[path](context.client, address, corpus=CORPUS_OF[corpus])
    context.path_printed = printed.getvalue()
    context.path_name = path


@when('the editor intake offers "{address}" as a new source')
def the_editor_brings(context, address):
    context.client = support.publication_holding(context.holding, status="accepted")
    context.path_result = support.through_editor_intake(context.client, address)


@when('research intake proposes "{address}" twice')
def research_twice(context, address):
    context.client = support.publication_holding(context.holding, status="accepted")
    context.held_before = copy.deepcopy(context.client.references())
    support.through_research_intake(context.client, address)
    context.path_result = support.through_research_intake(context.client, address)


@then('no Reference is created')
def nothing_created(context):
    assert support.created_references(context.client) == []
    assert ("create", "Reference") not in context.client.writes


@then('the held Reference is still accepted')
def still_accepted(context):
    (held,) = context.client.references()
    assert held["curationStatus"] == "accepted"
    assert held["lineageId"] == "reference-held-1"


@then('the held Reference is returned or reported')
def returned_or_reported(context):
    result = context.path_result
    text = json.dumps(result, default=str) + getattr(context, "path_printed", "")
    assert "reference-held-1" in text, result


@then('one Reference is created and it is pending')
def one_created(context):
    (created,) = support.created_references(context.client)
    assert created["curationStatus"] == "pending"


@given('a publication with three forms of one paper and two same-titled pages')
def a_publication_for_the_report(context):
    from procedures.newsroom.tests.test_reference_identity import report_rows

    context.client = support.RecordingMemory("knowledge-corpus-alpha-site")
    for row in report_rows():
        context.client.rows[("Reference", row["id"])] = row
    context.rows_before = copy.deepcopy(context.client.rows)


@when('the duplicates report runs')
def the_report_runs(context):
    import papyrus_content.references_commands as commands
    from unittest import mock

    output = StringIO()
    with mock.patch.object(commands, "create_authoring_client", return_value=(context.client, {})), redirect_stdout(output):
        commands.references_duplicates(["--format", "json"])
    context.report = json.loads(output.getvalue())


@then('it finds one identity group with two extra rows')
def one_group(context):
    assert context.report["identity"]["groups"] == 1 and context.report["identity"]["extraRows"] == 2


@then('it counts one same-title group of candidates that are not one identity')
def one_title_group(context):
    assert context.report["sameTitleCandidates"]["groupsNotAlreadyOneIdentity"] == 1


@then('nothing in the publication was written or changed')
def nothing_written(context):
    assert context.client.writes == [] and context.client.rows == context.rows_before
