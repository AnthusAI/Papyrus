"""Consumer-bump behaviour through the real bump_consumer.py, a throwaway Papyrus repository with release tags, a throwaway site, file:// registries and a fake gh."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from behave import given, when, then

SCRIPT = Path(__file__).resolve().parents[2] / 'infra' / 'pipeline' / 'bump_consumer.py'

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ['GH_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['pr', 'list']:
    print('[]')
"""


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.test', *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def schema(models):
    """A schema.ts where each model is (name, [indexed field, ...])."""
    out = ['const definitions = {']
    for name, fields in models:
        out.append(f'  {name}: modelWithoutSubscriptions({{ id: a.id() }})')
        if fields:
            out.append('    .secondaryIndexes((index) => [')
            out += [f'      index("{f}").queryField("by{f}"),' for f in fields]
            out.append('    ])')
        out.append('    .authorization((allow) => [allow.owner()]),')
    return '\n'.join(out + ['};', ''])


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def release(papyrus, version, models, subjects):
    write(papyrus / 'amplify' / 'data' / 'schema.ts', schema(models))
    git(papyrus, 'add', '-A')
    for subject in subjects:
        git(papyrus, 'commit', '--allow-empty', '-m', subject)
    git(papyrus, 'commit', '--allow-empty', '-m', f'chore(release): {version}')
    git(papyrus, 'tag', f'v{version}')


def build_papyrus(root):
    papyrus = root / 'papyrus'
    papyrus.mkdir()
    git(papyrus, 'init', '-q')
    release(papyrus, '1.0.0', [('Reference', ['a']), ('Brand', [])], ['feat: first release'])
    release(papyrus, '1.1.0', [('Reference', ['a', 'b']), ('Brand', [])], ['feat: forum posts reach the edge', 'docs: reword the guide'])
    release(papyrus, '1.2.0', [('Reference', ['a', 'b', 'c', 'd']), ('Brand', []), ('Notice', ['x', 'y', 'z'])], ['fix: stars survive a reload'])
    release(papyrus, '1.3.0', [('Reference', ['a', 'b', 'c', 'd']), ('Brand', []), ('Notice', ['x', 'y', 'z'])], [])
    return papyrus


def build_site(root, pin):
    remote = root / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    site = root / 'site'
    site.mkdir()
    git(site, 'init', '-q', '-b', 'develop')
    write(site / 'infra' / 'site.json', json.dumps({'papyrusVersion': pin}) + '\n')
    write(site / 'package.json', json.dumps({'dependencies': {'@anthusai/papyrus': pin}}, indent=2) + '\n')
    write(site / 'infra' / 'package.json', json.dumps({'dependencies': {'@anthusai/papyrus': pin}}, indent=2) + '\n')
    write(site / 'requirements.txt', f'papyrus-newsroom[markus]=={pin}\n')
    write(site / 'README.md', f'Install `papyrus-newsroom=={pin}`.\nPapyrus: since Papyrus 0.9.0 cards show renditions.\nThe schema version is {pin}.\n')
    git(site, 'add', '-A')
    git(site, 'commit', '-q', '-m', 'init')
    git(site, 'remote', 'add', 'origin', str(remote))
    return site


def registry(root, name, versions, shape):
    path = root / name
    path.write_text(json.dumps(shape(versions)))
    return path.as_uri()


@given('a site pinned to Papyrus {pin}')
def step_site(context, pin):
    root = Path(tempfile.mkdtemp())
    context.add_cleanup(lambda: subprocess.run(['rm', '-rf', str(root)]))
    context.root, context.pin = root, pin
    context.papyrus, context.site = build_papyrus(root), build_site(root, pin)
    bin_dir = root / 'bin'
    bin_dir.mkdir()
    gh = bin_dir / 'gh'
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    context.gh_log = root / 'gh.log'
    context.gh_log.write_text('')
    context.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', GH_LOG=str(context.gh_log))


def _publish(context, pypi, npm):
    context.pypi = registry(context.root, 'pypi.json', pypi, lambda vs: {'releases': {v: [{'yanked': False}] for v in vs}})
    context.npm = registry(context.root, 'npm.json', npm, lambda vs: {'versions': {v: {} for v in vs}})


@given('PyPI and npm both publish {version} as their newest release')
def step_both(context, version):
    versions = [v for v in ['1.0.0', '1.1.0', '1.2.0', '1.3.0'] if v <= version]
    _publish(context, versions, versions)


@given('PyPI publishes up to {pypi} and npm publishes up to {npm}')
def step_split(context, pypi, npm):
    _publish(context, [v for v in ['1.0.0', '1.1.0', '1.2.0', '1.3.0'] if v <= pypi], [v for v in ['1.0.0', '1.1.0', '1.2.0', '1.3.0'] if v <= npm])


def _run(context, *extra):
    context.result = subprocess.run(
        [sys.executable, str(SCRIPT), '--site', str(context.site), '--papyrus', str(context.papyrus), '--base', 'develop',
         '--pypi-url', context.pypi, '--npm-url', context.npm, *extra],
        capture_output=True, text=True, env=context.env, timeout=120)
    assert context.result.returncode == 0, context.result.stderr + context.result.stdout
    context.gh_calls = [json.loads(line) for line in context.gh_log.read_text().splitlines()]
    context.create = next((c for c in context.gh_calls if c[:2] == ['pr', 'create']), None)


@when('the bump runs')
def step_run(context):
    _run(context)


@when('the bump is dry-run')
def step_dry(context):
    _run(context, '--dry-run')


def _opt(call, flag):
    return call[call.index(flag) + 1]


def _pushed(context):
    return bool(git(context.root / 'remote.git', 'branch', '--list').strip())


@then('no branch is pushed and no pull request is opened')
def step_nothing(context):
    assert context.create is None, context.gh_calls
    assert not _pushed(context)


@then('a pull request titled "{title}" is opened against the integration branch')
def step_titled(context, title):
    assert context.create, context.result.stdout
    assert _opt(context.create, '--title') == title and _opt(context.create, '--base') == 'develop'


@then('the pull request is not a draft')
def step_not_draft(context):
    assert context.create and '--draft' not in context.create


@then('the pull request is a draft')
def step_draft(context):
    assert context.create and '--draft' in context.create


def _body(context):
    assert context.create, context.result.stdout
    return _opt(context.create, '--body')


@then('infra/site.json, package.json, infra/package.json, requirements.txt and README.md pin {version}')
def step_pins(context, version):
    # The pull request is on a branch of the site checkout, which the script left checked out.
    for name in ['infra/site.json', 'package.json', 'infra/package.json', 'requirements.txt']:
        assert version in (context.site / name).read_text() and context.pin not in (context.site / name).read_text(), name
    assert f'papyrus-newsroom=={version}' in (context.site / 'README.md').read_text()


@then('a comment about an earlier Papyrus {version} change still says {same}')
def step_history(context, version, same):
    assert f'since Papyrus {same} cards' in (context.site / 'README.md').read_text()


@then('a line that pins {version} but does not name Papyrus still says {same}')
def step_unrelated(context, version, same):
    assert f'The schema version is {same}.' in (context.site / 'README.md').read_text()


@then('the pull request body lists "{text}"')
def step_lists(context, text):
    assert text in _body(context)


@then('the pull request body does not list "{text}"')
def step_not_lists(context, text):
    assert text not in _body(context)


@then('the pull request body says one deploy can carry the bump')
def step_one_deploy(context):
    assert 'one deploy can carry this bump' in _body(context)


@then('the pull request body names the table "{table}" as needing a staged bump')
def step_names(context, table):
    assert re.search(rf'^- `{table}`:', _body(context), re.M), _body(context)


@then('the pull request body does not name the table "{table}" as needing a staged bump')
def step_not_names(context, table):
    assert not re.search(rf'^- `{table}`:', _body(context), re.M)


@then('infra/site.json still pins {version}')
def step_still(context, version):
    assert version in (context.site / 'infra' / 'site.json').read_text()
