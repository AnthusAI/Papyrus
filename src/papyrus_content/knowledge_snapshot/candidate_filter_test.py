from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import commands
from .candidate_filter import REASON_COMMON_WORD, REASON_STOP_WORD, REASON_UNDECLARED_KIND, CandidateFilter, load_stop_words, upper_fence, vocabulary_kinds
from .commands_test import client, run  # noqa: F401
from .reference_documents import ReferenceDocument, ReferenceText, biblicus_reference_id, write_documents_file
from .run_input import TypedItem

DOCUMENTS = 40
# How many documents each candidate turns up in, and how the extractor saw it written: the examples are the ones that were wrongly made
# concepts ('attachments', 'shows', 'material', 'curation') and the ones that are real ('dark patterns', 'GPT-4', 'confinement problem').
COMMON_WORDS = {"attachments": 14, "shows": 16, "material": 18, "curation": 12}
REAL_NAMES = {"GPT-4": 11, "dark patterns": 7, "confinement problem": 5}
KIND = {"attachments": "topic", "shows": "topic", "material": "topic", "curation": "topic", "GPT-4": "product", "dark patterns": "topic", "confinement problem": "topic"}


def mention(number: int, kind: str, text: str) -> dict:
    return {"id": f"e{number}", "kind": kind, "text": text, "state": "proposed", "span": {"start": 0, "end": len(text)}, "score": 0.9}


def typed_items(extra_noise: int = 90) -> list[dict]:
    """40 documents: each common word and real name in the stated number of them, and a long tail of names that turn up once or twice."""
    entities: dict[int, list[dict]] = {number: [] for number in range(DOCUMENTS)}
    counter = 0
    for table in (COMMON_WORDS, REAL_NAMES):
        for text, count in table.items():
            for number in range(count):
                counter += 1
                entities[number].append(mention(counter, KIND[text], text))
    for index in range(extra_noise):
        counter += 1
        entities[index % DOCUMENTS].append(mention(counter, "topic", f"Rare thing {index}"))
        if index % 3 == 0:
            counter += 1
            entities[(index + 7) % DOCUMENTS].append(mention(counter, "topic", f"Rare thing {index}"))
    return [{"item_id": biblicus_reference_id(f"reference-{number}"), "entities": found, "relations": []} for number, found in entities.items()]


def learned(**kwargs) -> CandidateFilter:
    items = [TypedItem.model_validate(entry) for entry in typed_items()]
    return CandidateFilter.learn(items, **kwargs)


def test_common_words_are_dropped_and_real_names_kept_by_what_the_extraction_itself_shows():
    candidate_filter = learned()
    for word in COMMON_WORDS:
        assert not candidate_filter.check("topic", word), word
    for name in REAL_NAMES:
        assert candidate_filter.check(KIND[name], name), name
    assert {(entry.name, entry.reason) for entry in candidate_filter.dropped} == {(word, REASON_COMMON_WORD) for word in COMMON_WORDS}
    assert all("fence" in entry.detail for entry in candidate_filter.dropped)


def test_the_fence_comes_from_the_data_and_moves_with_it():
    assert upper_fence([1]) is None
    assert upper_fence([1, 1, 1, 1]) == 1
    assert upper_fence([1, 2, 3, 4, 20]) == 4 + 1.5 * (4 - 2)


def test_a_name_written_with_capitals_or_digits_is_never_a_common_word_however_often_it_occurs():
    items = [TypedItem.model_validate(entry) for entry in typed_items()]
    for item in items[:30]:
        item.entities.append(item.entities[0].model_copy(update={"id": f"x-{item.item_id}", "kind": "product", "text": "Llama"}))
        item.entities.append(item.entities[0].model_copy(update={"id": f"y-{item.item_id}", "kind": "product", "text": "attention"}))
    candidate_filter = CandidateFilter.learn(items)
    assert candidate_filter.check("product", "Llama")
    assert not candidate_filter.check("product", "attention")  # written only in lower case, in nearly every document


def test_a_multi_word_name_is_never_judged_a_common_word():
    candidate_filter = learned()
    assert candidate_filter.check("topic", "dark patterns") and candidate_filter.check("topic", "Dark   Patterns")


def test_the_site_stop_words_and_the_english_stop_list_drop_a_name_made_only_of_them(tmp_path, monkeypatch):
    monkeypatch.setattr("papyrus_content.knowledge_snapshot.candidate_filter.english_stop_words", lambda: ["the", "and", "of"])
    words = tmp_path / "stop-words.txt"
    words.write_text("# the site's own\nCard   Cards  # trailing\n", encoding="utf-8")
    candidate_filter = CandidateFilter(stop_words=load_stop_words(words))
    assert not candidate_filter.check("topic", "The Cards")
    assert not candidate_filter.check("topic", "the")
    assert candidate_filter.check("topic", "The Card Game")
    assert [entry.reason for entry in candidate_filter.dropped] == [REASON_STOP_WORD, REASON_STOP_WORD]


def test_no_stop_word_list_when_scikit_learn_is_missing(monkeypatch):
    def missing():
        raise ValueError("install scikit-learn")

    monkeypatch.setattr("papyrus_content.knowledge_snapshot.candidate_filter.english_stop_words", missing)
    assert load_stop_words(None) == frozenset()


def test_a_kind_the_vocabulary_does_not_declare_is_dropped():
    kinds = vocabulary_kinds("entity_kinds:\n  - {key: model_family, label: family}\n  - {key: task, label: task}\n")
    candidate_filter = CandidateFilter(kinds=kinds)
    assert candidate_filter.check("Model Family", "Tern") and candidate_filter.check("task", "Voice cloning")
    assert not candidate_filter.check("animal", "Heron")
    assert candidate_filter.dropped[0].reason == REASON_UNDECLARED_KIND


# ---- through the command ------------------------------------------------------------------------------------------------------


@pytest.fixture
def documents_run(client, tmp_path):
    documents = [ReferenceDocument(f"reference-{number}", f"lineage-{number}", f"Paper {number}", f"https://example.org/{number}", None, ReferenceText("", "")) for number in range(DOCUMENTS)]
    documents_file = tmp_path / "reference-documents.json"
    write_documents_file(documents_file, documents)
    entities = tmp_path / "entities.json"
    entities.write_text(json.dumps({"schema_version": 1, "items": typed_items()}))
    vocabulary = tmp_path / "vocabulary.yml"
    vocabulary.write_text("entity_kinds:\n  - {key: topic, label: topic}\n  - {key: product, label: product}\n")
    return {"documents": documents_file, "entities": entities, "vocabulary": vocabulary, "client": client, "dir": tmp_path}


def node_names(client) -> set[str]:
    return {row["displayName"] for row in client.rows.get("SemanticNode", {}).values()}


def publish(files, *extra):
    run(commands.knowledge_publish_run, "--entities", str(files["entities"]), "--reference-documents", str(files["documents"]), *extra)


def test_publish_run_makes_no_node_for_a_dropped_candidate_and_says_what_it_dropped_and_why(documents_run, capsys):
    publish(documents_run, "--vocabulary", str(documents_run["vocabulary"]), "--apply")
    names = node_names(documents_run["client"])
    assert {"GPT-4", "dark patterns", "confinement problem"} <= names
    assert names.isdisjoint(COMMON_WORDS)
    out = capsys.readouterr().out
    for word in COMMON_WORDS:
        assert f"dropped\ttopic\t{word}\t{REASON_COMMON_WORD}" in out
    assert f"candidatesDropped.{REASON_COMMON_WORD}\t4" in out
    mentions = [row for row in documents_run["client"].rows["SemanticRelation"].values() if row["predicate"] == "mentions"]
    assert not any("attachments" in json.dumps(row) for row in mentions)


def test_the_json_plan_lists_the_dropped_candidates(documents_run, capsys):
    publish(documents_run, "--vocabulary", str(documents_run["vocabulary"]), "--json")
    plan = json.loads(capsys.readouterr().out)
    assert sorted(entry["name"] for entry in plan["dropped"]) == sorted(COMMON_WORDS)
    assert {entry["reason"] for entry in plan["dropped"]} == {REASON_COMMON_WORD}


def test_without_the_site_files_nothing_is_filtered(documents_run, capsys):
    publish(documents_run, "--apply")
    assert set(COMMON_WORDS) <= node_names(documents_run["client"])
    assert "dropped" not in capsys.readouterr().out


def test_a_concept_that_is_already_on_the_map_is_never_filtered_or_changed(documents_run):
    publish(documents_run, "--apply")  # an earlier run, before the filter: 'attachments' is a generated node
    before = {row["id"]: dict(row) for row in documents_run["client"].rows["SemanticNode"].values()}
    publish(documents_run, "--vocabulary", str(documents_run["vocabulary"]), "--apply")
    assert {row["id"]: dict(row) for row in documents_run["client"].rows["SemanticNode"].values()} == before
