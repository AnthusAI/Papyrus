"""The fixed BERTopic settings of a knowledge run, with the vectorizer that keeps cluster top terms readable.

Clusters are named from their top terms, and c-TF-IDF over raw words picks up page furniture: numbers ("20", "35"),
fragments ("f1"), generic words ("card", "model"). The vectorizer drops English stop words, the publication's own extra
stop words (a plain file, words separated by white space or lines, ``#`` for comments; the vectorizer compares single tokens, so a phrase is split into its words), tokens that are pure numbers and tokens shorter than
three characters. The vectorizer only changes the words a cluster is labelled with: clusters come from the embeddings,
and topic identity matches clusters by the overlap of their member items, so it does not move cluster identity.

Biblicus (``TopicModelingVectorizerConfig``) accepts only ``ngram_range`` and ``stop_words`` (``english`` or a list) and
refuses other keys, so there is no ``token_pattern`` or ``min_df`` to set. The rule is therefore written out as an
explicit stop-word list: English stop words, the extra words, every one- and two-character token and every whole
number up to ``NUMBER_LIMIT``. The default tokenizer already ignores one-character tokens.
"""

from __future__ import annotations

import itertools
import string
from collections.abc import Iterable
from pathlib import Path

import yaml

NUMBER_LIMIT = 9999
SHORT_TOKEN_LENGTH = 3


def english_stop_words() -> list[str]:
    try:
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    except ImportError as error:
        raise ValueError('The English stop-word list comes from scikit-learn; install it with pip install "biblicus[topic-modeling]".') from error
    return sorted(ENGLISH_STOP_WORDS)


def read_extra_stop_words(path: Path) -> list[str]:
    words: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        words.extend(line.split("#", 1)[0].casefold().split())
    return words


def stop_words(extra: Iterable[str] = (), base: Iterable[str] | None = None) -> list[str]:
    """English stop words, the extra words, short tokens and numbers, sorted and without repeats."""
    words = set(english_stop_words() if base is None else base)
    words.update(word.casefold() for word in extra if word and word.strip())
    alphabet = string.ascii_lowercase + string.digits
    for length in range(1, SHORT_TOKEN_LENGTH):
        words.update("".join(chars) for chars in itertools.product(alphabet, repeat=length))
    words.update(str(number) for number in range(NUMBER_LIMIT + 1))
    return sorted(words)


def topic_modeling_configuration(extra: Iterable[str] = (), base: Iterable[str] | None = None) -> dict:
    return {
        "schema_version": 1,
        "text_source": {"min_text_characters": 200},
        "llm_extraction": {"enabled": False},
        "lexical_processing": {"enabled": True, "lowercase": True, "strip_punctuation": True, "collapse_whitespace": True},
        "bertopic_analysis": {
            "parameters": {"nr_topics": None, "min_topic_size": 5},
            "vectorizer": {"ngram_range": [1, 2], "stop_words": stop_words(extra, base)},
            "umap_model": {"parameters": {"n_neighbors": 10, "n_components": 5, "min_dist": 0.0, "metric": "cosine", "random_state": 42}},
            "hdbscan_model": {
                "parameters": {
                    "min_cluster_size": 5,
                    "min_samples": 3,
                    "metric": "euclidean",
                    "cluster_selection_method": "eom",
                    "prediction_data": True,
                }
            },
        },
    }


def render(configuration: dict) -> str:
    return yaml.safe_dump(configuration, sort_keys=False, default_flow_style=None, width=100)
