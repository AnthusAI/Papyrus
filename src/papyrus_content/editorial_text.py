from __future__ import annotations

import re

_REFRAIN_MAX_WORDS = 12


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


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def is_rhetorical_refrain(members: list[dict]) -> bool:
    excerpts = [member["excerpt"].strip() for member in members]
    normalized = {excerpt.lower() for excerpt in excerpts}
    if len(normalized) != 1:
        return False
    excerpt = excerpts[0]
    if re.match(r"^#+\s", excerpt):
        return True
    if word_count(excerpt) <= _REFRAIN_MAX_WORDS:
        return True
    return False
