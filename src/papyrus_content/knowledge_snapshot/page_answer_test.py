"""The extractor's page answer rides on the concept, decides its public page together with the editor's decision, and orders the review (PPY-ce6234)."""

from __future__ import annotations

import json
from pathlib import Path

from ..knowledge_cloud import ai_review
from ..knowledge_wiki.sync import eligible_nodes, entity_specs
from . import commands
from .actors import ACTOR_HUMAN, Actor, decode_review
from .builder import build_files
from .commands_test import client, run  # noqa: F401
from .loaders import entity_node
from .model import EntityNode, ItemLink, KnowledgeData, SnapshotOptions
from .page_answer import PAGE_FIELD, PageAnswer, decode_page_answer, page_label, page_order_key, page_override

NOW = "2026-11-05T00:00:00Z"


def typed_file(tmp_path: Path, *names: tuple[str, float | None, int | None], run_name: str = "entities.json") -> Path:
    entities = []
    for number, (text, score, documents) in enumerate(names):
        page = {} if score is None else {"page_score": score, "page_answer": score >= 0.5, "page_documents": documents}
        entities.append({"id": f"e{number}", "kind": "task", "text": text, "state": "proposed", "entity_key": None, "span": None, "score": 0.9, **page})
    path = tmp_path / run_name
    path.write_text(json.dumps({"schema_version": 1, "items": [{"item_id": "item-alpha", "entities": entities, "relations": []}]}))
    return path


def publish(tmp_path, *names, run_name="entities.json"):
    run(commands.knowledge_publish_run, "--entities", str(typed_file(tmp_path, *names, run_name=run_name)), "--apply")


def node_named(client, name):
    return next(row for row in client.rows["SemanticNode"].values() if row["displayName"] == name)


def test_a_new_concept_carries_the_page_answer_and_the_document_count(client, tmp_path):
    publish(tmp_path, ("Tern Migration", 0.83, 4), ("Kestrel Study", 0.0, 1))
    stored = decode_page_answer(node_named(client, "Tern Migration")[PAGE_FIELD])
    assert (stored.score, stored.answer, stored.documents) == (0.83, True, 4) and stored.run_id
    single = decode_page_answer(node_named(client, "Kestrel Study")[PAGE_FIELD])
    assert (single.score, single.answer, single.documents) == (0.0, False, 1)


def test_a_concept_from_an_output_without_the_page_fields_has_no_answer(client, tmp_path):
    publish(tmp_path, ("Tern Migration", None, None))
    assert PAGE_FIELD not in node_named(client, "Tern Migration")


def test_a_later_run_updates_the_answer_and_a_run_that_finds_nothing_new_writes_nothing(client, tmp_path):
    publish(tmp_path, ("Tern Migration", 0.2, 1))
    node = node_named(client, "Tern Migration")
    writes = len(client.writes)
    publish(tmp_path, ("Tern Migration", 0.2, 1), run_name="again.json")
    assert len(client.writes) == writes
    publish(tmp_path, ("Tern Migration", 0.9, 3), run_name="third.json")
    updated = node_named(client, "Tern Migration")
    assert decode_page_answer(updated[PAGE_FIELD]).score == 0.9 and decode_page_answer(updated[PAGE_FIELD]).documents == 3
    assert {key: updated[key] for key in updated if key not in (PAGE_FIELD, "updatedAt")} == {key: node[key] for key in node if key not in (PAGE_FIELD, "updatedAt")}
    assert client.writes[writes:] == [("update", "SemanticNode", node["id"])]


def test_an_editors_decision_is_never_overwritten_by_a_run(client, tmp_path):
    publish(tmp_path, ("Tern Migration", 0.9, 3))
    node = node_named(client, "Tern Migration")
    run(commands.knowledge_entities_page, "--key", node["nodeKey"], "--set", "no", "--actor", "human", "--actor-name", "Ada")
    marks_before = node_named(client, "Tern Migration")["changeReason"]
    publish(tmp_path, ("Tern Migration", 0.1, 2), run_name="later.json")
    after = node_named(client, "Tern Migration")
    assert after["changeReason"] == marks_before and page_override(after) is False
    assert decode_page_answer(after[PAGE_FIELD]).score == 0.1  # the machine's answer moved, the decision did not


def test_a_rejected_concept_gets_no_answer(client, tmp_path):
    publish(tmp_path, ("Tern Migration", 0.9, 3))
    node = node_named(client, "Tern Migration")
    run(commands.knowledge_entities_reject, "--key", node["nodeKey"], "--actor", "human")
    publish(tmp_path, ("Tern Migration", 0.1, 5), run_name="later.json")
    assert decode_page_answer(node_named(client, "Tern Migration")[PAGE_FIELD]).score == 0.9


def accepted(name, **fields):
    row = {"id": f"id-{name}", "lineageId": f"lineage-{name}", "nodeKey": f"task--{name.lower()}", "nodeKind": "task", "displayName": name, "status": "accepted", **fields}
    return row


def answer(score, documents, answer=None):
    return PageAnswer(score, score >= 0.5 if answer is None else answer, documents, "run").encode()


def test_a_concept_has_a_page_by_the_editor_else_the_answer_else_as_before():
    assert entity_node(accepted("Legacy")).has_page and entity_node(accepted("Legacy")).page_answer is None  # no answer yet: keeps its page
    assert entity_node(accepted("Yes", pageAnswer=answer(0.7, 3))).has_page
    assert not entity_node(accepted("No", pageAnswer=answer(0.3, 3))).has_page
    given = Actor(actor=ACTOR_HUMAN, name="Ada", on="2026-11-05")
    from .actors import ReviewMarks

    gives = accepted("Given", pageAnswer=answer(0.1, 2), changeReason=ReviewMarks(page_given_by=given).encode())
    takes = accepted("Taken", pageAnswer=answer(0.9, 2), changeReason=ReviewMarks(page_taken_by=given).encode())
    assert entity_node(gives).has_page and not entity_node(takes).has_page
    assert entity_node(gives).page_documents == 2 and entity_node(gives).page_override is True


def test_a_stored_answer_that_is_not_in_the_shape_is_no_answer():
    for bad in (None, "", "not json", "{}", '{"score": "x", "answer": true, "documents": 1}', '{"score": 0.5, "answer": "yes", "documents": 1}', '{"score": 0.5, "answer": true, "documents": -1}'):
        assert decode_page_answer(bad) is None
    assert entity_node(accepted("Odd", pageAnswer="not json")).has_page


def knowledge(*nodes):
    links = tuple(ItemLink(item_key="item-1", node_lineage_id=node.lineage_id, confirmed=True) for node in nodes)
    return KnowledgeData(nodes=tuple(nodes), links=links)


def test_only_concepts_whose_page_answer_is_yes_get_a_page_and_the_rest_stay_filed_and_linked():
    nodes = [entity_node(accepted(name, **fields)) for name, fields in {"Yes": {"pageAnswer": answer(0.8, 3)}, "No": {"pageAnswer": answer(0.2, 3)}, "Legacy": {}}.items()]
    data = knowledge(*nodes)
    assert [node.name for node in eligible_nodes(data)] == ["Yes", "Legacy"]
    assert sorted(spec.front_matter["title"] for spec in entity_specs(data, {})) == ["Legacy", "Yes"]
    assert all(link.confirmed for link in data.links) and {node.name for node in data.nodes} == {"Yes", "No", "Legacy"}  # still accepted, filed and linked


def test_an_editor_can_give_a_page_against_a_no_and_take_it_from_a_yes():
    from .actors import ReviewMarks

    ada = Actor(actor=ACTOR_HUMAN, name="Ada", on="2026-11-05")
    nodes = [
        entity_node(accepted("Given", pageAnswer=answer(0.1, 2), changeReason=ReviewMarks(page_given_by=ada).encode())),
        entity_node(accepted("Taken", pageAnswer=answer(0.9, 5), changeReason=ReviewMarks(page_taken_by=ada).encode())),
    ]
    assert [node.name for node in eligible_nodes(knowledge(*nodes))] == ["Given"]


def test_the_snapshot_links_only_to_concepts_that_have_a_page():
    from datetime import date

    from .model import PublishedItem

    item = PublishedItem(key="item-1", item_id="i1", title="One", url="/posts/one/", published_at="2026-10-13T08:00:00Z")
    nodes = [entity_node(accepted("Yes", pageAnswer=answer(0.8, 3))), entity_node(accepted("No", pageAnswer=answer(0.2, 3)))]
    data = KnowledgeData(items=(item,), nodes=tuple(nodes), links=tuple(ItemLink("item-1", node.lineage_id, True) for node in nodes))
    files = build_files(data, SnapshotOptions(as_of=date(2026, 10, 19), entity_href_template="/wiki/{slug}/"))
    hrefs = {entity["name"]: entity["href"] for entity in files[next(path for path in files if path.endswith("index.json"))]["entities"]}
    assert hrefs["Yes"] and hrefs["No"] is None


def test_the_page_command_gives_takes_and_hands_back_and_says_what_it_does(client, tmp_path, capsys):
    publish(tmp_path, ("Tern Migration", 0.2, 3))
    key = node_named(client, "Tern Migration")["nodeKey"]
    flags = ("--key", key, "--actor", "human", "--actor-name", "Ada")
    run(commands.knowledge_entities_page, *flags, "--set", "yes", "--dry-run")
    assert page_override(node_named(client, "Tern Migration")) is None
    run(commands.knowledge_entities_page, *flags, "--set", "yes")
    node = node_named(client, "Tern Migration")
    assert page_override(node) is True and decode_review(node["changeReason"]).page_given_by.name == "Ada"
    assert entity_node({**node, "status": "accepted"}).has_page  # against the machine's no
    run(commands.knowledge_entities_page, *flags, "--set", "no")
    node = node_named(client, "Tern Migration")
    assert page_override(node) is False and decode_review(node["changeReason"]).page_given_by is None
    writes = len(client.writes)
    run(commands.knowledge_entities_page, *flags, "--set", "no")  # already decided: nothing written
    assert len(client.writes) == writes
    run(commands.knowledge_entities_page, *flags, "--set", "machine")
    assert page_override(node_named(client, "Tern Migration")) is None
    for bad in ("maybe", None):
        try:
            run(commands.knowledge_entities_page, *flags, *(("--set", bad) if bad else ()))
        except ValueError as error:
            assert "--set yes, no or machine" in str(error)
        else:
            raise AssertionError("a missing or unknown choice is refused")


def test_the_page_command_refuses_a_rejected_concept(client, tmp_path):
    publish(tmp_path, ("Tern Migration", 0.2, 3))
    key = node_named(client, "Tern Migration")["nodeKey"]
    run(commands.knowledge_entities_reject, "--key", key, "--actor", "human")
    try:
        run(commands.knowledge_entities_page, "--key", key, "--set", "yes", "--actor", "human")
    except ValueError as error:
        assert "rejected" in str(error)
    else:
        raise AssertionError("a rejected concept has no page to give")


def test_concepts_are_listed_for_review_by_page_score_with_the_document_count_and_no_cut_off(client, tmp_path, capsys):
    publish(tmp_path, ("Alder Study", 0.40, 9), ("Birch Study", 0.91, 2), ("Cedar Study", 0.91, 7), ("Dune Study", None, None), ("Elm Study", 0.0, 1))
    capsys.readouterr()
    run(commands.knowledge_entities_list)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.count("\t") > 3]
    names = [line.split("\t")[3] for line in lines]
    assert names == ["Cedar Study", "Birch Study", "Alder Study", "Elm Study", "Dune Study"]  # score, then documents; no answer last; nothing dropped
    assert lines[0].split("\t")[5:7] == ["0.91", "7"] and lines[-1].split("\t")[5:7] == ["-", "-"]


def test_an_editors_decision_is_shown_beside_the_score():
    from .actors import ReviewMarks

    row = {"id": "x", "displayName": "X", PAGE_FIELD: answer(0.3, 2), "changeReason": ReviewMarks(page_given_by=Actor(ACTOR_HUMAN, None, "2026-11-05")).encode()}
    assert page_label(row) == "0.30\t2\tpage: yes"
    assert page_order_key({"id": "a", "displayName": "A", PAGE_FIELD: answer(0.9, 1)}) < page_order_key({"id": "b", "displayName": "B", PAGE_FIELD: answer(0.8, 50)})


def test_the_ai_review_takes_the_concepts_the_extractor_thinks_most_page_worthy_first():
    class Typed:
        def entity_snippets(self, kind, names):
            return ["a sentence"]

    nodes = [
        {"id": "a", "displayName": "Alder", "nodeKind": "task", PAGE_FIELD: answer(0.2, 9)},
        {"id": "b", "displayName": "Birch", "nodeKind": "task"},
        {"id": "c", "displayName": "Cedar", "nodeKind": "task", PAGE_FIELD: answer(0.95, 2)},
        {"id": "d", "displayName": "Dune", "nodeKind": "task", PAGE_FIELD: answer(0.95, 6)},
    ]
    ordered = [entry["node"]["displayName"] for entry in ai_review.entity_candidates(nodes, Typed()).values()]
    assert ordered == ["Dune", "Cedar", "Alder", "Birch"]
