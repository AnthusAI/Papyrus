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
    (directory / "topic-identity.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "as_of": "2026-10-19",
                "clusters": [
                    {"uid": "tc-1", "event": "new", "member_count": 2, "member_item_ids": ["item-alpha", "item-beta"], "top_terms": ["voice", "clone", "audio", "tts"], "first_seen": "2026-10-06", "topic_id": 0},
                    {"uid": "tc-2", "event": "continued", "member_count": 1, "member_item_ids": ["item-gamma"], "top_terms": ["code"], "first_seen": "2026-08-01", "topic_id": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    (directory / "topic-trends.json").write_text(
        json.dumps({"weekly_bins": {"iso_weeks": weeks, "discovered_topics": [{"topic_id": 0, "counts": [0, 0, 0, 0, 0, 0, 1, 1]}, {"topic_id": 1, "counts": [1, 1, 1, 1, 1, 1, 1, 1]}]}}),
        encoding="utf-8",
    )
    (directory / "typed-entities.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"item_id": "item-alpha", "name": "Tern 3", "kind": "model", "state": "proposed"},
                    {"item_id": "item-alpha", "name": "tern  3", "kind": "model", "state": "proposed", "start": 4, "end": 10},
                    {"item_id": "item-beta", "name": "Tern 3", "kind": "model", "state": "resolved"},
                    {"item_id": "item-unknown", "name": "Ghost", "kind": "model"},
                    {"item_id": "item-alpha", "name": "Some Lab", "kind": "maker"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_publish_run_imports_clusters_and_extractor_entities_and_is_idempotent(client, tmp_path, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, "--run-dir", str(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply")
    out = capsys.readouterr().out
    assert "clustersNew\t2" in out and "extractorMentionsOfUnpublishedItems\t1" in out
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
    run(commands.knowledge_publish_run, "--run-dir", str(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply", "--json")
    plan = json.loads(capsys.readouterr().out)
    assert {key.split(":")[1] for key in plan["changes"]} == {"noop"}
    assert len(client.writes) == before


def test_a_continued_cluster_keeps_its_status_and_desk_name(client, tmp_path, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    flags = ("--run-dir", str(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply")
    run(commands.knowledge_publish_run, *flags)
    pid = cluster_proposal_id("tc-1")
    client.rows["SteeringProposal"][pid].update({"status": "accepted", "displayName": "Voice cloning", "reviewedBy": "desk", "reviewedAt": "2026-10-20T00:00:00Z"})
    write_run_directory(tmp_path / "run", run_id="run-2026-10-26")
    run(commands.knowledge_publish_run, *flags)
    proposal = client.rows["SteeringProposal"][pid]
    assert (proposal["status"], proposal["displayName"], proposal["reviewedBy"]) == ("accepted", "Voice cloning", "desk")
    assert decode_metadata(proposal["summary"])["runId"] == "run-2026-10-26"


def test_clusters_need_a_corpus(client, tmp_path):
    run_dir = write_run_directory(tmp_path / "run")
    with pytest.raises(ValueError, match="corpus"):
        run(commands.knowledge_publish_run, "--run-dir", str(run_dir))


def snapshot_context(out: Path):
    return SimpleNamespace(writer=LocalDirectoryWriter(out), projector=Projector(), invalidate=None)


def test_entity_review_then_snapshot_end_to_end(client, tmp_path, monkeypatch, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, "--run-dir", str(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply")
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

    run(commands.knowledge_entities_accept, "--key", "model--tern-3")
    run(commands.knowledge_entities_rename, "--key", "model--tern-3", "--name", "Tern-3")
    run(commands.knowledge_entities_describe, "--key", "task--voice-cloning", "--text", "Copying a voice from a short sample.", "--reviewed")
    tern = next(row for row in client.rows["SemanticNode"].values() if row["nodeKey"] == "model--tern-3")
    assert (tern["status"], tern["displayName"], tern["aliases"]) == ("accepted", "Tern-3", ["Tern 3"])
    voice = next(row for row in client.rows["SemanticNode"].values() if row["nodeKey"] == "task--voice-cloning")
    assert description_state(voice)[0] == "reviewed"

    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19", "--json")
    index = json.loads((out / INDEX_FILE).read_text())
    keys = {entity["key"]: entity for entity in index["entities"]}
    assert keys["model--tern-3"]["itemCount"] == 2 and keys["model--tern-3"]["name"] == "Tern-3"
    assert index["conceptOfTheWeek"]["key"] == "task--voice-cloning"
    entity = json.loads((out / "_data/knowledge/entities/task--voice-cloning.json").read_text())
    assert entity["relatedItems"][0]["url"] == "/posts/alpha/"
    assert entity["description"]["state"] == "reviewed"
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
    run(commands.knowledge_entities_reject, "--key", "maker--some-lab")
    run(commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19")
    assert not (out / "_data/knowledge/entities/maker--some-lab.json").exists()


def test_snapshot_clusters_use_the_desk_name_from_the_category(client, tmp_path, monkeypatch, capsys):
    run_dir = write_run_directory(tmp_path / "run")
    run(commands.knowledge_publish_run, "--run-dir", str(run_dir), "--corpus-key", "shipped", "--category-set", "set-1", "--apply")
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
    assert beats == [{"key": "decision-models", "name": "Decision models", "href": "/topics/decision-models/", "itemCount": 1, "series8": [0, 0, 0, 0, 0, 0, 1, 0]}]


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
        run(commands.knowledge_entities_accept, "--key", "nope")
    with pytest.raises(ValueError, match="already has the name"):
        run(commands.knowledge_entities_rename, "--key", "task--voice-cloning", "--name", "code completion")
    capsys.readouterr()
    run(commands.knowledge_entities_rename, "--key", "task--voice-cloning", "--name", "Voice cloning", "--dry-run")
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
