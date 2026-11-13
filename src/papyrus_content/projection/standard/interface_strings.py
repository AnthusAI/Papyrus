"""Interface strings: the words of a site's chrome in each language it serves, and the rule that a language is public only when they are complete.

Where they live: one JSON file per language in the site's static directory, ``strings/<tag>.json`` (``strings/en.json``, ``strings/es-419.json``,
``strings/zh-Hans.json``), a flat object of ``key: text``. The primary language's file names every key the site's own chrome needs (a hooks module
reads them from ``page.strings``); each other language's file gives the same keys in that language.

The keys the standard front end itself needs on a language edition are derived from ``projection.json``, so a setting written in the primary language
always has its translation:

* ``language.name``: the language's name in itself (``Español``, ``中文``), what a language switcher shows;
* ``site.description`` and ``site.tagline`` when the site sets them;
* ``home.label``: the name of the home link (``listings`` breadcrumbs);
* ``listing.pageSuffix``: what follows the title of page 2 and later of a listing, with ``{page}`` (`` — página {page}``);
* ``section.<name>.label`` and, when set, ``section.<name>.description``, for every section with a listing page;
* ``nav.<href>.label`` for every navigation link the edition keeps (home and section listings);
* ``footer.text`` when the site sets ``footer.text``.

:func:`missing_keys` is the check: a public language whose file lacks a key the rule requires is refused by the projection, naming the language and the
keys, so English words never appear on a Spanish page because a translation was forgotten.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

STRINGS_DIRECTORY = "strings"
LANGUAGE_NAME_KEY = "language.name"


class InterfaceStringsIncomplete(ValueError):
    """A public language lacks interface strings its pages need."""


def read_interface_strings(static_directory: Path | None) -> dict[str, dict[str, str]]:
    """``{tag: {key: text}}`` from ``strings/*.json`` of the static directory; empty when the site has none. A file that is not a flat object of
    strings is refused, naming it."""
    if static_directory is None or not (static_directory / STRINGS_DIRECTORY).is_dir():
        return {}
    found: dict[str, dict[str, str]] = {}
    for path in sorted((static_directory / STRINGS_DIRECTORY).glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in loaded.items()):
            raise ValueError(f"{STRINGS_DIRECTORY}/{path.name} must be a JSON object of interface string keys to text.")
        found[path.stem] = dict(loaded)
    return found


def required_keys(standard, primary_strings: Mapping[str, str], edition_nav_hrefs: tuple[str, ...]) -> tuple[str, ...]:
    """Every key a language edition needs: the standard front end's own (from the settings) and every key of the primary language's file."""
    keys = [LANGUAGE_NAME_KEY, "home.label", "listing.pageSuffix"]
    if standard.identity.description:
        keys.append("site.description")
    if standard.identity.tagline:
        keys.append("site.tagline")
    for section in standard.sections:
        if section.listing and section.listing_page:
            keys.append(f"section.{section.name}.label")
            if section.description:
                keys.append(f"section.{section.name}.description")
    keys.extend(f"nav.{href}.label" for href in edition_nav_hrefs)
    if standard.footer_text:
        keys.append("footer.text")
    keys.extend(primary_strings)
    return tuple(dict.fromkeys(keys))


def missing_keys(strings: Mapping[str, str], required: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(key for key in required if not (strings.get(key) or "").strip())
