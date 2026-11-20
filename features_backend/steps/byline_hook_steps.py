from __future__ import annotations

import sys
from pathlib import Path

from behave import given, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, item, settings  # noqa: E402

HOOK = "def byline(entry):\n    return {text}\n"


def plan(context, hook: str | None, authors: list[str]) -> None:
    context.byline_plan = {"hook": hook, "authors": authors}


@given('a site with item bylines on and no byline hook, and an article "{slug}" by "{first}" and "{second}"')
def without_hook(context, slug: str, first: str, second: str) -> None:
    plan(context, None, [first, second])
    context.byline_plan["slug"] = slug


@given('a site with item bylines on and a byline hook that says "{text}", and an article "{slug}" by "{first}" and "{second}"')
def with_hook(context, text: str, slug: str, first: str, second: str) -> None:
    plan(context, HOOK.format(text=repr(text)), [first, second])
    context.byline_plan["slug"] = slug


@given('a site with item bylines on and a byline hook that has nothing to say, and an article "{slug}" by "{first}" and "{second}"')
def with_silent_hook(context, slug: str, first: str, second: str) -> None:
    plan(context, HOOK.format(text="None"), [first, second])
    context.byline_plan["slug"] = slug


@when("the byline site is projected")
def project(context) -> None:
    chosen = context.byline_plan
    hook = chosen["hook"]
    config = settings(components={"itemByline": True}, **({"hooks": "hooks.py"} if hook else {}))
    site = DirectorySite(
        config,
        [item("index", section=None, title="Home", body="# Home\n"), item(chosen["slug"], date="2026-10-01", authors=chosen["authors"])],
        {"hooks.py": hook} if hook else None,
    )
    assert site.project_all().ok
    context.site = site
    context.add_cleanup(site.cleanup)
