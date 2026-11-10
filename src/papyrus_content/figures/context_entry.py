"""The design system's section of the editorial context pack: a pointer, built from the catalog row alone (one index query, no download)."""
from __future__ import annotations

from papyrus_content.guidelines import GuidelineStore


def design_system_entry(client, store: GuidelineStore | None = None) -> dict | None:
    """``{text, row}`` when the site stores a design system, else None (like the visual style, a site without one simply has no entry)."""
    from .records import KIND

    row = (store or GuidelineStore(client)).current_row(KIND)
    if row is None:
        return None
    text = (
        f"This site has a design system for figures (diagrams, charts and illustrations): version {row.get('versionNumber')}, {row.get('contentHash')}. "
        "Its tokens, fonts, role mapping and worked examples are backend data. Read it with `papyrus design-system show`, and look at its worked examples before drawing "
        "(`papyrus design-system pull DIR`). `papyrus figures render FOLDER` draws with it by default and always writes a light and a dark picture; both are mandatory. "
        "Follow the figures skill and the rules in `papyrus figures rules`. Never invent a brand."
    )
    return {"text": text, "row": row}
