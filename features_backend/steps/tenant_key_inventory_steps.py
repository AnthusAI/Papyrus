"""Steps for features_backend/tenant-key-inventory.feature (PPY-cd5926).

The scenarios about the check run the real generator (`scripts/generate-tenant-key-inventory.ts --check`) against a copy of the committed
inventory with one index row changed, or against a copy of the declared classes with one field removed or added. The reading scenario parses
the committed docs/tenant-key-inventory.md.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / 'scripts' / 'generate-tenant-key-inventory.ts'
TSX = REPO_ROOT / 'node_modules' / '.bin' / 'tsx'
DOC = REPO_ROOT / 'docs' / 'tenant-key-inventory.md'
CLASSES = REPO_ROOT / 'scripts' / 'lib' / 'tenant-key-classes.ts'
GLOBAL_MODELS = ['UserProfile', 'UserIdentity', 'PublicHandleClaim']
TENANT_MODELS = ['Item', 'PublishedItem', 'MediaAsset', 'PublishedMediaAsset', 'NewsroomSection']


def _generator(*arguments):
    assert TSX.exists(), 'run npm ci first: node_modules/.bin/tsx is missing'
    return subprocess.run([str(TSX), str(GENERATOR), *arguments], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300)


def _scratch(context, name, content):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    path = Path(directory.name) / name
    path.write_text(content)
    return path


def _classes():
    """The declared classes as JSON, read by loading the TypeScript module."""
    program = (
        f"import {{ PARTITION_FIELD_CLASSES }} from {json.dumps(str(CLASSES))};"
        "process.stdout.write(JSON.stringify(PARTITION_FIELD_CLASSES));"
    )
    result = subprocess.run([str(TSX), '--eval', program], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _rows(heading_cells):
    """The rows of the table in the committed document whose header starts with these cells."""
    lines = DOC.read_text().splitlines()
    header = '| ' + ' | '.join(heading_cells) + ' |'
    start = lines.index(next(line for line in lines if line.startswith(header)))
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith('|'):
            break
        rows.append([cell.strip().strip('`') for cell in line.strip().strip('|').split(' | ')])
    return rows


@given('schema.ts changes an index')
def index_changed(context):
    # The committed row no longer matches what the schema now says: change the sort key of one index in the copy.
    text = DOC.read_text()
    line = next(row for row in text.splitlines() if row.startswith('| `Assignment` | `listAssignmentsByStatusAndUpdatedAt` |'))
    context.doc_under_test = _scratch(context, 'inventory.md', text.replace(line, line.replace('`updatedAt`', '`createdAt`')))
    context.expected_fragments = ['Assignment index listAssignmentsByStatusAndUpdatedAt']


@given('an index is added whose partition field is not classified')
def index_unclassified(context):
    # Item's schedule index is the only user of scheduleState: without a class for it, the index is a new, unclassified one.
    classes = _classes()
    del classes['scheduleState']
    context.classes_under_test = _scratch(context, 'classes.json', json.dumps(classes))
    context.expected_fragments = ['Item index listItemsByScheduleStateAndScheduledPublishAt', 'scheduleState is not classified']


@given('a field is classified that no index partitions on')
def field_stale(context):
    classes = _classes()
    classes['retiredField'] = {'class': 'global', 'spread': 'open'}
    context.classes_under_test = _scratch(context, 'classes.json', json.dumps(classes))
    context.expected_fragments = ['retiredField']


@when('the inventory check runs in CI')
def check_runs(context):
    arguments = ['--check']
    if hasattr(context, 'doc_under_test'):
        arguments += ['--doc', str(context.doc_under_test)]
    if hasattr(context, 'classes_under_test'):
        arguments += ['--classes', str(context.classes_under_test)]
    context.result = _generator(*arguments)


@then('the inventory check fails naming the model and the index')
@then('the inventory check fails naming the field')
def fails_naming(context):
    assert context.result.returncode != 0, 'the check passed but should have failed'
    for fragment in context.expected_fragments:
        assert fragment in context.result.stderr, context.result.stderr


@then('the failure names the command that regenerates the inventory')
def names_command(context):
    assert 'npx tsx scripts/generate-tenant-key-inventory.ts' in context.result.stderr, context.result.stderr


@then('the failure says the partition field is not classified')
def says_unclassified(context):
    assert 'is not classified' in context.result.stderr, context.result.stderr


@then('the inventory check passes')
def inventory_check_passes(context):
    assert context.result.returncode == 0, context.result.stderr


@when('the inventory is read')
def inventory_read(context):
    context.models = _rows(['Model', 'Indexes', 'Can list one tenant\'s rows', 'Indexes that do'])
    context.indexes = _rows(['Model', 'Index', 'Partition', 'Sort', 'Class', 'Spread', 'Dense', 'Lists a tenant'])


@then('every model of the schema has a row')
def every_model(context):
    names = {row[0] for row in context.models}
    for name in TENANT_MODELS + GLOBAL_MODELS + ['Reference', 'Assignment', 'Message', 'SemanticRelation']:
        assert name in names, name
    assert len(names) == len(context.models), 'a model is listed twice'
    assert sum(int(row[1]) for row in context.models) == len(context.indexes)


@then('the five tenant models carry tenant-prefixed partition keys where the tenancy code prefixes them')
def tenant_prefixed(context):
    by_partition = {(row[0], row[2]): row[4] for row in context.indexes}
    for model, field in [('Item', 'typeStatus'), ('Item', 'tenantSlug'), ('Item', 'sectionStatus'), ('Item', 'headStageKey'),
                         ('PublishedItem', 'typeStatus'), ('NewsroomSection', 'tenantId')]:
        assert by_partition[(model, field)] == 'tenant-prefixed', (model, field)


@then('the reference feed keys are corpus-prefixed and the record ids are record-id')
def corpus_and_record(context):
    by_partition = {(row[0], row[2]): row[4] for row in context.indexes}
    for field in ['feedStateKey', 'starFeedKey', 'mediumFeedKey', 'contentNeededKey']:
        assert by_partition[('Reference', field)] == 'corpus-prefixed', field
    assert by_partition[('Reference', 'newsroomFeedKey')] == 'global'
    assert by_partition[('AssignmentEvent', 'assignmentId')] == 'record-id'
    assert by_partition[('Reference', 'lineageId')] == 'record-id'
    assert by_partition[('EditionItem', 'editionId')] == 'record-id'


@then('the global models UserProfile, UserIdentity and PublicHandleClaim are listed as global by design')
def globals_listed(context):
    status = {row[0]: row[2] for row in context.models}
    for name in GLOBAL_MODELS:
        assert status[name] == 'global by design', name


@then('the models that need a tenantId index are listed')
def need_index(context):
    text = DOC.read_text()
    section = text.split('## Models that need a tenantId index', 1)[1].split('\n## ', 1)[0]
    listed = set(re.findall(r'- `([A-Za-z]+)`', section))
    expected = {row[0] for row in context.models if row[2].endswith('needs a tenantId index')}
    assert listed == expected and listed, (listed, expected)
