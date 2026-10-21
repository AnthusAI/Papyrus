"""The shadow-run spread sample: deterministic, balanced by intake origin, spread over time, recorded."""
import json

import pytest

from papyrus_content.relevance_sample import (SAMPLE_POLICY, allocate, distribution, draw_sample, intake_origin,
                                              load_manifest, looks_like_test_fixture, write_manifest)

CORPUS = "knowledge-corpus-example"


def reference(lineage, *, day, reason="reference-import", run="catalog", actor="importer", uri=None):
    return {"lineageId": lineage, "contentHash": f"hash-{lineage}", "importedAt": f"2026-05-{day:02d}T00:00:00Z",
            "changeReason": reason, "curationStatusUpdatedBy": actor, "sourceUri": uri or f"https://example.org/{lineage}",
            "importRunId": f"knowledge-import-{CORPUS}-{run}-0123456789abcdef" if run else None}


def pool():
    catalog = [reference(f"catalog-{index:02d}", day=1 + index % 28) for index in range(40)]
    stubs = [reference(f"stub-{index:03d}", day=1 + index % 28, reason="grobid-citation-graph", run=None,
                       actor="url-text") for index in range(200)]
    email = [reference(f"email-{index}", day=10 + index, actor="editor@example.org") for index in range(3)]
    return catalog + stubs + email


def test_the_same_seed_draws_the_same_sample_in_the_same_order():
    first = draw_sample(pool(), size=20, seed="s1", corpus_id=CORPUS)
    again = draw_sample(list(reversed(pool())), size=20, seed="s1", corpus_id=CORPUS)
    assert first == again
    assert first["policy"] == SAMPLE_POLICY and first["size"] == 20


def test_a_different_seed_draws_a_different_sample():
    assert (draw_sample(pool(), size=20, seed="s1", corpus_id=CORPUS)["lineageIds"]
            != draw_sample(pool(), size=20, seed="s2", corpus_id=CORPUS)["lineageIds"])


def test_housekeeping_origins_are_left_out_unless_asked_for():
    default = draw_sample(pool(), size=100, seed="s", corpus_id=CORPUS)
    assert not any(lineage.startswith("stub-") for lineage in default["lineageIds"])
    assert default["size"] == 43
    assert default["excluded"] == {"housekeeping origin grobid-citation-graph": 200}
    topped_up = draw_sample(pool(), size=100, seed="s", corpus_id=CORPUS, include_housekeeping=True)
    assert topped_up["size"] == 100
    assert sum(lineage.startswith("stub-") for lineage in topped_up["lineageIds"]) == 57


def test_test_fixtures_are_never_sampled():
    fixtures = [reference("fixture-doi", day=1, uri="https://doi.org/10.5555/papyrus.e2e.1"),
                reference("fixture-agent", day=2, actor="behave-live-agent")]
    manifest = draw_sample([*pool(), *fixtures], size=100, seed="s", corpus_id=CORPUS)
    assert not any(lineage.startswith("fixture-") for lineage in manifest["lineageIds"])
    assert manifest["excluded"]["test fixture"] == 2
    assert all(looks_like_test_fixture(fixture) for fixture in fixtures)


def test_small_origins_are_taken_whole_and_the_rest_is_shared_evenly():
    manifest = draw_sample(pool(), size=23, seed="s", corpus_id=CORPUS, include_housekeeping=True)
    sampled = {origin: counts["sampled"] for origin, counts in manifest["strata"].items()}
    assert sampled["reference-import/catalog/editor@example.org"] == 3
    assert sorted(sampled.values()) == [3, 10, 10]


def test_picks_cover_the_whole_importedAt_timeline():
    manifest = draw_sample(pool(), size=12, seed="s", corpus_id=CORPUS)
    chosen = [row for row in pool() if row["lineageId"] in manifest["lineageIds"]]
    days = sorted(row["importedAt"][:10] for row in chosen if row["lineageId"].startswith("catalog-"))
    assert days[0] <= "2026-05-04" and days[-1] >= "2026-05-24"
    assert distribution(chosen, CORPUS)["importedAtRange"][0] <= "2026-05-04T00:00:00Z"


def test_any_prefix_of_the_order_is_itself_spread_across_origins():
    manifest = draw_sample(pool(), size=40, seed="s", corpus_id=CORPUS, include_housekeeping=True)
    by_id = {row["lineageId"]: row for row in pool()}
    first_batch = {intake_origin(by_id[lineage], CORPUS) for lineage in manifest["lineageIds"][:12]}
    assert len(first_batch) >= 2


def test_allocation_never_exceeds_a_stratum_or_the_total():
    assert allocate({"a": 2, "b": 50, "c": 50}, 30) == {"a": 2, "b": 14, "c": 14}
    assert allocate({"a": 2, "b": 3}, 30) == {"a": 2, "b": 3}
    assert sum(allocate({"a": 9, "b": 9, "c": 9}, 10).values()) == 10


def test_a_sample_needs_a_positive_size():
    with pytest.raises(ValueError, match="--sample"):
        draw_sample(pool(), size=0, seed="s", corpus_id=CORPUS)


def test_the_manifest_round_trips_and_refuses_edits_and_other_corpora(tmp_path):
    manifest = draw_sample(pool(), size=10, seed="s", corpus_id=CORPUS)
    path = tmp_path / "manifest.json"
    write_manifest(manifest, path)
    assert load_manifest(path, CORPUS) == manifest
    with pytest.raises(ValueError, match="not knowledge-corpus-other"):
        load_manifest(path, "knowledge-corpus-other")
    edited = json.loads(path.read_text())
    edited["lineageIds"].append("extra")
    path.write_text(json.dumps(edited))
    with pytest.raises(ValueError, match="edited after it was drawn"):
        load_manifest(path, CORPUS)
