from __future__ import annotations

from typing import Protocol, runtime_checkable

FASTEMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
FASTEMBED_EMBEDDER_ID = "fastembed-all-MiniLM-L6-v2"


@runtime_checkable
class SentenceEmbedder(Protocol):
    @property
    def embedder_id(self) -> str: ...

    def embed(self, sentences: tuple[str, ...]) -> list[list[float]]: ...


class FastembedEmbedder:
    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=FASTEMBED_MODEL_NAME)

    @property
    def embedder_id(self) -> str:
        return FASTEMBED_EMBEDDER_ID

    def embed(self, sentences: tuple[str, ...]) -> list[list[float]]:
        if not sentences:
            return []
        return [list(vector) for vector in self._model.embed(sentences)]


def resolve_local_embedder() -> SentenceEmbedder | None:
    try:
        return FastembedEmbedder()
    except ImportError:
        return None
