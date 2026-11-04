"""`papyrus stories repair-image-paths`: move a story's pictures to the one key the renditions look under.

Before the rule in ``renditions.media_key_for_source`` (a picture's object is ``media/<srcPath>``, for every tenant),
``stories save-version --images`` on a tenant site stored pictures at ``media/<tenant>/<srcPath>``. The story's body and
``MediaAsset`` rows said ``assets/<slug>/<file>`` but the renditions function made renditions under the tenant's key, so
a publish could not find them. This command repairs such a story without uploading anything again: it copies each object
inside the bucket to ``media/<srcPath>`` (the bucket then announces a new object and the renditions function makes the
renditions), and points the story's ``MediaAsset`` rows at the new key. The old objects are left where they are.

A dry run is the default; nothing is written without ``--write``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .renditions import media_key_for_source


@dataclass
class ImageRepairPlan:
    copies: dict[str, str] = field(default_factory=dict)  # old key -> canonical key, one per distinct object
    row_updates: list[tuple[str, str, str]] = field(default_factory=list)  # (MediaAsset id, old key, canonical key)
    already_canonical: int = 0
    unrepairable: list[str] = field(default_factory=list)  # rows without a srcPath, with the reason

    @property
    def needed(self) -> bool:
        return bool(self.row_updates)


def _src_path(row: dict[str, Any]) -> str | None:
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return None
    value = metadata.get("srcPath") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) and value else None


def plan_image_path_repair(rows: list[dict[str, Any]]) -> ImageRepairPlan:
    """The copies and row updates that bring every picture row of a story to ``media/<srcPath>``. Pure."""
    plan = ImageRepairPlan()
    for row in rows:
        if row.get("type") != "image":
            continue
        stored = row.get("storagePath")
        src = _src_path(row)
        if not stored or not src:
            plan.unrepairable.append(f"{row.get('id')}: has no storagePath or srcPath")
            continue
        wanted = media_key_for_source(src)
        if stored == wanted:
            plan.already_canonical += 1
            continue
        plan.copies.setdefault(stored, wanted)
        plan.row_updates.append((row["id"], stored, wanted))
    return plan


def story_media_rows(client, lineage_id: str) -> list[dict[str, Any]]:
    from .story_reporting import story_versions

    return [
        row for version in story_versions(client, lineage_id)
        for row in client.list_by_index("mediaAssetsByItemAndSortKey", version["id"])
    ]


def apply_image_path_repair(client, store, plan: ImageRepairPlan) -> list[tuple[str, str, str]]:
    """Copies, then re-points the rows. ``(kind, subject, outcome)`` for every step, in order.

    An object whose source is missing is reported and its rows are left alone, so nothing ever points at a key with no object.
    """
    results: list[tuple[str, str, str]] = []
    copied: set[str] = set()
    for old, new in sorted(plan.copies.items()):
        if store.exists(new):
            results.append(("object", new, "already-there"))
            copied.add(old)
        elif not store.exists(old):
            results.append(("object", old, "source-missing"))
        else:
            store.copy(old, new)
            results.append(("object", new, "copied"))
            copied.add(old)
    for row_id, old, wanted in plan.row_updates:
        if old not in copied:
            results.append(("row", row_id, "left-alone"))
            continue
        client.update_record("MediaAsset", {"id": row_id, "storagePath": wanted})
        results.append(("row", row_id, "updated"))
    return results


def plan_lines(lineage_id: str, plan: ImageRepairPlan) -> list[str]:
    lines = [f"stories\trepair-image-paths\t{lineage_id}\tobject\t{old}\t->\t{new}" for old, new in sorted(plan.copies.items())]
    lines += [f"stories\trepair-image-paths\t{lineage_id}\trow\t{row_id}\t->\t{wanted}" for row_id, _old, wanted in plan.row_updates]
    lines += [f"stories\trepair-image-paths\t{lineage_id}\tskipped\t{reason}" for reason in plan.unrepairable]
    return lines
