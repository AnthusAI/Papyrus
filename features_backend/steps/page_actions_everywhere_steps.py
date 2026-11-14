from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests.standard_frontend_support import ProjectedSite, fixture_settings  # noqa: E402

ACTIONS = re.compile(r'data-papyrus-page-actions data-markdown="([^"]*)" data-title="([^"]*)" data-canonical="([^"]*)"')
OWN_TEMPLATE = (
    "def main(page):\n"
    "    if page.kind == 'item':\n"
    "        return None\n"
    "    return '<section id=\"own\">' + page.article_actions() + '</section>'\n"
)


def actions_in(context, key: str) -> list[tuple[str, str, str]]:
    return ACTIONS.findall(context.site.text(key))


@given('a sectioned example site with the icon page actions and a collection "{label}" of everything tagged "{tag}"')
def sectioned_site(context, label: str, tag: str) -> None:
    settings = fixture_settings("sectioned")
    settings["pageActions"] = {"display": "icons", "actions": ["view", "copy", "x", "reddit", "share"]}
    settings["collections"] = [{"id": "rivers", "base": "rivers", "label": label, "select": {"tags": [tag]}}]
    context.example_settings = settings
    context.example_files = {}


@given("the site opts in to page actions on every page")
def opt_in(context) -> None:
    context.example_settings["pageActions"]["everywhere"] = True


@given("the page actions go in the aside")
def aside(context) -> None:
    context.example_settings["pageActions"]["placement"] = "aside"


@given("the site publishes no Markdown twins")
def no_twins(context) -> None:
    context.example_settings["agents"] = {"markdown": False, "llmsTxt": False, "llmsFull": False}


@given('the example page "{path}" is noindex')
def page_noindex(context, path: str) -> None:
    for page in context.example_settings["pages"]:
        if page["path"] == path:
            page["noindex"] = True


@given('the site has a page file "{source}" at "{path}" titled "{title}"')
def page_file(context, source: str, path: str, title: str) -> None:
    context.example_settings["pages"].append({"id": "models", "path": path, "title": title, "description": "How decisions get made.", "source": source})
    context.example_files[source] = f"# {title}\n\nA model *decides*.\n".encode("utf-8")


@given("the site has its own template that places the page actions on every page but articles")
def own_template(context) -> None:
    context.example_settings["hooks"] = "hooks.py"
    context.example_files["hooks.py"] = OWN_TEMPLATE


@when("the example site is projected")
def project(context) -> None:
    previous = getattr(context, "site", None)
    if previous is not None:
        previous.cleanup()
    context.site = ProjectedSite("sectioned", settings=context.example_settings, extra_files=context.example_files)
    context.add_cleanup(context.site.cleanup)


@then('the page "{key}" carries the page actions pointing at "{twin}"')
def carries_for(context, key: str, twin: str) -> None:
    found = actions_in(context, key)
    assert len(found) == 1 and found[0][0] == twin, found


@then('the page "{key}" carries the page actions for "{twin}" titled "{title}" at "{address}"')
def carries_for_titled(context, key: str, twin: str, title: str, address: str) -> None:
    found = actions_in(context, key)
    assert found == [(twin, title, address)], found


@then('the page "{key}" carries no page actions')
def carries_none(context, key: str) -> None:
    assert not actions_in(context, key), key
    assert "papyrus-page-actions-v1.js" not in context.site.text(key), key


@then('the Markdown twin "{twin}" exists')
def twin_exists(context, twin: str) -> None:
    assert twin.lstrip("/") in context.site.tree, sorted(context.site.tree)


@then('the page "{key}" loads the page actions script')
def loads_script(context, key: str) -> None:
    assert "_plugins/papyrus-page-actions-v1.js" in context.site.text(key)


@then('on the page "{key}" the page actions come before the heading')
def before_heading(context, key: str) -> None:
    body = context.site.text(key)
    assert body.index("data-papyrus-page-actions") < body.index("<h1"), body[:3000]


@then('on the page "{key}" the page actions come after the cards')
def after_cards(context, key: str) -> None:
    body = context.site.text(key)
    assert body.index("data-papyrus-page-actions") > body.index("markus-card-grid"), body[:3000]


@then("no page carries page actions")
def no_page_carries(context) -> None:
    carrying = [key for key in context.site.tree if key.endswith(".html") and actions_in(context, key)]
    assert not carrying, carrying


@then('the page "{key}" carries the page actions once inside "{identifier}"')
def once_inside(context, key: str, identifier: str) -> None:
    body = context.site.text(key)
    assert len(actions_in(context, key)) == 1, key
    assert f'<section id="{identifier}"><div class="markus-page-actions' in body, body[:3000]
