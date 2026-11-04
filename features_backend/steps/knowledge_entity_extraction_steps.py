from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot import commands  # noqa: E402


class FakeJev:
    """Jev as the scenario describes it: the answers it gives, and every question it was asked."""

    model = "jev-1.13.0"

    def __init__(self, context):
        self.context, self.failures = context, {}

    def ask(self, name, passages, criteria, publication):
        self.context.asked.append(name)
        if name in self.context.silent:
            return None
        answer = self.context.answers.get(name, ("model", 0.5))
        return {"choice": answer[0], "confidence": answer[1], "usage": {"input_tokens": 500, "output_tokens": 50}, "model": self.model}


def one_item_text(context, text):
    context.work = Path(tempfile.mkdtemp(prefix="entity-extraction-"))
    texts = context.work / "corpus" / "extracted" / "pipeline" / "ext1" / "text"
    texts.mkdir(parents=True)
    for number in (1, 2):
        (texts / f"doc-{number}.txt").write_text(text)
    context.corpus_text, context.registry, context.asked, context.error, context.output_file = text, [], [], None, None
    context.silent = getattr(context, "silent", set())
    if getattr(context, "vocabulary", None):
        (context.work / "vocabulary.yml").write_text(context.vocabulary)


@given('a corpus of two documents that both read "{text}"')
def step_corpus(context, text):
    context.answers = getattr(context, "answers", {})
    one_item_text(context, text)


@given('a corpus of two documents that both read "{first}" and "{second}" in separate paragraphs')
def step_paragraphs(context, first, second):
    context.answers = getattr(context, "answers", {})
    one_item_text(context, f"{first}\n\n{second}")


@given('the publication\'s vocabulary has the kinds "{first}" and "{second}"')
def step_vocabulary(context, first, second):
    context.vocabulary = f"publication: demo\nversion: 1\nentity_kinds:\n  - {{key: {first}, label: {first}}}\n  - {{key: {second}, label: {second}}}\n"
    (context.work / "vocabulary.yml").write_text(context.vocabulary)


@given('the wiki already holds the model "{name}" as "{key}"')
def step_registry(context, name, key):
    context.registry.append({"key": key, "kind": "model", "aliases": [name]})


@given('Jev answers "{first}" is a model with confidence {first_confidence:f}, and "{second}" is an organization with confidence {second_confidence:f}')
def step_answers(context, first, first_confidence, second, second_confidence):
    context.answers = {first: ("model", first_confidence), second: ("organization", second_confidence)}


@given('Jev answers "{name}" is a model with confidence {confidence:f}')
def step_answer(context, name, confidence):
    context.answers[name] = ("model", confidence)


@given('Jev does not answer for "{name}"')
def step_no_answer(context, name):
    context.silent.add(name)


def extract(context):
    (context.work / "registry.json").write_text(json.dumps(context.registry))
    out = context.work / "typed"
    if out.exists():
        for stale in out.iterdir():
            stale.unlink()
    flags = ["--corpus", str(context.work / "corpus"), "--extraction-snapshot", "pipeline:ext1", "--vocabulary", str(context.work / "vocabulary.yml"),
             "--registry", str(context.work / "registry.json"), "--out", str(out), "--usage-out", str(context.work / "usage.json")]
    context.asked, context.error = [], None
    with mock.patch.object(commands, "JevClient", lambda key: FakeJev(context)), mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "key"}):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                commands.knowledge_extract_entities(flags)
            except ValueError as error:
                context.error = str(error)
    context.paid = json.loads((context.work / "usage.json").read_text())
    path = out / "output.json"
    context.output_file = json.loads(path.read_text()) if path.exists() else None


@given("the entities were extracted")
@when("the entities are extracted")
def step_extract(context):
    extract(context)
    context.first = context.output_file


@when("the entities are extracted again")
def step_extract_again(context):
    extract(context)


def entities_of(context, item):
    return next(found for found in context.output_file["items"] if found["item_id"] == item)["entities"]


@then('the item "{item}" has the proposed {kind} "{text}" twice, with confidence {confidence:f}')
def step_proposed_twice(context, item, kind, text, confidence):
    found = [e for e in entities_of(context, item) if e["text"] == text]
    assert len(found) == 2 and all((e["kind"], e["state"], e["entity_key"], e["score"]) == (kind, "proposed", None, confidence) for e in found), found


@then('the item "{item}" has the proposed {kind} "{text}" once, with confidence {confidence:f}')
def step_proposed_once(context, item, kind, text, confidence):
    found = [e for e in entities_of(context, item) if e["text"] == text]
    assert len(found) == 1 and (found[0]["kind"], found[0]["state"], found[0]["score"]) == (kind, "proposed", confidence), found


@then('the item "{item}" has the resolved {kind} "{text}" with the entity key "{key}"')
def step_resolved(context, item, kind, text, key):
    found = [e for e in entities_of(context, item) if e["text"] == text]
    assert len(found) == 1 and (found[0]["kind"], found[0]["state"], found[0]["entity_key"]) == (kind, "resolved", key), found


@then("the file has no relations")
def step_no_relations(context):
    assert all(item["relations"] == [] for item in context.output_file["items"]) and context.output_file["summary"]["relations"] == 0


@then('Jev was not asked about "{name}"')
def step_not_asked(context, name):
    assert name not in context.asked, context.asked


@then('Jev was asked about "{first}" once and about "{second}" once')
def step_asked_once(context, first, second):
    assert context.asked.count(first) == 1 and context.asked.count(second) == 1, context.asked


@then("Jev was not asked anything")
def step_asked_nothing(context):
    assert context.asked == [], context.asked


@then("the run reports no paid calls")
def step_no_paid(context):
    assert context.paid == [], context.paid


@then("the file is the same as the first time")
def step_same(context):
    assert context.output_file == context.first


@then("no entity of the file starts or ends in the middle of a word")
def step_boundaries(context):
    for item in context.output_file["items"]:
        for entity in item["entities"]:
            start, end = entity["span"]["start"], entity["span"]["end"]
            assert context.corpus_text[start:end] == entity["text"]
            assert start == 0 or not context.corpus_text[start - 1].isalnum(), entity
            assert end == len(context.corpus_text) or not context.corpus_text[end].isalnum(), entity


@then("the command fails saying Jev gave no answer for {count:d} name")
def step_fails(context, count):
    assert context.error and f"no answer for {count} names" in context.error, context.error


@then("no entities file is written")
def step_no_file(context):
    assert context.output_file is None


@then('Jev\'s answer for "{kept}" is kept, so running again asks only about "{rest}"')
def step_kept(context, kept, rest):
    context.answers[rest] = ("organization", 0.9)
    extract(context)
    assert context.asked == [rest], context.asked


@then("no entity of the file spans a line break")
def step_no_line_break(context):
    assert context.output_file["summary"]["entities"] > 0
    assert not [e for item in context.output_file["items"] for e in item["entities"] if "\n" in e["text"]]
