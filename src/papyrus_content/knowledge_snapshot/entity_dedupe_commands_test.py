"""``knowledge entities add | merge | duplicates``, the duplicate check in ``publish-run``, and the AI review's accept path, on a fake store."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ..knowledge_cloud import ai_review as review
from . import commands
from .actors import decode_review, make_actor
from .commands_test import FakeClient, published_row
from .entity_add import DISAMBIGUATION_LINEAGE
from .keys import entity_key
from .publish_run import mention_record

NOW = "2026-11-10T00:00:00Z"
ACTOR = make_actor("ai", None, "2026-11-10")


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient([published_row("alpha", "2026-10-13T08:00:00Z"), published_row("beta", "2026-10-06T08:00:00Z")])
    monkeypatch.setattr(commands, "create_authoring_client", lambda *args, **kwargs: (fake, {}))
    return fake


def run(function, *flags) -> None:
    function(list(flags))


def seed(client, kind, name, *, status="accepted", aliases=(), description=None) -> dict:
    key = entity_key(kind, name)
    row = {
        "id": f"semantic-node-{key}-v1", "lineageId": f"semantic-node-{key}", "versionNumber": 1, "versionState": "current", "nodeKey": key, "nodeKind": kind,
        "displayName": name, "aliases": list(aliases), "status": status, "corpusId": "corpus-1",
        "changeReason": ACTOR_REASON if status == "accepted" else None,
    }
    if description:
        row["description"] = description
    client.rows.setdefault("SemanticNode", {})[row["id"]] = row
    return row


ACTOR_REASON = decode_review(None).replace(accepted_by=ACTOR).encode()


def mention(client, node, item_key, *, confirmed=True) -> dict:
    item = SimpleNamespace(key=f"lineage-{item_key}", item_id=f"item-{item_key}", kind="item")
    row = mention_record(item, node, source="extractor", confirmed=confirmed, import_run_id="seed", now=NOW)["expected"]
    client.rows.setdefault("SemanticRelation", {})[row["id"]] = row
    return row


def nodes_named(client, name):
    return [row for row in client.rows.get("SemanticNode", {}).values() if row["displayName"] == name]


def current(client, model="SemanticRelation"):
    return [row for row in client.rows.get(model, {}).values() if row.get("relationState", "current") == "current"]


# ---------------------------------------------------------------------------------------------------------- add
def test_add_creates_the_accepted_node_with_every_alias_and_a_second_run_changes_nothing(client, capsys):
    run(commands.knowledge_entities_add, "--kind", "organization", "--name", "National Transportation Safety Board", "--alias", "NTSB", "--alias", "ntsb", "--actor", "ai", "--actor-name", "Agent", "--dry-run")
    assert "created" in capsys.readouterr().out and not client.rows.get("SemanticNode")

    run(commands.knowledge_entities_add, "--kind", "organization", "--name", "National Transportation Safety Board", "--alias", "NTSB", "--alias", "ntsb", "--actor", "ai", "--actor-name", "Agent")
    [node] = nodes_named(client, "National Transportation Safety Board")
    assert (node["status"], node["nodeKey"], node["aliases"]) == ("accepted", "organization--national-transportation-safety-board", ["NTSB"])  # ntsb is NTSB: aliases are compared with case ignored
    marks = decode_review(node["changeReason"])
    assert marks.accepted_by.actor == "ai" and marks.accepted_by.name == "Agent" and marks.aliased_by.actor == "ai"

    capsys.readouterr()
    before = len(client.writes)
    run(commands.knowledge_entities_add, "--kind", "organization", "--name", "National Transportation Safety Board", "--alias", "NTSB", "--actor", "ai")
    assert "found" in capsys.readouterr().out and len(client.writes) == before


def test_add_finds_a_generated_node_accepts_it_and_adds_the_aliases_in_one_write(client, capsys):
    seed(client, "software", "Model Context Protocol", status="generated")
    run(commands.knowledge_entities_add, "--kind", "software", "--name", "Model Context Protocol", "--alias", "MCP", "--actor", "human", "--actor-name", "Ryan")
    [node] = nodes_named(client, "Model Context Protocol")
    assert (node["status"], node["aliases"]) == ("accepted", ["MCP"])
    marks = decode_review(node["changeReason"])
    assert marks.accepted_by.actor == "human" and marks.aliased_by.name == "Ryan"
    assert [write for write in client.writes if write[1] == "SemanticNode"] == [("update", "SemanticNode", node["id"])]


def test_add_refuses_a_rejected_node_a_duplicate_a_taken_alias_and_an_email(client):
    seed(client, "person", "Elon Musk")
    seed(client, "person", "Gone Person", status="rejected")
    seed(client, "software", "Protocol A", aliases=["PA"])
    with pytest.raises(ValueError, match="was rejected"):
        run(commands.knowledge_entities_add, "--kind", "person", "--name", "Gone Person", "--actor", "ai")
    with pytest.raises(ValueError, match="looks like 'Elon Musk'"):
        run(commands.knowledge_entities_add, "--kind", "person", "--name", "Musk", "--actor", "ai")
    with pytest.raises(ValueError, match="already has one of these names"):
        run(commands.knowledge_entities_add, "--kind", "software", "--name", "Protocol B", "--alias", "PA", "--actor", "ai")
    with pytest.raises(ValueError, match="email"):
        run(commands.knowledge_entities_add, "--kind", "software", "--name", "Protocol B", "--alias", "me@example.org", "--actor", "ai")
    with pytest.raises(ValueError, match="requires --kind"):
        run(commands.knowledge_entities_add, "--name", "x", "--actor", "ai")
    with pytest.raises(ValueError, match="requires --actor"):
        run(commands.knowledge_entities_add, "--kind", "software", "--name", "x")
    assert len(client.rows["SemanticNode"]) == 3


def test_add_tags_disambiguation_on_a_name_shared_across_kinds_and_on_every_entity_in_the_clash(client, monkeypatch, capsys):
    maker = seed(client, "maker", "Mistral")
    concept = seed(client, "concept", "Reasoning")
    made, linked = [], []
    monkeypatch.setattr("papyrus_content.signed_in_concepts.create_editor_concept", lambda c, typed, shown=None: made.append((typed, shown)) or {"ok": True})
    monkeypatch.setattr("papyrus_content.signed_in_concepts.create_concept_link", lambda c, *, subject, object_, note: linked.append((subject, object_, note)) or {"outcome": "created", "relationId": f"rel-{len(linked)}"})

    run(commands.knowledge_entities_add, "--kind", "model", "--name", "Mistral", "--alias", "Reasoning", "--actor", "ai", "--dry-run")
    assert not made and not linked and "tag\tDisambiguation" in capsys.readouterr().out

    run(commands.knowledge_entities_add, "--kind", "model", "--name", "Mistral", "--alias", "Reasoning", "--actor", "ai")
    [model] = [row for row in client.rows["SemanticNode"].values() if row["nodeKind"] == "model"]
    assert made == [("Disambiguation", "Disambiguation")]
    assert {subject for subject, _, _ in linked} == {model["lineageId"], maker["lineageId"], concept["lineageId"]}
    assert {object_ for _, object_, _ in linked} == {DISAMBIGUATION_LINEAGE}
    note = next(note for subject, _, note in linked if subject == maker["lineageId"])
    assert "'Mistral' names Mistral (model) and also Mistral (maker)" in note and "do not merge them" in note

    # The Disambiguation concept exists now: a second ambiguous add makes no second concept.
    made.clear()
    client.rows["SemanticNode"]["d"] = {"id": "d", "lineageId": DISAMBIGUATION_LINEAGE, "versionState": "current", "status": "accepted", "nodeKind": "concept", "nodeKey": "concept--disambiguation", "displayName": "Disambiguation", "aliases": []}
    seed(client, "software", "Mercury")
    run(commands.knowledge_entities_add, "--kind", "model", "--name", "Mercury", "--actor", "ai")
    assert not made


def test_a_name_that_is_unique_gets_no_disambiguation(client, monkeypatch):
    seed(client, "maker", "Some Lab")
    called = []
    monkeypatch.setattr("papyrus_content.signed_in_concepts.create_concept_link", lambda *a, **k: called.append(k))
    run(commands.knowledge_entities_add, "--kind", "model", "--name", "Other Model", "--actor", "ai")
    assert not called


# --------------------------------------------------------------------------------------------------------- merge
def two_entities(client):
    keep = seed(client, "person", "Elon Musk", aliases=["E. Musk"])
    gone = seed(client, "person", "Musk", aliases=["Musk, Elon"], description="Entrepreneur.")
    return keep, gone


def test_merge_supersedes_the_duplicate_moves_names_and_relations_and_is_idempotent(client, capsys):
    keep, gone = two_entities(client)
    moved = mention(client, gone, "alpha")
    shared_keep, shared_gone = mention(client, keep, "beta", confirmed=True), mention(client, gone, "beta", confirmed=False)
    between = {**moved, "id": "between", "subjectKind": "semanticNode", "subjectId": keep["id"], "subjectLineageId": keep["lineageId"], "subjectStateKey": f"semanticNode#{keep['lineageId']}"}
    client.rows["SemanticRelation"]["between"] = {**between, "objectId": gone["id"], "objectLineageId": gone["lineageId"], "predicate": "related_to"}

    run(commands.knowledge_entities_merge, "--from", gone["nodeKey"], "--into", keep["nodeKey"], "--actor", "ai", "--dry-run")
    out = capsys.readouterr().out
    assert "dry-run" in out and "never takes a page down" in out and client.rows["SemanticNode"][gone["id"]]["status"] == "accepted"

    run(commands.knowledge_entities_merge, "--from", gone["nodeKey"], "--into", keep["nodeKey"], "--actor", "human", "--actor-name", "Ryan")
    survivor = client.rows["SemanticNode"][keep["id"]]
    assert survivor["aliases"] == ["E. Musk", "Musk", "Musk, Elon"] and survivor["description"] == "Entrepreneur." and survivor["status"] == "accepted"
    marks = decode_review(survivor["changeReason"])
    assert marks.merged_by.name == "Ryan" and marks.aliased_by.actor == "human" and marks.accepted_by.actor == "ai"
    superseded = client.rows["SemanticNode"][gone["id"]]
    assert (superseded["versionState"], superseded["status"]) == ("superseded", "superseded")
    assert decode_review(superseded["changeReason"]).merged_by.name == "Ryan"

    live = current(client)
    assert not [row for row in live if gone["lineageId"] in (row["objectLineageId"], row["subjectLineageId"])]
    on_survivor = [row for row in live if keep["lineageId"] in (row["objectLineageId"], row["subjectLineageId"])]
    # alpha's mention moved with its metadata; beta's was already there (kept as it was, confirmed); the relation between the two is gone.
    assert sorted(row["subjectLineageId"] for row in on_survivor) == ["lineage-alpha", "lineage-beta"]
    assert json.loads(next(row for row in on_survivor if row["subjectLineageId"] == "lineage-beta")["metadata"])["confirmed"] is True
    assert json.loads(next(row for row in on_survivor if row["subjectLineageId"] == "lineage-alpha")["metadata"])["confirmed"] is True
    assert client.rows["SemanticRelation"][shared_keep["id"]]["relationState"] == "current"
    assert client.rows["SemanticRelation"][shared_gone["id"]]["relationState"] == "superseded"

    before = len(client.writes)
    with pytest.raises(ValueError, match="No entity"):
        run(commands.knowledge_entities_merge, "--from", gone["nodeKey"], "--into", keep["nodeKey"], "--actor", "ai")
    assert len(client.writes) == before


def test_merge_refuses_what_it_should(client):
    keep, gone = two_entities(client)
    other_kind = seed(client, "organization", "Musk Foundation")
    generated = seed(client, "person", "Generated Person", status="generated")
    rejected = seed(client, "person", "Rejected Person", status="rejected")
    third = seed(client, "person", "Third Person", aliases=["Musk, Elon"])
    with pytest.raises(ValueError, match="into itself"):
        run(commands.knowledge_entities_merge, "--from", keep["nodeKey"], "--into", keep["nodeKey"], "--actor", "ai")
    with pytest.raises(ValueError, match="different kinds"):
        run(commands.knowledge_entities_merge, "--from", other_kind["nodeKey"], "--into", keep["nodeKey"], "--actor", "ai")
    with pytest.raises(ValueError, match="not accepted"):
        run(commands.knowledge_entities_merge, "--from", gone["nodeKey"], "--into", generated["nodeKey"], "--actor", "ai")
    with pytest.raises(ValueError, match="rejected"):
        run(commands.knowledge_entities_merge, "--from", rejected["nodeKey"], "--into", keep["nodeKey"], "--actor", "ai")
    with pytest.raises(ValueError, match="already has the name 'Musk, Elon'"):
        run(commands.knowledge_entities_merge, "--from", gone["nodeKey"], "--into", keep["nodeKey"], "--actor", "ai")
    with pytest.raises(ValueError, match="requires --from"):
        run(commands.knowledge_entities_merge, "--into", keep["nodeKey"], "--actor", "ai")
    with pytest.raises(ValueError, match="requires --actor"):
        run(commands.knowledge_entities_merge, "--from", gone["nodeKey"], "--into", keep["nodeKey"])
    assert third["status"] == "accepted" and all(row["status"] != "superseded" for row in client.rows["SemanticNode"].values())


def test_after_a_merge_the_registry_resolves_the_old_spelling_to_the_survivor(client, tmp_path):
    keep, gone = two_entities(client)
    run(commands.knowledge_entities_merge, "--from", gone["nodeKey"], "--into", keep["nodeKey"], "--actor", "ai")
    out = tmp_path / "registry.json"
    run(commands.knowledge_entities_registry, "--out", str(out))
    [entry] = json.loads(out.read_text())
    assert entry["key"] == keep["nodeKey"] and "Musk" in entry["aliases"]


# ---------------------------------------------------------------------------------------------------- duplicates
def test_duplicates_lists_the_pairs_read_only_and_json_is_machine_readable(client, capsys):
    seed(client, "organization", "National Transportation Safety Board")
    seed(client, "organization", "NTSB")
    seed(client, "model", "AlphaGo")
    seed(client, "model", "AlphaGo Zero")
    before = len(client.writes)
    run(commands.knowledge_entities_duplicates)
    out = capsys.readouterr().out
    assert "organization--ntsb\torganization--national-transportation-safety-board\tacronym\tpropose\tmerge --from organization--ntsb --into organization--national-transportation-safety-board" in out
    assert "1 pairs" in out and "alphago" not in out and len(client.writes) == before
    run(commands.knowledge_entities_duplicates, "--kind", "model")
    assert "0 pairs" in capsys.readouterr().out
    run(commands.knowledge_entities_duplicates, "--json")
    assert json.loads(capsys.readouterr().out)[0]["rule"] == "acronym"


# ------------------------------------------------------------------------------------------------------ publish-run
def typed_file(tmp_path, *entities):
    path = tmp_path / "entities.json"
    rows = [{"id": f"e{index}", "kind": kind, "text": text, "state": "proposed", "entity_key": None, "span": None, "score": 0.9} for index, (kind, text) in enumerate(entities)]
    path.write_text(json.dumps({"schema_version": 1, "items": [{"item_id": "item-alpha", "entities": rows, "relations": []}]}))
    return str(path)


def mentions_of(client, node):
    return [row for row in current(client) if row["objectLineageId"] == node["lineageId"]]


def test_publish_run_links_a_respelled_name_to_the_entity_and_adds_it_as_an_alias(client, tmp_path, capsys):
    uk = seed(client, "organization", "The UK AI Security Institute")
    run(commands.knowledge_publish_run, "--entities", typed_file(tmp_path, ("organization", "And the UK AI Security Institute"), ("organization", "And the UK AI Security Institute")), "--skip-front-matter", "--corpus-key", "shipped", "--apply")
    out = capsys.readouterr().out
    assert "duplicate\tresolved" in out and "duplicatesResolved\t1" in out
    assert len(client.rows["SemanticNode"]) == 1
    assert client.rows["SemanticNode"][uk["id"]]["aliases"] == ["And the UK AI Security Institute"]
    assert len(mentions_of(client, uk)) == 1
    assert decode_review(client.rows["SemanticNode"][uk["id"]]["changeReason"]).aliased_by.name == "extractor resolution"


def test_publish_run_makes_no_node_for_a_look_alike_and_files_one_proposal_for_a_person(client, tmp_path, capsys):
    seed(client, "organization", "Redwood Research")
    seed(client, "person", "Elon Musk")
    flags = ("--entities", typed_file(tmp_path, ("organization", "Redwood"), ("person", "Musk"), ("organization", "Redwood")), "--skip-front-matter", "--corpus-key", "shipped", "--apply")
    run(commands.knowledge_publish_run, *flags)
    assert capsys.readouterr().out.count("duplicate\tproposed") == 3
    assert sorted(row["displayName"] for row in client.rows["SemanticNode"].values()) == ["Elon Musk", "Redwood Research"]
    assert not client.rows.get("SemanticRelation")
    proposals = client.rows["SteeringProposal"]
    assert sorted(row["proposalKind"] for row in proposals.values()) == ["entity-alias-edit", "entity-alias-edit"]
    assert {row["graphEntityId"] for row in proposals.values()} == {"organization--redwood-research", "person--elon-musk"}
    assert all(row["status"] == "proposed" and row["corpusId"] for row in proposals.values())
    # A second run files nothing new and leaves a person's decision on a proposal alone.
    decided = next(iter(proposals))
    proposals[decided]["status"] = "rejected"
    run(commands.knowledge_publish_run, *flags)
    assert len(client.rows["SteeringProposal"]) == 2 and client.rows["SteeringProposal"][decided]["status"] == "rejected"


def test_publish_run_without_a_corpus_holds_the_candidate_back_and_says_why(client, tmp_path, capsys):
    seed(client, "organization", "Redwood Research")
    run(commands.knowledge_publish_run, "--entities", typed_file(tmp_path, ("organization", "Redwood")), "--skip-front-matter", "--apply")
    out = capsys.readouterr().out
    assert "duplicate\theld" in out and "no --corpus-key or --corpus-id" in out
    assert len(client.rows["SemanticNode"]) == 1 and not client.rows.get("SteeringProposal")


def test_publish_run_still_makes_a_node_for_a_distinct_name(client, tmp_path):
    seed(client, "model", "AlphaGo")
    run(commands.knowledge_publish_run, "--entities", typed_file(tmp_path, ("model", "AlphaGo Zero"), ("concept", "Reinforcement learning"), ("concept", "RLHF")), "--skip-front-matter", "--corpus-key", "shipped", "--apply")
    assert sorted(row["displayName"] for row in client.rows["SemanticNode"].values()) == ["AlphaGo", "AlphaGo Zero", "RLHF", "Reinforcement learning"]
    assert not client.rows.get("SteeringProposal")


# ------------------------------------------------------------------------------------------------------ AI review
class AcceptingModel:
    """A reviewer that accepts every candidate on a quote of the snippet."""

    calls = 0

    def exhausted(self):
        return False

    def judge(self, task, payload):
        return {row["id"]: {"id": row["id"], "verdict": "accept", "evidence": [row["snippets"][0]], "about": True, "name": row["name"], "reason": "described"} for row in payload}


TEXT = "Redwood announced a new alignment programme this week. Pilot Lab described the programme in detail, and Elon Musk said Musk would attend."


def typed_run(*entities):
    rows = []
    for index, (kind, name) in enumerate(entities):
        start = TEXT.index(name)
        rows.append({"id": f"e{index}", "kind": kind, "text": name, "span": {"start": start, "end": start + len(name)}})
    return review.TypedRun({"items": [{"item_id": "i1", "entities": rows, "relations": []}]}, {"i1": TEXT})


def test_the_ai_review_holds_back_a_possible_duplicate_and_files_a_merge_proposal(client):
    accepted = seed(client, "organization", "Redwood Research")
    dup = seed(client, "organization", "Redwood", status="generated")
    fine = seed(client, "organization", "Pilot Lab", status="generated")
    typed = typed_run(("organization", "Redwood"), ("organization", "Pilot Lab"))
    proposals: list[dict] = []
    patches, decisions = review.review_entities([dup, fine], typed, lambda n: [], AcceptingModel(), ACTOR, now=NOW, vocabulary={"organization": "Organization"}, accepted=[accepted], proposals=proposals)
    by_subject = {d.subject: d for d in decisions}
    held = by_subject["organization: Redwood"]
    assert (held.verdict, held.gate, held.applied) == ("unsure", review.GATE_POSSIBLE_DUPLICATE, False) and "Redwood Research" in held.reason
    assert by_subject["organization: Pilot Lab"].applied is True
    assert [patch["expected"]["id"] for patch in patches if patch["expected"].get("status") == "accepted"] == [fine["id"]]
    [proposal] = proposals
    assert (proposal["proposalKind"], proposal["graphEntityId"], proposal["corpusId"]) == ("merge-graph-entity", accepted["nodeKey"], "corpus-1")
    assert f"knowledge entities merge --from {dup['nodeKey']} --into {accepted['nodeKey']}" in proposal["description"]
    changes = review.proposal_changes([proposal, proposal], client.get_record)
    assert len(changes) == 1 and changes[0]["action"] == "create"
    client.rows["SteeringProposal"] = {proposal["id"]: proposal}
    assert review.proposal_changes([proposal], client.get_record) == []


def test_a_node_accepted_in_the_pass_counts_for_the_nodes_after_it(client):
    first = seed(client, "person", "Elon Musk", status="generated")
    second = seed(client, "person", "Musk", status="generated")
    typed = typed_run(("person", "Elon Musk"), ("person", "Musk"))
    proposals: list[dict] = []
    patches, decisions = review.review_entities([first, second], typed, lambda n: [], AcceptingModel(), ACTOR, now=NOW, vocabulary={}, accepted=[], proposals=proposals)
    assert sum(1 for d in decisions if d.applied) == 1 and len(proposals) == 1 and proposals[0]["proposalKind"] == "merge-graph-entity"


def test_without_accepted_nodes_the_review_behaves_as_before(client):
    dup = seed(client, "organization", "Redwood", status="generated")
    typed = typed_run(("organization", "Redwood"))
    patches, decisions = review.review_entities([dup], typed, lambda n: [], AcceptingModel(), ACTOR, now=NOW, vocabulary={})
    assert decisions[0].applied is True
