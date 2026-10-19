from __future__ import annotations

from pathlib import Path


def biblicus_corpus_catalog_path(corpus_directory: Path) -> Path:
    from biblicus.corpus import Corpus

    return Corpus.open(corpus_directory).catalog_path
