"""How a site serves its languages: each language's URL prefix, which languages are public, and each language's slug policy (docs/multilingual-serving.md).

These are part of the one ``languages`` setting the editorial check settings already hold (``editorial_languages``): ``primary`` and ``enabled`` say
which languages the site writes in; the keys below say how they are served. There is no second language setting anywhere.

``prefixes``  ``{tag: path segment}`` for each enabled language other than the primary, which stays at the root (the "primary at root" URL mode, the only
              mode an existing site can have, because published URLs are never retired). Default: the tag's base subtag, lowercased
              (``es-419`` -> ``es``, ``zh-Hans`` -> ``zh``). The prefix is a path; the tag is what ``<html lang>``, ``hreflang``, ``og:locale`` and
              JSON-LD ``inLanguage`` say.
``public``    the languages whose pages the public site serves, the primary always among them. Default: only the primary. A language that is enabled
              but not public is written, translated and checked, and its published localizations get no page (the plan's "preview" state). The
              projection refuses a public language whose interface strings are not complete (``projection/standard/interface_strings.py``).
``slugs``     ``{tag: policy}``: how a localization's slug is drafted at its first publish (then fixed by the slug lock, like every slug):
              ``translated`` (the translated title, folded to ASCII), ``characters`` (the translated title in its own script, Chinese characters
              kept), ``pinyin`` (the title romanized by the romanizer the caller supplies) or ``primary`` (the primary Story's slug). Default by the
              language's script: ``characters`` for a language Humanus counts in characters (Chinese), ``translated`` for every other.

A setting that breaks a rule is refused with a message naming it; nothing is read as a default when it is wrong.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import humanus

from .editorial_languages import canonical, site_languages
from .markus_renderer.build import page_slug, slugify

SLUG_POLICIES = ("translated", "characters", "pinyin", "primary")
#: The longest slug, in bytes of UTF-8 (Ryan, 2026-11-13: no chosen cap, only the technical one). A slug is a directory name in a local build
#: (``articles/<slug>/index.html``), and 255 bytes is the file-name limit of the file systems a site is built on (APFS, ext4): 85 Chinese characters.
#: Its percent-encoded URL (9 bytes a Chinese character, 765 at most) stays inside S3's 1,024-byte keys and CloudFront's 8,192-byte request line;
#: it can exceed the 512-byte keys of the edge's redirect store, which only a retired or renamed page needs (docs/multilingual-serving.md).
SLUG_MAX_BYTES = 255
_PREFIX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class EmptySlug(ValueError):
    """A title that leaves nothing to make a slug from (only punctuation or symbols). The localization is not published until a person gives it a slug."""


@dataclass(frozen=True)
class ServingLanguages:
    """The languages a site serves, as the projection and the slug drafting read them."""

    primary: str
    enabled: tuple[str, ...]
    public: tuple[str, ...]
    prefixes: Mapping[str, str] = field(default_factory=dict)   # every enabled language; the primary's is ""
    slugs: Mapping[str, str] = field(default_factory=dict)      # every enabled language other than the primary

    def prefix(self, tag: str) -> str:
        return self.prefixes[tag]

    def is_public(self, tag: str) -> bool:
        return tag in self.public

    def digest_input(self) -> list:
        return [self.primary, list(self.public), sorted(self.prefixes.items())]


def default_prefix(tag: str) -> str:
    """The base subtag, lowercased: ``es-419`` -> ``es``, ``zh-Hans`` -> ``zh``."""
    return tag.split("-", 1)[0].lower()


def default_slug_policy(tag: str) -> str:
    return "characters" if humanus.resolve_language(tag).unit == "character" else "translated"


def serving_languages(settings: Mapping[str, Any]) -> ServingLanguages:
    """The serving part of the site's ``languages`` setting, checked. Refuses, naming the key, a prefix that is not a lowercase path segment or that two
    languages share, a public or slug language the site does not write in, a public list without the primary, and an unknown slug policy."""
    written = site_languages(settings)
    raw = settings["languages"]
    primary, enabled = written["primary"], tuple(written["enabled"])
    others = [tag for tag in enabled if tag != primary]

    def tags_of(mapping: Any, key: str) -> dict[str, Any]:
        if mapping is None:
            return {}
        if not isinstance(mapping, Mapping):
            raise ValueError(f"languages.{key} is a mapping of language tag to value.")
        found = {canonical(tag): value for tag, value in mapping.items()}
        stray = [tag for tag in found if tag not in others]
        if stray:
            raise ValueError(f"languages.{key} names {', '.join(stray)}, which is not an enabled language other than the primary ({primary}).")
        return found

    given = tags_of(raw.get("prefixes"), "prefixes")
    prefixes = {primary: ""}
    for tag in others:
        prefix = given.get(tag, default_prefix(tag))
        if not isinstance(prefix, str) or not _PREFIX.match(prefix):
            raise ValueError(f"languages.prefixes: {prefix!r} for {tag} is not a lowercase path segment (letters, digits and hyphens, like es or zh-hant).")
        taken = next((other for other, value in prefixes.items() if value == prefix), None)
        if taken is not None:
            raise ValueError(f"languages.prefixes: {tag} and {taken} would both be served under /{prefix}/.")
        prefixes[tag] = prefix

    public_raw = raw.get("public")
    if public_raw is None:
        public = (primary,)
    elif not isinstance(public_raw, list):
        raise ValueError("languages.public is the list of languages the public site serves.")
    else:
        public = tuple(dict.fromkeys(canonical(tag) for tag in public_raw))
        stray = [tag for tag in public if tag not in enabled]
        if stray:
            raise ValueError(f"languages.public names {', '.join(stray)}, which the site does not write in (its languages: {', '.join(enabled)}).")
        if primary not in public:
            raise ValueError(f"languages.public must include the primary language {primary}: its pages are the site.")
        public = (primary, *(tag for tag in public if tag != primary))

    policies = tags_of(raw.get("slugs"), "slugs")
    slugs = {}
    for tag in others:
        policy = policies.get(tag, default_slug_policy(tag))
        if policy not in SLUG_POLICIES:
            raise ValueError(f"languages.slugs: {policy!r} for {tag} is not one of {', '.join(SLUG_POLICIES)}.")
        slugs[tag] = policy
    return ServingLanguages(primary=primary, enabled=enabled, public=public, prefixes=prefixes, slugs=slugs)


# ---------------------------------------------------------------------------------------------------- slugs


def normalized_slug(slug: str) -> str:
    """A slug as it is stored and as every key and path is built from it: Unicode NFC, so the same title typed on two systems is one address."""
    return unicodedata.normalize("NFC", slug)


def _within_bytes(slug: str, limit: int) -> str:
    """``slug`` cut to at most ``limit`` bytes of UTF-8, at the last hyphen that fits (else after a whole character), never mid-character."""
    if len(slug.encode("utf-8")) <= limit:
        return slug
    cut = slug.encode("utf-8")[:limit].decode("utf-8", "ignore")
    word = cut.rsplit("-", 1)[0] if "-" in cut else cut
    return word.strip("-")


def script_slug(title: str) -> str:
    """A slug that keeps the title's own script, so a Chinese reader reads the address (the ``characters`` policy).

    Full-width letters and digits become their ordinary forms and letters are lowercased (Unicode NFKC, then lowercase); every run of anything that
    is not a letter or a digit (punctuation, full-width punctuation such as ，。「」, symbols, spaces including the ideographic space) becomes one hyphen;
    the result is NFC and at most :data:`SLUG_MAX_BYTES` bytes of UTF-8. A title whose letters all fold to ASCII gets the ordinary
    slug (:func:`papyrus_content.markus_renderer.build.page_slug`), so the stored slug is always the slug its page is served under.
    ``能泄露你住在哪里的声音`` stays as it is; ``AI，会说谎吗？`` is ``ai-会说谎吗``."""
    folded = unicodedata.normalize("NFKC", title).lower()
    parts, current = [], []
    for character in folded:
        if unicodedata.category(character)[0] in ("L", "N", "M"):
            current.append(character)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return page_slug(_within_bytes(unicodedata.normalize("NFC", "-".join(parts)), SLUG_MAX_BYTES))


def localized_slug(title: str, policy: str, *, primary_slug: str, romanize: Callable[[str], str] | None = None) -> str:
    """The slug a localization is first published under, by its language's policy. Refuses (:class:`EmptySlug`) a title that leaves nothing, rather
    than inventing an address: the localization waits for a person to name it."""
    if policy == "primary":
        return normalized_slug(primary_slug)
    if policy == "translated":
        slug = _within_bytes(slugify(title), SLUG_MAX_BYTES)
    elif policy == "characters":
        slug = script_slug(title)
    elif policy == "pinyin":
        if romanize is None:
            raise ValueError("The pinyin slug policy needs a romanizer: the caller passes the function that writes the title in Latin letters.")
        slug = _within_bytes(slugify(romanize(title)), SLUG_MAX_BYTES)
    else:
        raise ValueError(f"{policy!r} is not one of {', '.join(SLUG_POLICIES)}.")
    if not slug:
        raise EmptySlug(f"The title {title!r} leaves nothing to make a {policy} slug from; give this localization a slug.")
    return slug


def unique_slug(slug: str, taken: Callable[[str], bool]) -> str:
    """``slug``, or ``slug-2``, ``slug-3``, ... : the first that no other Story of the same language has (``taken`` answers for one language). The suffix
    keeps the slug within :data:`SLUG_MAX_BYTES`."""
    if not taken(slug):
        return slug
    number = 2
    while True:
        suffix = f"-{number}"
        candidate = _within_bytes(slug, SLUG_MAX_BYTES - len(suffix)) + suffix
        if not taken(candidate):
            return candidate
        number += 1
