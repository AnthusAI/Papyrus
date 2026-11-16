"""Interface strings: the words of a site's chrome in each language it serves, and the rule that a language is public only when they are complete.

Where they live: one JSON file per language in the site's static directory, ``strings/<tag>.json`` (``strings/en.json``, ``strings/es-419.json``,
``strings/zh-Hans.json``), a flat object of ``key: text``. The primary language's file names every key the site's own chrome needs (a hooks module
reads them from ``page.strings``); each other language's file gives the same keys in that language.

The keys the standard front end itself needs on a language edition are derived from ``projection.json``, so a setting written in the primary language
always has its translation:

* ``skipToMain``: the words of the skip link ("Skip to main content"), in every public language including the primary;
* ``switcherLabel``: the word "Language" in the language, the accessible name of the language switcher (with the current language's name), while the site
  draws one (``site.languageSwitcher.placement`` is not ``none``), in every public language including the primary;
* ``language.name``: the language's name in itself (``Español``, ``中文``), what a language switcher shows;
* ``site.name``: the publication's name in the language (masthead, ``<title>`` suffix, ``og:site_name``, feeds, Markdown twins, structured data; the primary
  language's name is ``site.name`` of ``projection.json`` and is listed as ``alternateName`` in the structured data of every edition); ``site.shortName`` when the
  site sets one, ``site.publisher`` when the site sets a publisher and ``feeds.title`` when the site gives its feeds a title other than the site's name;
* ``seo.defaultImage`` (a site path or URL) and ``seo.defaultImageAlt`` when the site sets a default share picture and its alt text: the picture usually carries the
  name, so each language has its own;
* ``site.description`` and ``site.tagline`` when the site sets them;
* ``home.label``: the name of the home link (``listings`` breadcrumbs);
* ``listing.pageSuffix``: what follows the title of page 2 and later of a listing, with ``{page}`` (`` — página {page}``);
* ``section.<name>.label`` and, when set, ``section.<name>.description``, for every section with a listing page;
* ``nav.<href>.label`` for every navigation link the edition keeps (home and section listings);
* ``notice.label`` and ``notice.text`` when the site sets ``site.notice`` (the publication's statement, for satire: it is said in the language on its pages, its
  Markdown twins, its feeds and its structured data, never in the primary language's words);
* ``footer.text`` when the site sets ``footer.text``;
* ``translation.label`` and ``translation.original``: the line every translated page carries ("Traducido por IA del {original}", with ``{original}`` the
  link to the original, whose words are ``translation.original``: "original en inglés").

:func:`missing_keys` is the check: a public language whose file lacks a key the rule requires is refused by the projection, naming the language and the
keys, so English words never appear on a Spanish page because a translation was forgotten.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

STRINGS_DIRECTORY = "strings"
LANGUAGE_NAME_KEY = "language.name"
SITE_NAME_KEY = "site.name"
SITE_SHORT_NAME_KEY = "site.shortName"
SITE_PUBLISHER_KEY = "site.publisher"
FEEDS_TITLE_KEY = "feeds.title"
SEO_IMAGE_KEY = "seo.defaultImage"
SEO_IMAGE_ALT_KEY = "seo.defaultImageAlt"
TRANSLATION_LABEL_KEY = "translation.label"
TRANSLATION_ORIGINAL_KEY = "translation.original"
UNTRANSLATED_LABEL_KEY = "listing.untranslated"
UNTRANSLATED_ORIGINAL_KEY = "listing.untranslatedOriginal"
#: Where ``translation.label`` places the link to the original.
ORIGINAL_PLACEHOLDER = "{original}"
SKIP_LINK_KEY = "skipToMain"
SWITCHER_LABEL_KEY = "switcherLabel"


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
    keys = [LANGUAGE_NAME_KEY, SKIP_LINK_KEY, SITE_NAME_KEY, "home.label", "listing.pageSuffix", TRANSLATION_LABEL_KEY, TRANSLATION_ORIGINAL_KEY, UNTRANSLATED_LABEL_KEY, UNTRANSLATED_ORIGINAL_KEY]
    if standard.identity.language_switcher_placement != "none":
        keys.append(SWITCHER_LABEL_KEY)
    if standard.identity.short_name:
        keys.append(SITE_SHORT_NAME_KEY)
    if standard.identity.publisher:
        keys.append(SITE_PUBLISHER_KEY)
    if standard.feeds.title and standard.feeds.title != standard.identity.name:
        keys.append(FEEDS_TITLE_KEY)
    if standard.seo.default_image:
        keys.append(SEO_IMAGE_KEY)   # the share picture carries the name, so each language has its own
    if standard.seo.default_image_alt:
        keys.append(SEO_IMAGE_ALT_KEY)
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
    if standard.identity.notice_label:
        keys.append("notice.label")
    if standard.identity.notice_text:
        keys.append("notice.text")
    if standard.footer_text:
        keys.append("footer.text")
    keys.extend(primary_strings)
    return tuple(dict.fromkeys(keys))


def missing_keys(strings: Mapping[str, str], required: tuple[str, ...]) -> tuple[str, ...]:
    """The required keys a language's strings lack or leave empty, and a ``translation.label`` with no place for the link to the original."""
    missing = [key for key in required if not (strings.get(key) or "").strip()]
    label = strings.get(TRANSLATION_LABEL_KEY) or ""
    if TRANSLATION_LABEL_KEY in required and label.strip() and ORIGINAL_PLACEHOLDER not in label:
        missing.append(f"{TRANSLATION_LABEL_KEY} (it must contain {ORIGINAL_PLACEHOLDER})")
    return tuple(missing)
