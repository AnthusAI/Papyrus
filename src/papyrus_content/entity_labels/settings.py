"""The site's languages as the editorial check settings store them. Nothing is imported: what only records a need loads no model or procedure code."""
from __future__ import annotations

import json
from typing import Any


def site_primary_language(client: Any) -> str:
    """The site's primary language, as the editorial check settings store it (``languages.primary``). Read straight from the row: the settings are validated
    when they are saved, and checking the tag against Humanus's language packs here would put Humanus in the consumer's bundle for nothing."""
    row = client.get_record("EditorialCheckSettings", "settings")
    values = json.loads(row["settings"]) if row and isinstance(row.get("settings"), str) else (row or {}).get("settings") or {}
    primary = (values.get("languages") or {}).get("primary")
    if not primary:
        raise ValueError("The editorial check settings name no primary language yet, so a concept's language cannot be set.")
    return str(primary)
