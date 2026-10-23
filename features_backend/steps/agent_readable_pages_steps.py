from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.standard.markdown import item_markdown  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite  # noqa: E402

ISLAND_FILES = {"assets/islands.js": "window.papyrusIslands = {};\n"}


def listed(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


@given('an agent-readable site with an article "{slug}" and the page file "{source}" at "{path}" titled "{title}" described as "{description}"')
def agent_site(context, slug: str, source: str, path: str, title: str, description: str) -> None:
    context.agent_settings = {
        "site": {"name": "Example", "productionUrl": "https://example.org"},
        "islands": {"script": "assets/islands.js"},
        "pageActions": {"ai": ["chatgpt", "claude", "perplexity"]},
        "pages": [{"id": "models", "path": path, "title": title, "description": description, "source": source}],
    }
    context.agent_content = Path(tempfile.mkdtemp(prefix="agent-content-"))
    context.agent_article = {slug: "The body of the article.\n"}
    context.agent_files = dict(ISLAND_FILES)


@given('the page file "{source}" is')
def agent_page_file(context, source: str) -> None:
    context.agent_files[source] = context.text + "\n"


@given('the agent-readable site lives under the base path "{base}"')
def agent_base_path(context, base: str) -> None:
    context.agent_settings["urls"] = {"style": "directory", "basePath": base}


@given('the page "{path}" is noindex')
def agent_noindex(context, path: str) -> None:
    for page in context.agent_settings["pages"]:
        if page["path"] == path:
            page["noindex"] = True


@given('the article "{slug}" has the body')
def agent_article_body(context, slug: str) -> None:
    context.agent_article[slug] = context.text + "\n"


@when("the twin of an article is built from this source")
def build_twin(context) -> None:
    entry = SimpleNamespace(title="Wide", authors=(), author_details=(), date="", updated="", summary_text="")
    context.twin_text = item_markdown(entry, context.text, None)


@then('the twin text says "{text}"')
def twin_says(context, text: str) -> None:
    assert text in context.twin_text, context.twin_text


@then('the twin text does not say "{text}"')
def twin_does_not_say(context, text: str) -> None:
    assert text not in context.twin_text, context.twin_text


@when("the agent-readable site is projected")
def project_agent_site(context) -> None:
    settings = {"urls": {"style": "directory"}, **context.agent_settings}
    for slug, body in context.agent_article.items():
        (context.agent_content / f"{slug}.md").write_text(
            f"---\ntitle: {slug.title()}\ndate: '2026-10-01'\ndescription: An article.\n---\n\n{body}", encoding="utf-8"
        )
    context.site = ProjectedSite(settings=settings, content=context.agent_content, extra_files=context.agent_files)
    context.add_cleanup(context.site.cleanup)


@then('the agent page "{key}" says "{text}"')
def agent_page_says(context, key: str, text: str) -> None:
    body = context.site.text(key)
    assert text in body, body[:4000]


@then('the agent page "{key}" does not say "{text}"')
def agent_page_does_not_say(context, key: str, text: str) -> None:
    assert text not in context.site.text(key)


@then('the agent site lacks these pages: "{keys}"')
def agent_lacks(context, keys: str) -> None:
    present = [key for key in listed(keys) if key in context.site.tree]
    assert not present, present
