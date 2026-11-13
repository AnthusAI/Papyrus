"""The languages a site writes in, and the language each Story is written in (PPY-d0132d).

Humanus reads text only in a language it has a language pack for, and every check states the language of its text and every policy pack the
language its policies are written for (since Humanus 0.35). A language with no pack is refused, never read as English. Papyrus answers three
questions here and nowhere else:

* **Which languages the site writes in**: the editorial check settings' ``languages``: ``primary``, the language Stories are first written in,
  and ``enabled``, every language the site publishes, the primary included. Each tag names the exact variant the site writes: a site that
  writes neutral Latin American Spanish enables ``es-419`` (Machines on Machines, Ryan 2026-11-13). Tags are kept in Humanus's spelling
  (``zh-CN`` is stored as ``zh-Hans``).
* **Which language a request means**: :func:`site_language`. A request for a base language (``es``) means the variant the site enabled
  (``es-419``); a language the site does not write in is refused, naming it.
* **Which language a Story is written in**: :func:`story_language`. Every Story Papyrus holds today was written in its site's primary language;
  the multilingual plan's ``Item.language`` (docs/plans/multilingual-publishing.md, written for every Item by its backfill) is read here once it
  exists, and in no other place.

A policy has a language too (``EditorialPolicy.language``): a tag, or ``*`` for a language-neutral policy (placeholder leaks, tool URL parameters)
that applies to text in every language. :func:`languages_served` says which policy languages apply to text in one language: the neutral ones, the
base language's and the variant's own, in that order of precedence.
"""
from __future__ import annotations

from typing import Any

import humanus

ANY_LANGUAGE = "*"
DEFAULT_LANGUAGES: dict[str, Any] = {"primary": "en", "enabled": ["en"]}

# The starter packs a language brings when a site enables it, as `ensure_default_policies` imports them: the base language's packs and then
# the variant's own. English keeps its one default; its writing-standard packs (plain-language, asd-ste100) stay a choice in the panel.
# A language Humanus serves but this table does not name brings none until a pack is chosen for it here.
DEFAULT_STARTER_PACKS: dict[str, tuple[str, ...]] = {
    "en": ("ai-writing-tells",),
    "es": ("typography-es", "ai-writing-tells-es"),
    "es-419": ("word-choice-es-419",),
    "zh-Hans": ("typography-zh-hans", "translationese-zh-hans", "ai-writing-tells-zh-hans"),
}


class LanguageNotEnabled(ValueError):
    """The request names a language the site does not write in."""


def canonical(tag: str) -> str:
    """``tag`` in Humanus's spelling (``zh-CN`` -> ``zh-Hans``); ``*`` stays ``*``. Raises ``humanus.UnsupportedLanguageError`` naming a tag no pack serves."""
    if tag == ANY_LANGUAGE:
        return tag
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("A language is a BCP 47 tag such as en, es-419 or zh-Hans.")
    return humanus.resolve_language(tag).tag


def site_languages(settings: dict[str, Any]) -> dict[str, Any]:
    """The site's ``{primary, enabled}``, each tag checked against the installed Humanus. A site setting a language Humanus cannot read is refused."""
    raw = settings.get("languages")   # settings as `editorial_checks.settings_from` reads them: stored values over the defaults
    if not isinstance(raw, dict) or not raw.get("primary") or not isinstance(raw.get("enabled"), list):
        raise ValueError("The editorial check settings' languages need a primary language and the list of enabled languages.")
    enabled = [canonical(tag) for tag in raw["enabled"]]
    primary = canonical(raw["primary"])
    if ANY_LANGUAGE in enabled or primary == ANY_LANGUAGE:
        raise ValueError("A site writes in named languages; * is only a policy's language.")
    if primary not in enabled:
        raise ValueError(f"The primary language {primary} is not among the enabled languages ({', '.join(enabled)}).")
    return {"primary": primary, "enabled": list(dict.fromkeys(enabled))}


def primary_language(settings: dict[str, Any]) -> str:
    return site_languages(settings)["primary"]


def site_language(tag: str, settings: dict[str, Any]) -> str:
    """The language the site writes that serves a request for ``tag``: the tag itself when enabled, else the variant of it the site enabled.

    ``es`` on a site that enabled ``es-419`` is ``es-419``: the variant is the site's setting, not the caller's guess. Refused, naming ``tag``,
    when Humanus has no pack for it or the site does not write in it."""
    wanted = canonical(tag)
    enabled = site_languages(settings)["enabled"]
    if wanted in enabled:
        return wanted
    variants = [language for language in enabled if humanus.resolve_language(language).base == wanted]
    if len(variants) == 1:
        return variants[0]
    raise LanguageNotEnabled(f"This site does not write in {tag} (its languages: {', '.join(enabled)}).")


def story_language(item: dict[str, Any] | None, settings: dict[str, Any]) -> str:
    """The language a Story (any saved Item version, idea or draft) is written in. See the module docstring: today, the site's primary language."""
    del item  # the Story's own language field arrives with the multilingual plan's Item.language; until then every Story is a primary-language Story
    return primary_language(settings)


def languages_served(language: str) -> tuple[str, ...]:
    """The policy languages that apply to text in ``language``, least specific first: ``*``, the base language (for a variant), the language."""
    pack = humanus.resolve_language(language)
    return (ANY_LANGUAGE, *((pack.base,) if pack.base else ()), pack.tag)


def starter_packs_for(language: str) -> tuple[str, ...]:
    """The default starter packs of one enabled language: its base language's, then its own."""
    return tuple(name for tag in languages_served(language)[1:] for name in DEFAULT_STARTER_PACKS.get(tag, ()))
