"""The parity command's report over a whole fixture site: the same corpus rendered from the file and from the index, and then with the data made to disagree. Offline."""
from __future__ import annotations

import copy

import pytest

from papyrus_content.home_page.parity import DIFFERENT, ROUNDING_TIER, parity_report
from papyrus_content.home_page.render_test import build_site
from procedures.newsroom.tests.home_page_index_support import TODAY, IndexedClient, make_corpus, make_row


class Skewed(IndexedClient):
    """The file path reads ``rows``; the index path reads ``index_rows``: what a snapshot that has gone stale looks like beside the index."""

    def __init__(self, rows, index_rows):
        super().__init__(rows)
        self.index_side = IndexedClient(index_rows)

    def iterate_pages(self, *arguments, **keywords):
        return self.index_side.iterate_pages(*arguments, **keywords)


@pytest.fixture()
def sites():
    """Two projected copies of the fixture site, one per variant, each with its own scratch directory."""
    made = {variant: build_site("snapshot", [], snapshot=False) for variant in ("snapshot", "index")}
    yield made
    for site in made.values():
        site.cleanup()


def run(sites, client):
    return parity_report(client, lambda variant: (sites[variant].context, sites[variant].out))


def test_a_corpus_that_both_paths_read_alike_is_in_parity(sites):
    report = run(sites, IndexedClient(make_corpus()))
    assert report["ok"] and report["differing"] == [] and report["missing"] == [] and report["identical"] >= 8, report


def test_a_stored_prediction_that_moved_after_the_file_was_made_is_listed_with_its_first_differing_card(sites):
    rows = make_corpus()
    moved = copy.deepcopy(rows)
    best = max((row for row in moved if row["curationStatus"] == "pending" and row.get("predictedAcceptProbability")), key=lambda row: row["predictedAcceptProbability"])
    best["predictedAcceptProbability"] = 0.5
    best["predictionSortKey"] = f"0.500000#{best['feedArrivalAt']}#{best['id']}"
    best["publicOrderKey"] = f"p0.500000#{best['feedArrivalAt']}#{best['id']}"
    report = run(sites, Skewed(rows, moved))
    assert not report["ok"]
    assert report["differing"] and all(item["kind"] == DIFFERENT and item["first"].startswith(("card ", "item ")) for item in report["differing"]), report["differing"]


def test_two_cards_that_round_to_the_same_percentage_differ_only_inside_a_rounding_tier(sites):
    rows = [make_row("later", "accepted", probability=0.904, arrived=TODAY, accepted=TODAY), make_row("sooner", "accepted", probability=0.896, arrived=TODAY.replace(hour=13), accepted=TODAY)]
    report = run(sites, IndexedClient(rows))
    assert report["differing"] and {item["kind"] for item in report["differing"]} == {ROUNDING_TIER}, report
    assert report["ok"] is True
