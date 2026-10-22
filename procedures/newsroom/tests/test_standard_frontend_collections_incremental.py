"""Incremental projection equals a full projection for a site of collections and authored page files with listing includes.

Same property and checks as ``test_standard_frontend_incremental``: after random publish, edit and unpublish operations the
pages an operation writes are exactly the pages whose bytes changed (plus the item's own), and a fresh ``project --all``
finds nothing to change. The pages under test are the ones whose input is a selection: collections (tags and sections,
featured entries, page sizes, two sort orders), tag pages narrowed by ``tagSelect`` and an authored home page and
page file whose ``::include`` blocks select entries by tag, section, collection, count and skip.
"""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from papyrus_content.projection.engine import reconcile
from papyrus_content.projection.item_state import read_item_state
from papyrus_content.projection.projector import MarkusProjectorSettings, read_static_files
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.hooks import Hooks
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from procedures.newsroom.tests import incremental_site
from procedures.newsroom.tests.incremental_site import Site, apply_operation
from procedures.newsroom.tests.standard_frontend_content_support import SITE

SETTINGS = {
    "site": SITE,
    "urls": {"sections": {"articles": {"listingPage": False}, "notes": {}}},
    "listings": {"pageSize": 3, "featuredCount": 1, "tagPageSize": 4, "tagSelect": {"sections": ["articles"]}, "homeCount": 2},
    "collections": [
        {"id": "everything", "base": "all", "select": {"sections": ["articles"]}, "pageSize": 2, "featuredCount": 1, "sitemapPages": True},
        {"id": "early", "select": {"tags": ["month-01", "month-02", "month-03"], "notTags": ["month-02"]}, "sort": "title", "ties": "slug-asc", "pageSize": 2},
        {"id": "late", "select": {"allTags": ["month-11"]}, "listEmpty": True},
    ],
    "pages": [
        {"id": "home", "path": "", "title": "Home", "source": "home.md"},
        {"id": "picks", "path": "picks", "title": "Picks", "source": "picks.md"},
    ],
}
HOME = '::band{size="bare"}\n# Home\n\n::include{kind="listing" collection="everything" count="3"}\n'
PICKS = (
    '::band{size="bare"}\n## Picks\n\n'
    '::include{kind="listing" tags="month-06,month-07" sections="articles" count="2" skip="1"}\n\n'
    '::include{kind="listing" collection="early" layout="bare" sort="date" ties="slug-asc"}\n\n'
    '::include{kind="listing" sections="notes" count="2"}\n'
)


def projector_factory(static: Path):
    def make() -> StandardMarkusProjector:
        (static / "home.md").write_text(HOME, encoding="utf-8")
        (static / "picks.md").write_text(PICKS, encoding="utf-8")
        return StandardMarkusProjector(
            MarkusProjectorSettings(theme=None),
            read_static_files(None, None),
            standard_settings_from_mapping(SETTINGS),
            static_directory=static,
            hooks=Hooks(),
            environment=None,
        )

    return make


class CollectionsIncrementalEqualsFullTests(unittest.TestCase):
    def run_sequence(self, seed: int, steps: int) -> None:
        rng = random.Random(seed)
        original = incremental_site.SECTIONS
        incremental_site.SECTIONS = ["articles", "notes"]
        try:
            with tempfile.TemporaryDirectory() as temporary:
                static = Path(temporary) / "static"
                static.mkdir()
                site = Site(projector_factory(static), Path(temporary) / "work")
                before_pages, _ = site.full()
                for step in range(steps):
                    site.touched.clear()
                    site.reports.clear()
                    name, item_id = apply_operation(site, rng)
                    site.project_item(item_id)
                    context = f"seed={seed} step={step} op={name} item={item_id}"
                    self.assertTrue(all(report.ok for report in site.reports), context)
                    incremental_pages, incremental_redirects = site.incremental()
                    full_pages, _full_redirects = site.full()
                    full_directory = site.work / f"full-{site.generation}"
                    self.assertEqual(incremental_pages, full_pages, context)
                    self.assertEqual(incremental_redirects, site.full_with_remembered_moves(), context)
                    touched = set(site.touched)
                    changed = {key for key in set(before_pages) | set(full_pages) if before_pages.get(key) != full_pages.get(key)}
                    self.assertLessEqual(changed, touched, f"{context}: pages changed but were not written")
                    state = read_item_state(site.store, item_id)
                    own = set(state.page_keys) | set(state.former_page_keys) if state else set()
                    if name != "rename":   # a rename is two projections; pages the in-between state rewrote and the end state restored are legitimate
                        # The Markdown twin of an authored page leaves out its includes, but its input digest is the page's,
                        # so it is rewritten (with the same bytes) together with the page whose include changed.
                        twins = {key for key in touched if key.endswith(".md") and key[:-3] + ".html" in changed}
                        rewritten = touched - changed - own - twins - {"llms-full.txt"}
                        if name == "hide":
                            # An include depends on the full fingerprint of the entries it shows, and the feed flag is part of it, so a page
                            # that shows the item is rewritten (with the same bytes); no page that does not show it may be.
                            href = f'href="/{state.page_keys[0]}"'
                            rewritten = {key for key in rewritten if href not in (full_directory / (key[:-3] + ".html" if key.endswith(".md") else key)).read_text(encoding="utf-8")}
                        self.assertEqual(rewritten, set(), f"{context}: pages written that did not change")
                    before_pages = full_pages
        finally:
            incremental_site.SECTIONS = original

    def test_collections_and_included_listings_match_a_full_projection_after_random_edits(self) -> None:
        for seed in range(4):
            with self.subTest(seed=seed):
                self.run_sequence(seed, 25)

    def test_the_sequences_exercise_the_collections_and_the_page_files(self) -> None:
        incremental_site.SECTIONS, original = ["articles", "notes"], incremental_site.SECTIONS
        try:
            with tempfile.TemporaryDirectory() as temporary:
                static = Path(temporary) / "static"
                static.mkdir()
                site = Site(projector_factory(static), Path(temporary) / "work")
                rng = random.Random(3)
                for _step in range(40):
                    _name, item_id = apply_operation(site, rng)
                    site.project_item(item_id)
                pages, _ = site.incremental()
                for key in ("index.html", "picks/index.html", "all/index.html", "late/index.html", "tags/index.html"):
                    self.assertIn(key, pages)
        finally:
            incremental_site.SECTIONS = original

    def test_reconcile_finds_no_drift_after_random_edits(self) -> None:
        original = incremental_site.SECTIONS
        incremental_site.SECTIONS = ["articles", "notes"]
        try:
            with tempfile.TemporaryDirectory() as temporary:
                static = Path(temporary) / "static"
                static.mkdir()
                site = Site(projector_factory(static), Path(temporary) / "work")
                rng = random.Random(11)
                for _step in range(20):
                    _name, item_id = apply_operation(site, rng)
                    site.project_item(item_id)
                outcome = reconcile(site.context, dry_run=True)
                self.assertFalse(outcome.drift, outcome.to_dict())
        finally:
            incremental_site.SECTIONS = original


if __name__ == "__main__":
    unittest.main()
