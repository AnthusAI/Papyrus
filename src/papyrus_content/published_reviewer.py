"""The person who reviewed a published version, carried from the checklist to the published record and from there to the site.

At publish, the lineage being published (a Story's own, or a translation's ``<story>--<language>``) may have a human review stamp for the version being published
(``story_checklist.lineage_review_stamp``). When it does, the published record carries ``reviewedBy: {name, at}`` in its metadata, and the projection puts the same
value on the entry's data, so a site's hooks read ``entry.data.get("reviewedBy")``. A delegated review is the person's review: the stamp names the person the agent
acted for, never the agent. No stamp, or a stamp for an earlier version, carries nothing.

The name is public only when it is a person's name: a recorded label shaped like an email address, a UUID or a site subject (``public_text.PRIVATE_SHAPES``), or a
label a recorder writes when it was given no name, is withheld, and then nothing is carried. The engine exposes the data; the site decides the wording.

The key is the engine's: a ``reviewedBy`` an author writes in a CMS Story's front matter is dropped from the entry, so a page names only a review the checklist
records. A file-based site (``projection/directory_source.py``) is its own record, so its files' ``reviewedBy`` is carried as written.
"""
from __future__ import annotations

from typing import Any, Mapping

from .content_item_lifecycle import is_story_item_type
from .public_text import contains_private_shape

REVIEWED_BY_KEY = "reviewedBy"

#: The labels the recorders write for a person who gave no name: ``papyrus stories step`` without ``--actor-label``, and the console without a username.
#: They name a tool or a role, not the person, so they are never published as a reviewer.
LABELS_RECORDED_WITHOUT_A_NAME = frozenset({"papyrus-cli", "editor"})


def public_reviewer_name(recorded_name: Any) -> str | None:
    """The recorded name as it may appear on a public page, or None when it is not a person's public name."""
    name = str(recorded_name or "").strip()
    if not name or name.casefold() in LABELS_RECORDED_WITHOUT_A_NAME or contains_private_shape(name):
        return None
    return name


def reviewed_by_from_stamp(stamp: Mapping[str, Any] | None) -> dict[str, str] | None:
    """``{"name", "at"}`` from a human review stamp, or None when there is no stamp or its person has no public name."""
    if stamp is None:
        return None
    name = public_reviewer_name(stamp.get("by"))
    if name is None:
        return None
    return {"name": name, "at": str(stamp.get("at") or "")} if stamp.get("at") else {"name": name}


def reviewed_by_for_publish(client, item: Mapping[str, Any]) -> dict[str, str] | None:
    """The reviewer of the version being published: the stamp of the item's own lineage at the item's Story version, or None. Only Stories have a checklist."""
    from .story_checklist import lineage_review_stamp

    if not is_story_item_type(item.get("type")):
        return None
    lineage = item.get("lineageId") or item["id"]
    return reviewed_by_from_stamp(lineage_review_stamp(client, lineage, int(item.get("versionNumber") or 0)))


def front_matter_with_recorded_reviewer(front_matter: Mapping[str, Any], metadata: Mapping[str, Any]) -> dict[str, Any]:
    """The entry's data: the front matter without an authored ``reviewedBy``, plus the reviewer the published record carries, when it carries one."""
    data = {key: value for key, value in front_matter.items() if key != REVIEWED_BY_KEY}
    recorded = metadata.get(REVIEWED_BY_KEY)
    if isinstance(recorded, Mapping) and recorded.get("name"):
        data[REVIEWED_BY_KEY] = dict(recorded)
    return data
