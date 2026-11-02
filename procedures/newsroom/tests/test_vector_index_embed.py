"""The embeddings request in src/papyrus_knowledge_query/vector_index.py stays inside OpenAI's limits and reports why it failed. Fake urlopen; no network."""
from __future__ import annotations

import io
import json
import urllib.error
from unittest import mock

import pytest

from papyrus_knowledge_query import vector_index


class Response:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok_urlopen(sent):
    def urlopen(request, timeout=None):
        inputs = json.loads(request.data)["input"]
        sent.append(inputs)
        return Response(json.dumps({"data": [{"index": i, "embedding": [float(len(t))]} for i, t in enumerate(inputs)]}).encode())
    return urlopen


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")


def candidate(key_, text):
    return {"key": key_, "text": text, "metadata": {}}


def write(candidates):
    sent, stats, put = [], {"vectorsWritten": 0, "embeddingRequests": 0, "embeddingInputCharacters": 0}, []
    with mock.patch("urllib.request.urlopen", ok_urlopen(sent)), mock.patch.object(vector_index, "_put_vectors", lambda arn, vectors: put.extend(vectors)):
        vector_index._write_pending_vectors(stats, "arn", candidates)
    return sent, stats, put


def test_empty_and_whitespace_texts_are_dropped_and_counted():
    sent, stats, put = write([candidate("a", "hello"), candidate("b", ""), candidate("c", "  \n\t"), candidate("d", "world")])
    assert sent == [["hello", "world"]]
    assert [v["key"] for v in put] == ["a", "d"] and stats["embeddingInputsEmpty"] == 2 and stats["vectorsWritten"] == 2


def test_a_batch_of_only_empty_texts_sends_no_request():
    sent, stats, put = write([candidate("a", " ")])
    assert sent == [] and put == [] and stats["embeddingRequests"] == 0 and stats["embeddingInputsEmpty"] == 1


def test_an_overlong_text_is_cut_to_the_byte_bound_and_counted():
    long_text = "é" * 10000   # 2 bytes a character
    sent, stats, _ = write([candidate("a", long_text), candidate("b", "short")])
    assert len(sent[0][0].encode("utf-8")) <= vector_index.EMBEDDING_MAX_INPUT_BYTES and sent[0][0] == "é" * (vector_index.EMBEDDING_MAX_INPUT_BYTES // 2)
    assert sent[0][1] == "short" and stats["embeddingInputsTruncated"] == 1


def test_requests_are_split_to_stay_under_the_per_request_total():
    text = "x" * 8000
    sent = []
    with mock.patch("urllib.request.urlopen", ok_urlopen(sent)):
        vectors = vector_index._embed([text] * 50)
    assert len(vectors) == 50 and len(sent) > 1
    assert all(sum(len(t.encode()) for t in group) <= vector_index.EMBEDDING_MAX_REQUEST_BYTES for group in sent)


def test_a_400_surfaces_the_body_message_and_not_the_key():
    body = json.dumps({"error": {"message": "'$.input' is invalid.", "type": "invalid_request_error"}}).encode()

    def urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(body))
    with mock.patch("urllib.request.urlopen", urlopen), pytest.raises(RuntimeError) as raised:
        vector_index._embed(["hello"])
    assert "HTTP 400" in str(raised.value) and "'$.input' is invalid." in str(raised.value) and "sk-secret" not in str(raised.value)
