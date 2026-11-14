from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import commands
from .commands_test import client, run  # noqa: F401
from .keys import entity_key, name_identity, normalize_name
from .publish_run import NodeIndex


def typed_file(tmp_path: Path, *names: tuple[str, str], kind: str = "model") -> Path:
    entities = [{"id": f"e{number}", "kind": entry_kind or kind, "text": text, "state": "proposed", "entity_key": None, "span": None, "score": 0.9} for number, (entry_kind, text) in enumerate(names)]
    path = tmp_path / "entities.json"
    path.write_text(json.dumps({"schema_version": 1, "items": [{"item_id": "item-alpha", "entities": entities, "relations": []}]}))
    return path


def nodes_named(client, name: str) -> list[dict]:
    return [row for row in client.rows.get("SemanticNode", {}).values() if row["displayName"] == name]


def mentions_of(client, lineage_id: str) -> list[dict]:
    return [row for row in client.rows.get("SemanticRelation", {}).values() if row["objectLineageId"] == lineage_id and row["predicate"] == "mentions"]


def extract(client, tmp_path, *names, **kwargs):
    run(commands.knowledge_publish_run, "--entities", str(typed_file(tmp_path, *names, **kwargs)), "--apply")


def test_one_identity_serves_the_name_lookup_and_the_entity_key():
    assert name_identity("GPT-4") == name_identity("GPT 4") == name_identity("gpt  4") == "gpt-4"
    assert entity_key("model", "GPT-4") == entity_key("model", "GPT 4")
    assert normalize_name("GPT-4") != normalize_name("GPT 4"), "the old lookup told them apart, which is the bug"
    assert name_identity("日本語") == normalize_name("日本語"), "a name with no ASCII letters keeps the folded name"


def test_the_node_index_finds_a_rejected_node_by_any_spelling_of_its_name_and_aliases():
    row = {"id": "n1", "lineageId": "l1", "nodeKey": "model--gpt-4", "nodeKind": "model", "displayName": "GPT-4", "aliases": ["OpenAI GPT-4"], "status": "rejected"}
    index = NodeIndex([row])
    assert index.resolve("model", "GPT 4")["id"] == "n1" and index.resolve("model", "gpt-4")["id"] == "n1" and index.resolve("model", "openai gpt 4")["id"] == "n1"
    assert index.resolve("task", "GPT 4") is None, "the kind is still part of the identity"


@pytest.mark.parametrize("rejecter", ["ai", "human"])
def test_a_rejected_name_stays_rejected_and_gets_no_new_link_under_any_spelling(client, tmp_path, capsys, rejecter):
    extract(client, tmp_path, ("model", "GPT-4"))
    [node] = nodes_named(client, "GPT-4")
    assert node["status"] == "generated" and len(mentions_of(client, node["lineageId"])) == 1
    run(commands.knowledge_entities_reject, "--key", node["nodeKey"], "--actor", rejecter)
    rejected = dict(client.rows["SemanticNode"][node["id"]])
    assert rejected["status"] == "rejected"
    links_before = {row["id"] for row in mentions_of(client, node["lineageId"])}
    writes_before = len(client.writes)
    capsys.readouterr()

    extract(client, tmp_path, ("model", "GPT 4"))

    assert nodes_named(client, "GPT 4") == [] and len(nodes_named(client, "GPT-4")) == 1
    assert client.rows["SemanticNode"][node["id"]] == rejected, "an existing concept is never changed"
    assert {row["id"] for row in mentions_of(client, node["lineageId"])} == links_before, "the rejected lineage collects no new link"
    assert len(client.writes) == writes_before, "nothing at all was written"
    out = capsys.readouterr().out
    assert "dropped\tmodel\tGPT 4\trejected earlier" in out and "candidatesDropped.rejected earlier\t1" in out and "linksSkippedRejected\t1" in out


def test_a_rejected_name_is_dropped_with_the_same_spelling_too_and_reported(client, tmp_path, capsys):
    extract(client, tmp_path, ("model", "GPT-4"))
    [node] = nodes_named(client, "GPT-4")
    run(commands.knowledge_entities_reject, "--key", node["nodeKey"], "--actor", "ai")
    capsys.readouterr()
    run(commands.knowledge_publish_run, "--entities", str(typed_file(tmp_path, ("model", "GPT-4"))), "--json")
    plan = json.loads(capsys.readouterr().out)
    assert [(entry["name"], entry["reason"]) for entry in plan["dropped"]] == [("GPT-4", "rejected earlier")]


def test_the_rejection_is_kind_specific_so_the_same_name_of_another_kind_is_still_a_candidate(client, tmp_path):
    extract(client, tmp_path, ("model", "Mercury"))
    [node] = nodes_named(client, "Mercury")
    run(commands.knowledge_entities_reject, "--key", node["nodeKey"], "--actor", "ai")
    extract(client, tmp_path, ("organization", "Mercury"))
    assert sorted(row["nodeKind"] for row in nodes_named(client, "Mercury")) == ["model", "organization"]


def test_a_spelling_of_an_accepted_name_links_to_that_concept_and_makes_no_second_one(client, tmp_path):
    extract(client, tmp_path, ("model", "GPT-4"))
    [node] = nodes_named(client, "GPT-4")
    run(commands.knowledge_entities_accept, "--key", node["nodeKey"], "--actor", "ai")
    before = dict(client.rows["SemanticNode"][node["id"]])
    extract(client, tmp_path, ("model", "GPT 4"))
    assert nodes_named(client, "GPT 4") == [] and len(nodes_named(client, "GPT-4")) == 1
    assert client.rows["SemanticNode"][node["id"]] == before
