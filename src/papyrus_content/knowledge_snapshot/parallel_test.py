from __future__ import annotations

import threading

import pytest

from . import commands
from .loaders import relations_of_nodes
from .parallel import DEFAULT_WORKERS, MAXIMUM_WORKERS, map_with_clients, worker_count


class Client:
    """A stand-in client that remembers the threads that used it and what it was asked."""

    def __init__(self) -> None:
        self.threads: set[int] = set()
        self.writes: list[tuple[str, str]] = []
        self.rows = {"state-a": [{"id": "r1"}, {"id": "r2"}], "state-b": [{"id": "r2"}, {"id": "r3"}]}

    def list_semantic_relations_by_object_state(self, state):
        self.threads.add(threading.get_ident())
        return list(self.rows.get(state, []))

    def list_semantic_relations_by_subject_state(self, state):
        self.threads.add(threading.get_ident())
        return []

    def create_record(self, model, payload):
        self.writes.append((model, payload["id"]))

    update_record = upsert = create_record


def test_results_come_back_in_input_order_and_each_worker_makes_one_client_and_keeps_it():
    made: list[Client] = []

    def factory():
        made.append(Client())
        return made[-1]

    items = list(range(200))
    results = map_with_clients(items, lambda client, item: (item * 2, id(client) > 0), client=Client(), client_factory=factory, workers=4)
    assert [value for value, _ in results] == [item * 2 for item in items]
    assert 1 <= len(made) <= 4


def test_one_worker_or_no_factory_is_the_plain_loop_over_the_given_client():
    given = Client()
    seen = []
    assert map_with_clients([1, 2, 3], lambda client, item: seen.append(client) or item, client=given, client_factory=lambda: Client(), workers=1) == [1, 2, 3]
    assert map_with_clients([1, 2, 3], lambda client, item: seen.append(client) or item, client=given, client_factory=None, workers=8) == [1, 2, 3]
    assert all(client is given for client in seen) and len(seen) == 6


def test_the_first_failure_is_raised():
    def work(client, item):
        if item == 5:
            raise RuntimeError("boom")
        return item

    with pytest.raises(RuntimeError, match="boom"):
        map_with_clients(range(20), work, client=Client(), client_factory=Client, workers=4)


def test_worker_count_defaults_and_bounds():
    assert worker_count(None) == DEFAULT_WORKERS and worker_count(True) == DEFAULT_WORKERS and worker_count("3") == 3
    for bad in ("0", str(MAXIMUM_WORKERS + 1), "many", "-2"):
        with pytest.raises(ValueError, match="--parallel"):
            worker_count(bad)


def test_relations_of_nodes_is_the_same_with_workers_as_without():
    nodes = [{"lineageId": "a", "id": "a-v1"}, {"lineageId": "b", "id": "b-v1"}]
    keys = {"semanticNode#a#current": "state-a", "semanticNode#b#current": "state-b"}

    class Keyed(Client):
        def list_semantic_relations_by_object_state(self, state):
            return super().list_semantic_relations_by_object_state(keys[state])

    plain = relations_of_nodes(Keyed(), nodes)
    parallel = relations_of_nodes(Keyed(), nodes, workers=4, client_factory=Keyed)
    assert [row["id"] for row in plain] == [row["id"] for row in parallel] == ["r1", "r2", "r3"]


def test_changes_are_applied_entities_first_over_worker_clients():
    changes = [
        {"modelName": "SemanticRelation", "action": "create", "expected": {"id": f"rel-{n}"}} for n in range(10)
    ] + [{"modelName": "SemanticNode", "action": "create", "expected": {"id": f"node-{n}"}} for n in range(5)] + [{"modelName": "SemanticRelation", "action": "noop", "expected": {"id": "same"}}]
    clients: list[Client] = []

    def factory():
        clients.append(Client())
        return clients[-1]

    commands.apply_changes(Client(), changes, workers=4, client_factory=factory)
    written = [write for client in clients for write in client.writes]
    assert sorted(written) == sorted([("SemanticNode", f"node-{n}") for n in range(5)] + [("SemanticRelation", f"rel-{n}") for n in range(10)])  # the noop is not written
    given = Client()
    commands.apply_changes(given, changes, workers=4, client_factory=None)  # no factory: sequential on the given client, entities first
    assert [model for model, _ in given.writes] == ["SemanticNode"] * 5 + ["SemanticRelation"] * 10
