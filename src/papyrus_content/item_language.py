"""The language of every Item version, and the language group that joins a Story's translations (PPY-843a7c; docs/plans/multilingual-publishing.md).

A **language group** is one Story told in several languages. Its key is the primary Story's ``lineageId`` (tenant-prefixed on a tenant backend, like
every other index key). Each language is its own **localization**: an ordinary Story lineage, a sibling of the primary, with its own versions,
checklist, published row and URL. Its lineage id is derived, ``{primaryLineageId}--{languageTag}``, so creating the same localization twice is the
same record.

Fields on ``Item`` (every version carries them; a new version copies them from the one it follows):

* ``language``: the BCP 47 tag the version is written in, in Humanus's spelling (``en``, ``es-419``, ``zh-Hans``). Every row has one.
* ``languageGroupId``: the primary lineage id. A primary-language Story is its own group.
* ``sourceLineageId``, ``sourceVersionNumber``, ``sourceContentHash``: on a localization version, the exact primary version it was translated from.
* ``syncState``: on a localization version, how it stands against its source (``current``, ``updating``, ``diverged``, ``conflict``).

The group's members are one query on the index ``languageGroupId + language`` (``listItemsByLanguageGroupAndLanguage``).

**How a row gets its language.** Only the localization procedure (``papyrus.story.localize``) writes a language other than the site's primary
language, and it always names the language and the group. Every other writer writes a Story in the primary language; the authoring client writes
that language and the Story's own lineage as its group on any Item it creates or replaces without them (:func:`with_item_language`), the same way it
stamps the tenant. Rows written before the fields existed get them from ``papyrus stories languages`` (:mod:`papyrus_content.item_language_backfill`).
A reader never guesses: :func:`papyrus_content.editorial_languages.story_language` refuses a saved row that has no language.
"""
from __future__ import annotations

from typing import Any

LANGUAGE_FIELD = "language"
LANGUAGE_GROUP_FIELD = "languageGroupId"
SOURCE_FIELDS = ("sourceLineageId", "sourceVersionNumber", "sourceContentHash")
SYNC_STATE_FIELD = "syncState"
LOCALIZATION_SEPARATOR = "--"


#: What a row without a language means. This version writes a language on every Item it creates, so such a row was written before the fields existed
#: or by a Papyrus release older than the one that added them (5.110.0): a CLI or function still on an older release writes rows without one, and
#: running the command repairs those rows but not the writer, which has to be upgraded.
MISSING_CAUSE = ("The row was written before the language fields existed, or by a Papyrus older than 5.110.0 (check the version of the CLI or function that "
                 "saved it, and upgrade it: an older writer keeps producing rows without a language). ")


class ItemLanguageMissing(ValueError):
    """A saved Item version has no language: it was written before the field existed and the backfill has not reached it."""


def localization_lineage_id(primary_lineage_id: str, language: str) -> str:
    """The derived lineage id of a Story's localization into ``language`` (plan: "Localization ids are derived, not slug-based").

    The id is ``{primary}--{language}`` and nothing about it is ever parsed back: whether a row is a translation is decided by the row's own language
    group (:func:`is_localization_of`), never by the shape of its id. So a primary lineage may contain ``--`` itself: the ids the site generates for a
    Story whose slug was cut short end in ``--{hash}`` (``content-item-a-florida-deputy-...-to--bde88a5abce21df8``), and its Spanish translation is
    ``content-item-a-florida-deputy-...-to--bde88a5abce21df8--es-419``.

    The derivation is still one-to-one, which is all that makes "creating the same localization twice is the same record" true: a BCP 47 tag never
    contains ``--`` (its subtags are joined by one hyphen), so the language is whatever follows the *last* ``--`` and the primary is what precedes it.
    The one input that would break that is refused. That a Story is itself a translation (and so has no translations of its own) is a fact about its
    row, checked where the row is read (:func:`papyrus_content.localize.record.collect`), not a property its id string can carry."""
    if not primary_lineage_id:
        raise ValueError("A localization needs the lineage id of its primary Story.")
    if not language or LOCALIZATION_SEPARATOR in language or "#" in language:
        raise ValueError(f"{language!r} is not a language tag: a tag has no {LOCALIZATION_SEPARATOR!r} (its subtags are joined by one hyphen), and the "
                         "derived lineage id could not be told apart from another Story's.")
    return f"{primary_lineage_id}{LOCALIZATION_SEPARATOR}{language}"


def item_language(row: dict[str, Any]) -> str:
    """The language a saved row is written in. Refuses a row without one, naming the command that writes it."""
    language = row.get(LANGUAGE_FIELD)
    if not language:
        raise ItemLanguageMissing(f"Item {row.get('id') or row.get('lineageId') or '?'} has no language yet. " + MISSING_CAUSE
                                  + "Run `papyrus stories languages` (it writes the site's primary language on every row that lacks it).")
    return str(language)


def item_language_group(row: dict[str, Any]) -> str:
    """The language group a saved row belongs to (as stored, tenant-prefixed on a tenant backend). Refuses a row without one, naming the command that writes it."""
    group = row.get(LANGUAGE_GROUP_FIELD)
    if not group:
        raise ItemLanguageMissing(f"Item {row.get('id') or row.get('lineageId') or '?'} has no language group yet. " + MISSING_CAUSE
                                  + "Run `papyrus stories languages` (it writes each row's own lineage as its group on every row that lacks it).")
    return str(group)


def bare_group_id(value: str | None, tenant_id: str | None) -> str | None:
    """A stored ``languageGroupId`` without its tenant prefix: the primary lineage id."""
    if not value:
        return None
    prefix = f"{tenant_id}#" if tenant_id else ""
    return value[len(prefix):] if prefix and value.startswith(prefix) else value


def is_localization_of(lineage_id: str | None, group_id: str | None, language: str | None) -> bool:
    """Whether ``lineage_id`` is the derived lineage of the localization into ``language`` of the Story ``group_id`` (``{group}--{language}``): the one test
    for "is this a translation". A Story of its own, in any language, has its own lineage as its group."""
    return bool(lineage_id and group_id and language and lineage_id == f"{group_id}{LOCALIZATION_SEPARATOR}{language}")


def translation_original(row: dict[str, Any], tenant_id: str | None = None) -> str | None:
    """The Story a saved row is a translation of, judged by what the row says and not by its id: the row's language group is another lineage than its own.
    None for a Story of its own, in any language (including one whose id contains ``--``)."""
    group = bare_group_id(row.get(LANGUAGE_GROUP_FIELD), tenant_id)
    lineage = row.get("itemLineageId") or row.get("lineageId")
    return group if group and lineage and group != lineage else None


def localization_original(row: dict[str, Any], tenant_id: str | None = None) -> str | None:
    """The primary lineage a localization row (an ``Item`` version or a ``PublishedItem``) is a translation of, or None for any other row."""
    group = bare_group_id(row.get(LANGUAGE_GROUP_FIELD), tenant_id)
    return group if is_localization_of(row.get("itemLineageId") or row.get("lineageId"), group, row.get(LANGUAGE_FIELD)) else None


def with_item_language(payload: dict[str, Any], current: dict[str, Any] | None, primary: str) -> dict[str, Any]:
    """The payload of an Item create or full replace with its language and group: as written, else as the stored row has them, else the
    site's primary language and the row's own lineage. A payload naming another language must name its group: only the localization procedure
    writes one, and it always does."""
    current = current or {}
    language = payload.get(LANGUAGE_FIELD) or current.get(LANGUAGE_FIELD) or primary
    group = payload.get(LANGUAGE_GROUP_FIELD) or current.get(LANGUAGE_GROUP_FIELD)
    if not group:
        if language != primary:
            raise ValueError(f"Item {payload.get('id')} is written in {language}, which is not the site's primary language ({primary}), "
                             "without a language group. A localization names the primary Story's lineage as its languageGroupId.")
        group = payload.get("lineageId") or current.get("lineageId") or payload.get("id")
    return {**payload, LANGUAGE_FIELD: language, LANGUAGE_GROUP_FIELD: group}
