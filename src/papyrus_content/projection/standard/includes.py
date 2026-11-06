"""``::include``: generated markup inside an authored Markus page, declared as data.

An authored page (a ``pages`` entry with a ``source`` file in the static directory, an item written in a directory
source) says where generated blocks go::

    ::include{kind="listing" collection="articles" count="6" card="article"}
    ::include{kind="listing" tags="featured,solutions" notTags="draft" sort="date" count="3" skip="1" layout="bare"}
    ::include{kind="listing" sections="articles" types="article" count="1" card="text" layout="bare"}
    ::include{kind="showcase"}
    ::include{kind="form" id="contact"}
    ::include{kind="block" name="proof-strip" depends="articles"}

``listing``   the entries a selection picks (see ``select.py``; ``collection`` borrows the selection, sort and ties of a
              configured collection, and the other attributes refine it), newest first unless ``sort`` says otherwise,
              ``skip`` entries dropped, then ``count`` kept. Each entry is the site's ``card`` hook (``card`` names a
              variant) or the default card; ``layout="grid"`` (default) wraps them in the card grid, ``bare`` does not.
              ``tag`` (``ul``, ``ol``, ``div`` or ``section``, with ``class``) wraps them in that element instead, and draws
              nothing at all when the selection is empty.
              A listing sorted by date also ranks by the editors' stars inside a ``bucket`` (``day``, ``week`` or ``none``; see ``story_order.py``).
              ``type`` and ``section`` are short forms of ``types`` and ``sections`` (several values joined by ``|`` or ``,``).
              ``sections="N" per="M"`` (a number) makes one group per section: the N sections whose best Story ranks highest, each with up to M
              Stories (``per`` may be a list, ``per="2,1"``: 2, then 1 for every later group). ``fallback="post"`` uses those types for a selection
              (or a section) that has none of ``type``. ``unique="true"`` claims what the listing shows in the page ledger and skips what an
              earlier listing on the page claimed. ``counts="true"`` puts ``data-count`` and the class ``papyrus-has-lead`` (the first is the best, so the
              largest) on the wrapper; groups always have them. ``heading="true"`` and ``more`` add a header to each group. See docs/home-page-groups.md.
``showcase``  the logo wall of the ``showcase`` settings.
``form``      a ``forms`` entry of ``projection.json``.
``references`` a grid of Reference cards from the home-page snapshot (see ``home_page_blocks.py``); needs ``homePage`` in
              ``projection.json``. Components on one page never show the same Reference twice: the first one wins.
              ``paged="true"`` (with ``homePage.references.paging``) makes it a list that loads more as the reader scrolls, with no cap:
              ``count`` is the first page, the rest is in data files (see ``home_page_lists.py`` and docs/home-page.md).
``block``     the markup the site's ``block`` hook returns for ``name``; the remaining attributes are passed to it.
              ``depends`` lists the sections (``@root`` for items without one, ``*`` for all) it reads. The names that start
              with ``knowledge-`` are the standard knowledge blocks (see ``knowledge_blocks.py``), rendered without a hook.

Dependencies are not written anywhere else: the selection an include renders from is the selection the page depends
on. :func:`include_inputs` is the digest of exactly the entries the page's includes show, so saving an item the
selection does not match writes nothing, and saving one it matches re-renders the page and only that page.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from . import home_page_blocks, knowledge_blocks
from .config import STORY_BUCKETS, StandardSettings
from .entries import StandardEntry, sorted_by
from .page_ledger import PageLedger
from .select import Selection, selection_from_mapping
from .story_order import rank_entries

KINDS = ("listing", "showcase", "form", "block", "references", "threads")
LISTING_ATTRIBUTES = {
    "kind", "collection", "sections", "tags", "allTags", "notTags", "types", "notTypes", "sort", "ties", "bucket", "count", "skip", "card", "layout", "tag", "class",
    "type", "section", "per", "fallback", "unique", "counts", "heading", "more",
}
STORY_LEDGER_PREFIX = "story:"
WRAPPER_TAGS = ("ul", "ol", "div", "section")
LAYOUTS = ("grid", "bare")


def _number(attributes: Mapping, name: str, source: str) -> int | None:
    if name not in attributes:
        return None
    try:
        value = int(attributes[name])
    except ValueError:
        value = -1
    if value < 0:
        raise ValueError(f"{source}: ::include {name} must be a whole number, got {attributes[name]!r}")
    return value


def check(attributes: Mapping, settings: StandardSettings, source: str) -> str:
    """Validate one include's attributes; the kind."""
    kind = attributes.get("kind", "")
    if kind not in KINDS:
        raise ValueError(f"{source}: ::include needs kind to be one of {', '.join(KINDS)}, got {kind!r}")
    if kind == "listing":
        unknown = set(attributes) - LISTING_ATTRIBUTES
        if unknown:
            raise ValueError(f"{source}: ::include listing has unknown attributes: {', '.join(sorted(unknown))}")
        collection = attributes.get("collection")
        if collection is not None and settings.collection(collection) is None:
            raise ValueError(f"{source}: ::include names collection {collection!r}, which projection.json does not define")
        if attributes.get("layout", "grid") not in LAYOUTS:
            raise ValueError(f"{source}: ::include layout must be one of {', '.join(LAYOUTS)}")
        if attributes.get("sort", "date") not in ("date", "order", "title") or attributes.get("ties", "slug-desc") not in ("slug-desc", "slug-asc"):
            raise ValueError(f"{source}: ::include sort is date, order or title; ties is slug-desc or slug-asc")
        if attributes.get("tag", "ul") not in WRAPPER_TAGS or ("class" in attributes and "tag" not in attributes and not is_group(attributes)):
            raise ValueError(f"{source}: ::include tag is one of {', '.join(WRAPPER_TAGS)}, and class needs a tag")
        if "tag" in attributes and attributes.get("layout", "grid") != "bare" and not is_group(attributes):
            raise ValueError(f"{source}: ::include tag goes with layout=\"bare\"")
        if "bucket" in attributes and attributes["bucket"] not in STORY_BUCKETS:
            raise ValueError(f"{source}: ::include listing bucket must be one of {', '.join(STORY_BUCKETS)}, got {attributes['bucket']!r}")
        _check_groups(attributes, source)
        _number(attributes, "count", source)
        _number(attributes, "skip", source)
    elif kind == "form":
        if not any(form.id == attributes.get("id") for form in settings.forms):
            raise ValueError(f"{source}: ::include form names {attributes.get('id')!r}, which projection.json does not define")
    elif kind == "block":
        if not attributes.get("name"):
            raise ValueError(f"{source}: ::include block needs a name")
        if attributes["name"].startswith(knowledge_blocks.PREFIX):
            knowledge_blocks.check(attributes, source)
    elif kind == "references":
        if settings.home_page is None:
            raise ValueError(f"{source}: ::include references: {home_page_blocks.NOT_CONFIGURED}")
        home_page_blocks.check(attributes, source)
        if home_page_blocks.is_paged(attributes) and settings.home_page.references.paging is None:
            raise ValueError(f"{source}: ::include references paged=\"true\" needs homePage.references.paging in projection.json (the site has not opted in)")
    elif kind == "threads":
        if settings.home_page is None:
            raise ValueError(f"{source}: ::include threads: {home_page_blocks.NOT_CONFIGURED}")
        home_page_blocks.check_threads(attributes, source)
    elif set(attributes) - {"kind"}:
        raise ValueError(f"{source}: ::include {kind} takes no attributes")
    return kind


def is_group(attributes: Mapping) -> bool:
    """True for a listing that makes one group per section: ``sections`` is a number (``sections="3"``), not a list of names."""
    return str(attributes.get("sections", "")).strip().isdigit()


def _check_groups(attributes: Mapping, source: str) -> None:
    for name in ("unique", "counts"):
        if attributes.get(name, "false") not in ("true", "false"):
            raise ValueError(f"{source}: ::include listing {name} must be \"true\" or \"false\", got {attributes[name]!r}")
    if "type" in attributes and "types" in attributes:
        raise ValueError(f"{source}: ::include listing takes type or types, not both")
    if "section" in attributes and ("sections" in attributes):
        raise ValueError(f"{source}: ::include listing takes section or sections, not both")
    if "fallback" in attributes and not (attributes.get("type") or attributes.get("types")):
        raise ValueError(f"{source}: ::include listing fallback goes with type (or types): it is what a selection with none of them shows instead")
    if "fallback" in attributes and not _names(attributes["fallback"]):
        raise ValueError(f"{source}: ::include listing fallback needs at least one type")
    grouped = is_group(attributes)
    if grouped:
        if int(attributes["sections"]) < 1:
            raise ValueError(f"{source}: ::include listing sections must be a number of groups of at least 1, got {attributes['sections']!r}")
        if "count" in attributes or "skip" in attributes:
            raise ValueError(f"{source}: ::include listing with sections=\"N\" takes per, not count or skip")
        if "section" in attributes:
            raise ValueError(f"{source}: ::include listing with sections=\"N\" chooses the sections itself, so it does not take section")
    elif "per" in attributes or "heading" in attributes or "more" in attributes:
        raise ValueError(f"{source}: ::include listing per, heading and more go with sections=\"N\" (one group per section)")
    if "per" in attributes and not all(part.isdigit() and int(part) >= 1 for part in _names(attributes["per"])) or ("per" in attributes and not _names(attributes["per"])):
        raise ValueError(f"{source}: ::include listing per must be a whole number of Stories, or a list of them, got {attributes['per']!r}")
    if attributes.get("counts") == "true" and "tag" not in attributes and not grouped and attributes.get("layout", "grid") == "bare":
        raise ValueError(f"{source}: ::include listing counts=\"true\" needs a wrapper: a tag, or the default grid")
    if attributes.get("heading", "true") not in ("true", "false"):
        raise ValueError(f"{source}: ::include listing heading must be \"true\" or \"false\", got {attributes['heading']!r}")


def _names(value: str) -> list[str]:
    """The values of ``a|b`` or ``a,b``."""
    return [part.strip() for part in str(value).replace("|", ",").split(",") if part.strip()]


def per_counts(attributes: Mapping) -> list[int]:
    """How many Stories each group takes; the last number repeats for every later group. One by default."""
    return [int(part) for part in _names(attributes.get("per", "1"))] or [1]


def _refinement(attributes: Mapping) -> dict:
    """The selection keys of an include, with the short forms ``type`` and ``section`` folded into ``types`` and ``sections``."""
    keys = {key: attributes[key] for key in ("sections", "tags", "allTags", "notTags", "types", "notTypes") if key in attributes}
    if "type" in attributes:
        keys["types"] = attributes["type"]
    if "section" in attributes:
        keys["sections"] = attributes["section"]
    if is_group(attributes):
        keys.pop("sections", None)
    return {key: ",".join(_names(value)) for key, value in keys.items()}


def _listing_selection(attributes: Mapping, settings: StandardSettings) -> tuple[Selection, str, str]:
    base = settings.collection(attributes.get("collection"))
    selection = base.select if base is not None else Selection()
    refined = selection_from_mapping(_refinement(attributes), "::include")
    merged = Selection(
        sections=refined.sections or selection.sections,
        tags=refined.tags or selection.tags,
        all_tags=refined.all_tags or selection.all_tags,
        not_tags=tuple(dict.fromkeys((*selection.not_tags, *refined.not_tags))),
        types=refined.types or selection.types,
        not_types=tuple(dict.fromkeys((*selection.not_types, *refined.not_types))),
    )
    sort = attributes.get("sort") or (base.sort if base is not None else "date")
    ties = attributes.get("ties") or (base.ties if base is not None else "slug-desc")
    return merged, sort, ties


@dataclass(frozen=True)
class Group:
    """One group of a ``sections="N"`` listing: the section's topic and its Stories, best first."""

    topic: str
    entries: tuple[StandardEntry, ...]


def _ranked(chosen: list[StandardEntry], sort: str, ties: str, attributes: Mapping, settings: StandardSettings, stars: Mapping[str, int] | None, as_of: date | None) -> list[StandardEntry]:
    ordered = sorted_by(chosen, sort, ties)
    if sort == "date" and stars:
        ordered = rank_entries(ordered, stars, attributes.get("bucket") or settings.listings.bucket, as_of)
    return ordered


def _unclaimed(chosen: list[StandardEntry], attributes: Mapping, ledger: PageLedger | None) -> list[StandardEntry]:
    if ledger is None or attributes.get("unique") != "true":
        return chosen
    return [entry for entry in chosen if STORY_LEDGER_PREFIX + entry.item_id not in ledger.seen]


def _claim(shown: list[StandardEntry], attributes: Mapping, ledger: PageLedger | None) -> list[StandardEntry]:
    if ledger is not None and attributes.get("unique") == "true":
        for entry in shown:
            ledger.claim(STORY_LEDGER_PREFIX + entry.item_id)
    return shown


def _fallback_selection(selection: Selection, attributes: Mapping) -> Selection | None:
    if "fallback" not in attributes:
        return None
    return Selection(
        sections=selection.sections, tags=selection.tags, all_tags=selection.all_tags, not_tags=selection.not_tags,
        types=tuple(_names(attributes["fallback"])), not_types=(),
    )


def listing_entries(
    attributes: Mapping, entries: list[StandardEntry], settings: StandardSettings, stars: Mapping[str, int] | None = None, as_of: date | None = None,
    ledger: PageLedger | None = None,
) -> list[StandardEntry]:
    """The entries a ``listing`` include shows, in order.

    A listing sorted by date also ranks by the editors' stars (``story_order.py``) when it is given the ``stars`` of the rated Stories: the newest ``bucket``
    first (``listings.bucket``, the last seven days unless the include says ``day``, ``week`` or ``none``; windows counted back from the day ``as_of``) and the stars inside it. ``skip`` and ``count`` cut the ranked list.

    With ``unique="true"`` and a page ``ledger`` the Stories an earlier listing placed are skipped and the ones shown are claimed; ``fallback`` lists other types
    when none of ``type`` is left. A listing with ``sections="N"`` is the Stories of :func:`listing_groups`, one group after the other.
    """
    if is_group(attributes):
        return [entry for group in listing_groups(attributes, entries, settings, stars, as_of, ledger) for entry in group.entries]
    selection, sort, ties = _listing_selection(attributes, settings)
    chosen = _unclaimed(_ranked(selection.select(entries), sort, ties, attributes, settings, stars, as_of), attributes, ledger)
    fallback = _fallback_selection(selection, attributes)
    if not chosen and fallback is not None:
        chosen = _unclaimed(_ranked(fallback.select(entries), sort, ties, attributes, settings, stars, as_of), attributes, ledger)
    skip = _number(attributes, "skip", "::include") or 0
    count = _number(attributes, "count", "::include")
    chosen = chosen[skip:]
    return _claim(chosen if count is None else chosen[:count], attributes, ledger)


def listing_groups(
    attributes: Mapping, entries: list[StandardEntry], settings: StandardSettings, stars: Mapping[str, int] | None = None, as_of: date | None = None,
    ledger: PageLedger | None = None,
) -> list[Group]:
    """The groups of a ``sections="N" per="M"`` listing: the N sections whose best Story ranks highest, each with up to M Stories, best first.

    A section with none of ``type`` uses the ``fallback`` types. A section that has nothing left (after the ledger) is skipped, so there is no empty group.
    The sections are ordered by the rank of the best Story each would show, in one ranking over every type the include may use; items without a section are not a group."""
    selection, sort, ties = _listing_selection(attributes, settings)
    fallback = _fallback_selection(selection, attributes)
    primary = _unclaimed(_ranked(selection.select(entries), sort, ties, attributes, settings, stars, as_of), attributes, ledger)
    backup = _unclaimed(_ranked(fallback.select(entries), sort, ties, attributes, settings, stars, as_of), attributes, ledger) if fallback is not None else []
    position = {entry.item_id: place for place, entry in enumerate(_ranked([*primary, *backup], sort, ties, attributes, settings, stars, as_of))}
    topics: dict[str, list[StandardEntry]] = {}
    for entry in primary:
        if entry.topic:
            topics.setdefault(entry.topic, []).append(entry)
    for entry in backup:
        if entry.topic and entry.topic not in topics:
            topics.setdefault(entry.topic, [])
    for topic, found in topics.items():
        if not found:
            found.extend(entry for entry in backup if entry.topic == topic)
    ordered = sorted(topics.items(), key=lambda item: position[item[1][0].item_id])
    counts = per_counts(attributes)
    groups: list[Group] = []
    for topic, found in ordered:
        if len(groups) >= int(attributes["sections"]):
            break
        shown = _claim(found[: counts[min(len(groups), len(counts) - 1)]], attributes, ledger)
        groups.append(Group(topic, tuple(shown)))
    return groups


def depends_of(attributes: Mapping) -> tuple[str, ...]:
    return tuple(part.strip() for part in attributes.get("depends", "").split(",") if part.strip())


def include_inputs(includes: list[dict], entries: list[StandardEntry], settings: StandardSettings, stars: Mapping[str, int] | None = None, as_of: date | None = None) -> list:
    """What a page's includes render from, as JSON-able data: the full fingerprint of each entry a listing shows (or a block reads)."""
    inputs: list = []
    ledger = PageLedger()   # a listing with unique="true" shows what the earlier ones left, so its inputs are worked out in the page's order
    for attributes in includes:
        kind = attributes.get("kind")
        if kind == "listing" and is_group(attributes):
            groups = listing_groups(attributes, entries, settings, stars, as_of, ledger)
            inputs.append([dict(attributes), [[group.topic, [entry.fingerprint(full=True) for entry in group.entries]] for group in groups]])
        elif kind == "listing":
            inputs.append([dict(attributes), [entry.fingerprint(full=True) for entry in listing_entries(attributes, entries, settings, stars, as_of, ledger)]])
        elif kind == "block":
            wanted = depends_of(attributes)
            chosen = [entry for entry in entries if "*" in wanted or (entry.topic or "@root") in wanted]
            inputs.append([dict(attributes), [entry.fingerprint(full=True) for entry in chosen]])
        elif kind == "references":
            inputs.append([dict(attributes), "home-page:references"])
        elif kind == "threads":
            inputs.append([dict(attributes), "home-page:threads"])
        else:
            inputs.append(dict(attributes))
    return inputs
