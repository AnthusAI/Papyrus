from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests.incremental_site import Site, add_item  # noqa: E402

SLUGS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]


@given("a site with public JSON of six published articles that has been projected")
def six_articles_with_public_json(context) -> None:
    context.work = tempfile.TemporaryDirectory()
    context.add_cleanup(context.work.cleanup)
    context.site = Site("public", Path(context.work.name))
    for number, slug in enumerate(SLUGS):
        add_item(context.site, f"item-{slug}", slug, date=f"2026-01-{number + 1:02d}")
        context.site.project_item(f"item-{slug}")
    context.error = None


@then('the pages written did not include "{key}"')
def written_without(context, key: str) -> None:
    written = {written_key for kind, written_key in context.site.store.operations if kind == "put"}
    assert key not in written, sorted(written)
