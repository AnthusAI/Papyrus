"""Tenant knowledge keys: the one builder, the writers that use it, and Reference intake on a shared stack."""
import copy
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from papyrus_content.catalog import reference_record
from papyrus_content.reference_feed_keys import feed_keys, feed_state_key
from papyrus_content.reference_intake import IntakeError, intake_references
from papyrus_content.tenant_knowledge_keys import (REFERENCE_FEED_KEY, REFERENCE_LINK_FEED_KEY, REFERENCE_REVIEWED_FEED_KEY, SEMANTIC_NODE_FEED_KEY,
                                                   SEMANTIC_RELATION_FEED_KEY, corpus_id_for_key, corpus_key_of, global_key, tenant_corpus_id)
from papyrus_content.tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE, TenantError
from procedures.newsroom.tests.test_reference_intake import ENDPOINT, ENV, IDENTITY, IntakeClient, payload

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTORS = REPO_ROOT / "scripts" / "fixtures" / "reference-feed-key-vectors.json"
FEEDS = [REFERENCE_FEED_KEY, REFERENCE_REVIEWED_FEED_KEY, SEMANTIC_NODE_FEED_KEY, SEMANTIC_RELATION_FEED_KEY, REFERENCE_LINK_FEED_KEY]


def _quoted(text):
    return re.findall(r'"([^"]*)"', text)


def _stack(context, mode, process_tenant=None):
    """Set the stack's tenancy mode and the process's configured tenant for the rest of the scenario, then restore the environment."""
    patcher = patch.dict(os.environ, {}, clear=False)
    patcher.start()
    context.add_cleanup(patcher.stop)
    os.environ.pop(TENANCY_MODE_ENVIRONMENT_VARIABLE, None)
    os.environ.pop("PAPYRUS_TENANT_ID", None)
    if mode == "shared":
        os.environ[TENANCY_MODE_ENVIRONMENT_VARIABLE] = "shared"
    if process_tenant:
        os.environ["PAPYRUS_TENANT_ID"] = process_tenant
    context.mode = mode


@given("the tenant knowledge key builder")
def builder(context):
    context.refusal = None
    context.built = None


@given("a shared stack")
def shared(context):
    _stack(context, "shared")


@given("a dedicated stack")
def dedicated(context):
    _stack(context, "dedicated")


@given('a dedicated stack whose fixed tenant id is "{tenant}"')
def dedicated_with_tenant(context, tenant):
    _stack(context, "dedicated", tenant)


@given('a shared stack whose process is configured for tenant "{tenant}"')
def shared_configured(context, tenant):
    _stack(context, "shared", tenant)


@when('tenant "{tenant}" builds the global keys {keys}')
def build_global_keys(context, tenant, keys):
    context.built = [global_key(value, tenant) for value in _quoted(keys)]


@when('the global keys and the corpus id of the corpus key "{key}" are built')
def build_unscoped(context, key):
    context.built = [global_key(value) for value in FEEDS]
    context.corpus_id = corpus_id_for_key(key)


@then("the keys are {keys}")
def keys_are(context, keys):
    assert context.built == _quoted(keys), context.built


@when('tenant "{tenant}" builds the corpus id of the corpus key "{key}"')
def build_corpus(context, tenant, key):
    context.corpus_id = corpus_id_for_key(key, tenant)
    context.tenant = tenant


@then('the corpus id is "{expected}"')
def corpus_is(context, expected):
    assert context.corpus_id == expected, context.corpus_id


@then("building it again from that id leaves it as it is")
def idempotent(context):
    assert tenant_corpus_id(context.corpus_id, context.tenant) == context.corpus_id


@then('the corpus key of that id is "{key}"')
def corpus_key(context, key):
    assert corpus_key_of(context.corpus_id) == key


@when('tenant "{first}" and tenant "{second}" each build the corpus id of the corpus key "{key}"')
def two_tenants(context, first, second, key):
    context.corpus_ids = [corpus_id_for_key(key, first), corpus_id_for_key(key, second)]
    context.feed_keys = [feed_state_key({"corpusId": corpus_id, "curationStatus": "pending"}) for corpus_id in context.corpus_ids]


@then("the two corpus ids differ")
def ids_differ(context):
    assert len(set(context.corpus_ids)) == 2


@then("the two Reference feed keys differ")
def feed_keys_differ(context):
    assert len(set(context.feed_keys)) == 2


@when("a global key is built with no tenant")
def global_without_tenant(context):
    try:
        context.built = global_key(REFERENCE_FEED_KEY)
        context.refusal = None
    except TenantError as error:
        context.built, context.refusal = None, str(error)


@when('the corpus id of the corpus key "{key}" is built with no tenant')
def corpus_without_tenant(context, key):
    try:
        context.corpus_id = corpus_id_for_key(key)
        context.refusal = None
    except TenantError as error:
        context.corpus_id, context.refusal = None, str(error)


@then("the build is refused naming the tenant it needs")
def refused(context):
    assert context.refusal and "tenant" in context.refusal and "PAPYRUS_TENANT_ID" in context.refusal, context.refusal


@then("no key is returned")
def no_key(context):
    assert context.built is None


@then('the key is "{expected}"')
def key_is(context, expected):
    assert context.built == expected, context.built


def _write_reference(context, tenant, status, key):
    item = {"item_id": "lead", "title": "Source", "source_uri": "https://example.test/report", "curation_status": status}
    plan = reference_record(item, {"corpusId": corpus_id_for_key(key, tenant), "importRunId": "run", "now": "2026-11-13T12:00:00Z", "actor": "tester", "tenantId": tenant})
    context.reference = plan["expected"]


@when('tenant "{tenant}" writes a pending Reference from the catalog in the corpus key "{key}"')
def write_pending(context, tenant, key):
    _write_reference(context, tenant, "pending", key)


@when('tenant "{tenant}" writes an accepted Reference from the catalog in the corpus key "{key}"')
def write_accepted(context, tenant, key):
    _write_reference(context, tenant, "accepted", key)


@when('the stack writes an accepted Reference from the catalog in the corpus key "{key}"')
def write_unscoped(context, key):
    _write_reference(context, None, "accepted", key)


@then('the Reference\'s corpus id is "{expected}"')
def reference_corpus(context, expected):
    assert context.reference["corpusId"] == expected


@then('its feed state key starts with "{prefix}"')
def feed_state_starts(context, prefix):
    assert feed_keys(context.reference)["feedStateKey"].startswith(prefix)


@then('its newsroom feed key is "{expected}"')
def newsroom_feed(context, expected):
    assert context.reference["newsroomFeedKey"] == expected


@then('its reviewed feed key is "{expected}"')
def reviewed_feed(context, expected):
    assert context.reference["reviewedFeedKey"] == expected


@then("it has no reviewed feed key")
def no_reviewed(context):
    assert context.reference["reviewedFeedKey"] is None


@given("{count} References across {tenants} tenants")
def many_references(context, count, tenants):
    total, tenant_count = int(count.replace(",", "")), int(tenants)
    context.rows = []
    for number in range(total):
        tenant = f"tenant-{number % tenant_count:02d}" if number % tenant_count else "alpha"
        corpus_id = corpus_id_for_key("demo", tenant)
        row = {"id": f"reference-{number}-v1", "corpusId": corpus_id, "curationStatus": "pending", "versionState": "current", "createdAt": "2026-11-13T12:00:00Z"}
        context.rows.append({**row, **feed_keys(row)})


@when('"{tenant}" opens Predictions')
def open_predictions(context, tenant):
    context.partition = f"{corpus_id_for_key('demo', tenant)}#unrated"
    context.read = [row for row in context.rows if row["feedStateKey"] == context.partition]


@then('the index query\'s partition starts with an "{tenant}" corpus id')
def partition_starts(context, tenant):
    assert context.partition.startswith(f"{tenant}.knowledge-corpus-"), context.partition


@then("no other tenant's row is read")
def only_own_rows(context):
    assert context.read and all(row["corpusId"].startswith("alpha.") for row in context.read)
    assert len(context.read) < len(context.rows)


@given("the shared vector file with tenant cases")
def vector_file(context):
    context.vectors = json.loads(VECTORS.read_text())["tenant"]
    assert context.vectors


@when("the Python builder runs every tenant case")
def run_vectors(context):
    from papyrus_content.tenant_knowledge_keys_test import TENANT_VECTORS, _environment, _run
    context.results = []
    for vector in TENANT_VECTORS:
        with patch.dict(os.environ, {}):
            for name in (TENANCY_MODE_ENVIRONMENT_VARIABLE, "PAPYRUS_TENANT_ID"):
                os.environ.pop(name, None)
            if vector["mode"] == "shared":
                os.environ[TENANCY_MODE_ENVIRONMENT_VARIABLE] = "shared"
            if vector["environmentTenantId"]:
                os.environ["PAPYRUS_TENANT_ID"] = vector["environmentTenantId"]
            try:
                context.results.append((vector, _run(vector), None))
            except TenantError as error:
                context.results.append((vector, None, error))


@then("it produces the keys in the file")
def vectors_match(context):
    for vector, found, refusal in context.results:
        if vector.get("refused"):
            assert refusal is not None, vector["name"]
        else:
            assert refusal is None and found == vector["key"], vector["name"]


@then("the TypeScript twin is tested against the same file by npm run test:tenant-knowledge-keys")
def typescript_twin(context):
    package = json.loads((REPO_ROOT / "package.json").read_text())
    assert "scripts/test-tenant-knowledge-keys.ts" in package["scripts"]["test:tenant-knowledge-keys"]
    assert "reference-feed-key-vectors.json" in (REPO_ROOT / "scripts" / "test-tenant-knowledge-keys.ts").read_text()


def _session(claims):
    identity = copy.deepcopy(IDENTITY)
    identity["claims"].update(claims)
    return identity


@given('an editor session whose token names tenant "{tenant}"')
def session_with_tenant(context, tenant):
    context.identity = _session({"papyrus_tenant_editor": tenant})


@given("an editor session with no tenant claim")
def session_without_tenant(context):
    context.identity = _session({})


@when("the editor adds a source URL for Reference intake")
def add_source(context):
    client = IntakeClient()
    corpus_id = corpus_id_for_key("demo", "alpha") if context.mode == "shared" else "corpus-one"
    client.tables["KnowledgeCorpus"] = {corpus_id: {"id": corpus_id, "role": "canonical", "name": "Demo"}}
    environment = {key: value for key, value in ENV.items() if key != "PAPYRUS_TENANT_ID"}   # the stack under test sets the tenant itself
    context.intake_client = client
    try:
        with patch.dict(os.environ, environment), patch("papyrus_content.reference_intake.upload_attachment_body", client.upload):
            context.intake_result = intake_references(client, payload(corpusId=corpus_id), context.identity)
        context.intake_refusal = None
    except IntakeError as error:
        context.intake_result, context.intake_refusal = None, str(error)


@then("the intake is accepted")
def intake_accepted(context):
    assert context.intake_refusal is None and context.intake_result["references"], context.intake_refusal


@then('the new Reference is in the corpus "{corpus_id}"')
def intake_corpus(context, corpus_id):
    reference = context.intake_client.tables["Reference"][context.intake_result["references"][0]["id"]]
    assert reference["corpusId"] == corpus_id
    assert reference["newsroomFeedKey"] == "alpha#references"


@then("the intake is refused naming PAPYRUS_SINGLE_PUBLICATION_BACKEND")
def intake_refused(context):
    assert context.intake_refusal and "PAPYRUS_SINGLE_PUBLICATION_BACKEND" in context.intake_refusal
