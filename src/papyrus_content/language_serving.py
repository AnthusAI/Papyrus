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

``segments``  ``{tag: {segment: translated segment}}``: the path segments of a language edition's sections, types and authored pages, in the language
              (``articles`` -> ``articulos``, ``security`` -> ``privacidad-y-seguridad``). The key is the segment as the edition would write it in
              English; a segment not listed keeps its English form. A translated segment is letters, digits, hyphens and underscores in any script
              (Chinese characters stay characters; URLs carry them percent-encoded), unique within its language. Default: none (English segments).

``auto``      ``{"enabled": true, "automation": "SITE.story-localize", "publish": true}``: translate every Story into every enabled language when it is
              published or republished (``localize/auto.py``). Off by default (no key, or ``enabled`` false). ``automation`` names the Automation that
              runs the registered translation procedure on the site's runner; ``publish`` (default true) publishes the translations a run saved
              cleanly, never a held one. The public gate still decides whether a published translation gets a page.

A setting that breaks a rule is refused with a message naming it; nothing is read as a default when it is wrong.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import humanus

from .editorial_languages import ANY_LANGUAGE, canonical, site_languages
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
class AutoTranslation:
    """The site's switch for translating on publish: the Automation that runs the translation procedure, and whether clean results publish."""

    automation: str
    publish: bool = True


@dataclass(frozen=True)
class ServingLanguages:
    """The languages a site serves, as the projection and the slug drafting read them."""

    primary: str
    enabled: tuple[str, ...]
    public: tuple[str, ...]
    prefixes: Mapping[str, str] = field(default_factory=dict)   # every enabled language; the primary's is ""
    slugs: Mapping[str, str] = field(default_factory=dict)      # every enabled language other than the primary
    auto: AutoTranslation | None = None                         # None: nothing is translated on publish (the default)
    segments: Mapping[str, Mapping[str, str]] = field(default_factory=dict)   # every enabled language other than the primary: {english segment: translated}

    def segments_of(self, tag: str) -> Mapping[str, str]:
        return self.segments.get(tag, {})

    def prefix(self, tag: str) -> str:
        return self.prefixes[tag]

    def is_public(self, tag: str) -> bool:
        return tag in self.public

    def digest_input(self) -> list:
        return [self.primary, list(self.public), sorted(self.prefixes.items()), sorted((tag, sorted(table.items())) for tag, table in self.segments.items())]


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
    segments = {tag: _segment_table(table, tag) for tag, table in tags_of(raw.get("segments"), "segments").items()}
    return ServingLanguages(primary=primary, enabled=enabled, public=public, prefixes=prefixes, slugs=slugs, auto=_auto_translation(raw.get("auto"), others), segments=segments)


def url_safe_segment(text: str) -> bool:
    """A path segment that is one address part in any script: letters, digits and combining marks, joined by single hyphens or underscores."""
    folded = unicodedata.normalize("NFC", text)
    return bool(folded) and folded == text and all(unicodedata.category(c)[0] in ("L", "N", "M") or c in "-_" for c in text) and not text.startswith(("-", "_")) and text == text.lower()


def _segment_table(raw: Any, tag: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"languages.segments.{tag} is a mapping of English path segment to the segment in the language.")
    table: dict[str, str] = {}
    for english, translated in raw.items():
        if not isinstance(english, str) or not _PREFIX.match(english):
            raise ValueError(f"languages.segments.{tag}: {english!r} is not a path segment as the English site writes it (lowercase letters, digits and hyphens).")
        if not isinstance(translated, str) or not url_safe_segment(translated):
            raise ValueError(f"languages.segments.{tag}: {translated!r} for {english} is not a URL-safe lowercase path segment (letters, digits, hyphens and underscores, one NFC form).")
        taken = next((other for other, value in table.items() if value == translated), None)
        if taken is not None:
            raise ValueError(f"languages.segments.{tag}: {english} and {taken} would both be served as /{translated}/.")
        table[english] = translated
    return table


def _auto_translation(raw: Any, others: list[str]) -> AutoTranslation | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError('languages.auto is {"enabled": true, "automation": ID, "publish": true}.')
    unknown = sorted(set(raw) - {"enabled", "automation", "publish"})
    if unknown:
        raise ValueError(f"languages.auto has no key {', '.join(unknown)} (its keys are enabled, automation and publish).")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("languages.auto.enabled is true or false.")
    publish = raw.get("publish", True)
    if not isinstance(publish, bool):
        raise ValueError("languages.auto.publish is true or false.")
    automation = raw.get("automation")
    if not enabled:
        return None
    if not isinstance(automation, str) or not automation.strip():
        raise ValueError("languages.auto.automation names the Automation that runs the translation procedure (papyrus automations list), for example SITE.story-localize.")
    if not others:
        raise ValueError("languages.auto translates into the enabled languages other than the primary, and the site has none.")
    return AutoTranslation(automation=automation.strip(), publish=publish)


def _unreadable(error: Exception) -> ValueError:
    """Humanus refuses a language it has no pack for with a LookupError; every refusal of this module is a ValueError naming the setting."""
    return error if isinstance(error, ValueError) else ValueError(str(error))


def checked_serving(languages: Any) -> ServingLanguages:
    """:func:`serving_languages` of a ``languages`` object alone (what the console form and the CLI hold), every refusal a ``ValueError``."""
    try:
        return serving_languages({"languages": languages})
    except (ValueError, LookupError) as error:
        raise _unreadable(error) from error


def describe_serving(languages: Any) -> dict[str, Any]:
    """What the console shows for a ``languages`` object: ``{"ok": True, ...}`` with every enabled language's effective prefix, public flag and slug
    policy and its defaults, or ``{"ok": False, "message": ...}`` with the refusal the projection would raise, so the form says it before saving.

    This is the one validation (:func:`serving_languages`); the console form calls it through the ``describeEditorialLanguages`` query and the CLI
    calls it directly, so neither holds a second copy of the rules."""
    try:
        serving = checked_serving(languages)
    except ValueError as error:
        return {"ok": False, "message": str(error)}
    return {
        "ok": True,
        "primary": serving.primary,
        "enabled": list(serving.enabled),
        "languages": [
            {
                "tag": tag,
                "primary": tag == serving.primary,
                "public": serving.is_public(tag),
                "prefix": serving.prefixes[tag],
                "defaultPrefix": default_prefix(tag) if tag != serving.primary else "",
                "slugPolicy": serving.slugs.get(tag),
                "defaultSlugPolicy": default_slug_policy(tag) if tag != serving.primary else None,
                "segments": dict(serving.segments_of(tag)),
            }
            for tag in serving.enabled
        ],
        "slugPolicies": list(SLUG_POLICIES),
        "auto": None if serving.auto is None else {"automation": serving.auto.automation, "publish": serving.auto.publish},
    }


def edit_serving(languages: Mapping[str, Any], *, public: list[str] | None = None, prefixes: Mapping[str, str | None] | None = None,
                 slugs: Mapping[str, str | None] | None = None, auto: Mapping[str, Any] | None = None,
                 segments: Mapping[str, Mapping[str, str | None]] | None = None) -> dict[str, Any]:
    """``languages`` with the serving keys edited, every other key kept as stored, and checked by :func:`serving_languages`. Refuses (``ValueError``)
    what the projection would refuse.

    ``public`` replaces the list of public languages; the primary is always public, so it is added when missing, and a list of only the primary is no
    key at all (the default). ``prefixes`` and ``slugs`` set the named languages' values and leave the others alone; a value of ``None`` or ``""``
    returns that language to its default. ``segments`` is ``{tag: {english segment: translated or None}}`` and sets those entries (None or empty removes one). ``auto`` merges the given keys (``enabled``, ``automation``, ``publish``) into ``languages.auto``; turning it off
    keeps the automation and the publish choice stored, so turning it on again needs nothing more."""
    result = dict(languages)
    try:
        primary = canonical(result.get("primary") or "")
        if public is not None:
            tags = [canonical(tag) for tag in public]
            listed = tuple(dict.fromkeys([primary, *tags]))
            result["public"] = list(listed)
            if listed == (primary,):
                result.pop("public")
        for key, edits in (("prefixes", prefixes), ("slugs", slugs)):
            if edits is None:
                continue
            merged = {canonical(tag): value for tag, value in (result.get(key) or {}).items()}
            for tag, value in edits.items():
                merged[canonical(tag)] = value
            kept = {tag: value for tag, value in merged.items() if value not in (None, "")}
            result[key] = kept
            if not kept:
                result.pop(key)
        if segments is not None:
            tables = {canonical(tag): dict(table) for tag, table in (result.get("segments") or {}).items()}
            for tag, edits in segments.items():
                table = tables.setdefault(canonical(tag), {})
                for english, value in edits.items():
                    table[english] = value
            kept_tables = {tag: {english: value for english, value in table.items() if value not in (None, "")} for tag, table in tables.items()}
            kept_tables = {tag: table for tag, table in kept_tables.items() if table}
            result["segments"] = kept_tables
            if not kept_tables:
                result.pop("segments")
        if auto is not None:
            result["auto"] = {**(result.get("auto") or {}), **auto}
    except LookupError as error:
        raise _unreadable(error) from error
    checked_serving(result)
    return result


def edit_enabled(languages: Mapping[str, Any], *, enable: Iterable[str] = (), disable: Iterable[str] = ()) -> dict[str, Any]:
    """``languages`` with the languages in ``enable`` added to ``enabled`` and the ones in ``disable`` taken out, every other key kept as stored, checked
    by :func:`serving_languages`.

    A tag is validated against the installed Humanus's language packs and stored in its spelling (``zh-CN`` is ``zh-Hans``); a tag it has no pack for is
    refused naming the supported ones. An enabled language is never public: ``public`` is left as it is (:func:`edit_serving` changes it). Enabling an
    enabled language and disabling one that is not enabled change nothing. Taking a language out takes its public flag, prefix, slug policy and segments
    with it (the console form does the same), and the primary cannot be taken out. Whether the language has translations is not known here: the caller
    asks before it disables."""
    result = dict(languages)
    try:
        primary = canonical(result.get("primary") or "")
        enabled = [canonical(tag) for tag in result.get("enabled") or []]
        adding = [canonical(tag) for tag in enable]
        removing = [canonical(tag) for tag in disable]
    except LookupError as error:
        raise _unreadable(error) from error
    if ANY_LANGUAGE in adding or ANY_LANGUAGE in removing:
        raise ValueError("A site writes in named languages; * is only a policy's language.")
    both = sorted(set(adding) & set(removing))
    if both:
        raise ValueError(f"{', '.join(both)} cannot be enabled and disabled in one command.")
    if primary in removing:
        raise ValueError(f"{primary} is the site's primary language, the language its Stories are written in; it cannot be disabled.")
    for tag in adding:
        if tag not in enabled:
            enabled.append(tag)
    enabled = [tag for tag in enabled if tag not in removing]
    result["enabled"] = enabled
    for tag in removing:
        if isinstance(result.get("public"), list):
            result["public"] = [kept for kept in result["public"] if canonical(kept) != tag]
        for key in ("prefixes", "slugs", "segments"):
            if isinstance(result.get(key), dict):
                kept = {name: value for name, value in result[key].items() if canonical(name) != tag}
                result[key] = kept
                if not kept:
                    result.pop(key)
    if result.get("public") == [primary]:
        result.pop("public")
    checked_serving(result)
    return result


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
