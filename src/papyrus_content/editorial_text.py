from __future__ import annotations

import re

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9']+")


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def sentence_spans(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    cursor = 0
    for paragraph in paragraphs(text):
        paragraph_start = text.find(paragraph, cursor)
        if paragraph_start < 0:
            paragraph_start = cursor
        local_offset = 0
        for sentence in sentences(paragraph):
            start = paragraph_start + paragraph.find(sentence, local_offset)
            end = start + len(sentence)
            spans.append((sentence, start, end))
            local_offset = paragraph.find(sentence, local_offset) + len(sentence)
        cursor = paragraph_start + len(paragraph)
    return spans


def tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


def word_count(text: str) -> int:
    return len(tokenize(text))


def line_at_offset(text: str, offset: int) -> str:
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end]
