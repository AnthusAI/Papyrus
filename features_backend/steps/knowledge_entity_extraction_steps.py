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
from papyrus_content.knowledge_snapshot.entity_extraction import JevClient  # noqa: E402


class Response:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


class FakeTransport:
    """Jev's endpoint as the scenario describes it: it answers the three questions of each request, and every request is kept."""

    def __init__(self, context):
        self.context, self.headers = context, {}

    def post(self, url, json, timeout):
        self.context.requests.append(json)
        name = json["state"]["name"]
        self.context.asked.append(name)
        if name in self.context.silent:
            return Response(401)
        kind, real, page = self.context.answers.get(name, ("model", 0.5, 0.5))
        answers = {"real": {"type": "noul", "noul": real}, "kind": {"type": "choice", "choice": kind, "confidence": 0.9}, "page": {"type": "noul", "noul": page}}
        return Response(200, {"answers": answers, "usage": {"input_tokens": 500, "output_tokens": 50}, "model": "jev-1.13.0"})


def one_item_text(context, text):
    context.work = Path(tempfile.mkdtemp(prefix="entity-extraction-"))
    texts = context.work / "corpus" / "extracted" / "pipeline" / "ext1" / "text"
    texts.mkdir(parents=True)
    text = text.replace("\\n", "\n")
    for number in (1, 2):
        (texts / f"doc-{number}.txt").write_text(text)
    context.corpus_text, context.registry, context.asked, context.requests, context.error, context.output_file = text, [], [], [], None, None
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


@given('a corpus of two documents that read "{first}" and "{second}"')
def step_two_documents(context, first, second):
    context.answers = getattr(context, "answers", {})
    one_item_text(context, first)
    texts = context.work / "corpus" / "extracted" / "pipeline" / "ext1" / "text"
    (texts / "doc-2.txt").write_text(second)


@given('a corpus of two documents that both read "{text}" followed by a reference list of {count:d} entries')
def step_reference_list(context, text, count):
    context.answers = getattr(context, "answers", {})
    one_item_text(context, text + "\n\n## References\n\n" + "\n".join(f"[{number}] Author {number}. Title." for number in range(1, count + 1)))


@given('the publication\'s vocabulary describes it as "{description}"')
def step_description(context, description):
    context.vocabulary += f"description: {description}\n"
    (context.work / "vocabulary.yml").write_text(context.vocabulary)


@given('the publication\'s vocabulary has the kinds "{first}" and "{second}"')
def step_vocabulary(context, first, second):
    context.vocabulary = f"publication: demo\nversion: 1\nentity_kinds:\n  - {{key: {first}, label: {first}}}\n  - {{key: {second}, label: {second}}}\n"
    (context.work / "vocabulary.yml").write_text(context.vocabulary)


@given('the wiki already holds the model "{name}" as "{key}"')
def step_registry(context, name, key):
    context.registry.append({"key": key, "kind": "model", "aliases": [name]})


@given('Jev answers "{first}" is a real {first_kind} with confidence {first_real:f} and page {first_page:f}, and "{second}" is a real {second_kind} with confidence {second_real:f} and page {second_page:f}')
def step_answers(context, first, first_kind, first_real, first_page, second, second_kind, second_real, second_page):
    context.answers = {first: (first_kind, first_real, first_page), second: (second_kind, second_real, second_page)}


@given('Jev answers "{name}" is a real {kind} with confidence {real:f} and page {page:f}')
def step_answer(context, name, kind, real, page):
    context.answers[name] = (kind, real, page)


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
    context.asked, context.requests, context.error = [], [], None
    with mock.patch.object(commands, "JevClient", lambda key: JevClient(key, session=FakeTransport(context), sleep=lambda _seconds: None)), mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "key"}):
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


@then('the item "{item}" has "{text}" with page score {score:f} and a page')
def step_page(context, item, text, score):
    found = [e for e in entities_of(context, item) if e["text"] == text]
    assert found and all((e["page_score"], e["page_answer"]) == (score, True) for e in found), found


@then('the item "{item}" has "{text}" with page score {score:f} and no page')
def step_no_page(context, item, text, score):
    found = [e for e in entities_of(context, item) if e["text"] == text]
    assert found and all((e["page_score"], e["page_answer"]) == (score, False) for e in found), found


@then('the item "{item}" has "{text}" with page score {score:f} and {documents:d} documents')
def step_documents(context, item, text, score, documents):
    found = [entity for entity in entities_of(context, item) if entity["text"] == text]
    assert found and all((entity["page_score"], entity["page_documents"]) == (score, documents) for entity in found), found


@then('the item "{item}" has no entity "{text}"')
def step_no_entity(context, item, text):
    assert not [e for e in entities_of(context, item) if e["text"] == text]


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


@then('Jev was asked only once about "{name}"')
def step_asked_one(context, name):
    assert context.asked.count(name) == 1, context.asked


@then('Jev was asked about "{first}" once and about "{second}" once')
def step_asked_two(context, first, second):
    assert context.asked.count(first) == 1 and context.asked.count(second) == 1, context.asked


@then("every request to Jev asks, in this order, whether the name is real, which kind it is and whether it deserves a page")
def step_three_questions(context):
    assert context.requests
    for body in context.requests:
        assert list(body["questions"]) == ["real", "kind", "page"], body["questions"]
        assert [body["questions"][name]["type"] for name in ("real", "kind", "page")] == ["noul", "choice", "noul"]


@then('every request describes the publication as "{description}"')
def step_publication(context, description):
    assert context.requests and all(body["state"]["publication"] == description for body in context.requests)


@then('the kinds offered to Jev are "{first}" and "{second}" and no answer for something that is not a concept')
def step_kinds(context, first, second):
    assert all(list(body["questions"]["kind"]["criteria"]) == [first, second] for body in context.requests)


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
