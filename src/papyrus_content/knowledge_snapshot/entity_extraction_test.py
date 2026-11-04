import json

import pytest

from . import entity_extraction as ex

STOP = {"the", "a", "of", "and", "is", "in", "was", "with", "this", "that", "for"}
CRITERIA = {"model": "named AI model", "organization": "AI lab or company", ex.NOT_A_CONCEPT: ex.NOT_A_CONCEPT_LABEL}


def passages_of(documents):
    return ex.find_candidates(documents, STOP)


def test_a_lower_case_match_never_starts_inside_a_capitalised_word():
    found = passages_of({"a": "Organization of Experts met. Organization of Experts met again. Organization of Experts spoke."})
    assert "organization of experts" in found
    inside = [key for key in found if key.startswith(("rganization", "ganization", "xperts", "perts")) or key.endswith(("rganization", "ganization"))]
    assert inside == []
    assert all(text[start:end] == written for key in found for _item, start, end, written in found[key]["mentions"] for text in ["Organization of Experts met. Organization of Experts met again. Organization of Experts spoke."])


def test_a_name_never_crosses_a_line_break():
    text = "ChatGPT\n\nChatGPT answered. Abstract\n\nMedical notes. Open\tAI Lab."
    found = passages_of({"a": text, "b": text})
    assert not [key for key in found if "\n" in key]
    assert {"chatgpt", "abstract", "open\tai lab"} <= set(found)
    assert all("\n" not in written for mentions in (found[key]["mentions"] for key in found) for _item, _start, _end, written in mentions)


def test_a_lower_case_word_is_not_taken_from_inside_a_longer_word_or_a_hyphenated_name():
    text = "Gemini-pro and Gemini-pro again. Bigconcept and bigconcepts. Subconfinement was seen."
    found = passages_of({"a": text, "b": text})
    assert "pro" not in found and "confinement" not in found
    assert all(text[start:end] == written for mentions in (found[key]["mentions"] for key in found) for _item, start, end, written in mentions)


def test_names_are_found_without_a_model_by_their_shape():
    text = "Claude-3 and GPT-4 were tested by Anthropic Research. The tooling uses memoryFoo for retrieval."
    found = passages_of({"a": text})
    assert {"claude-3", "gpt-4", "anthropic research", "memoryfoo"} <= set(found)
    assert found["anthropic research"]["mentions"][0][:3] == ("a", text.index("Anthropic"), text.index("Anthropic") + len("Anthropic Research"))


def test_a_lower_case_phrase_needs_two_documents_or_three_mentions():
    once = passages_of({"a": "we study dark patterns here.", "b": "nothing relevant."})
    assert "dark patterns" not in once
    twice = passages_of({"a": "we study dark patterns here.", "b": "dark patterns again."})
    assert "dark patterns" in twice
    thrice = passages_of({"a": "dark patterns; dark patterns; dark patterns."})
    assert "dark patterns" in thrice


def test_each_name_keeps_up_to_three_passages_from_different_documents():
    documents = {f"d{n}": f"Context {n}. Document {n} says Tern3 appears here and Tern3 again. More." for n in range(5)}
    found = passages_of(documents)["tern3"]
    assert len(found["contexts"]) == 3 and len({context for context in found["contexts"]}) == 3
    assert len(found["mentions"]) == 10


def test_registry_names_resolve_whatever_their_punctuation_or_case_and_a_short_word_keeps_its_case():
    matcher = ex.RegistryMatcher([
        {"key": "model--gpt-4", "kind": "model", "aliases": ["GPT-4"]},
        {"key": "organization--open-ai", "kind": "organization", "aliases": ["OpenAI", "Open AI Lab"]},
        {"key": "task--go", "kind": "task", "aliases": ["Go"]},
    ])
    text = "gpt 4 beat GPT-4. Go is a language; let us go. Open AI Lab and OpenAI."
    found = matcher.find(text)
    assert [(text[a:b], key) for a, b, _t, key, _k in found] == [
        ("gpt 4", "model--gpt-4"), ("GPT-4", "model--gpt-4"), ("Go", "task--go"), ("Open AI Lab", "organization--open-ai"), ("OpenAI", "organization--open-ai")]
    assert matcher.knows("gpt4") is False and matcher.knows("GPT 4") and matcher.knows("openai")


class Jev:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def __call__(self, name, passages):
        self.asked.append(name)
        answer = self.answers.get(name.casefold())
        return {"choice": answer[0], "confidence": answer[1], "usage": {"input_tokens": 500, "output_tokens": 50}, "model": "jev-1.13.0"} if answer else None


def candidates_of(text):
    return passages_of({"i1": text, "i2": text})


def test_answers_are_cached_by_name_passages_vocabulary_and_model(tmp_path):
    candidates = candidates_of("Tern3 beat Maple Lab.")
    cache = tmp_path / "cache.jsonl"
    jev = Jev({"tern3": ("model", 0.9), "maple lab": ("organization", 0.8), "beat": (ex.NOT_A_CONCEPT, 0.7)})
    decisions, usage, undecided = ex.decide(candidates, CRITERIA, jev, model="jev-1", cache_path=cache)
    assert undecided == 0 and len(usage) == len(jev.asked) == len(candidates) and usage[0] == {"model": "jev-1.13.0", "promptTokens": 500, "completionTokens": 50}
    again = Jev({})
    decisions_again, usage_again, undecided_again = ex.decide(candidates, CRITERIA, again, model="jev-1", cache_path=cache)
    assert again.asked == [] and usage_again == [] and undecided_again == 0 and decisions_again == decisions
    for change in ({"model": "jev-2"}, {"criteria": {**CRITERIA, "software": "a tool"}}):
        fresh = Jev({})
        ex.decide(candidates, change.get("criteria", CRITERIA), fresh, model=change.get("model", "jev-1"), cache_path=cache)
        assert len(fresh.asked) == len(candidates)
    changed = {**candidates_of("Tern3 beat Maple Lab.")}
    changed["tern3"] = {**changed["tern3"], "contexts": [*changed["tern3"]["contexts"], "Tern3 in a third document."]}
    fresh = Jev({})
    ex.decide(changed, CRITERIA, fresh, model="jev-1", cache_path=cache)
    assert fresh.asked == ["Tern3"]


def test_a_name_jev_could_not_answer_is_counted_and_what_was_paid_for_stays_cached(tmp_path):
    candidates = candidates_of("Tern3 beat Maple Lab.")
    cache = tmp_path / "cache.jsonl"
    _decisions, usage, undecided = ex.decide(candidates, CRITERIA, Jev({"tern3": ("model", 0.9)}), model="jev-1", cache_path=cache)
    assert undecided == len(candidates) - 1 and len(usage) == 1 and len(cache.read_text().splitlines()) == 1


def test_the_output_has_the_shape_publish_run_reads_and_keeps_every_confidence(tmp_path):
    text = "Tern3 beat Maple Lab. Mistral AI released Tern3. Mistral spoke. Beat."
    documents = {"i1": text, "i2": text}
    candidates = ex.find_candidates(documents, STOP)
    matcher = ex.RegistryMatcher([{"key": "organization--mistral-ai", "kind": "organization", "aliases": ["Mistral AI"]}])
    candidates = {key: found for key, found in candidates.items() if not matcher.knows(found["name"])}
    jev = Jev({"tern3": ("model", 0.12), "maple lab": ("organization", 0.8), "mistral": ("organization", 0.6)})
    decisions, _usage, undecided = ex.decide(candidates, CRITERIA, lambda name, passages: jev(name, passages) or {"choice": ex.NOT_A_CONCEPT, "confidence": 0.5, "model": "jev-1.13.0"}, model="jev-1.13.0", cache_path=tmp_path / "c.jsonl")
    output = ex.build_output(documents, candidates, decisions, matcher, {"publication": "p", "version": 1}, model="jev-1.13.0")
    assert undecided == 0 and output["schema_version"] == 1 and output["backend"] == {"id": "jev", "model": "jev-1.13.0"}
    assert set(output) == {"schema_version", "backend", "vocabulary", "items", "summary"} and output["vocabulary"]["publication"] == "p"
    item = output["items"][0]
    assert item["item_id"] == "i1" and item["relations"] == []
    by_text = {}
    for entity in item["entities"]:
        by_text.setdefault(entity["text"], []).append(entity)
        assert text[entity["span"]["start"]:entity["span"]["end"]] == entity["text"]
        assert set(entity) == {"id", "kind", "text", "state", "entity_key", "span", "score"}
    assert [entity["id"] for entity in item["entities"]] == [f"e{n}" for n in range(1, len(item["entities"]) + 1)]
    assert by_text["Tern3"][0] == {**by_text["Tern3"][0], "kind": "model", "state": "proposed", "entity_key": None, "score": 0.12}  # no confidence cut-off
    assert by_text["Mistral AI"][0]["state"] == "resolved" and by_text["Mistral AI"][0]["entity_key"] == "organization--mistral-ai" and by_text["Mistral AI"][0]["score"] == 1.0
    assert [entity["text"] for entity in item["entities"] if entity["text"].startswith("Mistral")] == ["Mistral AI", "Mistral"]
    assert "Beat" not in by_text
    assert output["summary"] == {"entities": sum(len(i["entities"]) for i in output["items"]), "items": 2, "proposed": output["summary"]["entities"] - 2, "resolved": 2, "relations": 0}


def test_a_mention_inside_the_mention_of_an_accepted_entity_is_not_proposed_again(tmp_path):
    documents = {"i1": "Mistral AI shipped it."}
    matcher = ex.RegistryMatcher([{"key": "organization--mistral-ai", "kind": "organization", "aliases": ["Mistral AI"]}])
    candidates = {"mistral": {"name": "Mistral", "contexts": ["x"], "mentions": [("i1", 0, 7, "Mistral")]}}
    output = ex.build_output(documents, candidates, {"mistral": {"choice": "organization", "confidence": 0.9}}, matcher, {}, model="m")
    assert [entity["state"] for entity in output["items"][0]["entities"]] == ["resolved"]


def test_the_vocabulary_cannot_use_the_answer_that_means_not_a_concept():
    with pytest.raises(ex.ExtractionError):
        ex.criteria_of({"entity_kinds": [{"key": ex.NOT_A_CONCEPT, "label": "x"}]})
    with pytest.raises(ex.ExtractionError):
        ex.criteria_of({"entity_kinds": []})
    assert list(ex.criteria_of({"entity_kinds": [{"key": "model", "label": "a model"}]})) == ["model", ex.NOT_A_CONCEPT]


class Response:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.responses, self.headers, self.posted = list(responses), {}, []

    def post(self, url, json, timeout):
        self.posted.append(json)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


ANSWER = {"answers": {"kind": {"choice": "model", "confidence": 0.9}}, "usage": {"input_tokens": 5, "output_tokens": 1}, "model": "jev-1.13.0"}


def test_the_client_asks_one_choice_per_name_and_retries_what_is_worth_retrying():
    waits = []
    session = Session([Response(429), OSError("reset"), Response(200, ANSWER)])
    client = ex.JevClient("key", session=session, sleep=waits.append)
    answer = client.ask("Tern3", ["p1"], CRITERIA, "demo")
    assert answer["choice"] == "model" and answer["usage"] == {"input_tokens": 5, "output_tokens": 1} and waits == [1, 2]
    assert session.headers["Authorization"] == "Bearer key"
    body = session.posted[0]
    assert body["model"] == "jev-1.13.0" and body["state"]["name"] == "Tern3" and body["state"]["passages"] == ["p1"]
    assert body["questions"]["kind"]["type"] == "choice" and body["questions"]["kind"]["criteria"] == CRITERIA


def test_the_client_gives_up_on_a_refusal_and_after_the_last_retry():
    refused = ex.JevClient("key", session=Session([Response(401)]), sleep=lambda _s: None)
    assert refused.ask("x", [], CRITERIA, "demo") is None and refused.failures[401] == 1
    tired = ex.JevClient("key", session=Session([Response(503)] * 2), sleep=lambda _s: None, attempts=2)
    assert tired.ask("x", [], CRITERIA, "demo") is None and tired.failures["gave up"] == 1
    with pytest.raises(ex.ExtractionError):
        ex.JevClient("")


# -- the command ------------------------------------------------------------------------------------------------------
class FakeClient:
    model = "jev-1.13.0"

    def __init__(self, key):
        assert key == "the-key"
        self.failures = {}

    def ask(self, name, passages, criteria, publication):
        FakeClient.asked.append(name)
        return None if name == "Stuck" else {"choice": "model", "confidence": 0.9, "usage": {"input_tokens": 10, "output_tokens": 2}, "model": self.model}


def corpus_for_command(tmp_path, text):
    texts = tmp_path / "corpus" / "extracted" / "pipeline" / "ext1" / "text"
    texts.mkdir(parents=True)
    (texts / "i1.txt").write_text(text)
    (texts / "i2.txt").write_text(text)
    vocabulary = tmp_path / "vocabulary.yml"
    vocabulary.write_text("publication: demo\nversion: 1\nentity_kinds:\n  - {key: model, label: a model}\n")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps([{"key": "model--gpt-4", "kind": "model", "aliases": ["GPT-4"]}]))
    return ["--corpus", str(tmp_path / "corpus"), "--extraction-snapshot", "pipeline:ext1", "--vocabulary", str(vocabulary), "--registry", str(registry),
            "--out", str(tmp_path / "typed"), "--usage-out", str(tmp_path / "usage.json")]


def test_the_command_writes_the_entities_file_the_usage_and_a_cache_that_a_rerun_uses(tmp_path, monkeypatch):
    from . import commands

    monkeypatch.setattr(commands, "JevClient", FakeClient)
    monkeypatch.setenv("TYPESAFE_API_KEY", "the-key")
    FakeClient.asked = []
    flags = corpus_for_command(tmp_path, "Tern3 beat GPT-4 today.")
    commands.knowledge_extract_entities(flags)
    output = json.loads((tmp_path / "typed" / "output.json").read_text())
    assert [(e["text"], e["state"], e["entity_key"]) for e in output["items"][0]["entities"]] == [("Tern3", "proposed", None), ("GPT-4", "resolved", "model--gpt-4")]
    assert "GPT-4" not in FakeClient.asked and "Tern3" in FakeClient.asked
    paid = json.loads((tmp_path / "usage.json").read_text())
    assert len(paid) == len(FakeClient.asked) and paid[0]["promptTokens"] == 10
    FakeClient.asked = []
    commands.knowledge_extract_entities(flags)
    assert FakeClient.asked == [] and json.loads((tmp_path / "usage.json").read_text()) == []
    assert (tmp_path / "corpus" / "analysis" / "entity-decisions" / "cache.jsonl").exists()


def test_the_command_fails_without_writing_the_file_when_jev_leaves_a_name_unanswered_but_reports_what_it_paid(tmp_path, monkeypatch):
    from . import commands

    monkeypatch.setattr(commands, "JevClient", FakeClient)
    monkeypatch.setenv("TYPESAFE_API_KEY", "the-key")
    FakeClient.asked = []
    flags = corpus_for_command(tmp_path, "Tern3 won. Stuck lost.")
    with pytest.raises(ValueError, match="no answer for"):
        commands.knowledge_extract_entities(flags)
    assert not (tmp_path / "typed" / "output.json").exists() and json.loads((tmp_path / "usage.json").read_text())


def test_the_command_needs_a_key_and_names_where_it_looks(tmp_path, monkeypatch):
    from . import commands

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
        commands.knowledge_extract_entities(corpus_for_command(tmp_path, "Tern3."))
