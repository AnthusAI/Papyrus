"""Declarative, publication-supplied rewrites for converted Markus fragments.

Why this exists
---------------
``markus convert`` runs **without** ``--allow-html`` and that is not
negotiable: ``security.py`` enforces it on every argv, and this module does
not touch, relax, or bypass it. Author-written Markdown therefore cannot
introduce raw HTML, which is exactly the property we want -- a story author
cannot smuggle a ``<script>`` into a built page.

That same property also blocks markup a **publication's own build code**
generated and merely needs to re-emit: a ``<mark>`` highlight (204 of them in
the Anth.us corpus), an inline ``<svg>`` diagram the build drew itself, a
table with ``colspan``. There was no supported way to do that, so publications
invented private Private Use Area sentinels and private post-processing passes
over Papyrus's HTML.

The security reasoning, stated plainly
--------------------------------------
* The trust boundary is unchanged. ``markus convert`` still rejects raw HTML
  from author content, and nothing here re-enables ``--allow-html``.
* A sentinel only becomes markup if it is in the fragment *at convert time*.
  Author Markdown is not a sentinel source: a publication's normalizer, which
  is build code in the publication's own repo and reviewed as code, puts them
  there. An author typing the literal code point U+E013 gets a build failure,
  not markup, unless the publication also opted into block passthrough.
* Inline passthrough is allow-listed (:data:`ALLOWED_INLINE`) down to a fixed
  set of harmless phrasing elements. No attributes, no ``<script>``, no
  ``<iframe>``, no event handlers -- the element name is the entire degree of
  freedom.
* Block passthrough is opaque and therefore *unbounded*, so it is off by
  default and must be turned on explicitly per publication with
  ``allow_block_passthrough=True``. That flag is the publication asserting
  "this markup is mine, my build code produced it."
* A surviving sentinel code point is a hard build error. A corrupted payload
  must fail the build, not ship a tofu box to a reader.

The PUA code points U+E010..U+E01F are **owned by Papyrus** and declared here
precisely so publications stop each inventing their own private range and
colliding.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

#: The Private Use Area block Papyrus reserves for fragment sentinels.
SENTINEL_FIRST = ""
SENTINEL_LAST = ""

INLINE_OPEN = ""
INLINE_SEP = ""
INLINE_CLOSE = ""
BLOCK_OPEN = ""
BLOCK_CLOSE = ""

#: Elements an inline sentinel may decode to. Phrasing content only, emitted
#: with no attributes at all -- the element name is the whole payload.
ALLOWED_INLINE = frozenset(
    {
        "mark",
        "sup",
        "sub",
        "kbd",
        "abbr",
        "cite",
        "q",
        "small",
        "ins",
        "del",
        "span",
    }
)

_ANY_SENTINEL = re.compile(f"[{SENTINEL_FIRST}-{SENTINEL_LAST}]")
_INLINE_RE = re.compile(
    f"{INLINE_OPEN}([A-Za-z][A-Za-z0-9]*){INLINE_SEP}(.*?){INLINE_CLOSE}",
    re.DOTALL,
)
# base32 alphabet only: A-Z, 2-7 and '='. Deliberately NOT base64 -- base64's
# '+' and '/' are harmless but its URL-safe variant's '_' (and any '*' in an
# ad-hoc alphabet) get eaten as Markdown emphasis delimiters, silently
# corrupting the payload somewhere in the middle of a long run.
_BLOCK_PAYLOAD = "[A-Z2-7=]+"
_BLOCK_RE = re.compile(f"{BLOCK_OPEN}({_BLOCK_PAYLOAD}){BLOCK_CLOSE}")
# A block element inside a <p> is invalid HTML and the browser reflows it out
# of the paragraph, which moves it in the document and breaks the stylesheet's
# selectors. When the sentinel is the paragraph's sole content, the paragraph
# itself was never wanted -- Markdown just wrapped a lone line.
_BLOCK_IN_P_RE = re.compile(
    r"<p(?:\s[^>]*)?>\s*"
    f"{BLOCK_OPEN}({_BLOCK_PAYLOAD}){BLOCK_CLOSE}"
    r"\s*</p>"
)
# Markus's document header (``markusmd.render._render_header``): one
# ``<header class="markus-header">`` as the first child of the document
# ``<article>``, containing only escaped front-matter text -- never a nested
# ``<header>``, so the lazy match is exact.
_MARKUS_HEADER_RE = re.compile(
    r'(<article class="markus-document"[^>]*>)<header class="markus-header">.*?</header>',
    re.DOTALL,
)
_CLASS_ATTR_RE = re.compile(r"(\s*)class=([\"'])([^\"']*)\2")


class FragmentTransformError(ValueError):
    """A fragment could not be transformed; the build must fail.

    Subclasses ``ValueError`` so ``inline_sentinel``'s contract violation and
    a decode failure are catchable the same way.
    """


def inline_sentinel(element: str, text: str) -> str:
    """Encode ``text`` to be re-emitted as ``<element>text</element>``.

    ``element`` must be in :data:`ALLOWED_INLINE`. ``text`` passes through
    Markdown as ordinary text, so it is escaped by ``markus convert`` and any
    Markdown inside it is still processed -- a highlight containing emphasis
    keeps the emphasis.
    """
    if element not in ALLOWED_INLINE:
        raise ValueError(
            f"inline sentinel element {element!r} is not allowed; "
            f"permitted: {', '.join(sorted(ALLOWED_INLINE))}"
        )
    if _ANY_SENTINEL.search(text):
        raise ValueError(
            "inline sentinel text may not contain Papyrus sentinel code points "
            f"(U+{ord(SENTINEL_FIRST):04X}..U+{ord(SENTINEL_LAST):04X})"
        )
    return f"{INLINE_OPEN}{element}{INLINE_SEP}{text}{INLINE_CLOSE}"


def block_sentinel(markup: str) -> str:
    """Encode publication-generated ``markup`` for verbatim re-emission.

    The payload is base32 (``A-Z2-7=``) so that nothing in it can be read as
    Markdown syntax on the way through ``markus convert``. Decoding requires
    ``FragmentTransform(allow_block_passthrough=True)``.
    """
    payload = base64.b32encode(markup.encode("utf-8")).decode("ascii")
    return f"{BLOCK_OPEN}{payload}{BLOCK_CLOSE}"


def _decode_block_payload(payload: str) -> str:
    padded = payload + "=" * (-len(payload) % 8)
    try:
        return base64.b32decode(padded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise FragmentTransformError(
            f"corrupt block sentinel payload ({exc}); refusing to emit the fragment"
        ) from exc


@dataclass(frozen=True)
class FragmentTransform:
    """A publication's declarative rewrite of one converted fragment.

    ``class_map``
        Maps a single class **token** to its replacement token(s), split on
        whitespace, so ``{"markus-document": "post post--body"}`` is one
        entry. An empty string removes the token. Replacement tokens are
        de-duplicated within an attribute, so two mapped tokens collapsing to
        the same class do not emit ``class="post post"``.
    ``allow_block_passthrough``
        Opt in to decoding :func:`block_sentinel` payloads. Off by default;
        see this module's docstring.
    ``drop_unmapped_classes``
        Class-name **prefixes** to strip when a token is not in ``class_map``
        -- e.g. ``("markus-",)`` for a publication that has mapped the markers
        it styles and wants the rest gone rather than inert-but-present.
    ``strip_header``
        Remove the ``<header class="markus-header">`` Markus renders from
        front-matter ``title``/``authors``/``date``/``description``. For a
        publication that renders its own article heading: Papyrus reads
        ``title`` for the page ``<title>``, so the front matter cannot simply
        omit it.

    Class rewriting runs *before* block sentinels are decoded, so a decoded
    block's markup is re-emitted exactly as the publication generated it and
    never silently reclassed.
    """

    class_map: Mapping[str, str] = field(default_factory=dict)
    allow_block_passthrough: bool = False
    drop_unmapped_classes: tuple[str, ...] = ()
    strip_header: bool = False

    def apply(self, fragment: str) -> str:
        if BLOCK_OPEN in fragment and not self.allow_block_passthrough:
            raise FragmentTransformError(
                "fragment contains a block sentinel but this FragmentTransform "
                "has allow_block_passthrough=False; set "
                "allow_block_passthrough=True to re-emit publication-generated "
                "block markup"
            )

        result = fragment
        if self.strip_header:
            result = _MARKUS_HEADER_RE.sub(r"\1", result, count=1)
        result = self._rewrite_classes(result)
        result = self._decode_inline(result)
        if self.allow_block_passthrough:
            result = self._decode_blocks(result)

        survivor = _ANY_SENTINEL.search(result)
        if survivor is not None:
            point = ord(survivor.group(0))
            raise FragmentTransformError(
                f"undecoded Papyrus sentinel U+{point:04X} survived at offset "
                f"{survivor.start()} in the transformed fragment; the payload is "
                "malformed and would render as a tofu box"
            )
        return result

    # -- stages ---------------------------------------------------------
    def _rewrite_classes(self, fragment: str) -> str:
        if not self.class_map and not self.drop_unmapped_classes:
            return fragment

        def replace(match: re.Match[str]) -> str:
            leading, quote, value = match.group(1), match.group(2), match.group(3)
            tokens: list[str] = []
            for token in value.split():
                if token in self.class_map:
                    for mapped in self.class_map[token].split():
                        if mapped not in tokens:
                            tokens.append(mapped)
                elif any(
                    token.startswith(prefix) for prefix in self.drop_unmapped_classes
                ):
                    continue
                elif token not in tokens:
                    tokens.append(token)
            if not tokens:
                # Drop the attribute entirely, leading whitespace included --
                # an empty class="" is noise in the output and in diffs.
                return ""
            return f"{leading}class={quote}{' '.join(tokens)}{quote}"

        return _CLASS_ATTR_RE.sub(replace, fragment)

    def _decode_inline(self, fragment: str) -> str:
        if INLINE_OPEN not in fragment:
            return fragment

        def replace(match: re.Match[str]) -> str:
            element, text = match.group(1), match.group(2)
            if element not in ALLOWED_INLINE:
                raise FragmentTransformError(
                    f"inline sentinel names element {element!r}, which is not in "
                    f"ALLOWED_INLINE ({', '.join(sorted(ALLOWED_INLINE))})"
                )
            return f"<{element}>{text}</{element}>"

        return _INLINE_RE.sub(replace, fragment)

    def _decode_blocks(self, fragment: str) -> str:
        if BLOCK_OPEN not in fragment:
            return fragment
        result = _BLOCK_IN_P_RE.sub(
            lambda m: _decode_block_payload(m.group(1)), fragment
        )
        return _BLOCK_RE.sub(lambda m: _decode_block_payload(m.group(1)), result)
