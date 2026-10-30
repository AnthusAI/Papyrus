from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

LIBRARY_KEY = "_plugins/mermaid-11.17.2.min.js"
LOADER_KEY = "_plugins/papyrus-mermaid-v1.js"


@given('a standard site with an article "{slug}"')
def standard_site(context, slug: str) -> None:
    context.agent_settings = {"site": {"name": "Example", "productionUrl": "https://example.org"}}
    context.agent_content = Path(tempfile.mkdtemp(prefix="mermaid-content-"))
    context.agent_article = {slug: "The body of the article.\n"}
    context.agent_files = {}


@given('the site\'s projection settings say "{key}" is {value}')
def site_setting(context, key: str, value: str) -> None:
    context.agent_settings[key] = json.loads(value)


@then('the agent page "{key}" contains')
def agent_page_contains(context, key: str) -> None:
    body = context.site.text(key)
    assert context.text in body, body[:4000]


@then("the site publishes its own copy of the Mermaid library and loader")
def publishes_library(context) -> None:
    assert LIBRARY_KEY in context.site.tree and LOADER_KEY in context.site.tree, sorted(context.site.tree)
    assert len(context.site.tree[LIBRARY_KEY]) > 100_000


@then("the site does not publish the Mermaid library or loader")
def does_not_publish_library(context) -> None:
    present = [key for key in (LIBRARY_KEY, LOADER_KEY) if key in context.site.tree]
    assert not present, present
