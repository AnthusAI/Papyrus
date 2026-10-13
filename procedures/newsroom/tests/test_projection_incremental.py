"""Incremental projection equals a full re-projection, after random sequences of edits.

After every operation, the site store that was maintained incrementally must
equal the store a fresh ``project_all`` writes from the same data, and the pages
the operation wrote must be exactly the pages whose content changed, plus the
operation's own pages.
"""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from papyrus_content.projection.engine import reconcile
from papyrus_content.projection.item_state import read_item_state
from procedures.newsroom.tests.incremental_site import Site, apply_operation


class IncrementalEqualsFullTests(unittest.TestCase):
    def run_sequence(self, kind: str, seed: int, steps: int) -> list[tuple[str, str, int]]:
        rng = random.Random(seed)
        log: list[tuple[str, str, int]] = []
        with tempfile.TemporaryDirectory() as temporary:
            site = Site(kind, Path(temporary))
            before_pages, _ = site.full()
            for step in range(steps):
                site.touched.clear()
                site.reports.clear()
                name, item_id = apply_operation(site, rng)
                site.project_item(item_id)
                self.assertTrue(all(report.ok for report in site.reports), (seed, step, name))
                incremental_pages, incremental_redirects = site.incremental()
                full_pages, full_redirects = site.full()
                context = f"kind={kind} seed={seed} step={step} op={name} item={item_id}"
                self.assertEqual(incremental_pages, full_pages, context)
                self.assertEqual(incremental_redirects, site.full_with_remembered_moves(), context)
                self.assertLessEqual(full_redirects.items(), incremental_redirects.items(), context)
                touched = set(site.touched)
                changed = {key for key in set(before_pages) | set(full_pages) if before_pages.get(key) != full_pages.get(key)}
                self.assertLessEqual(changed, touched, f"{context}: pages changed but were not written")
                state = read_item_state(site.store, item_id)
                own_pages = set(state.page_keys) | set(state.former_page_keys) if state else set()
                extra = touched - changed - own_pages
                self.assertEqual(extra, set(), f"{context}: pages written that did not change")
                before_pages = full_pages
                log.append((name, item_id, len(touched)))
        return log

    def test_generic_markus_site_matches_a_full_projection_after_random_edits(self) -> None:
        for seed in range(6):
            with self.subTest(seed=seed):
                self.run_sequence("generic", seed, 40)

    def test_site_with_public_json_matches_a_full_projection_after_random_edits(self) -> None:
        for seed in range(8):
            with self.subTest(seed=seed):
                self.run_sequence("public", seed, 40)

    def test_feed_shaped_site_matches_a_full_projection_after_random_edits(self) -> None:
        for seed in range(10):
            with self.subTest(seed=seed):
                self.run_sequence("feed", seed, 40)

    def test_reconcile_finds_no_drift_after_random_edits(self) -> None:
        for kind in ("generic", "feed", "public"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                rng = random.Random(7)
                site = Site(kind, Path(temporary))
                for _step in range(25):
                    _name, item_id = apply_operation(site, rng)
                    site.project_item(item_id)
                outcome = reconcile(site.context, dry_run=True)
                self.assertFalse(outcome.drift, outcome.to_dict())


if __name__ == "__main__":
    unittest.main()
