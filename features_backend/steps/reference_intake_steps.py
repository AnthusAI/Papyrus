import copy
import json
from behave import given, when, then
from procedures.newsroom.tests.test_reference_intake import IntakeClient, submit, payload, IDENTITY, address_only
from papyrus_content.reference_intake import IntakeError
from papyrus_content.story_reporting import link_reference_to_story, story_references
from procedures.newsroom.tests.test_story_reporting import LINEAGE


@given('an isolated publication intake backend')
def isolated(context):
    context.intake_client = IntakeClient()
    context.intake_before = copy.deepcopy(context.intake_client.tables)


def _backend_env(context):
    return getattr(context, 'intake_env', None)


@given('the backend carries a tenant and declares that it serves a single publication')
def single_publication(context):
    context.intake_env = {'PAPYRUS_TENANT_ID': 'tenant-a', 'PAPYRUS_SINGLE_PUBLICATION_BACKEND': 'true'}


@given('the backend carries a tenant and does not declare that it serves a single publication')
def undeclared(context):
    context.intake_env = {'PAPYRUS_TENANT_ID': 'tenant-a', 'PAPYRUS_SINGLE_PUBLICATION_BACKEND': ''}


@given('the backend carries a tenant and declares "{value}" for the single publication setting')
def declared_value(context, value):
    context.intake_env = {'PAPYRUS_TENANT_ID': 'tenant-a', 'PAPYRUS_SINGLE_PUBLICATION_BACKEND': value}


@when('its editor registers a reporting source')
def register(context):
    context.intake_result = submit(context.intake_client, env=_backend_env(context))


@then('the source is pending with attributable provenance')
def pending(context):
    ref = context.intake_client.tables['Reference'][context.intake_result['references'][0]['id']]
    assert ref['curationStatus'] == 'pending'
    assert ref['versionCreatedBy'] == 'user:editor-sub'
    provenance = json.loads(next(iter(context.intake_client.uploads.values())))
    assert provenance['actorSub'] == 'editor-sub'
    assert provenance['rationale'] == 'Primary reporting source'


@then('its returned record can be linked as consulted without changing the story')
def linked(context):
    c = context.intake_client
    link_reference_to_story(c, LINEAGE, context.intake_result['references'][0]['id'], role='consulted', actor='ChatGPT')
    assert story_references(c, LINEAGE)[0]['role'] == 'consulted'
    assert c.tables['Item'] == context.intake_before['Item']
    assert not c.tables.get('Message')
    assert not c.tables.get('PublishedItem')


@when('its editor repeats intake using a canonical equivalent URL')
def repeat(context):
    c = context.intake_client
    context.first_intake = submit(c)
    context.first_state = copy.deepcopy(c.tables)
    context.intake_result = submit(c, payload('HTTPS://EXAMPLE.TEST:443/report#different'))


@then('the same immutable source and provenance are returned')
def repeated(context):
    assert context.intake_result['references'] == context.first_intake['references']
    assert context.intake_client.tables == context.first_state
    assert len(context.intake_client.uploads) == 1


@when('intake is requested with a valid editor session')
def valid_editor(context):
    _attempt(context, payload(), copy.deepcopy(IDENTITY))


@when('intake is requested with an editor session whose token has the "{claim}" claim')
def tenant_token(context, claim):
    identity = copy.deepcopy(IDENTITY)
    identity['claims'][claim] = 'tenant-a'
    _attempt(context, payload(), identity)


@then('the refusal names the setting that declares a single publication')
def names_setting(context):
    assert 'PAPYRUS_SINGLE_PUBLICATION_BACKEND=true' in context.intake_refusal


def _attempt(context, data, identity):
    try:
        submit(context.intake_client, data, identity, env=_backend_env(context))
    except IntakeError as error:
        context.intake_rejected = True
        context.intake_refusal = str(error)
    else:
        raise AssertionError('Unauthorized intake succeeded')


@when('intake is requested with {violation}')
def rejected(context, violation):
    identity = copy.deepcopy(IDENTITY)
    data = payload()
    if violation == 'no identity': identity = {}
    if violation == 'a reader role': identity['claims']['cognito:groups'] = ['reader']
    if violation == 'another issuer': identity['claims']['iss'] = 'https://other/pool'
    if violation == 'another publication': data['publicationEndpoint'] = 'https://other/graphql'
    if violation == 'another corpus': data['corpusId'] = 'foreign-corpus'
    if violation == 'a caller selected tenant': data['tenantId'] = 'foreign'
    _attempt(context, data, identity)


@then('no intake data is written')
def untouched(context):
    assert context.intake_rejected
    assert context.intake_client.tables == context.intake_before
    assert not context.intake_client.uploads


class _CatalogClient:
    """Stands in for the signed-in AppSync client: one scripted answer per request, no network."""

    endpoint = "https://api.example.test/graphql"

    def __init__(self, timeout_on=None):
        self.calls = []
        self.timeout_on = timeout_on

    def graphql(self, query, variables):
        data = json.loads(variables["input"])
        self.calls.append(data)
        if len(self.calls) == self.timeout_on:
            raise TimeoutError("The read operation timed out")
        # The server derives the id from the source URL, so a repeat returns the same record.
        references = [{"id": "ref-" + item["source_uri"].rsplit("/", 1)[1], "curationStatus": "pending"} for item in data["items"]]
        return {"intakePendingReferences": json.dumps({"ok": True, "references": references})}


@given('a catalog file of {count:d} sources and a signed-in editor session')
def catalog_file(context, count):
    import tempfile
    from pathlib import Path

    directory = Path(tempfile.mkdtemp(prefix="papyrus-catalog-"))
    context.catalog_path = directory / "catalog.json"
    context.catalog_path.write_text(json.dumps({"items": [
        {"source_uri": f"https://example.test/paper-{number}", "title": f"Paper {number}", "ingestion_rationale": "Relevant."}
        for number in range(1, count + 1)
    ]}))
    context.catalog_client = _CatalogClient()
    context.catalog_runs = []


@given('the second request times out')
def second_times_out(context):
    context.catalog_client.timeout_on = 2


def _run_catalog(context):
    import contextlib
    import io
    from unittest.mock import patch

    from papyrus_content.cli import references_register_catalog

    steering = {"corpora": [{"key": "one", "name": "One", "role": "source"}]}
    out, failure = io.StringIO(), None
    flags = ["--config", "ignored", "--corpus-key", "one", "--catalog", str(context.catalog_path), "--status", "pending"]
    with patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "user"}), \
            patch("papyrus_content.cli.create_authoring_client", return_value=(context.catalog_client, {})), \
            patch("papyrus_content.reference_intake_cli.require_steering_config", return_value=steering), \
            contextlib.redirect_stdout(out):
        try:
            references_register_catalog(flags)
        except Exception as error:  # noqa: BLE001
            failure = error
    context.catalog_runs.append((out.getvalue().splitlines(), failure))


@when('the editor runs references create-from-catalog')
def run_catalog(context):
    _run_catalog(context)


@when('the editor runs references create-from-catalog twice')
def run_catalog_twice(context):
    _run_catalog(context)
    _run_catalog(context)


@then('the command sent {count:d} requests of one source each, in catalog order')
def one_each(context, count):
    calls = context.catalog_client.calls
    assert len(calls) == count, len(calls)
    assert [len(call["items"]) for call in calls] == [1] * count
    assert [call["items"][0]["source_uri"] for call in calls] == [f"https://example.test/paper-{n}" for n in range(1, count + 1)]


@then('it printed one recorded line per source, numbered "1/{total:d}" to "{last}"')
def numbered(context, total, last):
    lines = [line.split("\t") for line in context.catalog_runs[-1][0]]
    recorded = [line for line in lines if line[2] == "recorded"]
    assert [line[3] for line in recorded] == [f"{n}/{total}" for n in range(1, total + 1)], recorded
    assert last == f"{total}/{total}"


@then('it ended with a summary of {confirmed:d} confirmed and {missing:d} not confirmed')
def summary(context, confirmed, missing):
    lines = context.catalog_runs[-1][0]
    assert lines[-1] == f"references\tcreate-from-catalog\tsummary\tconfirmed={confirmed}\tnot-confirmed={missing}", lines[-1]


@then('it printed a failed line for "{position}" naming the source')
def failed_line(context, position):
    lines = [line.split("\t") for line in context.catalog_runs[-1][0]]
    failed = [line for line in lines if line[2] == "failed"]
    assert len(failed) == 1 and failed[0][3] == position and failed[0][4] == "https://example.test/paper-2", failed
    assert "timed out" in failed[0][5]


@then('the command failed telling the editor to run the same command again')
def failed_run_again(context):
    failure = context.catalog_runs[-1][1]
    assert isinstance(failure, ValueError) and "Run the same command again" in str(failure), failure


@then('both runs recorded the same Reference ids')
def same_ids(context):
    first, second = ([line.split("\t")[5] for line in lines if "\trecorded\t" in line] for lines, _ in context.catalog_runs)
    assert first == second == ["ref-paper-1", "ref-paper-2", "ref-paper-3"], (first, second)



@given('an isolated publication intake backend with one canonical corpus')
def with_canonical_corpus(context):
    isolated(context)
    context.intake_client.tables['KnowledgeCorpus'] = {
        'knowledge-corpus-pub': {'id': 'knowledge-corpus-pub', 'role': 'canonical', 'name': 'Publication'}}
    context.intake_before = copy.deepcopy(context.intake_client.tables)


@when('its editor registers an address with nothing else')
def register_address_only(context):
    try:
        context.intake_result = submit(context.intake_client, address_only())
        context.intake_refused = False
    except IntakeError:
        context.intake_refused = True


@then('the address is a pending Reference in the publication\'s own corpus')
def address_is_pending(context):
    ref = context.intake_client.tables['Reference'][context.intake_result['references'][0]['id']]
    assert ref['curationStatus'] == 'pending'
    assert ref['corpusId'] == 'knowledge-corpus-pub'
    context.address_reference = ref


@then('its title is the address and its rationale says an editor added it from the Newsroom')
def address_title(context):
    assert context.address_reference['title'] == 'https://example.test/well-architected-agent'
    provenance = json.loads(next(iter(context.intake_client.uploads.values())))
    assert provenance['rationale'] == 'Added by an editor from the Newsroom.'


@then('adding the same address again returns the same Reference')
def address_again(context):
    again = submit(context.intake_client, address_only())
    assert again['references'][0]['id'] == context.intake_result['references'][0]['id']
    assert len(context.intake_client.tables['Reference']) == 1


@then('the registration is refused and nothing is written')
def address_refused(context):
    assert context.intake_refused
    assert not context.intake_client.tables['Reference']
    assert not context.intake_client.uploads
