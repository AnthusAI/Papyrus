"""A Story's text as aligned blocks, and the parts of a block a translator never sees (PPY-843a7c).

**Blocks.** A body is split by Markus structure: paragraphs, headings, list items and quotes separated by blank lines are blocks; a container
directive (``:::note`` to its closing ``:::``) is one block; a fenced code block and an HTML comment are blocks that are copied, never
translated. A block's identity is the hash of its normalised text plus its occurrence number, so identical blocks (two rules) stay distinct
(the alignment spike, PPY-1e2f29). The title and the dek are blocks too (kinds ``title`` and ``deck``).

**What the translator never sees.** Everything that must survive byte for byte is replaced by a numbered placeholder ``⟦n⟧`` before a block
goes to a model and put back after: link and image targets, bare URLs, citation keys, inline code, HTML, and every directive attribute that is
not reader-facing text (only ``alt``, ``caption`` and ``title`` are translated; ``credit``, ``src``, ``layout`` and the rest are not). So the
system, not the translator, sets every link target and every credit (the translation experiment translated ``credit`` in 5 of 8 outputs), and
a reply that loses or repeats a placeholder is refused, never repaired by guesswork.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

TRANSLATABLE_ATTRIBUTES = ("alt", "caption", "title")
COPIED_KINDS = ("code", "comment", "rule")

_FENCE = re.compile(r"^(```|~~~)")
_CONTAINER_OPEN = re.compile(r"^(:{3,})[A-Za-z][\w-]*")
_COMMENT = re.compile(r"^<!--.*-->$", re.S)
_RULE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_PLACEHOLDER = re.compile(r"⟦(\d+)⟧")

# Inline parts that stay as written, in the order they are tried. A link keeps its text (translated) and loses only its target.
_INLINE = re.compile(
    r"(?P<code>`+[^`]*?`+)"
    r"|(?P<comment><!--.*?-->)"
    r"|(?P<html></?[A-Za-z][^>\n]*>)"
    r"|(?P<target>(?<=\])\((?:[^()\s]|\([^()\s]*\))+(?:\s+\"[^\"]*\")?\))"
    r"|(?P<citation>\[@[^\]\n]+\])"
    r"|(?P<url>https?://[^\s)<>\]\"]+)",
    re.S,
)
_ATTRIBUTE = re.compile(r'(?P<name>[A-Za-z][\w-]*)=(?P<quote>"|\')(?P<value>.*?)(?P=quote)', re.S)
_DIRECTIVE_ATTRIBUTES = re.compile(r"^(?P<head>:{2,}[A-Za-z][\w-]*(?:\[[^\]\n]*\])?)\{(?P<body>.*?)\}", re.S)


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


@dataclass(frozen=True)
class Block:
    id: str            # hash of the normalised text + "#" + occurrence
    kind: str          # title | deck | prose | container | directive | code | comment | rule
    text: str

    @property
    def translated(self) -> bool:
        return self.kind not in COPIED_KINDS


def _kind(text: str) -> str:
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    if _FENCE.match(first):
        return "code"
    if _COMMENT.match(text.strip()):
        return "comment"
    if _RULE.match(text.strip()):
        return "rule"
    if _CONTAINER_OPEN.match(first):
        return "container"
    if first.startswith("::") and not first.startswith(":::"):
        return "directive"
    return "prose"


def split_body(body: str) -> list[str]:
    """The body's blocks as text, in order. A container directive and a fenced code block stay whole, blank lines inside them included."""
    lines = body.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    current: list[str] = []
    index = 0

    def flush() -> None:
        if any(line.strip() for line in current):
            blocks.append("\n".join(current).strip("\n"))
        current.clear()

    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        container = _CONTAINER_OPEN.match(line)
        if (fence or container) and not current:
            closer = fence.group(1) if fence else container.group(1)
            current.append(line)
            index += 1
            depth = 1
            while index < len(lines):
                current.append(lines[index])
                stripped = lines[index].strip()
                if fence and stripped.startswith(closer):
                    break
                if container:
                    if _CONTAINER_OPEN.match(stripped) and stripped.startswith(closer) and not stripped == closer:
                        depth += 1
                    elif stripped == closer:
                        depth -= 1
                        if depth == 0:
                            break
                index += 1
            index += 1
            flush()
            continue
        if not line.strip():
            flush()
        else:
            current.append(line)
        index += 1
    flush()
    return blocks


def blocks_of(body: str, *, title: str | None = None, deck: str | None = None) -> list[Block]:
    """The Story's blocks with their identities: the title, the dek, then the body's blocks."""
    texts: list[tuple[str, str]] = []
    if title:
        texts.append(("title", title.strip()))
    if deck:
        texts.append(("deck", deck.strip()))
    texts += [(_kind(text), text) for text in split_body(body)]
    seen: dict[str, int] = {}
    out = []
    for kind, text in texts:
        digest = hashlib.sha256(f"{kind}\x1f{normalized(text)}".encode("utf-8")).hexdigest()[:16]
        seen[digest] = seen.get(digest, 0) + 1
        out.append(Block(f"{digest}#{seen[digest]}", kind, text))
    return out


def join_body(texts: list[str]) -> str:
    return "\n\n".join(text.strip("\n") for text in texts) + "\n"


@dataclass
class Protected:
    """A block with its fixed parts replaced by placeholders, and the parts to put back."""

    text: str
    parts: list[str] = field(default_factory=list)

    def restore(self, translated: str) -> str:
        """The translation with every part put back. Refuses a translation that loses, repeats or invents a placeholder."""
        found = [int(number) for number in _PLACEHOLDER.findall(translated)]
        expected = list(range(1, len(self.parts) + 1))
        if sorted(found) != expected:
            missing = sorted(set(expected) - set(found))
            repeated = sorted({n for n in found if found.count(n) > 1})
            invented = sorted(set(found) - set(expected))
            details = "; ".join(part for part in (
                f"missing {', '.join(f'⟦{n}⟧' for n in missing)}" if missing else "",
                f"repeated {', '.join(f'⟦{n}⟧' for n in repeated)}" if repeated else "",
                f"unknown {', '.join(f'⟦{n}⟧' for n in invented)}" if invented else "") if part)
            raise PlaceholderError(f"the translation does not keep every placeholder exactly once ({details})")
        return _PLACEHOLDER.sub(lambda match: self.parts[int(match.group(1)) - 1], translated)


class PlaceholderError(ValueError):
    """A model's text lost, repeated or invented a placeholder."""


def protect(text: str) -> Protected:
    """``text`` with every fixed part replaced by ``⟦n⟧``."""
    parts: list[str] = []

    def hold(value: str) -> str:
        parts.append(value)
        return f"⟦{len(parts)}⟧"

    def directive_attributes(match: re.Match) -> str:
        body = _ATTRIBUTE.sub(lambda attr: attr.group(0) if attr.group("name") in TRANSLATABLE_ATTRIBUTES
                              else f"{attr.group('name')}={attr.group('quote')}{hold(attr.group('value'))}{attr.group('quote')}", match.group("body"))
        return f"{match.group('head')}{{{body}}}"

    lines = []
    for line_block in re.split(r"(?m)^(?=:{2,}[A-Za-z])", text):
        lines.append(_DIRECTIVE_ATTRIBUTES.sub(directive_attributes, line_block, count=1))
    staged = "".join(lines)
    out = _INLINE.sub(lambda match: hold(match.group(0)), staged)
    return Protected(out, parts)


def protect_like(source: Protected, target: str) -> Protected:
    """A translated block protected with its source's parts: each part the source holds is replaced by the same placeholder. Used to send a
    translation back to a model for repair; :meth:`Protected.restore` then refuses a reply that lost a part."""
    out = target
    for number, part in sorted(enumerate(source.parts, start=1), key=lambda pair: len(pair[1]), reverse=True):
        out = out.replace(part, f"⟦{number}⟧", 1)
    return Protected(out, list(source.parts))
