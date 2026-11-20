"""Steps for features_backend/tenant-isolation-adversarial.feature (PPY-65e5a9).

The scenarios about the generator run the real generator (`scripts/generate-tenant-isolation-cases.ts`) against a copy of the committed case
table with one case removed, added or changed. The generated outline scenarios need the shared stack with two seeded tenants and are tagged
@isolation-pending: features_backend/environment.py reports them as skipped, and the steps below are stubs that fail loudly if one ever runs.
"""
import json
import subprocess
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / 'scripts' / 'generate-tenant-isolation-cases.ts'
TSX = REPO_ROOT / 'node_modules' / '.bin' / 'tsx'
CASES = REPO_ROOT / 'features_backend' / 'fixtures' / 'tenant-isolation' / 'cases.json'
GLOBAL_MODELS = ['UserProfile', 'UserIdentity', 'PublicHandleClaim']
PENDING = 'pending: needs the shared stack with two seeded tenants (PPY-29f730, later parts)'


def _generator(*arguments):
    assert TSX.exists(), 'run npm ci first: node_modules/.bin/tsx is missing'
    return subprocess.run([str(TSX), str(GENERATOR), *arguments], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300)


def _table():
    return json.loads(CASES.read_text())


def _check_with(context, table):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    path = Path(directory.name) / 'cases.json'
    path.write_text(json.dumps(table, indent=2) + '\n')
    context.result = _generator('--check', '--cases', str(path))


def _without(table, predicate):
    return dict(table, cases=[case for case in table['cases'] if not predicate(case)])


@given('a model is added to schema.ts')
def model_added(context):
    # A new model has no row in the committed table. Removing a real model's cases is the same state.
    context.model = 'Item'
    context.table_under_test = _without(_table(), lambda case: case['kind'] == 'model' and case['subject'] == 'Item')
    context.expected_fragment = 'model Item has no isolation case'


@given('an index is added to a model in schema.ts')
def index_added(context):
    context.table_under_test = _without(_table(), lambda case: case['id'] == 'index:itemBySlug')
    context.expected_fragment = 'index itemBySlug has no isolation case'


@given('a custom mutation is added to schema.ts')
def mutation_added(context):
    context.table_under_test = _without(_table(), lambda case: case['id'] == 'operation:grantUserRole')
    context.expected_fragment = 'operation grantUserRole has no isolation case'


@given('a function directory is added under amplify/functions')
def function_added(context):
    context.table_under_test = _without(_table(), lambda case: case['id'] == 'function:knowledge-query')
    context.expected_fragment = 'function knowledge-query has no isolation case'


@given('a model is removed from schema.ts but its cases remain')
def model_removed(context):
    table = _table()
    ghost = dict(table['cases'][0], id='model:GhostModel:get', subject='GhostModel', operation='get')
    context.table_under_test = dict(table, cases=table['cases'] + [ghost])
    context.expected_fragment = 'model GhostModel has a case but no longer exists'


@given('the committed case table differs from the schema')
def table_differs(context):
    table = _table()
    table['cases'][0] = dict(table['cases'][0], probe='edited by hand')
    context.table_under_test = table
    context.expected_fragment = 'is out of date'


@when('the generator check runs in CI')
def check_runs(context):
    if hasattr(context, 'table_under_test'):
        _check_with(context, context.table_under_test)
    else:
        context.result = _generator('--check')


@then('it fails naming the {kind}')
def fails_naming(context, kind):
    assert context.result.returncode != 0, 'the check passed but should have failed'
    assert context.expected_fragment in context.result.stderr, context.result.stderr


@then('it fails and names the command that regenerates it')
def fails_with_command(context):
    assert context.result.returncode != 0, 'the check passed but should have failed'
    assert context.expected_fragment in context.result.stderr, context.result.stderr
    assert 'npx tsx scripts/generate-tenant-isolation-cases.ts' in context.result.stderr, context.result.stderr


@then('it passes')
def check_passes(context):
    assert context.result.returncode == 0, context.result.stderr


@when('the case table is generated')
def table_generated(context):
    context.case_table = _table()
    context.models = sorted({case['subject'] for case in context.case_table['cases'] if case['kind'] == 'model'})


@then('each tenant-owned model has get, list, create with a foreign tenantId, update to a foreign tenantId, update of a foreign row and delete of a foreign row')
def operations_covered(context):
    operations = {}
    for case in context.case_table['cases']:
        if case['kind'] == 'model':
            operations.setdefault(case['subject'], set()).add(case['operation'])
    wanted = {'get', 'list', 'create-with-foreign-tenantId', 'update-to-foreign-tenantId', 'update-foreign-row', 'delete-foreign-row'}
    missing = {model: sorted(wanted - found) for model, found in operations.items() if model not in GLOBAL_MODELS and not wanted <= found}
    assert not missing, missing
    assert 'Item' in operations and 'Reference' in operations


@then('a model that disables an operation has no case for it')
def disabled_has_no_case(context):
    # Item turns subscriptions off (modelWithoutSubscriptions), so it has no subscription case.
    assert not [case for case in context.case_table['cases'] if case['kind'] == 'subscription' and case['subject'] == 'Item']


@then('the global models UserProfile, UserIdentity and PublicHandleClaim are recorded as reviewed decisions')
def global_models_reviewed(context):
    for model in GLOBAL_MODELS:
        cases = [case for case in context.case_table['cases'] if case['kind'] == 'model' and case['subject'] == model]
        assert cases, model
        assert all(case['expect'].startswith('reviewed:') for case in cases), model


@when('the gap report runs')
def report_runs(context):
    context.result = _generator('--report')


@then('it lists the models whose tenantId can be changed')
def lists_mutable(context):
    assert 'tenantId-can-be-changed' in context.result.stdout, context.result.stdout[:2000]


@then('it lists the indexes whose partition key is not tenant-prefixed')
def lists_unprefixed(context):
    assert 'index-not-tenant-prefixed' in context.result.stdout, context.result.stdout[:2000]


@then('it exits successfully')
def exits_successfully(context):
    assert context.result.returncode == 0, context.result.stderr


# The generated outline scenarios. They are skipped (see environment.py), so these never run until a later part supplies real sessions.

@given('editor sessions for "alpha" and "beta" on the shared stack')
def editor_sessions(context):
    raise NotImplementedError(PENDING)


@when('the "alpha" session performs {operation} on a "beta" {model}')
def model_operation(context, operation, model):
    raise NotImplementedError(PENDING)


@when('the "alpha" session calls {query} at one of "beta\'s" keys')
def index_call(context, query):
    raise NotImplementedError(PENDING)


@when('the "alpha" session subscribes to {event} on {model} while "beta" writes')
def subscribes(context, event, model):
    raise NotImplementedError(PENDING)


@when('the "alpha" session calls {operation} with "beta\'s" ids')
def custom_operation(context, operation):
    raise NotImplementedError(PENDING)


@when('the "alpha" session reaches the {function} function with an event naming "beta"')
def reaches_function(context, function):
    raise NotImplementedError(PENDING)


@when('the "alpha" session tries {surface}')
def tries_surface(context, surface):
    raise NotImplementedError(PENDING)


@then('it is denied or returns nothing of "beta"')
def denied_or_nothing(context):
    raise NotImplementedError(PENDING)
