"""The brand pack and the notice, through the real standard projection."""
import copy
import json
import re

from behave import given, when, then

from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings
from procedures.newsroom.tests.test_standard_frontend_brand import NOTICE, PACK

CONTENT = FIXTURES / 'sectioned' / 'content'


def _settings(pack_file=True, notice=True):
    raw = copy.deepcopy(fixture_settings('sectioned'))
    if pack_file:
        raw['brandPack'] = 'brand.json'
    if notice:
        raw['site']['notice'] = NOTICE
    return raw


def _page(context, key):
    return (context.site.out / key).read_text(encoding='utf-8')


@given('a site with a valid brand pack')
def step_valid(context):
    context.build = lambda: ProjectedSite(settings=_settings(), content=CONTENT, extra_files={'brand.json': json.dumps(PACK)})


@given('a site whose brand pack has body text too faint in dark mode')
def step_faint(context):
    pack = copy.deepcopy(PACK)
    pack['colors']['dark']['ink'] = '#5A6672'
    context.build = lambda: ProjectedSite(settings=_settings(), content=CONTENT, extra_files={'brand.json': json.dumps(pack)})


@given('a site whose brand pack asks for the heading font Lora')
def step_lora(context):
    pack = copy.deepcopy(PACK)
    pack['fonts']['heading'] = 'Lora'
    context.build = lambda: ProjectedSite(settings=_settings(), content=CONTENT, extra_files={'brand.json': json.dumps(pack)})


@given('a site with the notice "Satire. Everything on this site is invented."')
def step_notice(context):
    context.build = lambda: ProjectedSite(settings=_settings(), content=CONTENT, extra_files={'brand.json': json.dumps(PACK)})


@given('a site with no brand pack and no notice')
def step_plain(context):
    context.build = lambda: ProjectedSite('sectioned')


@when('the branded site is projected')
def step_project(context):
    context.error = None
    context.site = None
    try:
        context.site = context.build()
    except ValueError as error:
        context.error = str(error)


@then('every page links the shared theme and then the brand stylesheet last, and that stylesheet carries the pack in light and dark')
def step_linked(context):
    html = _page(context, 'index.html')
    links = re.findall(r'<link rel="stylesheet" href="([^"?]+)', html)
    assert 'papyrus-brand-' in links[-1]
    assert links.index('/css/papyrus-tokens.css') < links.index('/css/papyrus-publication.css') < len(links) - 1
    css = (context.site.out / links[-1].lstrip('/')).read_text(encoding='utf-8')
    assert '--papyrus-bg:#F5EFE0' in css and '--papyrus-bg:#17140F' in css


@then('the build stops naming ink on bg in the dark theme')
def step_names_pair(context):
    assert context.error and 'colors.dark: ink on bg' in context.error, context.error


@then('the build stops saying the platform does not host the font yet')
def step_unhosted(context):
    assert context.error and 'does not host yet' in context.error and 'Lora' in context.error, context.error


@then('it is on every kind of page, in the Markdown twin, in llms.txt, in both feeds and in the structured data')
def step_everywhere(context):
    for key in ('index.html', 'essays/index.html', 'essays/slow-water/index.html'):
        assert 'class="papyrus-notice"' in _page(context, key), key
    for key in ('essays/slow-water/index.md', 'llms.txt'):
        assert '> **Satire.** Everything on this site is invented.' in _page(context, key), key
    assert '<description>Satire. ' in _page(context, 'feed.xml') and '<summary>Satire. ' in _page(context, 'atom.xml')
    assert '"genre":"Satire"' in _page(context, 'essays/slow-water/index.html')


@then('no page links the shared theme or a brand stylesheet and none carries a notice')
def step_unchanged(context):
    html = _page(context, 'index.html')
    assert 'papyrus-tokens' not in html and 'papyrus-brand-' not in html and 'papyrus-notice' not in html
