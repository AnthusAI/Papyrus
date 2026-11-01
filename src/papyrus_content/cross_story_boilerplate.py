"""Cross-story boilerplate: a passage copied into several of a site's stories.

A closing section pasted into seven articles goes stale in all seven at once. This check needs the site's other
stories, so it lives in Papyrus (Humanus is stateless). It reports every run of ``COPIED_RUN_WORDS`` or more
consecutive words of a story that also appears, in the same order, in the latest version of another story of the
same site. It is plain string work: no model call, and the other stories' shingles are built once per check.

Left out of the comparison, so formatting and quoting never fake a match: front matter, code, directive lines
(``::citations{}``), citation markers (``[@key]``), link and image addresses, block quotes and quoted text.
A story's own earlier versions never count: only other lineages are compared.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .story_from_reference import COPIED_RUN_WORDS

POLICY_ID = "cross-story-boilerplate"
DETECTOR_ID = "shared-passage"
_BREAK = "\x00"
_FRONT_MATTER = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_FENCE = re.compile(r"^(?P<fence>`{3,}|~{3,}).*?(?:^(?P=fence)[ \t]*$|\Z)", re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_DIRECTIVE_LINE = re.compile(r"^[ \t]*:{2,}.*$", re.MULTILINE)
_CITATION = re.compile(r"\[@[^\]\n]*\]")
_LINK_TARGET = re.compile(r"(?<=\])\([^)\n]*\)")
_URL = re.compile(r"https?://\S+")
_BLOCKQUOTE = re.compile(r"^[ \t]*>.*$", re.MULTILINE)
_QUOTED = re.compile(r'"(?:(?!\n[ \t]*\n)[^"])+"|“(?:(?!\n[ \t]*\n)[^”])+”')
_WORD = re.compile(r"[a-z0-9]+")
MAX_SLUGS_NAMED = 6
MAX_EXCERPT_CHARS = 300


@dataclass(frozen=True)
class Story:
    lineage_id: str
    slug: str
    body: str


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda match: _BREAK * len(match.group(0)), text)


def comparable_text(body: str) -> str:
    """The body with every excluded span replaced by break characters, so offsets stay those of the original text."""
    text = body or ""
    front = _FRONT_MATTER.match(text)
    if front:
        text = _BREAK * front.end() + text[front.end():]
    for pattern in (_FENCE, _INLINE_CODE, _DIRECTIVE_LINE, _CITATION, _LINK_TARGET, _URL, _BLOCKQUOTE, _QUOTED):
        text = _blank(text, pattern)
    return text


def comparable_words(body: str) -> list[tuple[str, int, int, int]]:
    """``(word, start, end, block)`` for each prose word; words in different blocks are never part of one run."""
    words: list[tuple[str, int, int, int]] = []
    block = 0
    offset = 0
    for piece in comparable_text(body).lower().split(_BREAK):
        for match in _WORD.finditer(piece):
            words.append((match.group(0), offset + match.start(), offset + match.end(), block))
        offset += len(piece) + 1
        block += 1
    return words


def _windows(words: list[tuple[str, int, int, int]], run: int) -> Iterable[tuple[int, tuple[str, ...]]]:
    for index in range(len(words) - run + 1):
        if words[index][3] == words[index + run - 1][3]:
            yield index, tuple(word[0] for word in words[index:index + run])


class ShingleIndex:
    """Every ``run``-word window of the other stories, built once, mapped to the stories that contain it."""

    def __init__(self, stories: Iterable[Story], *, run: int = COPIED_RUN_WORDS) -> None:
        self.run = run
        self.stories = {story.lineage_id: story for story in stories}
        self._windows: dict[tuple[str, ...], set[str]] = {}
        for story in self.stories.values():
            for _, window in _windows(comparable_words(story.body), run):
                self._windows.setdefault(window, set()).add(story.lineage_id)

    def passages(self, body: str, *, own_lineage: str | None = None) -> list[dict[str, Any]]:
        """The shared passages of ``body``: ``{start, end, words, excerpt, stories}``, stories being other lineages' ``Story``s."""
        words = comparable_words(body)
        hits: list[tuple[int, set[str]]] = []
        for index, window in _windows(words, self.run):
            owners = self._windows.get(window)
            if owners:
                owners = owners - {own_lineage}
            if owners:
                hits.append((index, set(owners)))
        passages: list[dict[str, Any]] = []
        for index, owners in hits:
            last = passages[-1] if passages else None
            if last and index <= last["last_window"] + 1 and last["owners"] & owners:
                last["last_window"] = index
                last["owners"] |= owners
            else:
                passages.append({"first_window": index, "last_window": index, "owners": set(owners)})
        found = []
        for passage in passages:
            first, last = words[passage["first_window"]], words[passage["last_window"] + self.run - 1]
            found.append({
                "start": first[1], "end": last[2],
                "words": passage["last_window"] - passage["first_window"] + self.run,
                "excerpt": body[first[1]:last[2]],
                "stories": sorted((self.stories[lineage] for lineage in passage["owners"]), key=lambda story: story.slug),
            })
        return found


def story_label(story: Story) -> str:
    return f"{story.slug} ({story.lineage_id})" if story.lineage_id != story.slug else story.slug


def finding_message(passage: dict[str, Any]) -> str:
    stories = passage["stories"]
    named = ", ".join(story_label(story) for story in stories[:MAX_SLUGS_NAMED])
    more = f" and {len(stories) - MAX_SLUGS_NAMED} more" if len(stories) > MAX_SLUGS_NAMED else ""
    return (
        f"These {passage['words']} words also appear in {len(stories)} other current "
        f"{'story' if len(stories) == 1 else 'stories'}: {named}{more}. "
        "Shared boilerplate goes stale in every copy at once; link to one page or write it fresh here."
    )


def cross_story_findings(body: str, own_lineage: str | None, index: ShingleIndex, segments: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Editorial findings (Humanus finding shape, severity ``warn``) for each passage ``body`` shares with another story."""
    findings = []
    for passage in index.passages(body, own_lineage=own_lineage):
        excerpt = " ".join(passage["excerpt"].split())
        segment = next((s["id"] for s in segments or [] if s.get("kind") == "paragraph" and s["start"] <= passage["start"] < s["end"]), "doc")
        findings.append({
            "id": "f-xstory-" + hashlib.sha256(excerpt.encode("utf-8")).hexdigest()[:16],
            "policyId": POLICY_ID, "policyVersion": 1, "detectorId": DETECTOR_ID, "lane": "rules",
            "severity": "warn", "status": "violation", "segmentId": segment,
            "span": {"start": passage["start"], "end": passage["end"]},
            "excerpt": excerpt if len(excerpt) <= MAX_EXCERPT_CHARS else excerpt[:MAX_EXCERPT_CHARS].rstrip() + "…",
            "message": finding_message(passage),
        })
    return findings


def latest_stories(rows: Iterable[dict[str, Any]]) -> list[Story]:
    """One ``Story`` per lineage: its highest-numbered current or draft version."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("versionState") not in ("current", "draft"):
            continue
        lineage = row.get("lineageId") or row["id"]
        if lineage not in best or int(row.get("versionNumber") or 0) > int(best[lineage].get("versionNumber") or 0):
            best[lineage] = row
    return [Story(lineage, row.get("slug") or lineage, row.get("bodyMarkus") or "") for lineage, row in best.items()]
