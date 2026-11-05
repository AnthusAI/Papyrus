"""One changed Reference costs a fixed number of requests, whatever the size of the corpus, and the page it produces is the page a full read would."""

from __future__ import annotations

import copy
import dataclasses
import json
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import pytest

from papyrus_content.home_page.export import public_key
from papyrus_content.home_page.incremental import StateRefused, StoredState, apply_changes, fingerprint_of, sha_of, usable_state
from papyrus_content.home_page.settings import ThreadsSettings
from papyrus_content.home_page.state_store import DirtyBatch, MemoryStateStore
from papyrus_content.home_page.task import home_page_settings_of, run_home_page_snapshot
from papyrus_content.ideas.digest import RELEVANCE_PREDICATE
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

CORPUS = "knowledge-corpus-example"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
PAGE_SIZE = 100
REFERENCES_KEY = "_data/home-page/references.json"


class CorpusClient:
    """A corpus of ``count`` References behind the requests the snapshot makes, counting each request the way AppSync bills it (one per page of 100)."""

    def __init__(self, count: int) -> None:
        self.requests: Counter[str] = Counter()
        self.rows: dict[str, dict[str, Any]] = {}
        self.relations: dict[str, list[dict[str, Any]]] = {}
        self.previews: dict[str, list[dict[str, Any]]] = {}
        for index in range(count):
            self.add(index)

    @property
    def total(self) -> int:
        return sum(self.requests.values())

    def add(self, index: int) -> dict[str, Any]:
        accepted = index % 3 == 0
        arrival = f"2026-10-{1 + index % 28:02d}T{index % 24:02d}:{index % 60:02d}:00.000Z"
        lineage = f"reference-{index}"
        row = {
            "id": f"{lineage}-v1", "lineageId": lineage, "versionState": "current", "versionNumber": 1, "corpusId": CORPUS,
            "title": f"Reference number {index}", "sourceUri": f"https://example.org/posts/{index}", "createdAt": arrival, "feedArrivalAt": arrival,
            "curationStatus": "accepted" if accepted else "pending", "curationStatusKey": f"{CORPUS}#{'accepted' if accepted else 'pending'}",
            "feedStateKey": None if accepted else f"{CORPUS}#unrated", "curationStatusUpdatedAt": arrival, "curationActorKind": "human" if accepted else None,
            "starRating": 1 + index % 5 if accepted and index % 7 == 0 else None, "curationSectionId": "record-004" if index % 2 else None,
        }
        self.rows[row["id"]] = row
        confidence = 0.3 + (index % 7) / 10
        if not accepted and index % 10 != 5:
            row["predictedAcceptProbability"] = confidence   # the Cyclotron's first prediction, written onto the row; every tenth pending Reference has none yet
        self.relations[lineage] = [{"predicate": RELEVANCE_PREDICATE, "relationState": "current", "objectLineageId": "semantic-node-relevance-include-v1", "confidence": confidence, "createdAt": arrival}]
        if index % 4 == 0:
            self.previews[lineage] = [{"role": "preview", "sourceUri": f"https://images.example.org/{index}.jpg", "importedAt": arrival, "metadata": json.dumps({"description": f"About {index}.", "siteName": "Example"})}]
        return row

    def _pages(self, name: str, size: int) -> None:
        self.requests[name] += max(1, math.ceil(size / PAGE_SIZE))

    def list_by_index(self, index_name: str, key_value: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if index_name == "referencesByCurationStatusKey":
            found = [row for row in self.rows.values() if row["curationStatusKey"] == key_value]
        elif index_name == "referencesByFeedStateAndPrediction":
            found = [row for row in self.rows.values() if row["feedStateKey"] == key_value]
        elif index_name == "messageThreadsByKindAndUpdatedAt":
            found = []
        else:
            raise AssertionError(f"unexpected index {index_name}")
        self._pages(index_name, len(found))
        return copy.deepcopy(found)

    def get_record(self, model: str, record_id: str) -> dict[str, Any] | None:
        assert model == "Reference"
        self.requests["getReference"] += 1
        return copy.deepcopy(self.rows.get(record_id))

    def list_semantic_relations_by_subject_state(self, subject_state_key: str) -> list[dict[str, Any]]:
        lineage = subject_state_key.removeprefix("reference#").removesuffix("#current")
        found = self.relations.get(lineage, [])
        self._pages("relations", len(found))
        return copy.deepcopy(found)

    def list_reference_attachments_by_lineage(self, lineage_id: str) -> list[dict[str, Any]]:
        found = self.previews.get(lineage_id, [])
        self._pages("attachments", len(found))
        return copy.deepcopy(found)

    def list_records(self, model: str) -> list[dict[str, Any]]:
        assert model == "NewsroomSection"
        self.requests["sections"] += 1
        return [{"id": "record-004", "title": "Articles"}]

    def list_published_item_summaries(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []


def projected_site() -> ProjectedSite:
    directory = FIXTURES / "home-page"
    extra = {f"pages/{path.name}": path.read_bytes() for path in sorted((directory / "pages").glob("*.md"))}
    return ProjectedSite(settings=json.loads((directory / "projection.json").read_text(encoding="utf-8")), content=directory / "content", extra_files=extra)


@pytest.fixture
def site():
    projected = projected_site()
    yield projected
    projected.cleanup()


def run(site, client, store, dirty=None, *, threads=False, now=NOW):
    settings = home_page_settings_of(site.projector)
    if threads:
        settings = dataclasses.replace(settings, threads=ThreadsSettings(enabled=True))
    return run_home_page_snapshot(site.context, client, settings, now=now, state_store=store, dirty=dirty)


def document(site) -> dict[str, Any]:
    return json.loads(site.writer.get(REFERENCES_KEY))


def without_stamp(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "generatedAt"}


def accept(client: CorpusClient, index: int, stars: int | None = None) -> str:
    row = client.rows[f"reference-{index}-v1"]
    row.update({"curationStatus": "accepted", "curationStatusKey": f"{CORPUS}#accepted", "feedStateKey": None, "curationActorKind": "human", "curationStatusUpdatedAt": "2026-11-04T09:00:00.000Z"})
    if stars:
        row["starRating"] = stars
    return row["id"]


def test_the_incremental_page_is_the_page_a_full_read_builds(site):
    client, store = CorpusClient(300), MemoryStateStore()
    assert run(site, client, store)["mode"] == "full"
    changed = [accept(client, 1, stars=5), accept(client, 2), accept(client, 5, stars=1)]
    client.rows["reference-3-v1"]["title"] = "A retitled accepted Reference"
    client.rows["reference-6-v1"].update({"curationStatus": "rejected", "curationStatusKey": f"{CORPUS}#rejected"})
    client.rows["reference-8-v1"].update({"feedStateKey": None, "curationStatus": "archived"})
    client.rows["reference-7-v1"]["curationSectionId"] = "record-004"
    client.rows["reference-9-v1"]["starRating"] = 2
    fresh = client.add(300)
    ids = [*changed, "reference-3-v1", "reference-6-v1", "reference-8-v1", "reference-7-v1", "reference-9-v1", fresh["id"], "reference-gone-v1"]
    report = run(site, client, store, DirtyBatch(ids=frozenset(ids)))
    assert report["mode"] == "incremental" and report["changedRows"] == len(ids)
    incremental = document(site)

    again = projected_site()
    try:
        assert run_home_page_snapshot(again.context, client, home_page_settings_of(again.projector), now=NOW)["mode"] == "full"
        assert without_stamp(incremental) == without_stamp(json.loads(again.writer.get(REFERENCES_KEY)))
    finally:
        again.cleanup()


def test_a_superseded_version_replaces_its_record_and_a_dropped_one_leaves(site):
    client, store = CorpusClient(60), MemoryStateStore()
    run(site, client, store)
    old = client.rows["reference-3-v1"]
    newer = {**old, "id": "reference-3-v2", "versionNumber": 2, "title": "Version two"}
    old["versionState"] = "superseded"
    client.rows[newer["id"]] = newer
    run(site, client, store, DirtyBatch(ids=frozenset({"reference-3-v1", "reference-3-v2"})))
    titles = [record["title"] for record in document(site)["references"]]
    assert "Version two" in titles and "Reference number 3" not in titles
    newer["versionState"] = "superseded"
    run(site, client, store, DirtyBatch(ids=frozenset({"reference-3-v2"})))
    assert "Version two" not in [record["title"] for record in document(site)["references"]]


@pytest.mark.parametrize("count", [200, 5000])
def test_one_changed_reference_costs_a_fixed_number_of_requests(site, count):
    client, store = CorpusClient(count), MemoryStateStore()
    run(site, client, store)
    full_read = client.total
    assert full_read > count, "the full read costs requests in proportion to the corpus"

    client.requests.clear()
    changed = accept(client, 1, stars=4)
    report = run(site, client, store, DirtyBatch(ids=frozenset({changed})))
    assert report["mode"] == "incremental"
    assert dict(client.requests) == {"sections": 1, "getReference": 1, "relations": 1, "attachments": 1}, client.requests
    print(f"\nHOME-PAGE REQUESTS references={count} full_read={full_read} one_change={client.total}")  # noqa: T201


def test_ten_changes_cost_ten_times_one_and_none_cost_nothing(site):
    client, store = CorpusClient(1000), MemoryStateStore()
    run(site, client, store)
    client.requests.clear()
    ids = frozenset(accept(client, index) for index in range(1, 31, 3))
    run(site, client, store, DirtyBatch(ids=ids))
    assert client.total == 1 + 3 * len(ids)
    client.requests.clear()
    run(site, client, store, DirtyBatch())
    assert client.total == 0


def test_a_pending_reference_that_will_not_show_costs_two_requests_and_publishes_nothing(site):
    client, store = CorpusClient(100), MemoryStateStore()
    run(site, client, store)
    before = document(site)
    row = client.rows["reference-1-v1"]
    client.relations["reference-1"][0]["confidence"] = 0.05
    row["title"] = "Still pending and not recommended"
    client.requests.clear()
    run(site, client, store, DirtyBatch(ids=frozenset({row["id"]})))
    assert dict(client.requests) == {"sections": 1, "getReference": 1, "relations": 1}
    assert without_stamp(document(site)) == without_stamp(before)


def keys_of(site) -> set[str]:
    return {record["key"] for record in document(site)["references"]}


def test_a_pending_reference_nobody_has_predicted_is_on_no_page_and_costs_one_request_to_skip(site):
    """Ryan, 2026-11-05: an unpredicted Reference is not 50% and shows nothing. Reference 5 has a decision relation but no prediction written onto its row yet."""
    client, store = CorpusClient(100), MemoryStateStore()
    run(site, client, store)
    row = client.rows["reference-5-v1"]
    assert "predictedAcceptProbability" not in row
    assert public_key("reference-5") not in keys_of(site)
    row["title"] = "Retitled while unpredicted"
    client.requests.clear()
    run(site, client, store, DirtyBatch(ids=frozenset({row["id"]})))
    assert dict(client.requests) == {"sections": 1, "getReference": 1}, "its relations and attachments are not read"
    assert public_key("reference-5") not in keys_of(site)


def test_the_first_prediction_makes_the_reference_appear_with_its_video_picture_read_at_that_point(site):
    client, store = CorpusClient(100), MemoryStateStore()
    run(site, client, store)
    row = client.rows["reference-5-v1"]
    row.update({"medium": "video", "thumbnailPath": "assets/reference-thumbnails/a4645fd6b3de98f4-bb02a57c6adf.jpg"})
    run(site, client, store, DirtyBatch(ids=frozenset({row["id"]})))
    assert public_key("reference-5") not in keys_of(site), "a picture on an unpredicted row publishes nothing"
    row["predictedAcceptProbability"] = 0.8
    client.relations["reference-5"][0]["confidence"] = 0.8
    run(site, client, store, DirtyBatch(ids=frozenset({row["id"]})))
    record = next(item for item in document(site)["references"] if item["key"] == public_key("reference-5"))
    assert record["status"] == "recommended" and record["predictedAcceptProbability"] == 0.8 and record["confidence"] == 0.8
    assert record["image"] == "/assets/reference-thumbnails/a4645fd6b3de98f4-bb02a57c6adf.jpg"


def test_state_written_before_the_rule_changed_is_refused_so_the_unpredicted_rows_already_published_leave(monkeypatch, site):
    """An incremental run re-reads only the ids it is given, so rows published under the old rule would stay without a full read. The state format forces it."""
    from papyrus_content.home_page import incremental

    client, store = CorpusClient(100), MemoryStateStore()
    monkeypatch.setattr(incremental, "STATE_FORMAT", 1)
    for row in client.rows.values():
        row.pop("predictedAcceptProbability", None)   # under format 1 an unpredicted pending Reference counted as 0.5 and was published
    monkeypatch.setattr("papyrus_content.home_page.export.has_prediction", lambda row: True)
    run(site, client, store)
    assert public_key("reference-5") in keys_of(site)
    monkeypatch.undo()

    for index in range(100):
        row = client.rows[f"reference-{index}-v1"]
        if row["curationStatus"] == "pending" and index % 10 != 5:
            row["predictedAcceptProbability"] = 0.3 + (index % 7) / 10
    report = run(site, client, store, DirtyBatch(ids=frozenset({"reference-2-v1"})))
    assert report["mode"] == "full" and "settings or the build" in report["fullBecause"]
    assert public_key("reference-5") not in keys_of(site)


def test_threads_are_read_again_only_when_a_message_changed_or_an_old_reference_entered_the_page(site):
    client, store = CorpusClient(100), MemoryStateStore()
    run(site, client, store, threads=True)
    first = Counter(client.requests)
    assert first["messageThreadsByKindAndUpdatedAt"] > 0, "the first read builds the threads"

    client.requests.clear()
    fresh = client.add(100)
    fresh["createdAt"] = fresh["feedArrivalAt"] = "2026-11-04T12:30:00.000Z"
    accept(client, 100)
    run(site, client, store, DirtyBatch(ids=frozenset({fresh["id"]})), threads=True)
    assert "messageThreadsByKindAndUpdatedAt" not in client.requests, "a Reference that did not exist when the file was last built has no thread"

    client.requests.clear()
    accept(client, 1)
    run(site, client, store, DirtyBatch(ids=frozenset({"reference-1-v1"})), threads=True)
    assert client.requests["messageThreadsByKindAndUpdatedAt"] > 0, "an older Reference entering the page may already have a thread"

    client.requests.clear()
    run(site, client, store, DirtyBatch(message_seq=1), threads=True)
    assert client.requests["messageThreadsByKindAndUpdatedAt"] > 0 and client.requests["getReference"] == 0


def test_a_run_without_state_or_with_state_it_cannot_trust_reads_the_corpus_once(site):
    client, store = CorpusClient(120), MemoryStateStore()
    assert run(site, client, store, DirtyBatch(ids=frozenset({"reference-1-v1"})))["fullBecause"] == "there is no state yet"
    assert store.state is not None
    accept(client, 1)
    assert run(site, client, store, DirtyBatch(ids=frozenset({"reference-1-v1"})))["mode"] == "incremental"

    site.writer.put(REFERENCES_KEY, site.writer.get(REFERENCES_KEY) + b" ")
    assert "not the one the state was built with" in run(site, client, store, DirtyBatch(ids=frozenset({"reference-2-v1"})))["fullBecause"]

    assert run(site, client, store, DirtyBatch(ids=frozenset({"reference-2-v1"}), full_seq=3))["mode"] == "full"
    store.state = dataclasses.replace(store.state, fingerprint="another")
    assert "settings" in run(site, client, store, DirtyBatch(ids=frozenset({"reference-2-v1"})))["fullBecause"]

    store.state = dataclasses.replace(store.state, entries={})
    assert "different References" in run(site, client, store, DirtyBatch(ids=frozenset({"reference-2-v1"})))["fullBecause"]


def test_a_run_given_no_batch_is_a_full_read_and_leaves_state_for_the_next(site):
    client, store = CorpusClient(90), MemoryStateStore()
    assert run(site, client, store, None)["mode"] == "full"
    assert set(store.state.entries) == {record["key"] for record in document(site)["references"]}


def test_the_state_goes_with_the_file_that_was_written(site):
    client, store = CorpusClient(90), MemoryStateStore()
    run(site, client, store)
    assert store.state.snapshot_sha == sha_of(site.writer.get(REFERENCES_KEY))
    accept(client, 1, stars=3)
    run(site, client, store, DirtyBatch(ids=frozenset({"reference-1-v1"})))
    assert store.state.snapshot_sha == sha_of(site.writer.get(REFERENCES_KEY))
    assert store.state.entries[next(r["key"] for r in document(site)["references"] if r["title"] == "Reference number 1")].stars == 3


def test_a_star_only_change_reaches_the_page_in_an_incremental_run_and_who_rated_stays_private(site):
    client, store = CorpusClient(90), MemoryStateStore()
    run(site, client, store)
    accept(client, 1, stars=5)
    first = run(site, client, store, DirtyBatch(ids=frozenset({"reference-1-v1"})))
    assert first["mode"] == "incremental"
    assert any(standing.stars == 5 for standing in store.state.entries.values()), "the private state keeps the count for the order"
    def shown() -> int | None:
        return next(record["stars"] for record in json.loads(site.writer.get(REFERENCES_KEY))["references"] if record["title"] == "Reference number 1")

    assert shown() == 5, "the accepted Reference shows its count"
    # Only the count changes on the row (nothing else, so the status is already accepted): the next incremental run republishes it.
    client.rows["reference-1-v1"].update({"starRating": 3})
    second = run(site, client, store, DirtyBatch(ids=frozenset({"reference-1-v1"})))
    assert second["mode"] == "incremental" and second["written"] == [REFERENCES_KEY]
    assert shown() == 3
    assert all(b"starRating" not in content and b"starRatedBy" not in content and b"starRatedAt" not in content for content in site.tree.values())


def test_a_dry_run_saves_no_state(site):
    client, store = CorpusClient(60), MemoryStateStore()
    run_home_page_snapshot(site.context, client, home_page_settings_of(site.projector), now=NOW, dry_run=True, state_store=store, dirty=None)
    assert store.saves == 0 and site.writer.get(REFERENCES_KEY) is None


def test_usable_state_checks_every_condition():
    settings = type("S", (), {"references": type("R", (), {"fields": ("key",), "recommended_threshold": 0.5, "summary_characters": 240})()})()
    fingerprint = fingerprint_of(settings, CORPUS)
    assert fingerprint != fingerprint_of(settings, "another-corpus")
    body = json.dumps({"references": [{"key": "a1"}]}).encode()
    from papyrus_content.home_page.export import Standing

    state = StoredState(fingerprint, sha_of(body), {"a1": Standing("id", None, 0.5, None, None)})
    assert set(usable_state(state, fingerprint=fingerprint, snapshot=body)) == {"a1"}
    with pytest.raises(StateRefused):
        usable_state(state, fingerprint=fingerprint, snapshot=b"{}")
    with pytest.raises(StateRefused):
        usable_state(StoredState(fingerprint, sha_of(b"not json"), {}), fingerprint=fingerprint, snapshot=b"not json")


def test_apply_changes_with_nothing_changed_reads_nothing():
    client = CorpusClient(10)
    changes = apply_changes(client, CORPUS, type("S", (), {})(), {}, {}, [])
    assert changes.examined == 0 and client.total == 0 and changes.records == []
