"""GSI ledger behaviour through the real check script and schema fixtures."""
import subprocess
import tempfile
from pathlib import Path

from behave import given, when, then

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / 'features_backend' / 'fixtures' / 'gsi-ledger'


def _generated(context, name, count, previous):
    def source(total):
        lines = ''.join(f'      index("k{i}").queryField("q{i}"),\n' for i in range(total))
        return ('  Big: modelWithoutSubscriptions({\n      id: a.id(),\n    })\n    .secondaryIndexes((index) => [\n'
                f'{lines}    ]),\n')
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    base, current = Path(directory.name) / 'base.ts', Path(directory.name) / 'current.ts'
    base.write_text(source(previous))
    current.write_text(source(count))
    context.base, context.current = base, current
    context.table = 'Big'


def _fixture(context, name):
    context.base, context.current = FIXTURES / 'baseline.ts', FIXTURES / name


@given('a change that adds two indexes to Reference')
def step_two(context):
    _fixture(context, 'two-new.ts')


@given('a change that adds one index to Reference')
def step_one(context):
    _fixture(context, 'one-new.ts')


@given('a change that changes the keys of an existing Item index')
def step_keys(context):
    _fixture(context, 'changed-keys.ts')


@given('a change that takes a table to 16 indexes')
def step_sixteen(context):
    _generated(context, 'near', 16, 15)


@given('a change that takes a table to 19 indexes')
def step_nineteen(context):
    _generated(context, 'over', 19, 18)


@when('CI runs the GSI ledger check')
def step_run(context):
    context.result = subprocess.run(
        ['npx', 'tsx', 'scripts/check-gsi-ledger.ts', '--base', str(context.base), '--current', str(context.current)],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)


@then('the GSI ledger check fails naming Reference and both indexes')
def step_fails_both(context):
    assert context.result.returncode == 1, context.result.stdout
    for text in ('Reference', 'referencesByTenant', 'referencesByOwner'):
        assert text in context.result.stderr, context.result.stderr


@then('the GSI ledger check fails naming Item and the index')
def step_fails_item(context):
    assert context.result.returncode == 1, context.result.stdout
    assert 'Item index itemsByStage changed its keys' in context.result.stderr, context.result.stderr


@then('the GSI ledger check fails naming that table')
def step_fails_table(context):
    assert context.result.returncode == 1, context.result.stdout
    assert 'Big has 19 indexes' in context.result.stderr, context.result.stderr


@then('the GSI ledger check passes')
def step_passes(context):
    assert context.result.returncode == 0, context.result.stderr


@then("the release order lists Reference's new index in release 1")
def step_order(context):
    assert 'release 1: Reference.referencesByTenant' in context.result.stdout, context.result.stdout


@then('it warns that the table has 16 of the 20 indexes DynamoDB allows')
def step_warns(context):
    assert 'Big has 16 of the 20 indexes' in context.result.stderr, context.result.stderr
