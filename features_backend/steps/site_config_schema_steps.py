"""SiteConfig schema, converter and refusals, through the real converter and the real standard projector."""
import json
import shutil
import tempfile
from pathlib import Path

from behave import given, when, then

from papyrus_content.site_config import from_site_config, to_site_config, validate_site_config

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / 'src' / 'papyrus_content' / 'site_config' / 'fixtures'
SITE_FILES = {
    'Harbor Ledger': 'harbor-ledger',
    'Meridian Field Guide': 'meridian-field-guide',
}


def _render(settings, content):
    from procedures.newsroom.tests.standard_frontend_support import ProjectedSite
    settings = {key: value for key, value in settings.items() if key not in ('hooks', 'pages')}
    settings.get('chrome', {}).pop('scripts', None)
    site = ProjectedSite(settings=settings, content=content)
    try:
        return site.tree
    finally:
        site.cleanup()


@given("the {site} projection.json for conversion")
def step_projection(context, site):
    context.projection = json.loads((FIXTURES / f'{SITE_FILES[site]}.projection.json').read_text(encoding='utf-8'))


@when('it is converted to a SiteConfig and back')
def step_round_trip(context):
    context.site_config, context.rest = to_site_config(context.projection)
    context.round_tripped = from_site_config(context.site_config, context.rest)


@when('it is converted to a SiteConfig')
def step_convert(context):
    context.site_config, context.rest = to_site_config(context.projection)


@then('validation passes and the rendered home page is unchanged')
def step_unchanged(context):
    assert validate_site_config(context.site_config) == []
    assert context.round_tripped == context.projection
    work = Path(tempfile.mkdtemp(prefix='site-config-steps-'))
    try:
        root = work / 'content'
        for index, section in enumerate(context.site_config.get('sections', [])):
            (root / section['name']).mkdir(parents=True)
            (root / section['name'] / 'first.md').write_text(
                f"---\ntitle: First in {section['name']}\ndate: '2026-03-{10 + index:02d}'\n---\nBody.\n", encoding='utf-8')
        root.mkdir(exist_ok=True)
        (root / 'index.md').write_text('---\ntitle: Home\n---\nWelcome.\n', encoding='utf-8')
        original = _render(context.projection, root)
        again = _render(context.round_tripped, root)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    assert any(name.endswith('index.html') for name in original), 'no home page was rendered'
    assert original == again, 'a page changed'


@then('the SiteConfig is valid')
def step_valid(context):
    assert validate_site_config(context.site_config) == []


@then('the hooks stay behind with the dedicated site')
def step_hooks_behind(context):
    assert 'hooks' not in context.site_config
    assert context.rest['hooks'] == 'hooks.py'


@given("a shared tenant's SiteConfig with a custom CSS file")
def step_css_config(context):
    context.candidate = {'schemaVersion': 1, 'name': 'Example', 'css': 'brand.css'}
    context.expected_names = ['css']


@given("a shared tenant's SiteConfig with hooks, plugins and a URL style")
def step_code_config(context):
    context.candidate = {'schemaVersion': 1, 'name': 'Example', 'hooks': 'hooks.py', 'plugins': ['forum'], 'urls': {'style': 'directory'}}
    context.expected_names = ['hooks', 'plugins', 'urls']


@when('it is validated')
def step_validate(context):
    context.errors = validate_site_config(context.candidate)


@then('it is refused naming the setting')
def step_refused(context):
    for name in context.expected_names:
        assert any(error.startswith(f'{name}: refused') for error in context.errors), (name, context.errors)
