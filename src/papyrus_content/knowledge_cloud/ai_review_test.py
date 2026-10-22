import json
import urllib.error

import pytest

from ..knowledge_snapshot.actors import make_actor
from . import ai_review as r

ACTOR = make_actor("ai", None, "2026-10-26")
NOW = "2026-10-26T05:00:00Z"
TEXT = "OpenBMB released VoxCPM2, a 2B-parameter text-to-speech model built on the MiniCPM-4 backbone. The card lists 27B sizes."
TYPED = {
    "items": [
        {
            "item_id": "i1",
            "entities": [
                {"id": "e1", "kind": "model", "text": "VoxCPM2", "span": {"start": 17, "end": 24}},
                {"id": "e2", "kind": "model_family", "text": "MiniCPM-4", "span": {"start": 70, "end": 79}},
                {"id": "e3", "kind": "model", "text": "27B", "span": {"start": 100, "end": 103}},
            ],
            "relations": [{"id": "r1", "type": "member_of", "subject": "e1", "object": "e2", "span": {"start": 0, "end": 90}}],
        }
    ]
}


def typed():
    return r.TypedRun(TYPED, {"i1": TEXT})


def node(name, kind="model", node_id=None, status="generated", aliases=()):
    return {"id": node_id or f"n-{name}", "lineageId": f"l-{name}", "displayName": name, "nodeKind": kind, "status": status, "aliases": list(aliases), "changeReason": None}


class Model(r.LunaReviewer):
    """A reviewer whose 'API' answers from a script keyed by candidate name or relation text."""

    def __init__(self, answers, **kwargs):
        self.sent = []
        super().__init__("test-key", transport=self.transport, sleep=lambda _s: None, **kwargs)
        self.answers = answers

    def transport(self, url, headers, payload):
        candidates = json.loads(payload["input"])["candidates"]
        self.sent.append((payload, candidates))
        verdicts = []
        for candidate in candidates:
            label = candidate.get("name") or f"{candidate.get('subject')}->{candidate.get('object')}"
            verdict = self.answers.get(label, {"verdict": "unsure"})
            verdicts.append({"id": candidate["id"], "verdict": verdict["verdict"], "evidence": verdict.get("evidence", []), "name": verdict.get("name", ""), "reason": verdict.get("reason", "r")})
        return {"output_text": json.dumps({"verdicts": verdicts})}


def run_entities(nodes, answers, **kwargs):
    model = Model(answers, **kwargs)
    patches, decisions = r.review_entities(nodes, typed(), lambda n: [], model, ACTOR, now=NOW, vocabulary={"model": "AI model"})
    return model, patches, decisions


def test_accept_needs_a_verbatim_quote_that_names_the_thing():
    quote = "OpenBMB released VoxCPM2, a 2B-parameter text-to-speech model"
    _m, patches, decisions = run_entities([node("VoxCPM2")], {"VoxCPM2": {"verdict": "accept", "evidence": [quote]}})
    assert [p["expected"]["status"] for p in patches] == ["accepted"]
    assert decisions[0].applied


def test_an_invented_quote_is_not_accepted():
    _m, patches, decisions = run_entities([node("VoxCPM2")], {"VoxCPM2": {"verdict": "accept", "evidence": ["VoxCPM2 is a famous model"]}})
    assert patches == [] and decisions[0].verdict == r.UNSURE and not decisions[0].applied


def test_a_quote_that_does_not_name_the_thing_is_not_accepted():
    _m, patches, _d = run_entities([node("VoxCPM2")], {"VoxCPM2": {"verdict": "accept", "evidence": ["The card lists 27B sizes."]}})
    assert patches == []


def test_junk_is_rejected_and_unsure_changes_nothing():
    _m, patches, decisions = run_entities([node("27B"), node("VoxCPM2")], {"27B": {"verdict": "reject", "reason": "a size"}})
    assert [(p["expected"]["id"], p["expected"]["status"]) for p in patches] == [("n-27B", "rejected")]
    assert {d.subject: d.verdict for d in decisions} == {"model: 27B": "reject", "model: VoxCPM2": "unsure"}


def test_a_node_without_a_snippet_is_not_sent():
    model, patches, _d = run_entities([node("Ghost")], {})
    assert model.sent == [] and patches == []


def test_the_call_limit_stops_the_review_and_leaves_the_rest_unchanged():
    model, patches, _d = run_entities([node("VoxCPM2"), node("27B")], {}, max_calls=0)
    assert model.sent == [] and patches == []


def test_kind_labels_and_guidance_reach_the_model_and_the_key_stays_out_of_the_payload():
    model, _p, _d = run_entities([node("VoxCPM2")], {}, guidance="Prefer exact product names.")
    payload, candidates = model.sent[0]
    assert candidates[0]["kind_label"] == "AI model"
    assert "Prefer exact product names." in payload["instructions"]
    assert "test-key" not in json.dumps(payload) and payload["model"] == "gpt-6-luna" and payload["store"] is False


def relation(predicate="member_of", subject="VoxCPM2", target="MiniCPM-4"):
    return {
        "id": f"rel-{subject}", "predicate": predicate, "subjectKind": "semanticNode", "objectKind": "semanticNode",
        "relationState": "current", "subjectLineageId": f"l-{subject}", "objectLineageId": f"l-{target}", "metadata": "{}",
        "updatedAt": NOW,
    }


def run_relations(answers):
    nodes = {
        "l-VoxCPM2": node("VoxCPM2", status="accepted"),
        "l-MiniCPM-4": node("MiniCPM-4", kind="model_family", status="accepted"),
    }
    model = Model(answers)
    patches, decisions = r.review_relations([relation()], nodes, typed(), model, ACTOR, now=NOW)
    return patches, decisions


def test_a_relation_is_accepted_only_when_the_quote_names_both_ends_member_of_included():
    both = "a 2B-parameter text-to-speech model built on the MiniCPM-4 backbone"
    only_one = "OpenBMB released VoxCPM2, a 2B-parameter"
    patches, decisions = run_relations({"VoxCPM2 (model)->MiniCPM-4 (model_family)": {"verdict": "accept", "evidence": [only_one]}})
    assert patches == [] and decisions[0].verdict == r.UNSURE
    # "built on" names both ends only if the quote reaches MiniCPM-4 and VoxCPM2: this one lacks the subject
    patches, _d = run_relations({"VoxCPM2 (model)->MiniCPM-4 (model_family)": {"verdict": "accept", "evidence": [both]}})
    assert patches == []
    full = "OpenBMB released VoxCPM2, a 2B-parameter text-to-speech model built on the MiniCPM-4 backbone"
    patches, decisions = run_relations({"VoxCPM2 (model)->MiniCPM-4 (model_family)": {"verdict": "accept", "evidence": [full]}})
    assert len(patches) == 1 and patches[0]["modelName"] == "SemanticRelation" and decisions[0].applied
    assert json.loads(patches[0]["expected"]["metadata"])["confirmed"] is True


def test_a_contradicted_relation_is_rejected_and_the_row_records_ai():
    patches, _d = run_relations({"VoxCPM2 (model)->MiniCPM-4 (model_family)": {"verdict": "reject", "reason": "wrong"}})
    metadata = json.loads(patches[0]["expected"]["metadata"])
    assert metadata["confirmed"] is False and metadata["rejectedBy"]["actor"] == "ai"


def test_relations_with_an_unaccepted_end_are_skipped():
    model = Model({})
    nodes = {"l-VoxCPM2": node("VoxCPM2", status="accepted"), "l-MiniCPM-4": node("MiniCPM-4", kind="model_family")}
    patches, _d = r.review_relations([relation()], nodes, typed(), model, ACTOR, now=NOW)
    assert patches == [] and model.sent == []


def cluster(uid="cl-1", status="proposed"):
    summary = json.dumps({"kind": "papyrus-knowledge-cluster@1", "clusterUid": uid, "topTerms": ["tts", "speech"]})
    return {"id": f"p-{uid}", "proposalKind": "topic_cluster", "status": status, "summary": summary, "evidenceItemIds": ["a", "b", "c", "d"], "graphEntityId": uid}


def test_a_new_cluster_is_named_only_when_member_titles_are_quoted():
    titles = {"a": "Qwen3-TTS", "b": "Kokoro TTS", "c": "Chatterbox", "d": "Voxtral TTS"}
    titles_of = lambda ids: [titles[i] for i in ids]  # noqa: E731
    good = Model({"x": {}})
    good._transport = lambda *_a: {"output_text": json.dumps({"verdicts": [{"id": "c0", "verdict": "accept", "evidence": ["Qwen3-TTS", "Kokoro TTS", "Chatterbox"], "name": "Open text-to-speech models", "reason": "all TTS"}]})}
    patches, decisions = r.review_clusters([cluster()], titles_of, good, ACTOR, now=NOW)
    assert patches[0]["expected"]["displayName"] == "Open text-to-speech models" and patches[0]["expected"]["status"] == "accepted"
    bad = Model({})
    bad._transport = lambda *_a: {"output_text": json.dumps({"verdicts": [{"id": "c0", "verdict": "accept", "evidence": ["Qwen3-TTS", "made up"], "name": "TTS", "reason": "r"}]})}
    patches, decisions = r.review_clusters([cluster()], titles_of, bad, ACTOR, now=NOW)
    assert patches == [] and decisions[0].verdict == r.UNSURE


def test_accepted_clusters_are_not_reviewed_again():
    model = Model({})
    patches, _d = r.review_clusters([cluster(status="accepted")], lambda ids: ["x"] * 4, model, ACTOR, now=NOW)
    assert patches == [] and model.sent == []


def test_a_transient_http_error_is_retried_and_a_hard_one_is_not():
    calls = []

    def flaky(url, headers, payload):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(url, 429, "slow down", {}, None)
        return {"output_text": json.dumps({"verdicts": []})}

    model = r.LunaReviewer("k", transport=flaky, sleep=lambda _s: None)
    assert model.judge("t", [{"id": "x"}]) == {} and len(calls) == 3

    def forbidden(url, headers, payload):
        raise urllib.error.HTTPError(url, 401, "no", {}, None)

    with pytest.raises(r.ReviewError, match="HTTP 401"):
        r.LunaReviewer("k", transport=forbidden, sleep=lambda _s: None).judge("t", [{"id": "x"}])


def test_vocabulary_labels():
    text = "entity_kinds:\n  - {key: maker, label: company or developer}\n  - {key: model_family, label: AI model family}\n"
    assert r.vocabulary_labels(text)["model-family"] == "AI model family"
