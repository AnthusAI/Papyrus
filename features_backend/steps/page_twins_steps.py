from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import project_stale_listings  # noqa: E402
from procedures.newsroom.tests.page_twins_support import page_entry, snapshot_site  # noqa: E402
from procedures.newsroom.tests.reader_privacy import scan_files  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, cms_site, item, settings  # noqa: E402

DIRECTIVE = re.compile(r"^::(band|column|button|island|include|raw|endraw)", re.M)
EMPTY_REFERENCES = {"generatedAt": "2026-10-31T12:00:00.000Z", "references": []}
BLOCK_HOOKS = '''
DEPENDS_ON = []

def block(name, attributes, page):
    stories = [entry for entry in page.entries if entry.section is not None and entry.section.name == "posts"][:2]
    cards = "".join('<li class="card"><a href="%s">%s</a><span>%s</span></li>' % (entry.url, entry.title, entry.date) for entry in stories)
    return '<section class="strip"><h2>Proof strip</h2><ul>%s</ul></section>' % cards
'''


def plan(context) -> dict:
    return context.page_twin_plan


@given("a site with accepted and recommended References and two conversations")
def snapshot_plan(context) -> None:
    context.page_twin_plan = {"kind": "snapshot", "pages": {}, "entries": [], "references": None}


@given('the page "{path}" titled "{title}" is written as')
def page_file(context, path: str, title: str) -> None:
    page_id = path.replace("/", "-")
    plan(context)["pages"][f"pages/{page_id}.md"] = context.text + "\n"
    plan(context)["entries"].append(page_entry(page_id, path, title, "Every source." if path == "wire" else ""))


@given("the References snapshot is empty")
def empty_snapshot(context) -> None:
    plan(context)["references"] = EMPTY_REFERENCES


@given('a site with the stories "{first}" and "{second}" and a block hook "{name}" that draws a card for each')
def hook_plan(context, first: str, second: str, name: str) -> None:
    context.page_twin_plan = {"kind": "hook", "pages": {}, "entries": [], "stories": (first, second)}


@given("a site whose home item is written as")
def home_plan(context) -> None:
    context.page_twin_plan = {"kind": "home", "body": context.text + "\n"}


@given('a site with an article "{slug}" written as')
def article_plan(context, slug: str) -> None:
    context.page_twin_plan = {"kind": "article", "slug": slug, "body": context.text + "\n"}


@given("the page-twin site is projected")
@when("the page-twin site is projected")
def project_page_twin_site(context) -> None:
    chosen = plan(context)
    if chosen["kind"] == "snapshot":
        site = snapshot_site(chosen["pages"], chosen["entries"], forum=True, references=chosen["references"])
    elif chosen["kind"] == "hook":
        first, second = chosen["stories"]
        entries = [{**entry, "dependsOn": ["*"]} for entry in chosen["entries"]]
        site = cms_site(
            settings(urls={"sections": {"posts": {}}}, hooks="hooks.py", pages=entries),
            [item(first, date="2026-01-02"), item(second, date="2026-01-01")],
            {"hooks.py": BLOCK_HOOKS, **chosen["pages"]},
        )
    elif chosen["kind"] == "home":
        site = DirectorySite(settings(), [item("index", section=None, body=chosen["body"], title="Home"), item("hello", date="2026-10-01")])
        assert site.project_all().ok
    else:
        site = DirectorySite(settings(), [item("index", section=None, title="Home", body="# Home\n"), item(chosen["slug"], date="2026-10-01", body=chosen["body"])])
        assert site.project_all().ok
    context.site = site
    context.add_cleanup(site.cleanup)


@when("the title of the newest accepted Reference changes in the snapshot and the pages that read it are rewritten")
def retitle_newest_reference(context) -> None:
    site = context.site
    location = site.out / "_data/home-page/references.json"
    document = json.loads(location.read_text(encoding="utf-8"))
    document["references"][0]["title"] = "Accepted eight, retitled"
    location.write_text(json.dumps(document), encoding="utf-8")
    site.projector._home_page.reset()
    site.projector._plan_cache = None
    report = project_stale_listings(site.context, site.projector.home_page_reader_keys())
    assert report.ok, report


@then('the agent page "{key}" has no page directive')
def has_no_directive(context, key: str) -> None:
    text = context.site.text(key)
    assert not DIRECTIVE.search(text), text[:4000]


@then('the agent page "{key}" lists "{title}" once')
def lists_once(context, key: str, title: str) -> None:
    text = context.site.text(key)
    assert len(re.findall(rf"^- \[{re.escape(title)}\]\(", text, re.M)) == 1, text[:4000]


@then('the agent page "{key}" carries no identifier of a person')
def carries_no_person(context, key: str) -> None:
    assert scan_files({key: context.site.text(key)}, []) == {}
