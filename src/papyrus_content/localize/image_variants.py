"""Language variants of a Story's pictures (docs/figures.md, "Figures in other languages"). Optional, never required, never a block.

**The model.** A translation is its own Story (the sibling lineage ``<story>--<language>``), and the pictures it shows are the ones its own body and front
matter name. So a language variant of a picture is an ordinary stored picture (a light and a dark file, with renditions, saved in the translation's own
media like any other image) that the translation's ``::image{}`` line and cover (``image``/``imageDark``) point at instead of the original's. Because
every reader of a page (the page, the cards and listings, the social preview, the Markdown copy, the feeds, the sitemap) already reads the translation's
own body and front matter, nothing downstream needs to know that variants exist. With no variant the translation keeps naming the original picture, with
its alt text and caption translated, which is the default and is complete.

**The link.** The translation's front matter keeps a record of which pictures are variants, so a re-translation keeps them and a person can see them::

    imageVariants:
    - from: assets/the-story/hazard.png        # the original picture, as the original Story stores it
      fromDark: assets/the-story/hazard.dark.png
      src: assets/the-story--es/hazard-es.png  # the language variant, stored with the translation
      srcDark: assets/the-story--es/hazard-es.dark.png
      language: es

This module is pure text: it never reads or writes a backend.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

import yaml

from ..markus_renderer.content_markup import _ATTR_RE, _IMAGE_DIRECTIVE_RE
from ..projection.stored import FRONT_MATTER_IMAGE_KEYS

VARIANTS_KEY = "imageVariants"
_LIGHT_KEYS = ("image", "cover", "ogImage", "thumbnail")
_DARK_OF = {"image": "imageDark", "cover": "coverDark", "thumbnail": "thumbnailDark"}   # ogImage has no Night twin


def normalize(path: Any) -> str:
    """A stored picture path with no leading slash and no ``media/`` prefix: how paths compare."""
    text = str(path or "").strip().lstrip("/")
    return text[len("media/"):] if text.startswith("media/") else text


@dataclass(frozen=True)
class ImageVariant:
    original: str
    src: str
    language: str
    original_dark: str = ""
    src_dark: str = ""

    def as_entry(self) -> dict[str, str]:
        entry = {"from": self.original}
        if self.original_dark:
            entry["fromDark"] = self.original_dark
        entry["src"] = self.src
        if self.src_dark:
            entry["srcDark"] = self.src_dark
        entry["language"] = self.language
        return entry

    @classmethod
    def from_entry(cls, entry: Mapping[str, Any]) -> "ImageVariant":
        original, src = normalize(entry.get("from")), normalize(entry.get("src"))
        if not original or not src or not entry.get("language"):
            raise ValueError(f"an {VARIANTS_KEY} entry needs from, src and language (got {dict(entry)}).")
        return cls(original, src, str(entry["language"]), normalize(entry.get("fromDark")), normalize(entry.get("srcDark")))


def _load(front_matter_yaml: str | None) -> dict[str, Any]:
    loaded = yaml.safe_load(front_matter_yaml) if front_matter_yaml and front_matter_yaml.strip() else {}
    return loaded if isinstance(loaded, dict) else {}


def read_variants(front_matter_yaml: str | None) -> list[ImageVariant]:
    """The variants a front matter records, in the order recorded."""
    entries = _load(front_matter_yaml).get(VARIANTS_KEY) or []
    if not isinstance(entries, list):
        raise ValueError(f"front matter {VARIANTS_KEY} must be a list.")
    return [ImageVariant.from_entry(entry) for entry in entries if isinstance(entry, Mapping)]


def _quoted(key: str, value: str) -> str:
    """``key="value"``, in single quotes when the value holds a double quote (a directive cannot escape one)."""
    value = " ".join(value.split())
    if '"' not in value:
        return f'{key}="{value}"'
    return f"{key}='{value}'" if "'" not in value else f'{key}="{value.replace(chr(34), chr(8221))}"'


def _set_attribute(attrs: str, key: str, value: str | None) -> str:
    """``attrs`` (the inside of an ``::image{...}``) with ``key`` set to ``value`` (removed when None), keeping everything else as written."""
    for match in _ATTR_RE.finditer(attrs):
        if match.group("key") == key:
            if value is None:
                return (attrs[: match.start()].rstrip(" \t") + attrs[match.end():]) if attrs[: match.start()].strip() else attrs[match.end():].lstrip(" \t")
            return attrs[: match.start()] + _quoted(key, value) + attrs[match.end():]
    return attrs if value is None else attrs.rstrip() + " " + _quoted(key, value)


def _value(attrs: str, key: str) -> str | None:
    for match in _ATTR_RE.finditer(attrs):
        if match.group("key") == key:
            return next(v for v in (match.group("dq"), match.group("sq"), match.group("bare")) if v is not None)
    return None


def _point_body_at(body: str, variant: ImageVariant, texts: Mapping[str, str] | None = None) -> tuple[str, int]:
    """``body`` with every ``::image{}`` whose ``src`` is the variant's original pointing at the variant, and how many were changed. A variant with no
    dark picture turns the dark pairing off for that image, so a reader in dark mode never gets the original's words back."""
    changed = 0

    def directive(match: re.Match) -> str:
        nonlocal changed
        attrs = match.group("attrs")
        shown = _value(attrs, "src")
        if shown is None or normalize(shown) != variant.original:
            return match.group(0)
        changed += 1
        lead = "/" if shown.startswith("/") else ""
        attrs = _set_attribute(attrs, "src", lead + variant.src)
        attrs = _set_attribute(attrs, "srcDark", lead + variant.src_dark if variant.src_dark else "none")
        for key, text in (texts or {}).items():   # the variant's own alt text and caption, when the picture's words changed what they should say
            attrs = _set_attribute(attrs, key, text)
        return match.group(0).replace("{" + match.group("attrs") + "}", "{" + attrs + "}", 1)

    return _IMAGE_DIRECTIVE_RE.sub(directive, body), changed


def _original_dark(body: str, front_matter: Mapping[str, Any], original: str) -> str:
    for match in _IMAGE_DIRECTIVE_RE.finditer(body):
        shown, dark = _value(match.group("attrs"), "src"), _value(match.group("attrs"), "srcDark")
        if shown is not None and normalize(shown) == original and dark and dark.lower() != "none":
            return normalize(dark)
    for key, dark_key in _DARK_OF.items():
        if normalize(front_matter.get(key)) == original and front_matter.get(dark_key):
            return normalize(front_matter[dark_key])
    return ""


def apply_variant(front_matter_yaml: str | None, body: str, variant: ImageVariant, texts: Mapping[str, str] | None = None) -> tuple[str | None, str, int]:
    """The front matter and body of a translation with ``variant`` applied: its figures and cover name the variant, and the front matter records it
    (replacing an earlier record of the same original). Returns ``(front_matter, body, places)``, ``places`` being how many pictures were repointed
    (0 means the translation shows no picture named ``variant.original``, and the caller should say so). ``texts`` (``alt``, ``caption``) replaces those attributes
    on the repointed figures."""
    loaded = _load(front_matter_yaml)
    if not variant.original_dark:   # remember the original's Night picture, so a re-translation can put the original back exactly
        variant = replace(variant, original_dark=_original_dark(body, loaded, variant.original))
    body, places = _point_body_at(body, variant, texts)
    for key in _LIGHT_KEYS:
        if normalize(loaded.get(key)) == variant.original:
            lead = "/" if str(loaded[key]).startswith("/") else ""
            loaded[key] = lead + variant.src
            places += 1
            dark_key = _DARK_OF.get(key)
            if dark_key and dark_key in loaded:
                if variant.src_dark:
                    loaded[dark_key] = lead + variant.src_dark
                else:
                    del loaded[dark_key]
    if not places:
        return front_matter_yaml, body, 0
    return record_variant(yaml.safe_dump(loaded, allow_unicode=True, sort_keys=False), variant), body, places


def record_variant(front_matter_yaml: str | None, variant: ImageVariant) -> str:
    """The front matter with ``variant`` recorded under ``imageVariants`` (replacing an earlier record of the same original)."""
    loaded = _load(front_matter_yaml)
    kept = [entry for entry in (loaded.get(VARIANTS_KEY) or []) if not (isinstance(entry, Mapping) and normalize(entry.get("from")) == variant.original)]
    loaded[VARIANTS_KEY] = [*kept, variant.as_entry()]
    return yaml.safe_dump(loaded, allow_unicode=True, sort_keys=False)


def revert_body(body: str, variants: list[ImageVariant]) -> str:
    """``body`` with each variant's picture put back to the original's (the inverse of the body half of :func:`apply_variant`). The translation run works on
    text that names the original pictures, as the source does, so the whole-document directive check compares like with like; :func:`carry_forward` puts the
    variants back when the result is saved."""
    for variant in variants:
        def directive(match: re.Match, variant: ImageVariant = variant) -> str:
            attrs = match.group("attrs")
            shown = _value(attrs, "src")
            if shown is None or normalize(shown) != variant.src:
                return match.group(0)
            lead = "/" if shown.startswith("/") else ""
            attrs = _set_attribute(attrs, "src", lead + variant.original)
            attrs = _set_attribute(attrs, "srcDark", lead + variant.original_dark if variant.original_dark else None)
            return match.group(0).replace("{" + match.group("attrs") + "}", "{" + attrs + "}", 1)

        body = _IMAGE_DIRECTIVE_RE.sub(directive, body)
    return body


def remove_variant(front_matter_yaml: str | None, body: str, variant: ImageVariant) -> tuple[str | None, str]:
    """The front matter and body of a translation with ``variant`` taken out: its figures and cover name the original again and the record is dropped."""
    body = revert_body(body, [variant])
    loaded = _load(front_matter_yaml)
    for key in _LIGHT_KEYS:
        if normalize(loaded.get(key)) == variant.src:
            lead = "/" if str(loaded[key]).startswith("/") else ""
            loaded[key] = lead + variant.original
            dark_key = _DARK_OF.get(key)
            if dark_key and variant.original_dark:
                loaded[dark_key] = lead + variant.original_dark
            elif dark_key:
                loaded.pop(dark_key, None)
    loaded[VARIANTS_KEY] = [entry for entry in (loaded.get(VARIANTS_KEY) or []) if not (isinstance(entry, Mapping) and normalize(entry.get("src")) == variant.src)]
    if not loaded[VARIANTS_KEY]:
        del loaded[VARIANTS_KEY]
    return (yaml.safe_dump(loaded, allow_unicode=True, sort_keys=False) if loaded else None), body


def carry_forward(front_matter_yaml: str | None, body: str, variants: list[ImageVariant]) -> tuple[str | None, str]:
    """A fresh translation (made from the original's pictures) with the earlier translation's variants applied again, so re-translating a Story never
    loses a localized figure. A variant whose original the new source no longer shows is dropped with the figure."""
    for variant in variants:
        front_matter_yaml, body, _ = apply_variant(front_matter_yaml, body, variant)
    return front_matter_yaml, body


def images_with_text(body: str, front_matter_yaml: str | None, facts: Mapping[str, Mapping[str, Any]], variants: list[ImageVariant] = ()) -> list[dict[str, Any]]:
    """The pictures of a Story whose stored record says they hold words (``facts``: normalized stored path -> that picture's ``figure`` record, from the
    ``MediaAsset`` metadata written when ``papyrus figures render``'s pictures were saved). Each is ``{src, where, labels, localized}``; ``localized`` is True
    when the translation already has a variant for it. A picture with no record (a photograph, or a figure saved before records were kept) is not reported:
    Papyrus does not guess at words in pixels."""
    done = {variant.original for variant in variants}
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def consider(src: str | None, where: str) -> None:
        path = normalize(src)
        record = facts.get(path) if path else None
        if path and path not in seen and isinstance(record, Mapping) and record.get("embeddedText"):
            seen.add(path)
            found.append({"src": path, "where": where, "labels": int(record.get("textLabels") or 0), "localized": path in done})

    front_matter = _load(front_matter_yaml)
    for key in _LIGHT_KEYS:
        consider(front_matter.get(key), "cover")
    for match in _IMAGE_DIRECTIVE_RE.finditer(body or ""):
        consider(_value(match.group("attrs"), "src"), "figure")
    return found


__all__ = ["FRONT_MATTER_IMAGE_KEYS", "ImageVariant", "VARIANTS_KEY", "apply_variant", "carry_forward", "images_with_text", "revert_body", "normalize", "read_variants"]
