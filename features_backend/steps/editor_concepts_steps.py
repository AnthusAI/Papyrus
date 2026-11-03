import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_idea_signal_inputs as ts  # noqa: E402
import test_monitoring_vectors as tv  # noqa: E402
from papyrus_content.ideas.signal_inputs import load_signal_inputs  # noqa: E402
from papyrus_content import monitoring_vectors as vectors  # noqa: E402
from papyrus_knowledge_query import vector_index  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402


def make_nodes(description=None):
    def node(number, name, kind, key, **more):
        return {"id": f"node-{number}-v1", "lineageId": f"node-{number}", "versionState": "current", "status": "accepted", "displayName": name, "nodeKind": kind, "nodeKey": key, **more}

    return [node(1, "fake website networks", "editor_concept", "editor_concept--fake-website-networks", description=description, aliases=[]),
            node(2, "Ada Lovelace", "personAuthor", "author.name.adalovelace"), node(3, "Coverage: AI", "coverageQuestion", "coverage.ai")]


@given('the editor concept "fake website networks" next to an author and a coverage question')
def step_nodes(context):
    context.editor = SimpleNamespace(nodes=make_nodes(), cards=None)


@given('the editor concept "fake website networks" with the description "{text}"')
def step_nodes_described(context, text):
    context.editor = SimpleNamespace(nodes=make_nodes(text), cards=None)


@when("the concept cards are prepared for those nodes")
def step_cards(context):
    nodes = context.editor.nodes

    class Graph:
        def graphql(self, query, variables):
            return {"listSemanticNodes": {"items": nodes, "nextToken": None}}

    context.editor.cards = vector_index._prepare_concept_card_vectors(Graph())


@then("the editor concept has a card and the author and the coverage question have none")
def step_only_editor(context):
    assert [card["metadata"]["nodeKey"] for card in context.editor.cards] == ["editor_concept--fake-website-networks"], context.editor.cards


@then("the card of the editor concept names the concept")
def step_names(context):
    assert "fake website networks" in context.editor.cards[0]["text"], context.editor.cards[0]["text"]


@then("the card of the editor concept holds the description")
def step_description(context):
    assert "Sites that exist to look like independent news." in context.editor.cards[0]["text"]


@given("3 accepted References of which an editor tagged one with the editor concept and the machine suggested it for another")
def step_tagged(context):
    rows = [ts.voted(number, "accepted", actor=None) for number in (1, 2, 3)]
    context.editor = SimpleNamespace(rows=rows, client=ts.TaggedClient(references=rows, tags=[ts.tag(rows[0]), ts.tag(rows[1], provenance="suggested", state="suggested")]))


@when("the idea signals read the site")
def step_read(context):
    load_signal_inputs(context.editor.client, site="example-site", now=NOW)


@then("only the tagged Reference has its concept links read")
def step_only_tagged(context):
    assert context.editor.client.relation_queries == [f"reference#{context.editor.rows[0]['lineageId']}#current"], context.editor.client.relation_queries


@when("the vector pass plans its suggestions")
def step_plan(context):
    class Client(ts.TaggedClient):
        def list_by_index(self, index, key):
            if key == "reference-links":
                return self.tags
            return [row for row in self.references if key.endswith("#accepted")] if key.endswith("#accepted") else []

    client = Client(references=context.editor.rows, tags=context.editor.client.tags, threads=[])
    rows = [{**row, "curationStatusUpdatedAt": f"2026-10-0{index + 1}T00:00:00Z"} for index, row in enumerate(context.editor.rows)]
    client.references = rows
    context.editor.order, _ = vectors.plan_since(client, {"corpusId": rows[0]["corpusId"]}, None, vectors.signal_lineages(client))


@then("the tagged Reference comes first")
def step_first(context):
    assert context.editor.order[0]["id"] == context.editor.rows[0]["id"], [row["id"] for row in context.editor.order]
