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
#: The reader-facing front matter texts, beside the title and the dek, that a translation carries (kind ``field:<key>``): the blurb that summarizes the Story
#: in listings and on social cards, and the cover picture's alt text. ``sources`` titles stay as written (the references list stays in its own language).
FRONT_MATTER_FIELDS = ("blurb", "imageAlt")
FIELD_PREFIX = "field:"
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
    kind: str          # title | deck | field:<key> | prose | container | directive | code | comment | rule
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
        if not current and _LEAF_OPEN.match(line) and not _attributes_closed(line):
            # A leaf directive whose attribute list runs over several lines (``::image{`` … ``}``) is one block, a blank line inside it included: cut
            # there, its second half is prose to the translator, which translates the credit and loses the closing brace.
            current.append(line)
            index += 1
            while index < len(lines):
                current.append(lines[index])
                if _attributes_closed("\n".join(current)):
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


_LEAF_OPEN = re.compile(r"^::[A-Za-z][\w-]*(?:\[[^\]\n]*\])?\{")


def _attributes_closed(text: str) -> bool:
    """Whether the leaf directive's ``{`` … ``}`` attribute list is closed in ``text`` (a brace inside a quoted value does not count)."""
    depth, quote = 0, None
    for character in text[text.index("{"):]:
        if quote:
            quote = None if character == quote else quote
        elif character in "\"'":
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return True
    return False


def blocks_of(body: str, *, title: str | None = None, deck: str | None = None, fields: tuple[tuple[str, str], ...] = ()) -> list[Block]:
    """The Story's blocks with their identities: the title, the dek, the front matter fields (blurb, cover alt text), then the body's blocks."""
    texts: list[tuple[str, str]] = []
    if title:
        texts.append(("title", title.strip()))
    if deck:
        texts.append(("deck", deck.strip()))
    texts += [(FIELD_PREFIX + key, text.strip()) for key, text in fields if text and text.strip()]
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
        self._refuse_damaged_links(translated)
        return _PLACEHOLDER.sub(lambda match: self.parts[int(match.group(1)) - 1], translated)

    def _refuse_damaged_links(self, translated: str) -> None:
        """A link is ``[text]⟦n⟧``: the target placeholder stands right after the closing bracket of the link text. A model that writes the target itself, or
        moves the placeholder away from its text, would save a link with no anchor (``这是(/articles/x/)一宗…``): the translation is refused, so the model
        is asked again, and nothing damaged is ever stored."""
        for match in _PLACEHOLDER.finditer(translated):
            part = self.parts[int(match.group(1)) - 1]
            if part.startswith("(") and not translated[: match.start()].endswith("]"):
                raise PlaceholderError(f"the link target ⟦{match.group(1)}⟧ must stand directly after the closing ] of its link text, as in [text]⟦{match.group(1)}⟧")
        without = _PLACEHOLDER.sub("\x00", translated)
        for number, part in enumerate(self.parts, start=1):
            if len(part) >= 6 and part in without:
                raise PlaceholderError(f"you wrote the held text of ⟦{number}⟧ yourself; write only the placeholder ⟦{number}⟧ and never its contents")

    def mask(self, text: str) -> str:
        """``text`` with every held part replaced by its placeholder, for what a model is told about a problem: it must never read a link target and paste it."""
        shown = [(number, part) for number, part in enumerate(self.parts, start=1)]
        shown += [(number, part[1:-1].split(" ", 1)[0]) for number, part in enumerate(self.parts, start=1) if part.startswith("(") and part.endswith(")")]   # the target alone
        for number, part in sorted(shown, key=lambda pair: len(pair[1]), reverse=True):
            if part:
                text = text.replace(part, f"⟦{number}⟧")
        return text


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


# --- soft line breaks ---------------------------------------------------------------------------------------------------------------------------

_LINE_BREAKS = re.compile(r"(\n(?:[ \t]*\n)+|\n)")
_LINE_CLASS = (("fence", re.compile(r"^\s*(?::{2,}|```|~~~)")), ("list", re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")), ("heading", re.compile(r"^\s*#{1,6}\s")),
               ("quote", re.compile(r"^\s*>")), ("table", re.compile(r"^\s*\|")), ("html", re.compile(r"^\s*<")))


def _line_class(line: str) -> str:
    return next((name for name, pattern in _LINE_CLASS if pattern.match(line)), "prose")


def _lines_and_joints(text: str) -> tuple[list[str], list[str]]:
    """The non-blank lines of a block and what joins each to the next: ``soft`` (a single newline) or ``blank`` (a blank line)."""
    parts = _LINE_BREAKS.split(text.strip("\n"))
    return parts[0::2], ["blank" if len(joint.strip(" \t")) > 1 else "soft" for joint in parts[1::2]]


def keep_soft_breaks(source: str, target: str) -> str:
    """The translated block with a blank line turned back into the single newline the source has there, where the two blocks line up with certainty.

    A translator often turns a lone newline inside a paragraph (a soft break) into a blank line, which makes a second paragraph the source does not
    have. The source's soft break is put back only when the alignment can be verified: the two blocks have the same number of lines, every line has
    the same kind (a prose line, a directive or fence line, a list item, a heading, a quote), and every blank line of the source is a blank line
    of the translation at the same place. Then the translation differs only by blank lines at the source's soft breaks, and those are joined with
    a single newline. Anything else (an extra paragraph, a merged one, lines that do not line up) is left as written, for the structure check to
    hold. A source with no soft break is never touched."""
    source_lines, source_joints = _lines_and_joints(source)
    if "soft" not in source_joints:
        return target
    target_lines, target_joints = _lines_and_joints(target)
    if len(target_lines) != len(source_lines) or [_line_class(line) for line in target_lines] != [_line_class(line) for line in source_lines]:
        return target
    if any(joint == "blank" and target_joints[index] != "blank" for index, joint in enumerate(source_joints)):
        return target
    lead = target[:len(target) - len(target.lstrip("\n"))]
    trail = target[len(target.rstrip("\n")):]
    parts = _LINE_BREAKS.split(target.strip("\n"))
    for number, (was, now) in enumerate(zip(source_joints, target_joints)):
        if was == "soft" and now == "blank":
            parts[2 * number + 1] = "\n"
    return lead + "".join(parts) + trail
