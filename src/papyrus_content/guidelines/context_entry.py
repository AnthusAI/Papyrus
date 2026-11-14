"""The writing and image guidelines' section of the editorial context: pointers built from the catalog rows alone (one index query for each, no download).

Like the design system's entry, the text says that the guidelines exist, their version and hash, and the command that reads them resolved for the section.
The entry's source is the version's own row, so a draft is traced to the exact guidelines it was written under. The agent context pack carries the guidelines in full.
"""
from __future__ import annotations

from .store import GuidelineStore

#: (kind, the entry's name in the editorial context, what the guidelines are called in the pointer)
ENTRIES = (("writing", "writing-guidelines", "writing guidelines"), ("image", "visual-style", "image style guidelines"))
#: Image guidelines are resolved for a use and a Story by the image resolver, not by the guidelines door.
IMAGE_COMMAND = "papyrus images profile resolve"


def pointer_text(label: str, scope: str, kind: str, row: dict, section: str | None) -> str:
    where = f"The {scope}'s {label}" if scope == "publication" else f"This section's {label} (laid over the publication's)"
    flag = f" --section {section}" if section else ""
    command = IMAGE_COMMAND if kind == "image" else f"papyrus guidelines resolve --kind {kind}{flag}"
    return (f"{where} are stored as versioned data: version {row.get('versionNumber')}, {row.get('contentHash')}. "
            f"Read them resolved for this scope with `{command}`; an agent's context pack carries them in full.")


def guideline_entries(client, section: str | None, *, skip_publication: tuple[str, ...] = (), store: GuidelineStore | None = None) -> list[dict]:
    """``[{scope, kind, text, row}]`` for the publication's guidelines of each kind and, when ``section`` is given, the section's own. A scope with no document has no entry."""
    guidelines = store or GuidelineStore(client)
    found: list[dict] = []
    for kind, name, label in ENTRIES:
        for scope, key in (("publication", None), ("section", section)):
            if scope == "section" and not key:
                continue
            if scope == "publication" and name in skip_publication:
                continue
            row = guidelines.current_row(kind, key)
            if row is not None:
                found.append({"scope": scope, "kind": name, "text": pointer_text(label, scope, kind, row, key), "row": row})
    return found
