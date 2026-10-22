from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from papyrus_content.projection.writers import LocalDirectoryWriter

from . import commands
from .builder import CLUSTERS_FILE, INDEX_FILE
from .cluster_records import cluster_proposal_id, decode_metadata
from .actors import decode_review
from .loaders import description_state
from .weeks import week_label, week_number


class FakeClient:
    def __init__(self, published_rows):
        self.published_rows = published_rows
        self.rows: dict[str, dict[str, dict]] = {}
        self.writes: list[tuple[str, str, str]] = []

    def list_published_item_summaries(self):
        return copy.deepcopy(self.published_rows)

    def list_records(self, model):
        return copy.deepcopy(list(self.rows.get(model, {}).values()))

    def get_record(self, model, record_id):
        row = self.rows.get(model, {}).get(record_id)
        return copy.deepcopy(row)

    def create_record(self, model, payload):
        self.writes.append(("create", model, payload["id"]))
        self.rows.setdefault(model, {})[payload["id"]] = copy.deepcopy(payload)

    def update_record(self, model, payload):
        self.writes.append(("update", model, payload["id"]))
        self.rows[model][payload["id"]].update(copy.deepcopy(payload))

    def upsert(self, model, payload):
        if payload["id"] in self.rows.get(model, {}):
            self.update_record(model, payload)
        else:
            self.create_record(model, payload)

    def _relations_by(self, field, state):
        return copy.deepcopy([row for row in self.rows.get("SemanticRelation", {}).values() if row.get(field) == state])

    def list_semantic_relations_by_object_state(self, state):
        return self._relations_by("objectStateKey", state)

    def list_semantic_relations_by_subject_state(self, state):
        return self._relations_by("subjectStateKey", state)


def published_row(name: str, published_at: str, entities=(), tags=()):
    front_matter = {"title": name, "entities": [{"kind": kind, "name": entity} for kind, entity in entities], "tags": list(tags)}
    return {
        "id": f"published-lineage-{name}",
        "sourceItemId": f"item-{name}",
        "itemLineageId": f"lineage-{name}",
        "versionNumber": 1,
        "type": "article",
        "status": "published",
        "slug": name,
        "section": "posts",
        "title": name.title(),
        "aliases": [],
        "publishedAt": published_at,
        "metadata": json.dumps({"projection": {"frontMatter": front_matter, "pageTitle": name.title()}}),
    }


class Projector:
    policy = None

    def item_page_paths(self, summary):
        return (f"{summary.section}/{summary.slug}/index.html",)


@pytest.fixture
def client(monkeypatch):
    rows = [
        published_row("alpha", "2026-10-13T08:00:00Z", entities=[("task", "Voice cloning"), ("maker", "Some Lab")], tags=["decision-models"]),
        published_row("beta", "2026-10-06T08:00:00Z", entities=[("task", "voice  CLONING")]),
        published_row("gamma", "2026-09-01T08:00:00Z", entities=[("task", "Code completion")]),
        published_row("draft-like", "2026-10-13T08:00:00Z"),
    ]
    fake = FakeClient(rows)
    monkeypatch.setattr(commands, "create_authoring_client", lambda *args, **kwargs: (fake, {}))
    return fake


def run(function, *flags) -> None:
    function(list(flags))


def today_utc() -> str:
    return commands.today()


def tern_marks(row) -> dict:
    marks = decode_review(row["changeReason"])
    return {"acceptedBy": marks.accepted_by.to_dict() if marks.accepted_by else None}


def test_publish_run_dry_run_writes_nothing_then_apply_is_idempotent(client, capsys):
    run(commands.knowledge_publish_run)
    out = capsys.readouterr().out
    assert "dry-run" in out and "nodesCreated\t3" in out and "linksFrontMatter\t4" in out
    assert client.writes == []

    run(commands.knowledge_publish_run, "--apply")
    capsys.readouterr()
    assert len([write for write in client.writes if write[1] == "SemanticNode"]) == 3
    assert len([write for write in client.writes if write[1] == "SemanticRelation"]) == 4
    nodes = {row["nodeKey"]: row for row in client.rows["SemanticNode"].values()}
    assert sorted(nodes) == ["maker--some-lab", "task--code-completion", "task--voice-cloning"]
    assert all(row["status"] == "accepted" for row in nodes.values())

    before = len(client.writes)
    run(commands.knowledge_publish_run, "--apply", "--json")
    plan = json.loads(capsys.readouterr().out)
    assert set(plan["changes"]) <= {"SemanticNode:noop", "SemanticRelation:noop"}
    assert len(client.writes) == before


def test_front_matter_links_are_confirmed_and_resolve_by_case_and_space(client, capsys):
    run(commands.knowledge_publish_run, "--apply")
    relations = list(client.rows["SemanticRelation"].values())
    voice = next(row for row in client.rows["SemanticNode"].values() if row["nodeKey"] == "task--voice-cloning")
    to_voice = [row for row in relations if row["objectId"] == voice["id"]]
    assert {row["subjectLineageId"] for row in to_voice} == {"lineage-alpha", "lineage-beta"}
    for row in to_voice:
        assert (row["predicate"], row["subjectKind"], row["objectKind"]) == ("mentions", "item", "semanticNode")
        assert json.loads(row["metadata"]) == {"confirmed": True, "kind": "knowledge.item_mention", "linkSource": "front_matter"}


def test_removing_an_entity_from_front_matter_supersedes_its_link(client, capsys):
    run(commands.knowledge_publish_run, "--apply")
    capsys.readouterr()
    client.published_rows[1] = published_row("beta", "2026-10-06T08:00:00Z")
    run(commands.knowledge_publish_run, "--apply")
    states = {row["subjectLineageId"]: row["relationState"] for row in client.rows["SemanticRelation"].values() if row["objectId"].endswith("voice-cloning-v1")}
    assert states == {"lineage-alpha": "current", "lineage-beta": "superseded"}


def test_a_generated_node_named_in_front_matter_becomes_accepted_and_a_rejected_one_is_left_alone(client, capsys):
    generated = {"id": "semantic-node-graph-1", "lineageId": "semantic-node-graph-1", "versionNumber": 1, "versionState": "current", "nodeKey": "x:y:z", "nodeKind": "task", "displayName": "Code Completion", "aliases": [], "status": "generated"}
    rejected = {**generated, "id": "semantic-node-graph-2", "lineageId": "semantic-node-graph-2", "displayName": "Some Lab", "nodeKind": "maker", "status": "rejected"}
    client.rows["SemanticNode"] = {row["id"]: row for row in (generated, rejected)}
    run(commands.knowledge_publish_run, "--apply")
    out = capsys.readouterr().out
    assert client.rows["SemanticNode"]["semantic-node-graph-1"]["status"] == "accepted"
    assert client.rows["SemanticNode"]["semantic-node-graph-2"]["status"] == "rejected"
    assert "rejected entity" in out
    assert not any(row["objectId"] == "semantic-node-graph-2" for row in client.rows["SemanticRelation"].values())


def write_run_directory(directory: Path, *, run_id="run-2026-10-19") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    weeks = [week_label(week_number(date(2026, 10, 19)) - offset) for offset in range(7, -1, -1)]
    identity_cluster = {"successor_uids": [], "topic_id": 0, "predecessor_uids": []}
    (directory / "identity.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "analysis_id": "topic-identity",
                "run_id": run_id,
                "previous_run_id": None,
                "generated_at": "2026-10-19T06:00:00Z",
                "threshold": 0.5,
                "trends_snapshot_id": "trends-1",
                "series_iso_weeks": weeks,
                "document_count": 3,
                "outlier_document_count": 0,
                "cluster_count": 2,
                "event_counts": {"new": 1, "continued": 1},
                "clusters": [
                    {**identity_cluster, "uid": "tc-1", "event": "new", "label": "0_voice_clone", "member_item_count": 2, "member_item_ids": ["item-alpha", "item-beta"],
                     "top_terms": ["voice", "clone", "audio", "tts"], "first_seen": "2026-10-19", "earliest_published_at": "2026-10-06T08:00:00Z", "weekly_series": [0, 0, 0, 0, 0, 0, 1, 1]},
                    {**identity_cluster, "uid": "tc-2", "topic_id": 1, "event": "continued", "label": "1_code", "member_item_count": 1, "member_item_ids": ["item-gamma"],
                     "top_terms": ["code"], "first_seen": "2026-08-01", "earliest_published_at": "2026-09-01T08:00:00Z", "weekly_series": [1, 1, 1, 1, 1, 1, 1, 1]},
                ],
                "gone": [],
            }
        ),
        encoding="utf-8",
    )
    (directory / "trends.json").write_text(
        json.dumps(
            {
                "analysis_id": "topic-governance",
                "snapshot_id": "trends-1",
                "weekly_bins": {
                    "bin": "weekly", "weeks": 8, "as_of": "2026-10-19", "iso_weeks": weeks, "week_starts": [], "undated_items": 0,
                    "discovered_topics": [
                        {"topic_id": 0, "label": "voice", "counts": [0, 0, 0, 0, 0, 0, 1, 1]},
                        {"topic_id": 1, "label": "code", "counts": [2, 2, 2, 2, 2, 2, 2, 2]},
                    ],
                    "canonical_topics": [],
                },
            }
        ),
        encoding="utf-8",
    )
    (directory / "entities.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "vocabulary": {"publication": "shipped", "version": 1, "hash": "abc"},
                "backend": {"id": "gliner2-hybrid", "model": "gliner2-base", "revision": "1", "threshold": 0.7},
                "summary": {},
                "items": [
                    {
                        "item_id": "item-alpha",
                        "entities": [
                            {"id": "e1", "kind": "model", "text": "Tern 3", "state": "proposed", "entity_key": None, "span": {"start": 4, "end": 10}, "score": 0.9},
                            {"id": "e2", "kind": "model", "text": "tern  3", "state": "proposed", "entity_key": None, "span": {"start": 40, "end": 47}, "score": 0.8},
                            {"id": "e3", "kind": "maker", "text": "Some Lab", "state": "resolved", "entity_key": "maker--some-lab", "span": {"start": 0, "end": 8}, "score": 1.0},
                        ],
                        "relations": [{"id": "r1", "type": "made_by", "subject": "e1", "object": "e3", "state": "proposed", "span": {"start": 0, "end": 20}, "score": 0.7}],
                    },
                    {
                        "item_id": "item-beta",
                        "entities": [{"id": "e1", "kind": "model", "text": "Tern 3", "state": "resolved", "entity_key": "model--tern-3", "span": {"start": 1, "end": 7}, "score": 1.0}],
                        "relations": [],
                    },
                    {"item_id": "item-unknown", "entities": [{"id": "e1", "kind": "model", "text": "Ghost", "state": "proposed", "entity_key": None, "span": None, "score": 0.5}], "relations": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    return directory


def run_flags(directory: Path) -> tuple[str, ...]:
    return ("--identity", str(directory / "identity.json"), "--trends", str(directory / "trends.json"), "--entities", str(directory / "entities.json"))


def test_publish_run_imports_clusters_and_extractor_entities_and_is_idempotent(client, tmp_path, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, *run_flags(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply")
    out = capsys.readouterr().out
    assert "clustersNew\t2" in out and "extractorItemsNotPublished\t1" in out
    proposals = client.rows["SteeringProposal"]
    proposal = proposals[cluster_proposal_id("tc-1")]
    assert (proposal["proposalKind"], proposal["status"], proposal["graphEntityId"], proposal["categorySetId"]) == ("topic_cluster", "proposed", "tc-1", "set-1")
    assert proposal["evidenceItemIds"] == ["item-alpha", "item-beta"]
    metadata = decode_metadata(proposal["summary"])
    assert metadata["event"] == "new" and metadata["topTerms"] == ["voice", "clone", "audio", "tts"] and sum(metadata["weeklySeries"].values()) == 2
    generated = [row for row in client.rows["SemanticNode"].values() if row["status"] == "generated"]
    assert [row["nodeKey"] for row in generated] == ["model--tern-3"]
    extractor_links = [row for row in client.rows["SemanticRelation"].values() if json.loads(row["metadata"])["linkSource"] == "extractor"]
    assert sorted(row["subjectLineageId"] for row in extractor_links) == ["lineage-alpha", "lineage-beta"]
    assert all(json.loads(row["metadata"])["confirmed"] is False for row in extractor_links)
    some_lab_links = [row for row in client.rows["SemanticRelation"].values() if row["subjectLineageId"] == "lineage-alpha" and row["objectId"].endswith("some-lab-v1")]
    assert len(some_lab_links) == 1 and json.loads(some_lab_links[0]["metadata"])["confirmed"] is True

    before = len(client.writes)
    run(commands.knowledge_publish_run, *run_flags(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply", "--json")
    plan = json.loads(capsys.readouterr().out)
    assert {key.split(":")[1] for key in plan["changes"]} == {"noop"}
    assert len(client.writes) == before


def test_a_continued_cluster_keeps_its_status_and_name(client, tmp_path, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    flags = (*run_flags(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply")
    run(commands.knowledge_publish_run, *flags)
    pid = cluster_proposal_id("tc-1")
    client.rows["SteeringProposal"][pid].update({"status": "accepted", "displayName": "Voice cloning", "reviewedBy": "ai", "reviewedAt": "2026-10-20T00:00:00Z"})
    write_run_directory(tmp_path / "run", run_id="run-2026-10-26")
    run(commands.knowledge_publish_run, *flags)
    proposal = client.rows["SteeringProposal"][pid]
    assert (proposal["status"], proposal["displayName"], proposal["reviewedBy"]) == ("accepted", "Voice cloning", "ai")
    assert decode_metadata(proposal["summary"])["runId"] == "run-2026-10-26"


def test_clusters_need_a_corpus(client, tmp_path):
    run_dir = write_run_directory(tmp_path / "run")
    with pytest.raises(ValueError, match="corpus"):
        run(commands.knowledge_publish_run, *run_flags(run_dir))


def snapshot_context(out: Path):
    return SimpleNamespace(writer=LocalDirectoryWriter(out), projector=Projector(), invalidate=None)


def test_entity_review_then_snapshot_end_to_end(client, tmp_path, monkeypatch, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, *run_flags(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply")
    capsys.readouterr()
    monkeypatch.setattr(commands, "_context_for", lambda _client, options: snapshot_context(Path(options["out"])))
    out = tmp_path / "site"

    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19")
    index = json.loads((out / INDEX_FILE).read_text())
    assert sorted(entity["key"] for entity in index["entities"]) == ["maker--some-lab", "task--code-completion", "task--voice-cloning"]
    assert "model--tern-3" not in {entity["key"] for entity in index["entities"]}

    run(commands.knowledge_entities_list, "--status", "generated", "--counts")
    listing = capsys.readouterr().out
    assert "model--tern-3" in listing and "0 confirmed\t2 unconfirmed" in listing

    run(commands.knowledge_entities_accept, "--actor", "ai", "--key", "model--tern-3")
    run(commands.knowledge_entities_rename, "--actor", "ai", "--key", "model--tern-3", "--name", "Tern-3")
    run(commands.knowledge_entities_describe, "--key", "task--voice-cloning", "--text", "Copying a voice from a short sample.", "--actor", "human", "--actor-name", "Ada")
    tern = next(row for row in client.rows["SemanticNode"].values() if row["nodeKey"] == "model--tern-3")
    assert (tern["status"], tern["displayName"], tern["aliases"]) == ("accepted", "Tern-3", ["Tern 3"])
    voice = next(row for row in client.rows["SemanticNode"].values() if row["nodeKey"] == "task--voice-cloning")
    assert description_state(voice)[0] == "reviewed"
    assert tern_marks(tern)["acceptedBy"] == {"actor": "ai", "name": None, "on": today_utc()}

    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19", "--json")
    index = json.loads((out / INDEX_FILE).read_text())
    keys = {entity["key"]: entity for entity in index["entities"]}
    assert keys["model--tern-3"]["itemCount"] == 2 and keys["model--tern-3"]["name"] == "Tern-3"
    assert index["conceptOfTheWeek"]["key"] == "task--voice-cloning"
    entity = json.loads((out / "_data/knowledge/entities/task--voice-cloning.json").read_text())
    assert entity["relatedItems"][0]["url"] == "/posts/alpha/"
    assert entity["description"] == {"state": "reviewed", "editedBy": {"actor": "human", "name": "Ada", "on": today_utc()}}
    assert keys["model--tern-3"]["acceptedBy"] == {"actor": "ai", "name": None, "on": today_utc()}
    first = {path.name: path.read_bytes() for path in (out / "_data/knowledge").rglob("*.json")}
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19")
    assert {path.name: path.read_bytes() for path in (out / "_data/knowledge").rglob("*.json")} == first
    assert "0 written" in capsys.readouterr().out.splitlines()[-1]


def test_reject_removes_an_entity_from_the_snapshot_and_orphan_files_are_deleted(client, tmp_path, monkeypatch, capsys):
    run(commands.knowledge_publish_run, "--apply")
    monkeypatch.setattr(commands, "_context_for", lambda _client, options: snapshot_context(Path(options["out"])))
    out = tmp_path / "site"
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19")
    assert (out / "_data/knowledge/entities/maker--some-lab.json").exists()
    run(commands.knowledge_entities_reject, "--actor", "ai", "--key", "maker--some-lab")
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19")
    assert not (out / "_data/knowledge/entities/maker--some-lab.json").exists()


def test_snapshot_clusters_use_the_category_name(client, tmp_path, monkeypatch, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, *run_flags(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply")
    pid = cluster_proposal_id("tc-1")
    key = client.rows["SteeringProposal"][pid]["categoryKey"]
    client.rows["SteeringProposal"][pid]["status"] = "accepted"
    client.rows["Category"] = {
        "cat-1": {"id": "cat-1", "versionState": "current", "status": "accepted", "categorySetId": "set-1", "categoryKey": key, "displayName": "Voice cloning", "parentCategoryKey": None}
    }
    monkeypatch.setattr(commands, "_context_for", lambda _client, options: snapshot_context(Path(options["out"])))
    out = tmp_path / "site"
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19", "--beats-category-set", "set-1")
    clusters = json.loads((out / CLUSTERS_FILE).read_text())
    assert [(row["uid"], row["name"], row["state"]) for row in clusters["clusters"]] == [("tc-1", "Voice cloning", "new")]
    assert clusters["runId"] == "run-2026-10-19"
    beats = json.loads((out / INDEX_FILE).read_text())["beats"]
    assert [(beat["key"], beat["itemCount"]) for beat in beats] == [(key, 2)]


def test_beats_from_a_scoring_style_config(client, tmp_path, monkeypatch):
    run(commands.knowledge_publish_run, "--apply")
    monkeypatch.setattr(commands, "_context_for", lambda _client, options: snapshot_context(Path(options["out"])))
    config = tmp_path / "scoring.json"
    config.write_text(json.dumps({"topics": {"decision-models": {"label": "Decision models", "path": "/topics/decision-models/"}}}))
    out = tmp_path / "site"
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19", "--beats-config", str(config))
    beats = json.loads((out / INDEX_FILE).read_text())["beats"]
    assert beats == [{"key": "decision-models", "name": "Decision models", "href": "/topics/decision-models/", "itemCount": 1, "series8": [0, 0, 0, 0, 0, 0, 1, 0], "topEntities": ["maker--some-lab", "task--voice-cloning"]}]


def test_offline_records_snapshot(tmp_path):
    records = {
        "items": [{"key": "l1", "itemId": "i1", "title": "One", "url": "/one/", "publishedAt": "2026-10-13T00:00:00Z"}],
        "nodes": [{"id": "n1", "lineageId": "n1", "versionState": "current", "nodeKey": "task--demo", "nodeKind": "task", "displayName": "Demo", "status": "accepted"}],
        "relations": [
            {"id": "r1", "predicate": "mentions", "subjectKind": "item", "objectKind": "semanticNode", "subjectLineageId": "l1", "objectLineageId": "n1", "metadata": json.dumps({"confirmed": True})}
        ],
    }
    file = tmp_path / "records.json"
    file.write_text(json.dumps(records))
    run(commands.knowledge_snapshot, "--records", str(file), "--out", str(tmp_path / "out"), "--as-of", "2026-10-19")
    index = json.loads((tmp_path / "out" / INDEX_FILE).read_text())
    assert [entity["key"] for entity in index["entities"]] == ["task--demo"]


def test_snapshot_needs_a_destination_and_a_valid_cluster_mode(client):
    with pytest.raises(ValueError, match="--out"):
        run(commands.knowledge_snapshot)
    with pytest.raises(ValueError, match="hide or unnamed"):
        run(commands.knowledge_snapshot, "--out", "x", "--unaccepted-clusters", "all")


def test_entity_review_refuses_unknown_keys_and_duplicate_names(client, capsys):
    run(commands.knowledge_publish_run, "--apply")
    with pytest.raises(ValueError, match="No entity"):
        run(commands.knowledge_entities_accept, "--actor", "ai", "--key", "nope")
    with pytest.raises(ValueError, match="already has the name"):
        run(commands.knowledge_entities_rename, "--actor", "ai", "--key", "task--voice-cloning", "--name", "code completion")
    capsys.readouterr()
    run(commands.knowledge_entities_rename, "--actor", "ai", "--key", "task--voice-cloning", "--name", "Voice cloning", "--dry-run")
    assert "nothing to change" in capsys.readouterr().out


def test_reproject_runs_the_site_projection_after_the_files_are_written(client, tmp_path, monkeypatch, capsys):
    run(commands.knowledge_publish_run, "--apply")
    monkeypatch.setattr(commands, "_context_for", lambda _client, options: snapshot_context(Path(options["out"])))
    seen = []

    class Report:
        ok = True
        errors: list = []

        def to_dict(self):
            return {"written": 5, "deleted": 0, "redirectsWritten": 0, "invalidated": 0}

    def fake_project_all(context):
        seen.append(sorted(path.name for path in (tmp_path / "site" / "_data" / "knowledge").rglob("index.json")))
        return Report()

    monkeypatch.setattr(commands, "project_all", fake_project_all)
    run(commands.knowledge_snapshot, "--out", str(tmp_path / "site"), "--as-of", "2026-10-19", "--reproject")
    assert seen == [["index.json"]]
    assert "Projected: 5 written" in capsys.readouterr().out


def test_the_reconcile_leaves_the_knowledge_files_alone():
    from papyrus_content.projection.plugins import is_plugin_runtime_key

    assert is_plugin_runtime_key("_data/knowledge/index.json")
    assert is_plugin_runtime_key("posts/_data/knowledge/entities/task--x.json")
    assert is_plugin_runtime_key("_data/reader/items.json")
    assert not is_plugin_runtime_key("posts/knowledge.html")


def node_by_key(client, key):
    return next(row for row in client.rows["SemanticNode"].values() if row["nodeKey"] == key)


def snapshot_to(tmp_path, monkeypatch, *flags, projector=None):
    monkeypatch.setattr(commands, "_context_for", lambda _client, options: SimpleNamespace(writer=LocalDirectoryWriter(Path(options["out"])), projector=projector or Projector(), invalidate=None))
    run(commands.knowledge_snapshot, "--out", str(tmp_path / "site"), "--as-of", "2026-10-19", *flags)
    return tmp_path / "site"


# ------------------------------------------------------------------ who accepted

def test_front_matter_entities_are_recorded_as_accepted_by_the_ai_never_a_person(client, capsys):
    run(commands.knowledge_publish_run, "--apply", "--actor-name", "Research agent")
    for row in client.rows["SemanticNode"].values():
        accepted = decode_review(row["changeReason"]).accepted_by
        assert (accepted.actor, accepted.name, accepted.on) == ("ai", "Research agent", today_utc()) and row["status"] == "accepted"
    before = len(client.writes)
    run(commands.knowledge_publish_run, "--apply", "--json")
    assert len(client.writes) == before


def test_an_accepted_front_matter_node_without_a_record_gets_the_ai_record_but_a_hand_made_node_does_not(client, capsys):
    run(commands.knowledge_publish_run, "--apply")
    capsys.readouterr()
    legacy = node_by_key(client, "task--code-completion")
    legacy["changeReason"] = "front-matter entity"
    hand_made = {**legacy, "id": "semantic-node-hand", "lineageId": "semantic-node-hand", "nodeKey": "tool--hand", "displayName": "Hand", "importRunId": "other-run", "changeReason": None}
    client.rows["SemanticNode"].update({legacy["id"]: legacy, hand_made["id"]: hand_made})
    run(commands.knowledge_publish_run, "--apply")
    assert decode_review(client.rows["SemanticNode"][legacy["id"]]["changeReason"]).accepted_by.actor == "ai"
    assert client.rows["SemanticNode"]["semantic-node-hand"]["changeReason"] is None


def test_the_snapshot_publishes_who_accepted_each_entity_and_cluster(client, tmp_path, monkeypatch, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, *run_flags(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply", "--actor-name", "Research agent")
    run(commands.knowledge_clusters_accept, "--uid", "tc-1", "--name", "Voice cloning", "--actor", "ai", "--actor-name", "Topic agent")
    out = snapshot_to(tmp_path, monkeypatch)
    index = json.loads((out / INDEX_FILE).read_text())
    assert {row["acceptedBy"]["actor"] for row in index["entities"]} == {"ai"}
    assert index["entities"][0]["acceptedBy"]["name"] == "Research agent"
    clusters = json.loads((out / CLUSTERS_FILE).read_text())["clusters"]
    assert [(row["uid"], row["name"], row["acceptedBy"]) for row in clusters] == [("tc-1", "Voice cloning", {"actor": "ai", "name": "Topic agent", "on": today_utc()})]


@pytest.mark.parametrize(
    ("function", "extra"),
    [
        (commands.knowledge_entities_accept, ("--key", "task--voice-cloning")),
        (commands.knowledge_entities_reject, ("--key", "task--voice-cloning")),
        (commands.knowledge_entities_rename, ("--key", "task--voice-cloning", "--name", "Cloning")),
        (commands.knowledge_entities_describe, ("--key", "task--voice-cloning", "--text", "Copying a voice.")),
        (commands.knowledge_clusters_accept, ("--uid", "tc-1", "--name", "Voice")),
        (commands.knowledge_clusters_name, ("--uid", "tc-1", "--name", "Voice")),
        (commands.knowledge_clusters_reject, ("--uid", "tc-1")),
        (commands.knowledge_relations_accept, ("--id", "x")),
        (commands.knowledge_relations_reject, ("--id", "x")),
    ],
)
def test_every_review_command_requires_an_actor_with_no_default(client, function, extra):
    with pytest.raises(ValueError, match="requires --actor ai\\|human"):
        run(function, *extra)
    with pytest.raises(ValueError, match="--actor is required"):
        run(function, *extra, "--actor", "robot")
    with pytest.raises(ValueError, match="email"):
        run(function, *extra, "--actor", "human", "--actor-name", "ann@example.org")
    assert client.writes == []


def test_a_description_edited_by_an_ai_is_ai_edited_and_by_a_person_is_reviewed(client, capsys):
    run(commands.knowledge_publish_run, "--apply")
    run(commands.knowledge_entities_describe, "--key", "task--voice-cloning", "--text", "Copying a voice.", "--actor", "ai", "--actor-name", "Wiki agent")
    voice = node_by_key(client, "task--voice-cloning")
    state, editor = description_state(voice)
    assert (state, editor.actor, editor.name) == ("ai_edited", "ai", "Wiki agent")
    assert decode_review(voice["changeReason"]).accepted_by.actor == "ai"
    run(commands.knowledge_entities_describe, "--key", "task--voice-cloning", "--text", "Copying a voice from a sample.", "--actor", "human", "--actor-name", "Ada")
    assert description_state(node_by_key(client, "task--voice-cloning"))[0] == "reviewed"


def test_a_person_accepting_after_the_ai_replaces_the_record_and_the_same_actor_twice_changes_nothing(client, capsys):
    run(commands.knowledge_publish_run, "--apply")
    capsys.readouterr()
    run(commands.knowledge_entities_accept, "--key", "task--voice-cloning", "--actor", "human", "--actor-name", "Ada")
    assert decode_review(node_by_key(client, "task--voice-cloning")["changeReason"]).accepted_by.actor == "human"
    capsys.readouterr()
    run(commands.knowledge_entities_accept, "--key", "task--voice-cloning", "--actor", "human", "--actor-name", "Ada")
    assert "nothing to change" in capsys.readouterr().out


def test_reject_records_who_rejected_and_accept_clears_it(client, capsys):
    run(commands.knowledge_publish_run, "--apply")
    run(commands.knowledge_entities_reject, "--key", "maker--some-lab", "--actor", "human", "--actor-name", "Ada")
    marks = decode_review(node_by_key(client, "maker--some-lab")["changeReason"])
    assert marks.accepted_by is None and marks.rejected_by.name == "Ada"
    run(commands.knowledge_entities_accept, "--key", "maker--some-lab", "--actor", "ai")
    marks = decode_review(node_by_key(client, "maker--some-lab")["changeReason"])
    assert marks.rejected_by is None and marks.accepted_by.actor == "ai"


# ------------------------------------------------------------------ clusters

CLUSTER_FLAGS = ("--corpus-key", "shipped", "--category-set", "set-1", "--apply")


def test_clusters_are_accepted_named_and_rejected_with_an_actor_and_a_continued_run_keeps_it(client, tmp_path, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, *run_flags(run_dir), *CLUSTER_FLAGS)
    capsys.readouterr()
    run(commands.knowledge_clusters_list)
    assert "tc-1\tproposed" in capsys.readouterr().out
    with pytest.raises(ValueError, match="A cluster name is needed"):
        run(commands.knowledge_clusters_accept, "--uid", "tc-1", "--actor", "ai")
    run(commands.knowledge_clusters_accept, "--uid", "tc-1", "--name", "Voice cloning", "--actor", "human", "--actor-name", "Ada")
    proposal = client.rows["SteeringProposal"][cluster_proposal_id("tc-1")]
    assert (proposal["status"], proposal["displayName"], proposal["reviewedBy"]) == ("accepted", "Voice cloning", "human:Ada")
    assert decode_metadata(proposal["summary"])["acceptedBy"] == {"actor": "human", "name": "Ada", "on": today_utc()}
    capsys.readouterr()
    run(commands.knowledge_clusters_accept, "--uid", "tc-1", "--actor", "ai")
    assert "nothing to change" in capsys.readouterr().out
    run(commands.knowledge_clusters_name, "--uid", "tc-1", "--name", "Voice cloning and TTS", "--actor", "ai")
    write_run_directory(tmp_path / "run", run_id="run-2026-10-26")
    run(commands.knowledge_publish_run, *run_flags(run_dir), *CLUSTER_FLAGS)
    proposal = client.rows["SteeringProposal"][cluster_proposal_id("tc-1")]
    metadata = decode_metadata(proposal["summary"])
    assert (proposal["displayName"], metadata["runId"], metadata["acceptedBy"]["name"]) == ("Voice cloning and TTS", "run-2026-10-26", "Ada")
    run(commands.knowledge_clusters_reject, "--uid", "tc-2", "--actor", "ai")
    assert client.rows["SteeringProposal"][cluster_proposal_id("tc-2")]["status"] == "rejected"
    with pytest.raises(ValueError, match="only a proposed cluster"):
        run(commands.knowledge_clusters_accept, "--uid", "tc-2", "--name", "Code", "--actor", "ai")
    with pytest.raises(ValueError, match="No cluster"):
        run(commands.knowledge_clusters_reject, "--uid", "nope", "--actor", "ai")


def test_review_proposal_sends_knowledge_clusters_to_the_command_that_records_the_actor(client, tmp_path, monkeypatch):
    from papyrus_content import categories_commands

    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, *run_flags(run_dir), *CLUSTER_FLAGS)
    monkeypatch.setattr(categories_commands, "create_authoring_client", lambda *args, **kwargs: (client, {}))
    with pytest.raises(ValueError, match="knowledge clusters accept"):
        categories_commands.categories_review_proposal(["--proposal", cluster_proposal_id("tc-1"), "--action", "accept"])


def test_a_new_cluster_is_judged_by_its_earliest_publication_not_the_run_date(client, tmp_path, monkeypatch):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, *run_flags(run_dir), *CLUSTER_FLAGS)
    run(commands.knowledge_clusters_accept, "--uid", "tc-1", "--name", "Voice cloning", "--actor", "ai")
    run(commands.knowledge_clusters_accept, "--uid", "tc-2", "--name", "Code", "--actor", "ai")
    identity = json.loads((run_dir / "identity.json").read_text())
    identity["clusters"][1]["event"] = "new"
    identity["clusters"][1]["earliest_published_at"] = "2026-06-01T00:00:00Z"
    (run_dir / "identity.json").write_text(json.dumps(identity))
    run(commands.knowledge_publish_run, *run_flags(run_dir), *CLUSTER_FLAGS)
    out = snapshot_to(tmp_path, monkeypatch)
    states = {row["uid"]: row["state"] for row in json.loads((out / CLUSTERS_FILE).read_text())["clusters"]}
    assert states == {"tc-1": "new", "tc-2": None}


# ------------------------------------------------------------------ typed entities and relations

def test_a_resolved_mention_links_unconfirmed_unless_confirm_resolved_and_the_node_is_accepted(client, tmp_path, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, *run_flags(run_dir), *CLUSTER_FLAGS)
    to_lab = [row for row in client.rows["SemanticRelation"].values() if row["objectId"].endswith("some-lab-v1") and row["subjectLineageId"] == "lineage-alpha"]
    assert len(to_lab) == 1 and json.loads(to_lab[0]["metadata"])["confirmed"] is True     
    to_tern = [row for row in client.rows["SemanticRelation"].values() if row["objectId"].endswith("tern-3-v1")]
    assert {json.loads(row["metadata"])["confirmed"] for row in to_tern} == {False}
    assert {json.loads(row["metadata"])["extractorState"] for row in to_tern} == {"proposed", "resolved"}


def test_confirm_resolved_confirms_only_resolved_mentions_of_accepted_nodes(client, tmp_path, capsys):
    run(commands.knowledge_publish_run, "--apply")
    run(commands.knowledge_entities_accept, "--key", "task--code-completion", "--actor", "ai")
    run_dir = write_run_directory(tmp_path / "run")
    entities = json.loads((run_dir / "entities.json").read_text())
    entities["items"][1]["entities"].append({"id": "e2", "kind": "task", "text": "Code completion", "state": "resolved", "entity_key": "task--code-completion", "span": None, "score": 1.0})
    entities["items"][1]["entities"].append({"id": "e3", "kind": "task", "text": "Voice cloning", "state": "proposed", "entity_key": None, "span": None, "score": 0.6})
    (run_dir / "entities.json").write_text(json.dumps(entities))
    flags = ("--entities", str(run_dir / "entities.json"), "--apply", "--confirm-resolved")
    run(commands.knowledge_publish_run, *flags)
    out = capsys.readouterr().out
    assert "linksConfirmedByResolution\t1" in out
    beta_links = {
        json.loads(row["metadata"])["extractorState"]: json.loads(row["metadata"])
        for row in client.rows["SemanticRelation"].values()
        if row["subjectLineageId"] == "lineage-beta" and json.loads(row["metadata"])["linkSource"] == "extractor"
    }
    assert beta_links["resolved"]["confirmed"] is True and beta_links["resolved"]["confirmedBy"]["actor"] == "ai"
    voice_links = [row for row in client.rows["SemanticRelation"].values() if row["subjectLineageId"] == "lineage-beta" and row["objectId"].endswith("voice-cloning-v1")]
    assert [json.loads(row["metadata"])["linkSource"] for row in voice_links] == ["front_matter"]


def test_typed_relations_wait_for_accepted_nodes_then_for_a_reviewer_and_only_accepted_ones_are_neighbours(client, tmp_path, monkeypatch, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    flags = ("--entities", str(run_dir / "entities.json"), "--apply")
    run(commands.knowledge_publish_run, *flags)
    assert "relationsSkippedUnaccepted\t1" in capsys.readouterr().out
    assert not [row for row in client.rows["SemanticRelation"].values() if row["predicate"] == "made_by"]

    run(commands.knowledge_entities_accept, "--key", "model--tern-3", "--actor", "ai")
    run(commands.knowledge_publish_run, *flags)
    assert "relationsProposed\t1" in capsys.readouterr().out
    run(commands.knowledge_relations_list)
    listing = capsys.readouterr().out
    relation = next(row for row in client.rows["SemanticRelation"].values() if row["predicate"] == "made_by")
    assert f"{relation['id']}\tproposed\tmade_by" in listing
    assert json.loads(relation["metadata"])["confirmed"] is False and relation["subjectKind"] == relation["objectKind"] == "semanticNode"

    out = snapshot_to(tmp_path, monkeypatch)
    tern = json.loads((out / "_data/knowledge/entities/model--tern-3.json").read_text())
    assert [row for row in tern["neighbours"] if row["relation"] == "made_by"] == []

    run(commands.knowledge_relations_accept, "--id", relation["id"], "--actor", "human", "--actor-name", "Ada")
    assert json.loads(client.rows["SemanticRelation"][relation["id"]]["metadata"])["acceptedBy"]["name"] == "Ada"
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19")
    tern = json.loads((out / "_data/knowledge/entities/model--tern-3.json").read_text())
    assert [(row["relation"], row["key"]) for row in tern["neighbours"] if row["relation"] == "made_by"] == [("made_by", "maker--some-lab")]

    run(commands.knowledge_relations_reject, "--id", relation["id"], "--actor", "ai")
    assert json.loads(client.rows["SemanticRelation"][relation["id"]]["metadata"])["confirmed"] is False
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19")
    tern = json.loads((out / "_data/knowledge/entities/model--tern-3.json").read_text())
    assert [row for row in tern["neighbours"] if row["relation"] == "made_by"] == []
    with pytest.raises(ValueError, match="No relation"):
        run(commands.knowledge_relations_accept, "--id", "missing", "--actor", "ai")


# ------------------------------------------------------------------ base path

class BasedPolicy:
    root = "posts/"

    def key(self, site_key):
        return self.root + site_key

    def path(self, site_path):
        return "/" + self.root + site_path.lstrip("/")

    def url_for_key(self, key):
        return "/" + key.removesuffix("index.html")


class BasedProjector:
    policy = BasedPolicy()

    def item_page_paths(self, summary):
        return (f"posts/{summary.slug}/index.html",)


def test_a_based_site_gets_its_snapshot_under_the_base_path_with_hrefs_under_it(client, tmp_path, monkeypatch):
    run(commands.knowledge_publish_run, "--apply")
    out = snapshot_to(tmp_path, monkeypatch, "--entity-href", "/concepts/{key}/", projector=BasedProjector())
    stored = sorted(path.relative_to(out).as_posix() for path in out.rglob("*.json"))
    assert stored and all(key.startswith("posts/_data/knowledge/") for key in stored)
    index = json.loads((out / "posts/_data/knowledge/index.json").read_text())
    assert {row["href"] for row in index["entities"]} == {f"/posts/concepts/{row['key']}/" for row in index["entities"]}
    entity = json.loads((out / "posts/_data/knowledge/entities/task--voice-cloning.json").read_text())
    assert entity["relatedItems"][0]["url"].startswith("/posts/")
    before = {path: (out / path).read_bytes() for path in stored}
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19", "--entity-href", "/concepts/{key}/")
    assert {path: (out / path).read_bytes() for path in stored} == before


def test_a_template_that_already_names_the_base_path_is_taken_as_written():
    projector = BasedProjector()
    assert commands.based_template(projector, "/posts/concepts/{key}/") == "/posts/concepts/{key}/"
    assert commands.based_template(projector, "https://example.com/{key}") == "https://example.com/{key}"
    assert commands.based_template(Projector(), "/concepts/{key}/") == "/concepts/{key}/"
    assert commands.based_template(projector, None) is None


# ------------------------------------------------------------------ the operator lane

def test_auth_and_amplify_outputs_select_the_lane_and_endpoint_on_purpose_and_are_announced(client, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "user")
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://old.example/graphql")
    outputs = tmp_path / "amplify_outputs.json"
    outputs.write_text(json.dumps({"data": {"url": "https://abc123.appsync-api.us-east-1.amazonaws.com/graphql"}}))
    run(commands.knowledge_entities_list, "--auth", "iam", "--amplify-outputs", str(outputs), "--status", "all")
    announced = [line for line in capsys.readouterr().err.splitlines() if line.startswith("knowledge\tauth")]
    assert announced == ["knowledge\tauth\tiam\tabc123.appsync-api.us-east-1.amazonaws.com"]
    with pytest.raises(ValueError, match="--auth must be user or iam"):
        run(commands.knowledge_entities_list, "--auth", "guest")
    with pytest.raises(ValueError, match="Cannot read --amplify-outputs"):
        run(commands.knowledge_entities_list, "--amplify-outputs", str(tmp_path / "missing.json"))
    outputs.write_text("{}")
    with pytest.raises(ValueError, match="no GraphQL endpoint"):
        run(commands.knowledge_entities_list, "--amplify-outputs", str(outputs))


# ------------------------------------------------------------------ retype and registry

def test_retype_migrates_the_node_its_links_and_its_relations_and_is_idempotent(client, tmp_path, monkeypatch, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    flags = ("--entities", str(run_dir / "entities.json"), "--apply")
    run(commands.knowledge_publish_run, *flags)
    run(commands.knowledge_entities_accept, "--key", "model--tern-3", "--actor", "ai")
    run(commands.knowledge_publish_run, *flags)
    capsys.readouterr()
    old = next(row for row in client.rows["SemanticNode"].values() if row["nodeKey"] == "model--tern-3")
    relation = next(row for row in client.rows["SemanticRelation"].values() if row["predicate"] == "made_by")
    run(commands.knowledge_relations_accept, "--id", relation["id"], "--actor", "ai")

    run(commands.knowledge_entities_retype, "--key", "model--tern-3", "--kind", "model_family", "--actor", "ai", "--actor-name", "Reviewer", "--dry-run")
    assert "dry-run" in capsys.readouterr().out and not [n for n in client.rows["SemanticNode"].values() if n["nodeKey"].startswith("model-family")]

    run(commands.knowledge_entities_retype, "--key", "model--tern-3", "--kind", "model_family", "--actor", "ai", "--actor-name", "Reviewer")
    assert "model--tern-3 -> model-family--tern-3" in capsys.readouterr().out
    nodes = {row["nodeKey"]: row for row in client.rows["SemanticNode"].values()}
    new = nodes["model-family--tern-3"]
    assert (new["status"], new["versionState"], new["displayName"], new["aliases"], new["nodeKind"]) == ("accepted", "current", old["displayName"], old["aliases"], "model_family")
    marks = decode_review(new["changeReason"])
    assert marks.accepted_by.actor == "ai" and marks.retyped_by.to_dict() == {"actor": "ai", "name": "Reviewer", "on": today_utc()}
    superseded = client.rows["SemanticNode"][old["id"]]
    assert (superseded["versionState"], superseded["status"]) == ("superseded", "superseded")

    current = [row for row in client.rows["SemanticRelation"].values() if row["relationState"] == "current"]
    assert not [row for row in current if old["lineageId"] in (row["objectLineageId"], row["subjectLineageId"])]
    moved = [row for row in current if new["lineageId"] in (row["objectLineageId"], row["subjectLineageId"])]
    assert len(moved) == 3
    assert {row["predicate"] for row in moved} == {"mentions", "made_by"}
    assert all(json.loads(row["metadata"]).get("confirmed") is not None for row in moved)
    accepted_relation = next(row for row in moved if row["predicate"] == "made_by")
    assert json.loads(accepted_relation["metadata"])["acceptedBy"]["actor"] == "ai"

    before = len(client.writes)
    with pytest.raises(ValueError, match="No entity"):
        run(commands.knowledge_entities_retype, "--key", "model--tern-3", "--kind", "model_family", "--actor", "ai")
    with pytest.raises(ValueError, match="already of kind"):
        run(commands.knowledge_entities_retype, "--key", "model-family--tern-3", "--kind", "model_family", "--actor", "ai")
    assert len(client.writes) == before

    out = snapshot_to(tmp_path, monkeypatch)
    index = json.loads((out / INDEX_FILE).read_text())
    keys = {entity["key"] for entity in index["entities"]}
    assert "model-family--tern-3" in keys and "model--tern-3" not in keys
    assert not (out / "_data/knowledge/entities/model--tern-3.json").exists()


def test_retype_refuses_the_same_kind_a_taken_key_a_rejected_node_and_needs_an_actor(client, capsys):
    run(commands.knowledge_publish_run, "--apply")
    client.rows["SemanticNode"]["extra"] = {
        "id": "extra", "lineageId": "extra", "versionNumber": 1, "versionState": "current", "nodeKey": "maker--voice-cloning",
        "nodeKind": "maker", "displayName": "Voice cloning", "aliases": [], "status": "generated",
    }
    with pytest.raises(ValueError, match="already of kind"):
        run(commands.knowledge_entities_retype, "--key", "task--voice-cloning", "--kind", "task", "--actor", "ai")
    with pytest.raises(ValueError, match="already holds the key"):
        run(commands.knowledge_entities_retype, "--key", "task--voice-cloning", "--kind", "maker", "--actor", "ai")
    with pytest.raises(ValueError, match="requires --actor ai\\|human"):
        run(commands.knowledge_entities_retype, "--key", "task--voice-cloning", "--kind", "model")
    with pytest.raises(ValueError, match="requires --key"):
        run(commands.knowledge_entities_retype, "--actor", "ai")
    run(commands.knowledge_entities_reject, "--key", "task--code-completion", "--actor", "ai")
    with pytest.raises(ValueError, match="rejected"):
        run(commands.knowledge_entities_retype, "--key", "task--code-completion", "--kind", "model", "--actor", "ai")


def test_the_registry_holds_every_accepted_node_with_all_its_names_and_drops_ambiguous_aliases(client, tmp_path, capsys):
    def node_row(key, kind, name, aliases, status="accepted"):
        return {"id": f"{key}-v1", "lineageId": key, "versionNumber": 1, "versionState": "current", "nodeKey": key, "nodeKind": kind, "displayName": name, "aliases": aliases, "status": status}

    rows = [
        node_row("maker--mistral-ai", "maker", "Mistral AI", ["Mistral", "mistral  ai", "Mistral-AI", "team@example.org"]),
        node_row("maker--other", "maker", "Other Lab", ["Mistral.", "Other"]),
        node_row("model--gemma-3", "model", "Gemma 3", []),
        node_row("model--generated", "model", "Generated", [], status="generated"),
    ]
    client.rows["SemanticNode"] = {row["id"]: row for row in rows}
    out = tmp_path / "run" / "registry.json"
    run(commands.knowledge_entities_registry, "--out", str(out))
    registry = json.loads(out.read_text())
    assert registry == [
        {"aliases": ["Mistral AI"], "key": "maker--mistral-ai", "kind": "maker"},
        {"aliases": ["Other Lab", "Other"], "key": "maker--other", "kind": "maker"},
        {"aliases": ["Gemma 3"], "key": "model--gemma-3", "kind": "model"},
    ]
    captured = capsys.readouterr()
    assert "3 entities" in captured.out and "'mistral'" in captured.err
    with pytest.raises(ValueError, match="--out"):
        run(commands.knowledge_entities_registry)


def test_a_rename_keeps_the_old_name_so_both_makers_resolve_through_the_registry(client, tmp_path):
    from .registry import build_registry

    run(commands.knowledge_publish_run, "--apply")
    run(commands.knowledge_entities_rename, "--key", "maker--some-lab", "--name", "Some Lab Inc", "--actor", "ai")
    registry, warnings = build_registry(client.list_records("SemanticNode"))
    entry = next(row for row in registry if row["key"] == "maker--some-lab")
    assert entry["aliases"] == ["Some Lab Inc", "Some Lab"] and warnings == []


def test_topic_config_writes_the_vectorizer_with_the_extra_stop_words(tmp_path, monkeypatch):
    import yaml

    from . import topic_config

    monkeypatch.setattr(topic_config, "english_stop_words", lambda: ["the", "and"])
    words = tmp_path / "stop-words.txt"
    words.write_text("# Shipped\ncard\nModels\n\nhugging  face  # two words\n", encoding="utf-8")
    out = tmp_path / "topic-modeling.yml"
    run(commands.knowledge_topic_config, "--out", str(out), "--stop-words", str(words))
    configuration = yaml.safe_load(out.read_text())
    vectorizer = configuration["bertopic_analysis"]["vectorizer"]
    listed = set(vectorizer["stop_words"])
    assert vectorizer["ngram_range"] == [1, 2]
    assert {"the", "and", "card", "models", "hugging", "face"} <= listed
    assert {"20", "35", "2026", "9999", "f1", "ab", "x", "7"} <= listed
    assert not ({"voice", "clone", "10000", "f1x", "abc"} & listed)
    assert vectorizer["stop_words"] == sorted(listed)
    assert configuration["bertopic_analysis"]["hdbscan_model"]["parameters"]["min_cluster_size"] == 5
    assert configuration["bertopic_analysis"]["parameters"] == {"nr_topics": None, "min_topic_size": 5}
    with pytest.raises(ValueError, match="--out"):
        run(commands.knowledge_topic_config)


# ------------------------------------------------------------------ kinds, aliases, concept kinds

def node_row(key, kind, name, aliases=(), status="accepted"):
    return {"id": f"{key}-v1", "lineageId": key, "versionNumber": 1, "versionState": "current", "nodeKey": key, "nodeKind": kind, "displayName": name, "aliases": list(aliases), "status": status}


def test_a_kind_keeps_the_vocabulary_key_in_nodes_and_only_the_entity_key_uses_hyphens(client, tmp_path, monkeypatch):
    path = tmp_path / "entities.json"
    path.write_text(json.dumps({
        "schema_version": 1, "vocabulary": {}, "backend": {}, "summary": {},
        "items": [{"item_id": "item-alpha", "entities": [{"id": "e1", "kind": "model_family", "text": "Tern", "state": "proposed", "entity_key": None, "span": None, "score": 0.9}], "relations": []}],
    }))
    run(commands.knowledge_publish_run, "--entities", str(path), "--apply")
    node = next(row for row in client.rows["SemanticNode"].values() if row["nodeKey"].startswith("model-family--"))
    assert (node["nodeKey"], node["nodeKind"]) == ("model-family--tern", "model_family")
    legacy = node_row("model-family--old", "model-family", "Old", status="generated")
    client.rows["SemanticNode"][legacy["id"]] = legacy
    from .publish_run import NodeIndex

    assert NodeIndex(client.rows["SemanticNode"].values()).resolve("model_family", "old")["id"] == legacy["id"]


def test_the_registry_writes_the_canonical_kind_and_maps_to_the_vocabulary_keys(client, tmp_path, capsys):
    client.rows["SemanticNode"] = {row["id"]: row for row in [
        node_row("model-family--tern", "model-family", "Tern"),
        node_row("model--gemma-3", "model", "Gemma 3"),
        node_row("benchmark--swe", "benchmark", "SWE"),
    ]}
    out = tmp_path / "registry.json"
    run(commands.knowledge_entities_registry, "--out", str(out))
    assert {entry["key"]: entry["kind"] for entry in json.loads(out.read_text())} == {"benchmark--swe": "benchmark", "model--gemma-3": "model", "model-family--tern": "model_family"}
    assert client.rows["SemanticNode"]["model-family--tern-v1"]["nodeKind"] == "model-family"

    vocabulary = tmp_path / "vocabulary.yml"
    vocabulary.write_text("version: 1\nentity_kinds:\n  - {key: model, label: AI model}\n  - {key: model_family, label: family}\n")
    run(commands.knowledge_entities_registry, "--out", str(out), "--vocabulary", str(vocabulary))
    assert {entry["key"]: entry["kind"] for entry in json.loads(out.read_text())} == {"model--gemma-3": "model", "model-family--tern": "model_family"}
    assert "benchmark--swe has kind 'benchmark', which the vocabulary does not have" in capsys.readouterr().err
    vocabulary.write_text("version: 1\n")
    with pytest.raises(ValueError, match="no entity_kinds"):
        run(commands.knowledge_entities_registry, "--out", str(out), "--vocabulary", str(vocabulary))


def test_alias_adds_a_name_records_the_actor_and_makes_a_rejected_duplicate_resolve_to_the_accepted_node(client, tmp_path, capsys):
    from .publish_run import NodeIndex
    from .registry import build_registry

    client.rows["SemanticNode"] = {row["id"]: row for row in [
        node_row("maker--mistral-ai", "maker", "Mistral AI"),
        node_row("maker--mistral", "maker", "Mistral", status="rejected"),
        node_row("maker--other", "maker", "Other Lab", ["Other"]),
    ]}
    run(commands.knowledge_entities_alias, "--key", "maker--mistral-ai", "--add", "Mistral", "--actor", "ai", "--actor-name", "Reviewer", "--dry-run")
    assert client.rows["SemanticNode"]["maker--mistral-ai-v1"]["aliases"] == []
    run(commands.knowledge_entities_alias, "--key", "maker--mistral-ai", "--add", "Mistral", "--actor", "ai", "--actor-name", "Reviewer")
    node = client.rows["SemanticNode"]["maker--mistral-ai-v1"]
    assert node["aliases"] == ["Mistral"]
    assert decode_review(node["changeReason"]).aliased_by.to_dict() == {"actor": "ai", "name": "Reviewer", "on": today_utc()}
    assert NodeIndex(client.list_records("SemanticNode")).resolve("maker", "mistral")["nodeKey"] == "maker--mistral-ai"
    assert build_registry(client.list_records("SemanticNode"))[0][0]["aliases"] == ["Mistral AI", "Mistral"]
    before = len(client.writes)
    run(commands.knowledge_entities_alias, "--key", "maker--mistral-ai", "--add", "mistral ", "--actor", "human")
    assert len(client.writes) == before
    with pytest.raises(ValueError, match="merge the two by hand"):
        run(commands.knowledge_entities_alias, "--key", "maker--mistral-ai", "--add", "Other", "--actor", "ai")
    with pytest.raises(ValueError, match="rejected"):
        run(commands.knowledge_entities_alias, "--key", "maker--mistral", "--add", "Mistral Inc", "--actor", "ai")
    with pytest.raises(ValueError, match="requires --add"):
        run(commands.knowledge_entities_alias, "--key", "maker--mistral-ai", "--actor", "ai")
    with pytest.raises(ValueError, match="requires --actor ai\\|human"):
        run(commands.knowledge_entities_alias, "--key", "maker--mistral-ai", "--add", "X")
    with pytest.raises(ValueError, match="email"):
        run(commands.knowledge_entities_alias, "--key", "maker--mistral-ai", "--add", "a@b.example", "--actor", "ai")


def test_concept_kinds_limit_the_concept_of_the_week_and_the_default_is_every_kind(client, tmp_path, monkeypatch):
    run(commands.knowledge_publish_run, "--apply")
    run(commands.knowledge_entities_describe, "--key", "task--voice-cloning", "--text", "Copying a voice.", "--actor", "ai")
    run(commands.knowledge_entities_describe, "--key", "maker--some-lab", "--text", "A lab.", "--actor", "ai")

    def concept(*flags):
        return json.loads((snapshot_to(tmp_path, monkeypatch, *flags) / INDEX_FILE).read_text())["conceptOfTheWeek"]

    assert concept()["key"] == "task--voice-cloning"
    assert concept("--concept-kinds", "maker")["key"] == "maker--some-lab"
    assert concept("--concept-kinds", "Task, model_family")["key"] == "task--voice-cloning"
    assert concept("--concept-kinds", "model_family") is None
    with pytest.raises(ValueError, match="--concept-kinds"):
        run(commands.knowledge_snapshot, "--out", str(tmp_path / "site"), "--concept-kinds")


# ------------------------------------------------------------------ the model kind and member_of

def test_a_model_is_its_own_kind_labelled_model_and_is_related_to_its_family_only_when_the_extractor_said_so(client, tmp_path, monkeypatch, capsys):
    path = tmp_path / "entities.json"
    path.write_text(json.dumps({
        "schema_version": 1, "vocabulary": {}, "backend": {}, "summary": {},
        "items": [{
            "item_id": "item-alpha",
            "entities": [
                {"id": "e1", "kind": "model", "text": "Tern 3", "state": "proposed", "entity_key": None, "span": None, "score": 0.9},
                {"id": "e2", "kind": "model_family", "text": "Tern", "state": "proposed", "entity_key": None, "span": None, "score": 0.9},
                {"id": "e3", "kind": "model", "text": "Lone 1", "state": "proposed", "entity_key": None, "span": None, "score": 0.9},
            ],
            "relations": [{"id": "r1", "type": "member_of", "subject": "e1", "object": "e2", "state": "proposed", "span": None, "score": 0.8}],
        }],
    }))
    flags = ("--entities", str(path), "--apply")
    for key in ("model--tern-3", "model-family--tern", "model--lone-1"):
        run(commands.knowledge_publish_run, *flags)
        run(commands.knowledge_entities_accept, "--key", key, "--actor", "ai")
    run(commands.knowledge_publish_run, *flags)
    capsys.readouterr()

    relations = [row for row in client.rows["SemanticRelation"].values() if row["predicate"] == "member_of"]
    assert len(relations) == 1 and relations[0]["subjectId"].startswith("semantic-node-model--tern-3")
    assert relations[0]["objectId"].startswith("semantic-node-model-family--tern")
    run(commands.knowledge_relations_accept, "--id", relations[0]["id"], "--actor", "ai")

    out = snapshot_to(tmp_path, monkeypatch)
    index = json.loads((out / "_data/knowledge/index.json").read_text())
    labels = {row["key"]: row["label"] for row in index["kinds"]}
    assert (labels["model"], labels["model_family"]) == ("Model", "Model Family")
    kinds = {row["key"]: row["kind"] for row in index["entities"] if row["kind"].startswith("model")}
    assert kinds == {"model--tern-3": "model", "model-family--tern": "model_family", "model--lone-1": "model"}

    def neighbours(key):
        body = json.loads((out / f"_data/knowledge/entities/{key}.json").read_text())
        return [(row["relation"], row["key"]) for row in body["neighbours"] if row["relation"] == "member_of"]

    assert neighbours("model--tern-3") == [("member_of", "model-family--tern")]
    assert neighbours("model-family--tern") == [("member_of", "model--tern-3")]
    assert neighbours("model--lone-1") == []

def test_reproject_builds_its_context_with_the_deletion_guard_unless_allowed(client, tmp_path, monkeypatch):
    from papyrus_content import project_commands
    from papyrus_content.projection.engine import DeletionGuard

    monkeypatch.setattr(project_commands, "load_projector", lambda _environment: Projector())
    monkeypatch.setattr(project_commands, "warn_if_checkout_is_behind", lambda _directory: None)
    guarded = project_commands._context_for(client, {"out": str(tmp_path), "static-dir": str(tmp_path)})
    unguarded = project_commands._context_for(client, {"out": str(tmp_path), "allow-deletions": True})
    assert guarded.deletion_guard == DeletionGuard()
    assert unguarded.deletion_guard is None
