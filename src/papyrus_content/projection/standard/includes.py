"""``::include``: generated markup inside an authored Markus page, declared as data.

An authored page (a ``pages`` entry with a ``source`` file in the static directory, an item written in a directory
source) says where generated blocks go::

    ::include{kind="listing" collection="articles" count="6" card="article"}
    ::include{kind="listing" tags="featured,solutions" notTags="draft" sort="date" count="3" skip="1" layout="bare"}
    ::include{kind="showcase"}
    ::include{kind="form" id="contact"}
    ::include{kind="block" name="proof-strip" depends="articles"}

``listing``   the entries a selection picks (see ``select.py``; ``collection`` borrows the selection, sort and ties of a
              configured collection, and the other attributes refine it), newest first unless ``sort`` says otherwise,
              ``skip`` entries dropped, then ``count`` kept. Each entry is the site's ``card`` hook (``card`` names a
              variant) or the default card; ``layout="grid"`` (default) wraps them in the card grid, ``bare`` does not.
``showcase``  the logo wall of the ``showcase`` settings.
``form``      a ``forms`` entry of ``projection.json``.
``block``     the markup the site's ``block`` hook returns for ``name``; the remaining attributes are passed to it.
              ``depends`` lists the sections (``@root`` for items without one, ``*`` for all) it reads.

Dependencies are not written anywhere else: the selection an include renders from is the selection the page depends
on. :func:`include_inputs` is the digest of exactly the entries the page's includes show, so saving an item the
selection does not match writes nothing, and saving one it matches re-renders the page and only that page.
"""

from __future__ import annotations

from collections.abc import Mapping

from .config import StandardSettings
from .entries import StandardEntry, sorted_by
from .select import Selection, selection_from_mapping

KINDS = ("listing", "showcase", "form", "block")
LISTING_ATTRIBUTES = {"kind", "collection", "sections", "tags", "allTags", "notTags", "sort", "ties", "count", "skip", "card", "layout"}
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
        _number(attributes, "count", source)
        _number(attributes, "skip", source)
    elif kind == "form":
        if not any(form.id == attributes.get("id") for form in settings.forms):
            raise ValueError(f"{source}: ::include form names {attributes.get('id')!r}, which projection.json does not define")
    elif kind == "block":
        if not attributes.get("name"):
            raise ValueError(f"{source}: ::include block needs a name")
    elif set(attributes) - {"kind"}:
        raise ValueError(f"{source}: ::include {kind} takes no attributes")
    return kind


def _listing_selection(attributes: Mapping, settings: StandardSettings) -> tuple[Selection, str, str]:
    base = settings.collection(attributes.get("collection"))
    selection = base.select if base is not None else Selection()
    refined = selection_from_mapping({key: attributes[key] for key in ("sections", "tags", "allTags", "notTags") if key in attributes}, "::include")
    merged = Selection(
        sections=refined.sections or selection.sections,
        tags=refined.tags or selection.tags,
        all_tags=refined.all_tags or selection.all_tags,
        not_tags=tuple(dict.fromkeys((*selection.not_tags, *refined.not_tags))),
    )
    sort = attributes.get("sort") or (base.sort if base is not None else "date")
    ties = attributes.get("ties") or (base.ties if base is not None else "slug-desc")
    return merged, sort, ties


def listing_entries(attributes: Mapping, entries: list[StandardEntry], settings: StandardSettings) -> list[StandardEntry]:
    """The entries a ``listing`` include shows, in order."""
    selection, sort, ties = _listing_selection(attributes, settings)
    chosen = sorted_by(selection.select(entries), sort, ties)
    skip = _number(attributes, "skip", "::include") or 0
    count = _number(attributes, "count", "::include")
    chosen = chosen[skip:]
    return chosen if count is None else chosen[:count]


def depends_of(attributes: Mapping) -> tuple[str, ...]:
    return tuple(part.strip() for part in attributes.get("depends", "").split(",") if part.strip())


def include_inputs(includes: list[dict], entries: list[StandardEntry], settings: StandardSettings) -> list:
    """What a page's includes render from, as JSON-able data: the full fingerprint of each entry a listing shows (or a block reads)."""
    inputs: list = []
    for attributes in includes:
        kind = attributes.get("kind")
        if kind == "listing":
            inputs.append([dict(attributes), [entry.fingerprint(full=True) for entry in listing_entries(attributes, entries, settings)]])
        elif kind == "block":
            wanted = depends_of(attributes)
            chosen = [entry for entry in entries if "*" in wanted or (entry.section.name if entry.section else "@root") in wanted]
            inputs.append([dict(attributes), [entry.fingerprint(full=True) for entry in chosen]])
        else:
            inputs.append(dict(attributes))
    return inputs
