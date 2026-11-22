"""What kind of change one version of a Story is against another (PPY-cc6a0f, with the scoping of PPY-a2c230).

A Story's words are its text: the title, the dek, the blurb and every body block that is not a picture. Its pictures are the image directives in the body and
the cover's front matter (``image``, its alt text, credit and caption). Two versions compare as one of three kinds:

* ``text_unchanged``: the words and the pictures are the same (a republish, a change of section or type);
* ``picture_only``: the words are the same and a picture, its credit or its alt text differs;
* ``text_edited``: a word of the text differs.

A step whose answer depends on the text (a ``versioned`` step: the copy edit, the four review lenses, a translation's human review) is reopened when a version
after its skip is ``text_edited`` against the version the skip was made for; a picture-only change never reopens it.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .item_front_matter import front_matter
from .localize.blocks import blocks_of, normalized

TEXT_UNCHANGED, PICTURE_ONLY, TEXT_EDITED = "text_unchanged", "picture_only", "text_edited"
CHANGE_KINDS = (TEXT_UNCHANGED, PICTURE_ONLY, TEXT_EDITED)
CHANGE_KIND_WORDS = {TEXT_UNCHANGED: "text unchanged", PICTURE_ONLY: "picture only", TEXT_EDITED: "text edited"}

#: The front matter of the cover picture: a change to any of them is a change of picture, not of text.
PICTURE_FRONT_MATTER = ("image", "cover", "imageAlt", "imageCredit", "imageCaption")
#: The front matter whose words are the Story's text, beside the title and the dek.
TEXT_FRONT_MATTER = ("blurb",)
_DEK_KEYS = ("dek", "deck")
_PICTURE_DIRECTIVES = ("::image",)


def _digest(parts: list[str]) -> str:
    return hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()


def text_and_picture_fingerprints(row: Mapping[str, Any]) -> tuple[str, str]:
    """``(text, pictures)``: a hash of the version's words and a hash of its pictures, each insensitive to whitespace."""
    loaded = front_matter(row)
    deck = next((loaded[key] for key in _DEK_KEYS if isinstance(loaded.get(key), str)), None) or row.get("deck")
    fields = tuple((key, loaded[key]) for key in TEXT_FRONT_MATTER if isinstance(loaded.get(key), str) and loaded[key].strip())
    blocks = blocks_of(row.get("bodyMarkus") or "", title=row.get("title") or row.get("headline") or loaded.get("title"), deck=deck, fields=fields)
    is_picture = [block.kind == "directive" and block.text.lstrip().startswith(_PICTURE_DIRECTIVES) for block in blocks]
    text = [f"{block.kind}\x1f{normalized(block.text)}" for block, picture in zip(blocks, is_picture) if not picture]
    pictures = [normalized(block.text) for block, picture in zip(blocks, is_picture) if picture]
    pictures += [f"{key}\x1f{normalized(str(loaded[key]))}" for key in PICTURE_FRONT_MATTER if loaded.get(key) not in (None, "")]
    return _digest(text), _digest(pictures)


def change_kind(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> str:
    """The kind of change ``after`` is against ``before``. A first version (no ``before``) is all new text."""
    if before is None:
        return TEXT_EDITED
    before_text, before_pictures = text_and_picture_fingerprints(before)
    after_text, after_pictures = text_and_picture_fingerprints(after)
    if before_text != after_text:
        return TEXT_EDITED
    return PICTURE_ONLY if before_pictures != after_pictures else TEXT_UNCHANGED
