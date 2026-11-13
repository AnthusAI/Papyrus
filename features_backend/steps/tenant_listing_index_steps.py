"""Steps for features_backend/tenant-listing-index.feature (PPY-1ce06f).

The export scenario runs the tenant client against the in-memory AppSync and DynamoDB double of the tenant-client tests, which counts the
rows each read touches. The ledger scenario runs the real check script on the reader steering schema, with ReaderVote's tenantId index
taken out (the released shape) and with a second new index added.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests.test_tenancy import InMemoryGraphQLBackend, seed_reader_votes, tenant_client  # noqa: E402

READER_VOTE_FIELDS = "id tenantId subjectKey subjectType readerId dimension value voterRole"
READER_STEERING_SCHEMA = REPO_ROOT / "amplify" / "plugins" / "reader-steering" / "schema.ts"
TENANT_INDEX = 'index("tenantId").sortKeys(["id"]).name("votesByTenant").queryField("listReaderVotesByTenant")'
SECOND_INDEX = 'index("readerId").name("votesByReader").queryField("listReaderVotesByReader")'


@given("{count:d} tenants with ReaderVote rows")
def tenants_with_votes(context, count):
    context.backend = InMemoryGraphQLBackend()
    context.vote_counts = {}
    for number in range(count):
        tenant = "alpha" if number == 0 else f"tenant-{number:02d}"
        context.vote_counts[tenant] = number % 9 + 4   # tenants of different sizes, alpha among the small ones
        seed_reader_votes(context.backend, tenant, context.vote_counts[tenant])


@when('the tenant "{tenant}" is exported')
def tenant_exported(context, tenant):
    context.exported_tenant = tenant
    context.backend.queries.clear()
    context.backend.rows_read = 0
    context.exported_rows = tenant_client(context.backend, tenant).list_tenant_rows("ReaderVote", READER_VOTE_FIELDS)


@then("ReaderVote is read through the tenantId index and the read count equals alpha's rows")
def read_through_tenant_index(context):
    tenant = context.exported_tenant
    fields = [re.search(r"\{\s*(\w+)\(", query).group(1) for query, _ in context.backend.queries]
    assert fields and set(fields) == {"listReaderVotesByTenant"}, fields
    assert {variables["tenantId"] for _, variables in context.backend.queries} == {tenant}
    expected = context.vote_counts[tenant]
    assert len(context.exported_rows) == expected, (len(context.exported_rows), expected)
    assert {row["tenantId"] for row in context.exported_rows} == {tenant}
    assert context.backend.rows_read == expected, (context.backend.rows_read, expected)
    assert len(context.backend.tables["ReaderVote"]) > expected   # the other tenants' rows were there and were not read


def _scratch(context, name, text):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    path = Path(directory.name) / name
    path.write_text(text)
    return path


def _ledger(base, current):
    return subprocess.run(["npx", "tsx", "scripts/check-gsi-ledger.ts", "--base", str(base), "--current", str(current)],
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)


@given("the released reader steering schema, before ReaderVote had a tenantId index")
def released_reader_steering(context):
    context.reader_steering = READER_STEERING_SCHEMA.read_text()
    line = f"      .secondaryIndexes((index) => [{TENANT_INDEX}])\n"
    assert context.reader_steering.count(line) == 1, "ReaderVote's tenantId index is no longer declared where this step looks for it"
    context.released = _scratch(context, "released.ts", context.reader_steering.replace(line, ""))


@when("this change's reader steering schema is compared with it")
def compare_change(context):
    context.result = _ledger(context.released, READER_STEERING_SCHEMA)


@then("the ledger passes and places ReaderVote's tenantId index in release 1")
def ledger_passes(context):
    assert context.result.returncode == 0, context.result.stderr
    assert re.search(r"release 1: .*ReaderVote\.votesByTenant", context.result.stdout), context.result.stdout


@when("a second new ReaderVote index is added to the same release")
def second_index(context):
    current = context.reader_steering.replace(f"[{TENANT_INDEX}]", f"[{TENANT_INDEX}, {SECOND_INDEX}]")
    context.result = _ledger(context.released, _scratch(context, "current.ts", current))


@then("the ledger fails naming ReaderVote and both of its new indexes")
def ledger_fails(context):
    assert context.result.returncode == 1, context.result.stdout
    for text in ("ReaderVote gains 2 indexes", "votesByTenant", "votesByReader"):
        assert text in context.result.stderr, context.result.stderr
