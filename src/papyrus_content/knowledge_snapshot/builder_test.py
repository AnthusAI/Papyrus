from __future__ import annotations

import dataclasses
import json
from datetime import date, timedelta

from papyrus_content.reader_steering.snapshot import encoded

from .actors import Actor
from .builder import CLUSTERS_FILE, CLUSTERS_HISTORY_FILE, INDEX_FILE, build_files, entity_file
from .model import (
    Beat,
    Cluster,
    EntityNode,
    FrontMatterEntity,
    ItemLink,
    KnowledgeData,
    NodeRelation,
    PublishedItem,
    SnapshotOptions,
)
from .trends import change_of, percent_change
from .weeks import week_label, week_number

AS_OF = date(2026, 10, 19)
AI = Actor("ai", None, "2026-10-12")
ADA = Actor("human", "Ada", "2026-10-13")
MONDAY_WEEK = week_number(AS_OF)


def published_in_week(offset: int, name: str, day: int = 0) -> str:
    return (AS_OF - timedelta(weeks=offset) + timedelta(days=day)).isoformat() + "T09:30:00Z"


def item(name: str, offset: int, **overrides) -> PublishedItem:
    return PublishedItem(
        key=f"lineage-{name}",
        item_id=f"item-{name}",
        title=overrides.pop("title", f"Title {name}"),
        url=overrides.pop("url", f"/items/{name}/"),
        published_at=overrides.pop("published_at", published_in_week(offset, name)),
        **overrides,
    )


def node(kind: str, name: str, **overrides) -> EntityNode:
    key = f"{kind}--{name.lower().replace(' ', '-')}"
    values = {"lineage_id": f"semantic-node-{key}", "node_key": key, "kind": kind, "name": name, "status": "accepted"}
    values.update(overrides)
    return EntityNode(**values)


def link(item_name: str, target: EntityNode, confirmed: bool = True) -> ItemLink:
    return ItemLink(item_key=f"lineage-{item_name}", node_lineage_id=target.lineage_id, confirmed=confirmed)


OPTIONS = SnapshotOptions(as_of=AS_OF)


def two_tasks():
    voice = node("task", "Voice cloning", description="Copying a voice from a short sample.", description_state="reviewed", description_edited_by=ADA, accepted_by=AI)
    completion = node("task", "Code completion")
    maker = node("maker", "Some Lab")
    items = []
    links = []
    for index in range(12):
        items.append(item(f"v{index}", offset=index % 4))
        links.append(link(f"v{index}", voice))
    for index in range(6):
        items.append(item(f"p{index}", offset=4 + index % 4))
        links.append(link(f"p{index}", voice))
    for index in range(3):
        items.append(item(f"c{index}", offset=index))
        links.append(link(f"c{index}", completion))
    links.append(link("v0", maker))
    links.append(link("v1", maker))
    return KnowledgeData(items=tuple(items), nodes=(voice, completion, maker), links=tuple(links)), voice, completion, maker


def test_change_definition_twelve_against_six_is_plus_one_hundred():
    assert percent_change(12, 6) == 100
    assert change_of([0, 0, 0, 0, 1, 1, 1, 3]).percent is None
    assert change_of([0] * 8).to_dict() == {"last4": 0, "prior4": 0, "percent": None}


def test_percent_needs_a_base_of_five():
    assert percent_change(9, 4) is None
    assert percent_change(9, 5) == 80
    assert percent_change(2, 5) == -60
    assert percent_change(1, 8) == -88


def test_the_index_carries_every_entitys_full_weekly_history_from_its_first_week():
    data, *_ = two_tasks()
    files = build_files(data, OPTIONS)
    row = next(entity for entity in files[INDEX_FILE]["entities"] if entity["key"] == "task--voice-cloning")
    assert row["seriesWeekly"] == [1, 1, 2, 2, 3, 3, 3, 3] and len(row["seriesWeekly"]) == row["weeksOfHistory"] == 8
    assert row["seriesWeekly"][-8:] == row["series8"] and sum(row["seriesWeekly"]) == row["itemCount"]
    assert row["seriesWeeklyStart"] < files[INDEX_FILE]["asOf"]
    assert row["dateBasis"] == "publication"


def test_weekly_series_and_change_for_an_entity():
    data, voice, _completion, _maker = two_tasks()
    files = build_files(data, OPTIONS)
    entity = files[entity_file("task--voice-cloning")]
    assert entity["itemCount"] == 18
    assert entity["series8"] == [1, 1, 2, 2, 3, 3, 3, 3]
    assert len(entity["series26"]) == 26
    assert entity["series26"][-8:] == entity["series8"]
    assert entity["change"] == {"last4": 12, "prior4": 6, "percent": 100}
    assert entity["weeksOfHistory"] == 8
    index = files[INDEX_FILE]
    row = next(row for row in index["entities"] if row["key"] == "task--voice-cloning")
    assert row["change"] == entity["change"] and row["isNew"] is False


def test_an_entity_first_linked_two_weeks_ago_is_new_and_not_trending():
    data, _voice, completion, _maker = two_tasks()
    files = build_files(data, OPTIONS)
    row = next(row for row in files[INDEX_FILE]["entities"] if row["key"] == "task--code-completion")
    assert row["isNew"] is True and row["weeksOfHistory"] == 3
    assert "task--code-completion" not in files[INDEX_FILE]["trending"]


def test_only_confirmed_links_to_published_dated_items_count():
    voice = node("task", "Voice cloning")
    data = KnowledgeData(
        items=(
            item("a", 0),
            item("undated", 0, published_at=None),
            item("future", 0, published_at="2026-12-01T00:00:00Z"),
        ),
        nodes=(voice,),
        links=(
            link("a", voice),
            link("a", voice, confirmed=False),
            link("undated", voice),
            link("future", voice),
            link("unpublished", voice),
        ),
    )
    files = build_files(data, OPTIONS)
    assert files[entity_file("task--voice-cloning")]["itemCount"] == 1


def test_unaccepted_entities_and_entities_without_links_are_left_out():
    generated = node("task", "Generated one", status="generated")
    rejected = node("task", "Rejected one", status="rejected")
    unlinked = node("task", "Unlinked")
    data = KnowledgeData(
        items=(item("a", 0),),
        nodes=(generated, rejected, unlinked),
        links=(link("a", generated), link("a", rejected)),
    )
    files = build_files(data, OPTIONS)
    assert files[INDEX_FILE]["entities"] == []
    assert [key for key in files if key.startswith("_data/knowledge/entities/")] == []


def _corpus(shapes: dict[str, tuple[str, int, int]]):
    """Entities by name: ``name -> (kind, mentions in the last four weeks, mentions in the four weeks before)``."""
    entities, links, items = [], [], []
    for name, (kind, last, prior) in shapes.items():
        target = node(kind, name)
        entities.append(target)
        for index in range(last):
            items.append(item(f"{name}-l{index}", offset=index % 4))
            links.append(link(f"{name}-l{index}", target))
        for index in range(prior):
            items.append(item(f"{name}-p{index}", offset=4 + index % 4))
            links.append(link(f"{name}-p{index}", target))
    return KnowledgeData(items=tuple(items), nodes=tuple(entities), links=tuple(links))


def test_trending_is_surprise_over_the_entitys_own_baseline_and_the_corpus_growth_not_a_raw_count():
    # The shape of 2026-10-26: a licence and a task carry the biggest counts and rise with the whole corpus; makers with few mentions are the news.
    data = _corpus(
        {
            "mit": ("licence", 60, 40),
            "text generation": ("task", 80, 55),
            "nvidia": ("maker", 6, 1),
            "olmo": ("model_family", 5, 2),
            "steady": ("maker", 9, 8),
            "quiet": ("maker", 1, 0),
        }
    )
    # nvidia gained share; olmo (+3 on a small base) is not far enough above its baseline; the licence and the task rose with the corpus.
    assert build_files(data, OPTIONS)[INDEX_FILE]["trending"] == ["maker--nvidia"]


def test_a_broad_kind_needs_a_far_larger_surprise_than_a_maker_to_trend():
    shapes = {"anchor": ("maker", 4, 1), "same shape": ("task", 4, 1), "filler": ("maker", 30, 30)}
    order = build_files(_corpus(shapes), OPTIONS)[INDEX_FILE]["trending"]
    assert order == ["maker--anchor"]  # the same counts as a task: the task is demoted below the threshold, the maker is not


def test_entities_that_only_grew_with_the_corpus_do_not_trend():
    # Everything doubles: no entity gained share, so nobody is news.
    data = _corpus({"a": ("maker", 20, 10), "b": ("maker", 20, 10), "c": ("model", 20, 10)})
    assert build_files(data, OPTIONS)[INDEX_FILE]["trending"] == []


def test_trending_ties_break_by_recent_mentions_then_key():
    data = _corpus({"zeta": ("maker", 4, 0), "alpha": ("maker", 4, 0), "big": ("maker", 6, 1), "filler": ("model", 40, 40)})
    order = build_files(data, OPTIONS)[INDEX_FILE]["trending"]
    assert order.index("maker--alpha") < order.index("maker--zeta")


def test_concept_of_the_week_is_the_reviewed_entity_with_the_most_recent_items():
    data, voice, completion, maker = two_tasks()
    files = build_files(data, OPTIONS)
    concept = files[INDEX_FILE]["conceptOfTheWeek"]
    assert concept == {
        "key": "task--voice-cloning",
        "name": "Voice cloning",
        "href": None,
        "lede": "Copying a voice from a short sample.",
        "editedBy": {"actor": "human", "name": "Ada", "on": "2026-10-13"},
        "itemCount": 18,
        "makerCount": 1,
    }
    without_review = KnowledgeData(
        items=data.items,
        nodes=tuple(
            EntityNode(**{**node.__dict__, "description_state": "draft"}) if node.lineage_id == voice.lineage_id else node
            for node in data.nodes
        ),
        links=data.links,
    )
    assert build_files(without_review, OPTIONS)[INDEX_FILE]["conceptOfTheWeek"] is None


def test_description_edited_by_ai_counts_for_concept_of_the_week_and_says_so():
    data, voice, *_ = two_tasks()
    edited = EntityNode(**{**voice.__dict__, "description_state": "ai_edited", "description_edited_by": AI})
    files = build_files(KnowledgeData(items=data.items, nodes=(edited, *data.nodes[1:]), links=data.links), OPTIONS)
    assert files[INDEX_FILE]["conceptOfTheWeek"]["editedBy"] == {"actor": "ai", "name": None, "on": "2026-10-12"}
    assert files[entity_file("task--voice-cloning")]["description"] == {"state": "ai_edited", "editedBy": {"actor": "ai", "name": None, "on": "2026-10-12"}}


def test_a_draft_description_has_no_editor_and_is_not_the_concept_of_the_week():
    data, voice, *_ = two_tasks()
    draft = EntityNode(**{**voice.__dict__, "description_state": "draft", "description_edited_by": None})
    files = build_files(KnowledgeData(items=data.items, nodes=(draft, *data.nodes[1:]), links=data.links), OPTIONS)
    assert files[INDEX_FILE]["conceptOfTheWeek"] is None
    assert files[entity_file("task--voice-cloning")]["description"] == {"state": "draft", "editedBy": None}


def test_a_cluster_says_who_accepted_it_and_the_new_rule_uses_the_earliest_publication_not_the_run_date():
    old_story = cluster("old", event="new", earliest_published_at="2026-08-01", accepted_by=AI, weekly_series=weekly(0, 0, 0, 0, 0, 0, 2, 3))
    fresh = cluster("fresh", event="new", earliest_published_at="2026-10-12", accepted_by=ADA, weekly_series=weekly(0, 0, 0, 0, 0, 0, 2, 3))
    rows = {row["uid"]: row for row in build_files(KnowledgeData(items=(item("a", 0),), clusters=(old_story, fresh)), OPTIONS)[CLUSTERS_FILE]["clusters"]}
    assert rows["old"]["state"] is None and rows["fresh"]["state"] == "new"
    assert rows["old"]["acceptedBy"] == {"actor": "ai", "name": None, "on": "2026-10-12"}
    assert rows["fresh"]["acceptedBy"] == {"actor": "human", "name": "Ada", "on": "2026-10-13"}


def test_an_unnamed_cluster_does_not_claim_an_acceptance():
    shown = build_files(
        KnowledgeData(items=(item("a", 0),), clusters=(cluster("p", accepted=False, name=None, accepted_by=AI, member_item_keys=("lineage-a",)),)),
        SnapshotOptions(as_of=AS_OF, unaccepted_clusters="unnamed"),
    )[CLUSTERS_FILE]
    assert shown["clusters"][0]["acceptedBy"] is None


def test_neighbours_are_confirmed_relations_and_shared_items():
    data, voice, completion, maker = two_tasks()
    related = KnowledgeData(
        items=data.items,
        nodes=data.nodes,
        links=data.links,
        relations=(
            NodeRelation(voice.lineage_id, completion.lineage_id, "related_to", confirmed=True),
            NodeRelation(voice.lineage_id, maker.lineage_id, "related_to", confirmed=False),
        ),
    )
    entity = build_files(related, OPTIONS)[entity_file("task--voice-cloning")]
    assert entity["neighbours"] == [
        {"relation": "mentioned_with", "key": "maker--some-lab", "name": "Some Lab", "kind": "maker", "weight": 2},
        {"relation": "related_to", "key": "task--code-completion", "name": "Code completion", "kind": "task", "weight": 0},
    ]
    assert [row["reason"] for row in entity["relatedItems"]] == ["task--voice-cloning"] * 12
    assert entity["relatedItems"][0]["publishedAt"] >= entity["relatedItems"][-1]["publishedAt"]


def test_description_state_is_reported_without_the_text():
    data, _voice, _completion, _maker = two_tasks()
    entity = build_files(data, OPTIONS)[entity_file("task--voice-cloning")]
    assert entity["description"] == {"state": "reviewed", "editedBy": {"actor": "human", "name": "Ada", "on": "2026-10-13"}}
    assert entity["acceptedBy"] == {"actor": "ai", "name": None, "on": "2026-10-12"}
    other = build_files(data, OPTIONS)[entity_file("task--code-completion")]
    assert other["description"] == {"state": "none", "editedBy": None} and other["acceptedBy"] is None


def test_beats_count_member_items_per_week():
    data, voice, _completion, _maker = two_tasks()
    beat = Beat(key="decision-models", name="Decision models", href="/topics/decision-models/", item_keys=frozenset({"lineage-v0", "lineage-v1", "lineage-p0", "lineage-gone"}))
    files = build_files(KnowledgeData(items=data.items, nodes=data.nodes, links=data.links, beats=(beat,)), OPTIONS)
    row = files[INDEX_FILE]["beats"][0]
    assert row["itemCount"] == 3 and sum(row["series8"]) == 3
    assert files[INDEX_FILE]["topicCount"] == 1


def test_a_beat_lists_its_top_entities_by_the_beats_items_and_a_cluster_lists_the_beats_it_overlaps():
    data, voice, completion, maker = two_tasks()
    beat = Beat(key="voices", name="Voices", href=None, item_keys=frozenset({"lineage-v0", "lineage-v1", "lineage-v2", "lineage-c0", "lineage-gone"}))
    other = Beat(key="elsewhere", name="Elsewhere", href=None, item_keys=frozenset({"lineage-p0"}))
    unrelated = Beat(key="unrelated", name="Unrelated", href=None, item_keys=frozenset({"lineage-gone"}))
    clusters = (
        cluster("c", member_item_keys=("lineage-v0", "lineage-p0"), weekly_series=weekly(1, 1, 1, 1, 1, 1, 1, 1)),
        cluster("d", member_item_keys=(), member_count=1, weekly_series=weekly(1, 1, 1, 1, 1, 1, 1, 1)),
    )
    files = build_files(KnowledgeData(items=data.items, nodes=data.nodes, links=data.links, beats=(beat, other, unrelated), clusters=clusters), OPTIONS)
    rows = {row["key"]: row for row in files[INDEX_FILE]["beats"]}
    assert rows["voices"]["topEntities"] == ["task--voice-cloning", "maker--some-lab", "task--code-completion"]
    assert rows["elsewhere"]["topEntities"] == ["task--voice-cloning"] and rows["unrelated"]["topEntities"] == []
    by_uid = {row["uid"]: row for row in files[CLUSTERS_FILE]["clusters"]}
    assert by_uid["c"]["beats"] == ["elsewhere", "voices"] and by_uid["d"]["beats"] == []


def test_a_beat_keeps_at_most_twelve_top_entities():
    nodes = tuple(node("tool", f"Tool {index:02d}") for index in range(15))
    items = (item("a", 0),)
    data = KnowledgeData(items=items, nodes=nodes, links=tuple(link("a", one) for one in nodes), beats=(Beat("b", "B", None, frozenset({"lineage-a"})),))
    top = build_files(data, OPTIONS)[INDEX_FILE]["beats"][0]["topEntities"]
    assert top == [f"tool--tool-{index:02d}" for index in range(12)]


def test_an_entity_carries_its_public_aliases_in_the_index():
    named = node("task", "Safe task", aliases=("secret@example.org", "Fine alias"))
    data = KnowledgeData(items=(item("a", 0),), nodes=(named,), links=(link("a", named),))
    assert build_files(data, OPTIONS)[INDEX_FILE]["entities"][0]["aliases"] == ["Fine alias"]


def test_no_beats_without_a_beat_source():
    data, *_ = two_tasks()
    assert build_files(data, OPTIONS)[INDEX_FILE]["beats"] == []


def cluster(uid: str, **overrides) -> Cluster:
    values = {
        "uid": uid,
        "accepted": True,
        "name": f"Cluster {uid}",
        "event": "continued",
        "top_terms": ("agent", "tool"),
        "weekly_series": {},
        "earliest_published_at": "2026-06-01",
        "member_item_keys": ("lineage-a", "lineage-b"),
        "member_count": 2,
        "run_id": "run-1",
        "run_as_of": "2026-10-19",
    }
    values.update(overrides)
    return Cluster(**values)


def weekly(*counts: int) -> dict[str, int]:
    last = len(counts)
    return {week_label(MONDAY_WEEK - (last - 1 - index)): count for index, count in enumerate(counts)}


def test_clusters_hide_unaccepted_by_default_and_label_state_by_the_change_rule():
    data = KnowledgeData(
        items=(item("a", 0), item("b", 1)),
        clusters=(
            cluster("growing", weekly_series=weekly(5, 5, 5, 5, 8, 8, 8, 8)),
            cluster("cooling", weekly_series=weekly(8, 8, 8, 8, 5, 5, 5, 5)),
            cluster("flat", weekly_series=weekly(5, 5, 5, 5, 5, 5, 5, 5)),
            cluster("young", earliest_published_at="2026-10-05", event="continued", weekly_series=weekly(0, 0, 0, 0, 0, 3, 4, 5)),
            cluster("fresh", earliest_published_at="2026-10-12", event="new", weekly_series=weekly(0, 0, 0, 0, 0, 0, 2, 3)),
            cluster("proposed", accepted=False, name=None),
        ),
    )
    clusters = build_files(data, OPTIONS)[CLUSTERS_FILE]
    states = {row["uid"]: row["state"] for row in clusters["clusters"]}
    assert states == {"growing": "growing", "cooling": "cooling", "flat": None, "young": None, "fresh": "new"}
    assert clusters["unacceptedClusters"] == "hide" and clusters["runId"] == "run-1"
    grown = next(row for row in clusters["clusters"] if row["uid"] == "growing")
    assert grown["series8"] == [5, 5, 5, 5, 8, 8, 8, 8] and grown["weeksOfData"] > 8 and grown["itemCount"] == 2


def test_unnamed_mode_shows_proposed_clusters_without_a_name():
    data = KnowledgeData(items=(item("a", 0),), clusters=(cluster("proposed", accepted=False, name=None, member_item_keys=("lineage-a",)),))
    shown = build_files(data, SnapshotOptions(as_of=AS_OF, unaccepted_clusters="unnamed"))[CLUSTERS_FILE]
    assert [(row["uid"], row["name"], row["href"]) for row in shown["clusters"]] == [("proposed", None, None)]


def test_cluster_items_that_are_not_published_do_not_count():
    data = KnowledgeData(items=(item("a", 0),), clusters=(cluster("x", member_item_keys=("lineage-a", "lineage-secret")),))
    assert build_files(data, OPTIONS)[CLUSTERS_FILE]["clusters"][0]["itemCount"] == 1


def test_same_records_and_as_of_give_byte_identical_output():
    data, *_ = two_tasks()
    first = {key: encoded(value) for key, value in build_files(data, OPTIONS).items()}
    second = {key: encoded(value) for key, value in build_files(data, OPTIONS).items()}
    assert first == second
    assert b"generatedAt" not in b"".join(first.values())


def test_public_safe_output_has_no_email_or_private_text():
    leaky = node("maker", "Ann <ann@example.org>")
    named = node("task", "Safe task", aliases=("secret@example.org", "Fine alias"), description="Mail ann@example.org", description_state="reviewed", description_edited_by=ADA)
    data = KnowledgeData(
        items=(item("a", 0, title="Contact ann@example.org"), item("b", 0, title="A clean title")),
        nodes=(leaky, named),
        links=(link("a", leaky), link("a", named), link("b", named)),
    )
    files = build_files(data, OPTIONS)
    text = "\n".join(encoded(value).decode() for value in files.values())
    assert "@" not in text
    assert files[entity_file("task--safe-task")]["aliases"] == ["Fine alias"]
    assert [row["title"] for row in files[entity_file("task--safe-task")]["relatedItems"]] == ["A clean title"]
    assert files[INDEX_FILE]["conceptOfTheWeek"] is None


INDEX_FIELDS = {"schemaVersion", "asOf", "entityCount", "topicCount", "kinds", "beats", "entities", "trending", "conceptOfTheWeek"}
KIND_FIELDS = {"key", "label", "count"}
BEAT_FIELDS = {"key", "name", "href", "itemCount", "series8", "topEntities"}
INDEX_ENTITY_FIELDS = {"key", "kind", "name", "aliases", "href", "acceptedBy", "itemCount", "weeksOfHistory", "series8", "series26", "dateBasis", "seriesWeekly", "seriesWeeklyStart", "change", "isNew"}
CHANGE_FIELDS = {"last4", "prior4", "percent"}
CONCEPT_FIELDS = {"key", "name", "href", "lede", "editedBy", "itemCount", "makerCount"}
ACTOR_FIELDS = {"actor", "name", "on"}
ENTITY_FIELDS = {
    "schemaVersion", "key", "kind", "name", "aliases", "acceptedBy", "description", "href", "itemCount", "weeksOfHistory",
    "series8", "series26", "dateBasis", "change", "neighbours", "relatedItems",
}
DESCRIPTION_FIELDS = {"state", "editedBy"}
NEIGHBOUR_FIELDS = {"relation", "key", "name", "kind", "weight"}
RELATED_FIELDS = {"title", "url", "publishedAt", "reason"}
CLUSTERS_FIELDS = {"schemaVersion", "asOf", "runId", "unacceptedClusters", "clusters"}
CLUSTER_FIELDS = {"uid", "beats", "name", "acceptedBy", "state", "itemCount", "topTerms", "series8", "weeksOfData", "href"}


def test_guest_surface_pins_the_exact_field_set_of_every_file():
    data, voice, completion, maker = two_tasks()
    data = KnowledgeData(
        items=data.items,
        nodes=data.nodes,
        links=data.links,
        relations=(NodeRelation(voice.lineage_id, completion.lineage_id, "related_to", confirmed=True),),
        clusters=(cluster("c", member_item_keys=("lineage-v0",), accepted_by=AI, weekly_series=weekly(1, 1, 1, 1, 1, 1, 1, 1)),),
        beats=(Beat("b", "B", None, frozenset({"lineage-v0"})),),
    )
    files = build_files(data, OPTIONS)
    index = files[INDEX_FILE]
    assert set(index) == INDEX_FIELDS
    assert all(set(row) == KIND_FIELDS for row in index["kinds"])
    assert all(set(row) == BEAT_FIELDS for row in index["beats"])
    assert all(set(row) == INDEX_ENTITY_FIELDS and set(row["change"]) == CHANGE_FIELDS for row in index["entities"])
    assert set(index["conceptOfTheWeek"]) == CONCEPT_FIELDS and set(index["conceptOfTheWeek"]["editedBy"]) == ACTOR_FIELDS
    assert any(row["acceptedBy"] and set(row["acceptedBy"]) == ACTOR_FIELDS for row in index["entities"])
    entity_files = [value for key, value in files.items() if key.startswith("_data/knowledge/entities/")]
    assert len(entity_files) == 3
    for entity in entity_files:
        assert set(entity) == ENTITY_FIELDS
        assert set(entity["description"]) == DESCRIPTION_FIELDS
        assert entity["acceptedBy"] is None or set(entity["acceptedBy"]) == ACTOR_FIELDS
        assert entity["description"]["editedBy"] is None or set(entity["description"]["editedBy"]) == ACTOR_FIELDS
        assert set(entity["change"]) == CHANGE_FIELDS
        assert all(set(row) == NEIGHBOUR_FIELDS for row in entity["neighbours"])
        assert all(set(row) == RELATED_FIELDS for row in entity["relatedItems"])
    assert sum(len(entity["neighbours"]) for entity in entity_files) > 0
    clusters = files[CLUSTERS_FILE]
    assert set(clusters) == CLUSTERS_FIELDS
    assert clusters["clusters"] and all(set(row) == CLUSTER_FIELDS for row in clusters["clusters"])
    assert all(set(row["acceptedBy"]) == ACTOR_FIELDS for row in clusters["clusters"])
    history = files[CLUSTERS_HISTORY_FILE]
    assert set(history) == {"schemaVersion", "asOf", "weeks"} and len(history["weeks"]) == 1
    assert set(history["weeks"][0]) == {"asOf", "runId", "clusters", "events"}
    assert all(set(row) == {"uid", "label", "itemCount"} for row in history["weeks"][0]["clusters"])
    assert set(files) == {INDEX_FILE, CLUSTERS_FILE, CLUSTERS_HISTORY_FILE, *(f"_data/knowledge/entities/{key}.json" for key in ("task--voice-cloning", "task--code-completion", "maker--some-lab"))}
    json.dumps(files)


def test_only_clusters_of_the_latest_run_are_published():
    data = KnowledgeData(
        items=(item("a", 0),),
        clusters=(
            cluster("old", member_item_keys=("lineage-a",), run_id="run-1", run_as_of="2026-10-12"),
            cluster("current", member_item_keys=("lineage-a",), run_id="run-2", run_as_of="2026-10-19"),
        ),
    )
    clusters = build_files(data, OPTIONS)[CLUSTERS_FILE]
    assert [row["uid"] for row in clusters["clusters"]] == ["current"] and clusters["runId"] == "run-2"


def test_the_snapshot_reports_the_vocabulary_form_of_a_kind_even_for_a_node_stored_with_hyphens():
    family = node("model-family", "Tern", accepted_by=AI)
    data = KnowledgeData(items=(item("a", 0),), nodes=(family,), links=(link("a", family),))
    index = build_files(data, OPTIONS)[INDEX_FILE]
    assert [row["kind"] for row in index["entities"]] == ["model_family"]
    assert [row["key"] for row in index["kinds"]] == ["model_family"]


def test_concept_kinds_restrict_the_concept_of_the_week_to_those_kinds():
    data, *_ = two_tasks()
    assert build_files(data, dataclasses.replace(OPTIONS, concept_kinds=("maker",)))[INDEX_FILE]["conceptOfTheWeek"] is None
    assert build_files(data, dataclasses.replace(OPTIONS, concept_kinds=("task", "maker")))[INDEX_FILE]["conceptOfTheWeek"]["key"] == "task--voice-cloning"


def test_model_and_model_family_are_two_kinds_with_two_labels():
    model = node("model", "Tern 3", accepted_by=AI)
    family = node("model-family", "Tern", accepted_by=AI)
    data = KnowledgeData(items=(item("a", 0),), nodes=(model, family), links=(link("a", model), link("a", family)))
    index = build_files(data, OPTIONS)[INDEX_FILE]
    assert {row["key"]: row["label"] for row in index["kinds"]} == {"model": "Model", "model_family": "Model Family"}
    assert {row["key"]: row["kind"] for row in index["entities"]} == {"model--tern-3": "model", "model-family--tern": "model_family"}


def test_a_member_of_relation_links_a_model_to_its_family_and_an_unrelated_model_stays_unrelated():
    model = node("model", "Tern 3", accepted_by=AI)
    family = node("model-family", "Tern", accepted_by=AI)
    lone = node("model", "Lone 1", accepted_by=AI)
    data = KnowledgeData(
        items=(item("a", 0), item("b", 0)),
        nodes=(model, family, lone),
        links=(link("a", model), link("a", family), link("b", lone)),
        relations=(NodeRelation(model.lineage_id, family.lineage_id, "member_of", confirmed=True),),
    )
    files = build_files(data, OPTIONS)

    def explicit(key):
        return [(row["relation"], row["key"]) for row in files[entity_file(key)]["neighbours"] if row["relation"] == "member_of"]

    assert explicit("model--tern-3") == [("member_of", "model-family--tern")]
    assert explicit("model-family--tern") == [("member_of", "model--tern-3")]
    assert explicit("model--lone-1") == []


# -- monitor records (the Hub): data that counts and has no page ---------------------------------------------------------
def record(name: str, offset: int, **overrides) -> PublishedItem:
    return PublishedItem(
        key=f"lineage-ref-{name}",
        item_id=f"reference-{name}",
        title=overrides.pop("title", f"org/{name}"),
        url=f"https://huggingface.co/org/{name}",
        published_at=overrides.pop("published_at", published_in_week(offset, name)),
        kind="monitor-record",
        summary=f"org/{name} is a text-generation model by org, released 2026-10-12.",
        source="huggingface",
        **overrides,
    )


def record_link(name: str, target: EntityNode) -> ItemLink:
    return ItemLink(item_key=f"lineage-ref-{name}", node_lineage_id=target.lineage_id, confirmed=True, source="monitor")


def hub_data():
    licence = node("licence", "Apache-2.0")
    maker = node("maker", "Org")
    lone = node("model", "org/lone")
    base = node("model", "org/base")
    tuned = node("model", "org/tuned")
    items = [item("story", 0), record("a", 0), record("b", 1), record("lone", 1), record("base", 3), record("tuned", 0)]
    links = [link("story", licence)]
    links += [record_link(name, licence) for name in ("a", "b")] + [record_link(name, maker) for name in ("a", "b")]
    links += [record_link("lone", lone), record_link("base", base), record_link("tuned", tuned)]
    relation = NodeRelation(tuned.lineage_id, base.lineage_id, "built_on", True, subtype="finetune", evidence="https://huggingface.co/org/tuned", provenance="from the Hugging Face Hub")
    return KnowledgeData(items=tuple(items), nodes=(licence, maker, lone, base, tuned), links=tuple(links), relations=(relation,)), licence, maker


def test_records_count_in_an_entity_next_to_site_items_and_are_listed_apart():
    data, licence, _maker = hub_data()
    files = build_files(data, SnapshotOptions(as_of=AS_OF, entity_href_template="/wiki/{slug}/"))
    entry = next(row for row in files[INDEX_FILE]["entities"] if row["key"] == "licence--apache-2-0")
    detail = files[entity_file("licence--apache-2-0")]
    assert (entry["itemCount"], entry["recordCount"]) == (3, 2)
    assert detail["recordCount"] == 2 and sum(detail["series8"]) == 3
    assert [row["url"] for row in detail["relatedItems"]] == ["/items/story/"]  # a record is never listed as an item
    assert [row["title"] for row in detail["relatedRecords"]] == ["org/a", "org/b"]
    first = detail["relatedRecords"][0]
    assert first["url"] == "https://huggingface.co/org/a" and first["provenance"] == "from the Hugging Face Hub" and first["summary"].startswith("org/a is a text-generation model")
    assert entry["href"] == "/wiki/licence-apache-2-0/"  # a site item mentions it, so it has a page


def test_an_entity_only_records_mention_has_no_page_link_and_needs_support_to_appear():
    data, _licence, _maker = hub_data()
    files = build_files(data, SnapshotOptions(as_of=AS_OF, entity_href_template="/wiki/{slug}/"))
    by_key = {row["key"]: row for row in files[INDEX_FILE]["entities"]}
    assert by_key["maker--org"]["href"] is None and by_key["maker--org"]["recordCount"] == 2
    assert "model--org-lone" not in by_key  # one record and no relation: not worth an entity on the map
    assert {"model--org-base", "model--org-tuned"} <= set(by_key)  # a built-on relation puts both ends on the map
    assert by_key["model--org-tuned"]["href"] is None


def test_a_built_on_relation_keeps_its_subtype_evidence_and_provenance():
    data, _licence, _maker = hub_data()
    files = build_files(data, SnapshotOptions(as_of=AS_OF))
    tuned = files[entity_file("model--org-tuned")]
    [neighbour] = [row for row in tuned["neighbours"] if row["relation"] == "built_on"]
    assert neighbour["key"] == "model--org-base"
    assert (neighbour["subtype"], neighbour["evidence"], neighbour["provenance"]) == ("finetune", "https://huggingface.co/org/tuned", "from the Hugging Face Hub")


def test_records_have_weekly_history_from_their_source_date():
    data, _licence, _maker = hub_data()
    files = build_files(data, SnapshotOptions(as_of=AS_OF))
    detail = files[entity_file("licence--apache-2-0")]
    assert detail["series8"][-1] == 2 and detail["series8"][-2] == 1  # the story and record a in this week, record b in the week before


def test_a_cluster_counts_its_records_and_says_how_many():
    data, _licence, _maker = hub_data()
    cluster = Cluster(
        uid="cl-1", accepted=True, name="Open models", event="new", top_terms=("open",), weekly_series={week_label(MONDAY_WEEK): 3},
        earliest_published_at=published_in_week(0, "a"), member_item_keys=("lineage-story", "lineage-ref-a", "lineage-ref-b"), member_count=3, run_id="r1",
        accepted_by=AI,
    )
    files = build_files(dataclasses.replace(data, clusters=(cluster,)), SnapshotOptions(as_of=AS_OF))
    [row] = files[CLUSTERS_FILE]["clusters"]
    assert (row["itemCount"], row["recordCount"]) == (3, 2)


def test_a_snapshot_without_records_has_none_of_the_record_fields():
    data, _voice, _completion, _maker = two_tasks()
    files = build_files(data, OPTIONS)
    text = json.dumps(files)
    assert "recordCount" not in text and "relatedRecords" not in text


def test_a_concept_series_counts_each_item_in_its_publication_week_and_declares_that_basis():
    voice = node("task", "Voice cloning", accepted_by=AI)
    items = [item("early", offset=6), item("middle", offset=3), item("latest", offset=0)]
    data = KnowledgeData(items=tuple(items), nodes=(voice,), links=tuple(link(each.key.removeprefix("lineage-"), voice) for each in items))
    files = build_files(data, OPTIONS)
    entity = files[entity_file("task--voice-cloning")]
    assert entity["series8"] == [0, 1, 0, 0, 1, 0, 0, 1]
    assert entity["dateBasis"] == "publication"
    assert next(row for row in files[INDEX_FILE]["entities"] if row["key"] == "task--voice-cloning")["dateBasis"] == "publication"
