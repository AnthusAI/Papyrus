"""Backfill of relevance_decision_is relations for References the router delivered before #517."""
from datetime import datetime, timezone
import json

import pytest

from papyrus_content.monitoring_backfill import backfill
from papyrus_content.monitoring_cloud import DynamoStore

from test_monitoring_router import lab, table  # noqa: F401  (fixtures)


def run_backfill(lab, apply=False, **kwargs):
    lines = []
    routes = lambda: [DynamoStore._clean(item) for (_, sk), item in sorted(lab.table.items.items()) if sk.startswith("ROUTE#")]
    result = backfill(lab.table, "hn", appsync=lambda endpoint: next(c for c in lab.clients.values() if c.endpoint == endpoint),
                      apply=apply, routes=routes, emit=lines.append, **kwargs)
    return result, lines


def forget_relations(client):
    """The state before #517: the Reference exists, the decision relation and its node do not."""
    saved = {k: dict(v) for k, v in client.rows.items() if k[0] in ("SemanticRelation", "SemanticNode")
             and (k[0] == "SemanticNode" or v["predicate"] == "relevance_decision_is")}
    for key in saved:
        del client.rows[key]
    client.ops.clear()
    return saved


def test_a_delivered_include_gets_exactly_the_relation_the_router_would_have_written(lab):
    lab.cyclotron.labels = {("hn-101", "p-apyr-us"): "exclude"}
    lab.run()
    client = lab.clients["anth-us"]
    (original,) = client.relations()
    forget_relations(client)

    result, lines = run_backfill(lab)                     # dry run: the default
    assert result["counts"]["anth-us"]["planned"] == 1 and not client.writes() and not client.relations()
    assert any("label=include" in line and "plan" in line for line in lines)

    result, _ = run_backfill(lab, apply=True)
    assert result["counts"]["anth-us"]["written"] == 1
    (written,) = client.relations()
    assert written == original                             # same id, metadata and provenance as the router's own write
    assert ("SemanticNode", "semantic-node-relevance-include-v1") in client.rows
    assert not client.relations("superseded")


def test_a_reference_that_already_has_a_current_relation_is_skipped(lab):
    lab.run()
    client = lab.clients["anth-us"]
    before = dict(client.rows)
    client.ops.clear()
    result, _ = run_backfill(lab, apply=True)
    assert result["counts"]["anth-us"]["skipped: already has a current relation"] == 1
    assert not client.writes() and client.rows == before


def test_an_exclude_was_never_delivered_so_nothing_is_planned_or_read(lab):
    lab.cyclotron.labels = {("hn-101", p): "exclude" for p in ("anth-us", "p-apyr-us", "threat-intelligence")}
    lab.run(task="route")
    result, _ = run_backfill(lab, apply=True)
    assert all(not counts for counts in result["counts"].values()) and not result["writes"]
    assert not lab.clients                                 # no Reference, so no AppSync client was opened


def test_a_rerun_writes_nothing(lab):
    lab.run()
    forget_relations(lab.clients["anth-us"])
    first, _ = run_backfill(lab, apply=True)
    assert first["counts"]["anth-us"]["written"] == 1
    client = lab.clients["anth-us"]
    client.ops.clear()
    second, _ = run_backfill(lab, apply=True)
    assert second["counts"]["anth-us"] == {"delivered": 1, "skipped: already has a current relation": 1}
    assert not client.writes() and len(client.relations()) == 1


def test_publication_and_since_filters(lab):
    lab.run()
    for client in lab.clients.values():
        forget_relations(client)
    only, _ = run_backfill(lab, publication_ids=["anth-us"])
    assert set(only["counts"]) == {"anth-us"} and only["counts"]["anth-us"]["planned"] == 1
    late = datetime(2100, 1, 1, tzinfo=timezone.utc)
    result, _ = run_backfill(lab, since=late)
    assert all(c.get("skipped: before --since") == 1 and "planned" not in c for c in result["counts"].values())
    with pytest.raises(ValueError):
        run_backfill(lab, publication_ids=["nope"])


def test_a_reference_delivered_by_two_decisions_gets_only_the_latest(lab):
    from copy import deepcopy
    lab.run()
    forget_relations(lab.clients["anth-us"])
    route, disc = lab.table.items[("MONITOR#hn", "ROUTE#101#000001")], lab.table.items[("MONITOR#hn", "DISC#101#000001")]
    later = deepcopy(route)
    later.update(sk="ROUTE#101#000002", revision=2)
    later["decision"].update(decisionId="dec-hn-101-later", decidedAt="2099-01-01T00:00:00Z")
    lab.table.items[("MONITOR#hn", "ROUTE#101#000002")] = later
    lab.table.items[("MONITOR#hn", "DISC#101#000002")] = {**deepcopy(disc), "sk": "DISC#101#000002", "revision": 2}
    result, _ = run_backfill(lab, apply=True, publication_ids=["anth-us"])
    assert result["counts"]["anth-us"] == {"delivered": 2, "written": 1, "skipped: a later decision on the same Reference": 1}
    (relation,) = lab.clients["anth-us"].relations()
    assert json.loads(relation["metadata"])["decisionId"] == "dec-hn-101-later"
