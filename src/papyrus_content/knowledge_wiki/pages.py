"""The text of generated wiki pages: pure functions from accepted records to front matter and Markus.

Nothing here writes, reads the clock or calls a language model. A page body is the approved description, or a minimal
factual line (name, kind, other names) when there is none, followed by the knowledge blocks of the standard front end.
The counts, series and neighbours are drawn from the snapshot at projection time, never copied into the page.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import yaml

from ..knowledge_snapshot.keys import kind_label, slug as slugify
from ..wiki_stamp import REVIEW_KEY, SUPERSEDED_KEY, UPDATED_KEY

KIND_ENTITY = "entity"
KIND_BEAT = "beat"
KIND_SUBTOPIC = "subtopic"
PRESERVED_KEYS = ("pin", "annotations", SUPERSEDED_KEY)
STAMP_KEYS = (REVIEW_KEY, UPDATED_KEY)
BLOCK = '::include{{kind="block" name="knowledge-entity" key="{key}" part="{part}"{extra}}}'
LISTING = '::include{{kind="listing"{sections} tags="{tags}" count="{count}"}}'


@dataclass(frozen=True)
class PageSpec:
    """One generated page: its identity (``key`` is the entity key or topic key), slug, front matter and Markus body."""

    kind: str
    key: str
    slug: str
    front_matter: dict[str, Any]
    body: str
    notes: tuple[str, ...] = field(default=())


def front_matter_yaml(front_matter: Mapping[str, Any]) -> str:
    return yaml.safe_dump(dict(front_matter), sort_keys=False, allow_unicode=True, width=1000)


def clean_text(text: str | None) -> str:
    return " ".join(str(text or "").split())


def _annotation(annotations: Any) -> str:
    if not isinstance(annotations, Sequence) or isinstance(annotations, str) or not annotations:
        return ""
    first = annotations[0]
    if not isinstance(first, Mapping) or not first.get("date"):
        return ""
    label = clean_text(first.get("label")).replace('"', "'")
    return f' annotate="{clean_text(str(first["date"]))}"' + (f' annotateLabel="{label}"' if label else "")


def entity_body(name: str, kind: str, aliases: Sequence[str], description: str | None, key: str, annotations: Any = None) -> str:
    text = clean_text(description)
    if not text:
        other = f" Also known as: {', '.join(aliases)}." if aliases else ""
        text = f"{name} is listed here as a {kind_label(kind).lower()}.{other}"
    extra = _annotation(annotations)
    return (
        f"# {name}\n\n"
        f"{text}\n\n"
        f"{BLOCK.format(key=key, part='trend', extra=extra)}\n\n"
        f"{BLOCK.format(key=key, part='neighbourhood', extra='')}\n\n"
        "## Related coverage\n\n"
        f"{BLOCK.format(key=key, part='related', extra='')}\n"
    )


def preserved(existing: Mapping[str, Any] | None) -> dict[str, Any]:
    """The front matter an editor owns and sync never rewrites: ``pin``, ``annotations`` and ``superseded_by``."""
    return {name: existing[name] for name in PRESERVED_KEYS if existing and existing.get(name) is not None}


def entity_page(
    *,
    key: str,
    kind: str,
    name: str,
    aliases: Sequence[str],
    description: str | None,
    related: Sequence[str],
    beat: str | None,
    existing: Mapping[str, Any] | None = None,
) -> PageSpec:
    """The page of one accepted entity. ``existing`` is the front matter of the page as it stands, for what editors own."""
    kept = preserved(existing)
    front: dict[str, Any] = {"title": name, "entityKey": key, "kind": kind}
    if aliases:
        front["entityAliases"] = list(aliases)
    if beat:
        front["beat"] = beat
    if related:
        front["related"] = list(related)
    if clean_text(description):
        front["description"] = clean_text(description)
    front.update(kept)
    return PageSpec(KIND_ENTITY, key, slugify(key), front, entity_body(name, kind, aliases, description, key, kept.get("annotations")))


def topic_page(
    *,
    kind: str,
    key: str,
    slug: str,
    name: str,
    description: str | None,
    tags: Sequence[str],
    count: int,
    sections: Sequence[str] = (),
    parent: str | None = None,
    subtopics: Sequence[tuple[str, str, str]] = (),
    existing: Mapping[str, Any] | None = None,
) -> PageSpec:
    """A beat or subtopic page. ``subtopics`` is ``[(title, slug, path)]`` and is only given for a beat with enough items."""
    front: dict[str, Any] = {"title": name, "topicKey": key, "topicKind": kind}
    if parent:
        front["parentTopic"] = parent
    if clean_text(description):
        front["description"] = clean_text(description)
    front.update(preserved(existing))
    parts = [f"# {clean_text(name)}"]
    if clean_text(description):
        parts.append(clean_text(description))
    listed_in = f' sections="{",".join(sections)}"' if sections else ""
    parts.append(LISTING.format(sections=listed_in, tags=",".join(dict.fromkeys(tag.replace('"', "") for tag in tags if tag)), count=count))
    if subtopics:
        parts.append("## Subtopics\n\n" + "\n".join(f"- [{clean_text(title)}]({path})" for title, _slug, path in subtopics))
    return PageSpec(kind, key, slug, front, "\n\n".join(parts) + "\n")


def comparable(front_matter: Mapping[str, Any]) -> dict[str, Any]:
    """A front matter without what publishing writes (the stamp and its date), for telling whether a page changed."""
    return {name: value for name, value in front_matter.items() if name not in STAMP_KEYS}
