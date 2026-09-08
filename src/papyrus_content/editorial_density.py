from __future__ import annotations

import gzip
from dataclasses import dataclass
from typing import Any

from .editorial_diagnosis_schema import stable_finding_id
from .editorial_text import sentence_spans, tokenize, word_count

# Function-word inventory aligned with Ure (1971) / Halliday lexical-density practice.
FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
    }
)


@dataclass(frozen=True)
class DensityThresholds:
    min_words: int
    min_lexical_density: float
    max_gzip_ratio: float


@dataclass(frozen=True)
class DensitySummary:
    word_count: int
    sentence_count: int
    lexical_density: float
    gzip_ratio: float


@dataclass(frozen=True)
class DensityAnalysis:
    summary: DensitySummary
    findings: tuple[dict[str, Any], ...]


def lexical_density(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    content_words = sum(1 for token in tokens if token not in FUNCTION_WORDS)
    return content_words / len(tokens)


def gzip_ratio(text: str) -> float:
    encoded = text.encode("utf-8")
    if not encoded:
        return 1.0
    compressed = gzip.compress(encoded)
    return len(compressed) / len(encoded)


def analyze_density(text: str, thresholds: DensityThresholds) -> DensityAnalysis:
    normalized = text.replace("\r\n", "\n")
    tokens = tokenize(normalized)
    total_words = len(tokens)
    total_sentences = len(sentence_spans(normalized))
    density_value = lexical_density(tokens)
    compression_value = gzip_ratio(normalized)

    summary = DensitySummary(
        word_count=total_words,
        sentence_count=total_sentences,
        lexical_density=round(density_value, 4),
        gzip_ratio=round(compression_value, 4),
    )

    if total_words < thresholds.min_words:
        return DensityAnalysis(summary=summary, findings=())

    findings: list[dict[str, Any]] = []
    if density_value < thresholds.min_lexical_density:
        findings.append(
            _document_finding(
                "low_lexical_density",
                normalized,
                (
                    "Document lexical density is below the profile threshold "
                    f"({density_value:.3f} < {thresholds.min_lexical_density:.3f})."
                ),
            )
        )
    if compression_value <= thresholds.max_gzip_ratio:
        findings.append(
            _document_finding(
                "high_compressibility",
                normalized,
                (
                    "Document compresses unusually well for its length "
                    f"(gzip ratio {compression_value:.3f} <= {thresholds.max_gzip_ratio:.3f})."
                ),
            )
        )

    return DensityAnalysis(summary=summary, findings=tuple(findings))


def density_summary_as_dict(summary: DensitySummary) -> dict[str, Any]:
    return {
        "wordCount": summary.word_count,
        "sentenceCount": summary.sentence_count,
        "lexicalDensity": summary.lexical_density,
        "gzipRatio": summary.gzip_ratio,
    }


def _document_finding(kind: str, text: str, rationale: str) -> dict[str, Any]:
    start = 0
    end = len(text)
    return {
        "id": stable_finding_id(kind, text, start, end),
        "kind": kind,
        "excerpt": text[start:end],
        "span": {"start": start, "end": end},
        "rationale": rationale,
    }
