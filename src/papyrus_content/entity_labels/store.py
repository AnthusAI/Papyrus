"""EntityLabel rows through the site's data API. Every read is a query on a named index; nothing here lists the table."""
from __future__ import annotations

from typing import Any

from .keys import WORK_STATES, name_key, work_key

MODEL = "EntityLabel"


class LabelStore:
    def __init__(self, client: Any):
        self.client = client
        self.tenant_id = getattr(client, "tenant_id", None)

    def of_entity(self, entity_key: str, language: str | None = None) -> list[dict[str, Any]]:
        """Every name of one thing (a handful of rows), or only one language's."""
        rows = self.client.list_by_index("entityLabelsByEntity", entity_key)
        return [row for row in rows if language is None or row.get("language") == language]

    def named(self, language: str, text: str, kind: str = "concept") -> list[dict[str, Any]]:
        """The labels that have this name (case, width and white space folded) in this language, of any role."""
        return self.client.list_by_index("entityLabelsByName", name_key(language, text, self.tenant_id, kind))

    def needing_work(self, language: str, state: str, kind: str = "concept") -> list[dict[str, Any]]:
        if state not in WORK_STATES:
            raise ValueError(f"Labels needing work are {', '.join(WORK_STATES)}; not {state}.")
        return self.client.list_by_index("entityLabelsByWork", work_key(language, state, self.tenant_id, kind))

    def create(self, row: dict[str, Any]) -> None:
        self.client.create_record(MODEL, _present(row))

    def update(self, row: dict[str, Any], *, removing: tuple[str, ...] = ()) -> None:
        """A partial update. The fields named in ``removing`` are cleared (a label that no longer needs work has no ``workKey``)."""
        self.client.update_record(MODEL, {**_present(row), **{name: None for name in removing}})

    def delete(self, label_id: str) -> None:
        self.client.delete_record(MODEL, label_id)


def _present(row: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in row.items() if value is not None}
