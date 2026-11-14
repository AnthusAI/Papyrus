import json
import subprocess
from pathlib import Path

from behave import then, when

REPO_ROOT = Path(__file__).resolve().parents[2]


def probe(context, names, describe=None):
    payload = json.dumps({"names": names, **({"describe": describe} if describe else {})})
    done = subprocess.run(["npx", "tsx", str(REPO_ROOT / "scripts" / "editor-concept-probe.ts"), payload], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    context.written = json.loads(done.stdout.strip().splitlines()[-1])


@when('an editor types the hashtag "{name}" on a Reference')
def step_type(context, name):
    probe(context, [name])


@when('an editor types the hashtags "{first}" and "{second}" on a Reference')
def step_type_two(context, first, second):
    probe(context, [first, second])


@when('an editor types the hashtag "{name}" on a Reference and later describes it as "{words}"')
def step_describe(context, name, words):
    probe(context, [name], words)


@then('a concept "{name}" of the kind editor concept exists with the key "{key}", accepted, with who made it and when and no description')
def step_concept(context, name, key):
    [node] = context.written["nodes"]
    assert (node["displayName"], node["nodeKind"], node["nodeKey"], node["status"], node["versionCreatedBy"], node["versionCreatedAt"], node.get("description")) == (name, "editor_concept", key, "accepted", "editor-1", "2026-11-02T12:00:00Z", None), node


@then("the Reference has one current tagged_with link to it, made by a person and confirmed")
def step_link(context):
    [row] = context.written["relations"]
    assert (row["relationState"], row["predicate"], row["objectKind"], row["metadata"]["provenance"], row["metadata"]["decision"]) == ("current", "tagged_with", "semanticNode", "human", "accepted"), row


@then("there is one concept and one link")
def step_one(context):
    assert len(context.written["nodes"]) == 1 and len(context.written["relations"]) == 1, context.written


@then("the concept holds those words and who wrote them")
def step_words(context):
    [node] = context.written["nodes"]
    assert node["description"] == "Sites made to look like news." and node["versionCreatedBy"] == "editor-2", node
