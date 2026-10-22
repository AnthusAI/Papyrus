from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot.actors import Actor  # noqa: E402
from papyrus_content.knowledge_snapshot.builder import INDEX_FILE, build_files, entity_file  # noqa: E402
from papyrus_content.knowledge_snapshot.keys import slug  # noqa: E402
from papyrus_content.knowledge_snapshot.model import (  # noqa: E402
    EntityNode, ItemLink, KnowledgeData, NodeRelation, PublishedItem, SnapshotOptions,
)
from papyrus_content.knowledge_wiki.pages import entity_body  # noqa: E402
from papyrus_content.relation_types import load_semantic_relation_type_seeds  # noqa: E402

AI = Actor("ai", None, "2026-10-12")
OPTIONS = SnapshotOptions(as_of=date(2026, 10, 19))


def _state(context):
    if not hasattr(context, "knowledge"):
        context.knowledge = {"items": [], "nodes": {}, "links": [], "relations": []}
    return context.knowledge


def _add(context, kind, name, item_name):
    state = _state(context)
    key = f"{slug(kind)}--{slug(name)}"
    node = EntityNode(lineage_id=f"semantic-node-{key}", node_key=key, kind=kind, name=name, status="accepted", accepted_by=AI)
    state["nodes"][name] = node
    if not any(item.key == f"lineage-{item_name}" for item in state["items"]):
        state["items"].append(PublishedItem(key=f"lineage-{item_name}", item_id=f"item-{item_name}", title=f"Title {item_name}",
                                            url=f"/items/{item_name}/", published_at="2026-10-19T09:30:00Z"))
    state["links"].append(ItemLink(item_key=f"lineage-{item_name}", node_lineage_id=node.lineage_id, confirmed=True))


@given('an accepted model "{model}" and an accepted model family "{family}" mentioned in one item')
def step_model_and_family(context, model, family):
    _add(context, "model", model, "first")
    _add(context, "model_family", family, "first")


@given('an accepted model "{model}" mentioned in another item')
def step_other_model(context, model):
    _add(context, "model", model, "second")


@given('a confirmed "{predicate}" relation from the model "{model}" to the family "{family}"')
def step_relation(context, predicate, model, family):
    nodes = _state(context)["nodes"]
    _state(context)["relations"].append(NodeRelation(nodes[model].lineage_id, nodes[family].lineage_id, predicate, confirmed=True))


@when("the knowledge snapshot is built")
def step_build(context):
    state = _state(context)
    data = KnowledgeData(items=tuple(state["items"]), nodes=tuple(state["nodes"].values()), links=tuple(state["links"]),
                         relations=tuple(state["relations"]))
    context.files = build_files(data, OPTIONS)


@then('the snapshot lists the kinds "{first}" and "{second}" with the labels "{first_label}" and "{second_label}"')
def step_kinds(context, first, second, first_label, second_label):
    labels = {row["key"]: row["label"] for row in context.files[INDEX_FILE]["kinds"]}
    assert labels == {first: first_label, second: second_label}, labels


def _body(context, name):
    node = _state(context)["nodes"][name]
    return entity_body(name, node.kind, [], None, node.node_key)


@then('the wiki page text for "{name}" says it is listed as a "{kind}"')
def step_wiki_text(context, name, kind):
    text = _body(context, name)
    assert f"{name} is listed here as a {kind}." in text, text


def _neighbours(context, name, predicate):
    key = _state(context)["nodes"][name].node_key
    return [row["name"] for row in context.files[entity_file(key)]["neighbours"] if row["relation"] == predicate]


@then('the neighbours of "{name}" include "{other}" as "{predicate}"')
def step_neighbour(context, name, other, predicate):
    assert _neighbours(context, name, predicate) == [other], _neighbours(context, name, predicate)


@then('"{name}" has no "{predicate}" neighbour')
def step_no_neighbour(context, name, predicate):
    assert _neighbours(context, name, predicate) == []


@when('the seeded relation type "{key}" is read')
def step_lookup(context, key):
    context.relation_type = next(entry for entry in load_semantic_relation_type_seeds() if entry["key"] == key)


@then('it is an ontology relation labelled "{label}" that runs from a semantic node to a semantic node')
def step_ontology(context, label):
    seed = context.relation_type
    assert (seed["domain"], seed["label"]) == ("ontology", label)
    assert (seed["allowedSubjectKinds"], seed["allowedObjectKinds"]) == (["semanticNode"], ["semanticNode"])


@then("it is not transitive or symmetric")
def step_flags(context):
    assert not context.relation_type["isTransitive"] and not context.relation_type["isSymmetric"]
