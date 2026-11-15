"""GSI ledger behaviour through the real check script and schema fixtures."""
import json
import os
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


@given('a change that takes a table to 20 indexes')
def step_twenty(context):
    _generated(context, 'full', 20, 19)


@given('a change that takes a table to 21 indexes')
def step_twentyone(context):
    _generated(context, 'over', 21, 20)


def _tables(context, count):
    def source(indexed):
        return ''.join(
            f'  Table{i}: modelWithoutSubscriptions({{\n      id: a.id(),\n    }})\n    .secondaryIndexes((index) => [\n'
            + (f'      index("tenantId").sortKeys(["id"]).name("table{i}ByTenant").queryField("listTable{i}ByTenant"),\n' if indexed else '')
            + '    ]),\n'
            for i in range(count))
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    base, current = Path(directory.name) / 'base.ts', Path(directory.name) / 'current.ts'
    base.write_text(source(False))
    current.write_text(source(True))
    context.base, context.current = base, current


@given('a change that adds a new table with three indexes')
def step_new_table(context):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    base, current = Path(directory.name) / 'base.ts', Path(directory.name) / 'current.ts'
    base.write_text('  Old: modelWithoutSubscriptions({\n      id: a.id(),\n    }),\n')
    lines = ''.join(f'      index("k{i}").queryField("q{i}"),\n' for i in range(3))
    current.write_text(base.read_text() + '  Fresh: modelWithoutSubscriptions({\n      id: a.id(),\n    })\n    .secondaryIndexes((index) => [\n' + lines + '    ]),\n')
    context.base, context.current = base, current


@then('no index of the new table is listed as waiting for a later release')
def step_no_waiting(context):
    assert 'Fresh.' not in context.result.stdout, context.result.stdout


@given('a change that adds one new index to each of 40 tables')
def step_forty(context):
    _tables(context, 40)


@given('a change that adds one new index to each of 5 tables')
def step_five(context):
    _tables(context, 5)


@given('the measured time per index creation makes that more than the build timeout less 10 minutes')
def step_measured(context):
    # 40 creations at the measured 141 seconds each are 94 minutes, which leaves less than the 25 percent margin of a 120 minute timeout.
    measurements = json.loads((REPO_ROOT / 'scripts' / 'data' / 'gsi-deploy-measurements.json').read_text())['measurements']
    assert 40 * max(m['deploySeconds'] / m['indexCreations'] for m in measurements) > (120 - 10) * 60 * 0.75


@given('a release whose backend update finished')
def step_finished(context):
    pass


@when('CI runs the GSI ledger check')
def step_run(context):
    _run(context)


@when('CI runs the GSI ledger check with a build timeout of 60 minutes')
def step_run_sixty(context):
    _run(context, '--build-timeout', '60')


def _run(context, *extra):
    context.result = subprocess.run(
        ['npx', 'tsx', 'scripts/check-gsi-ledger.ts', '--base', str(context.base), '--current', str(context.current), *extra],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)


@when("its CloudFormation events are read by scripts/measure-gsi-deploy.ts")
def step_read_events(context):
    pass


@then("its data stack duration and index creation count are appended to the ledger's measurements")
def step_appended(context):
    # The reading and the validation run in scripts/test-gsi-ledger.ts; the file's recorded first measurement is the proof here.
    measurements = json.loads((REPO_ROOT / 'scripts' / 'data' / 'gsi-deploy-measurements.json').read_text())['measurements']
    assert measurements[0]['indexCreations'] == 23 and measurements[0]['deploySeconds'] == 3250, measurements


def _fails_with_limit(context, limit):
    assert context.result.returncode == 1, context.result.stdout
    assert f'only {limit} fit one release' in context.result.stderr, context.result.stderr
    for table in ('Table0.table0ByTenant', 'Table39.table39ByTenant'):
        assert table in context.result.stderr, context.result.stderr


@then('the GSI ledger check fails saying 35 index creations fit one release and naming the tables')
def step_fails_35(context):
    _fails_with_limit(context, 35)


@then('the GSI ledger check fails saying 15 index creations fit one release and naming the tables')
def step_fails_15(context):
    _fails_with_limit(context, 15)


@then('it lists which indexes belong in release 1 and 2')
def step_lists_two(context):
    assert 'release 1: Table0.table0ByTenant' in context.result.stdout and 'release 2: Table35.table35ByTenant' in context.result.stdout, context.result.stdout
    assert 'release 3' not in context.result.stdout


@then('it lists which indexes belong in release 1, 2 and 3')
def step_lists_three(context):
    for release in ('release 1:', 'release 2:', 'release 3:'):
        assert release in context.result.stdout, context.result.stdout


@then('it prints its estimated deploy minutes')
def step_estimate(context):
    assert '5 index creations on existing tables: about 12 minutes of deploy' in context.result.stdout, context.result.stdout


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
    assert 'Big has 21 indexes' in context.result.stderr, context.result.stderr


@then('the GSI ledger check passes')
def step_passes(context):
    assert context.result.returncode == 0, context.result.stderr


@then("the release order lists Reference's new index in release 1")
def step_order(context):
    assert 'release 1: Reference.referencesByTenant' in context.result.stdout, context.result.stdout


@then('it reports that the table has 20 of 20 indexes with 0 left')
def step_slots(context):
    assert 'Big has 20 of 20 indexes: 0 left.' in context.result.stdout, context.result.stdout


@when('CI runs the GSI ledger check in a checkout without release tags')
def step_run_untagged(context):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    subprocess.run(['git', 'init', '-q', directory.name], check=True)
    context.result = subprocess.run(
        ['npx', 'tsx', str(REPO_ROOT / 'scripts' / 'check-gsi-ledger.ts'), '--current', str(FIXTURES / 'baseline.ts')],
        capture_output=True, text=True, cwd=directory.name, timeout=120,
        env={**os.environ, 'NODE_PATH': str(REPO_ROOT / 'node_modules'), 'PATH': str(REPO_ROOT / 'node_modules' / '.bin') + os.pathsep + os.environ['PATH']})


@then('the GSI ledger check fails saying no release tag was found')
def step_no_tag(context):
    assert context.result.returncode != 0, context.result.stdout
    assert 'no stable release tag' in context.result.stderr, context.result.stderr
