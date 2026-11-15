from __future__ import annotations

from papyrus_content.entity_labels.fakes import FakeSite
from papyrus_content.entity_labels.keys import fold, name_key, work_key
from papyrus_content.entity_labels.lookup import find_concepts
from papyrus_content.entity_labels.primary import primary_text_hash, sync_node
from papyrus_content.entity_labels.store import LabelStore

NOW = "2026-11-15T12:00:00Z"


def site_with(*nodes):
    site = FakeSite()
    for args in nodes:
        site.add_node(*args[:3], **(args[3] if len(args) > 3 else {}))
    return site


def sync_all(site):
    for node in list(site.tables["SemanticNode"].values()):
        sync_node(site, node, primary_language="en", now=NOW)


def test_fold_makes_one_name_of_its_spellings():
    assert fold("  Ｈuman   OVERSIGHT ") == "human oversight" == fold("human oversight")
    assert name_key("es-419", "Supervisión  Humana") == "concept#es-419#supervisión humana"
    assert work_key("es-419", "stale") == "concept#es-419#stale" and work_key("es-419", "current") is None


def test_a_node_without_a_language_is_given_the_primary_one_and_its_names_become_rows():
    site = site_with(("c1", "editor_concept--human-oversight", "Human oversight", {"aliases": ["human control"], "description": "People keep authority."}))
    counts = sync_node(site, site.tables["SemanticNode"]["c1-v1"], primary_language="en", now=NOW)
    assert counts == {"created": 3, "updated": 0, "deleted": 0, "language": 1, "stale": 0}
    assert site.tables["SemanticNode"]["c1-v1"]["language"] == "en"
    rows = {row["id"]: row for row in site.tables["EntityLabel"].values()}
    assert set(rows) == {"concept#c1#en", "concept#c1#en#alias#human control", "concept#c1#en#hidden#human-oversight"}
    assert rows["concept#c1#en"]["nameKey"] == "concept#en#human oversight" and rows["concept#c1#en"]["origin"] == "primary" and rows["concept#c1#en"]["syncState"] == "current"
    assert "workKey" not in rows["concept#c1#en"]


def test_a_second_sync_writes_nothing_and_a_renamed_concept_moves_its_rows():
    site = site_with(("c1", "editor_concept--human-oversight", "Human oversight", {"aliases": ["human control"]}))
    sync_all(site)
    before = len(site.writes)
    sync_all(site)
    assert len(site.writes) == before
    node = site.tables["SemanticNode"]["c1-v1"]
    node.update(displayName="Human supervision", aliases=[])
    counts = sync_node(site, node, primary_language="en", now=NOW)
    assert counts["deleted"] == 1 and counts["updated"] == 1 and counts["created"] == 0
    assert {row["text"] for row in site.tables["EntityLabel"].values()} == {"Human supervision", "human-oversight"}


def test_names_are_found_by_index_never_by_listing_the_table():
    site = site_with(("c1", "editor_concept--human-oversight", "Human oversight", {"aliases": ["human control"]}),
                     ("c2", "editor_concept--automation-bias", "Automation bias"))
    sync_all(site)
    site.scans = 0
    for typed in ("Human Oversight", "human control", "#human-oversight", "editor_concept--human-oversight", "human-oversight"):
        assert [node["lineageId"] for node in find_concepts(site, typed)] == ["c1"], typed
    assert [node["lineageId"] for node in find_concepts(site, "#automation-bias (editor_concept)")] == ["c2"]
    assert find_concepts(site, "#automation-bias (person)") == [] and find_concepts(site, "nothing like it") == []
    assert site.scans == 0


def test_the_languages_asked_are_read_in_order():
    site = site_with(("c1", "editor_concept--human-oversight", "Human oversight"))
    sync_all(site)
    LabelStore(site).create({"id": "concept#c1#es-419", "entityKind": "concept", "entityId": "c1", "entityKey": "concept#c1", "language": "es-419", "role": "preferred", "text": "Supervisión humana",
                             "nameKey": name_key("es-419", "Supervisión humana"), "sortKey": "es-419#preferred#supervisión humana", "origin": "machine"})
    assert [node["lineageId"] for node in find_concepts(site, "supervisión humana", languages=["es-419", "en"])] == ["c1"]
    assert find_concepts(site, "supervisión humana", languages=["en"]) == []


def test_a_translated_label_becomes_stale_when_the_text_it_came_from_changes_and_conflict_when_pinned():
    site = site_with(("c1", "editor_concept--human-oversight", "Human oversight", {"description": "Old words."}))
    sync_all(site)
    node = site.tables["SemanticNode"]["c1-v1"]
    old = primary_text_hash(node)
    store = LabelStore(site)
    for language, pinned in (("es-419", False), ("zh-Hans", True)):
        store.create({"id": f"concept#c1#{language}", "entityKind": "concept", "entityId": "c1", "entityKey": "concept#c1", "language": language, "role": "preferred", "text": "x", "nameKey": name_key(language, "x"),
                      "sortKey": f"{language}#preferred#x", "origin": "machine", "pinned": pinned, "syncState": "current", "sourceContentHash": old})
    node["description"] = "New words."
    counts = sync_node(site, node, primary_language="en", now=NOW)
    assert counts["stale"] == 2
    rows = site.tables["EntityLabel"]
    assert rows["concept#c1#es-419"]["syncState"] == "stale" and rows["concept#c1#es-419"]["workKey"] == "concept#es-419#stale"
    assert rows["concept#c1#zh-Hans"]["syncState"] == "conflict" and rows["concept#c1#zh-Hans"]["workKey"] == "concept#zh-Hans#conflict"
    assert [row["id"] for row in store.needing_work("es-419", "stale")] == ["concept#c1#es-419"]
    assert sync_node(site, node, primary_language="en", now=NOW)["stale"] == 0


def test_a_translated_label_is_never_touched_by_the_primary_reconcile_otherwise():
    site = site_with(("c1", "editor_concept--human-oversight", "Human oversight"))
    sync_all(site)
    node = site.tables["SemanticNode"]["c1-v1"]
    LabelStore(site).create({"id": "concept#c1#es-419", "entityKind": "concept", "entityId": "c1", "entityKey": "concept#c1", "language": "es-419", "role": "preferred", "text": "Supervisión humana",
                             "nameKey": name_key("es-419", "Supervisión humana"), "sortKey": "es-419#preferred#supervisión humana", "origin": "human", "pinned": True,
                             "syncState": "current", "sourceContentHash": primary_text_hash(node)})
    counts = sync_node(site, node, primary_language="en", now=NOW)
    assert counts == {"created": 0, "updated": 0, "deleted": 0, "language": 0, "stale": 0}
    assert site.tables["EntityLabel"]["concept#c1#es-419"]["text"] == "Supervisión humana"


def test_the_backfill_dry_run_writes_nothing_and_the_real_run_is_resumable():
    from papyrus_content.entity_labels.backfill import backfill_entity_labels

    site = site_with(("c1", "editor_concept--human-oversight", "Human oversight", {"aliases": ["human control"]}), ("c2", "editor_concept--automation-bias", "Automation bias"))
    dry = backfill_entity_labels(site, apply=False, now=NOW)
    assert (dry["concepts"], dry["wouldChange"], site.writes) == (2, 2, [])
    first = backfill_entity_labels(site, apply=True, limit=1, now=NOW)
    assert first["concepts"] == 1
    rest = backfill_entity_labels(site, apply=True, now=NOW)
    assert rest["created"] == 3 and rest["language"] == 1   # the first concept was done and writes nothing again
    assert backfill_entity_labels(site, apply=True, now=NOW)["created"] == 0
    assert all(node["language"] == "en" for node in site.tables["SemanticNode"].values())


def test_a_concept_and_a_section_with_one_name_are_two_names():
    assert name_key("en", "Safety", None, "concept") != name_key("en", "Safety", None, "section")


def test_a_concept_with_no_name_is_found_by_its_id_and_never_stops_the_consumer():
    site = FakeSite()
    site.tables["SemanticNode"]["bare-v1"] = {"id": "bare-v1", "lineageId": "bare", "versionState": "current", "status": "accepted"}
    sync_node(site, site.tables["SemanticNode"]["bare-v1"], primary_language="en", now=NOW)
    assert [row["text"] for row in site.tables["EntityLabel"].values()] == ["bare"]
