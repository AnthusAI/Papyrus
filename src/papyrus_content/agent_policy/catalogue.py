"""The site store's catalogue over a site's GraphQL API, for writing (PPY-e6f31e).

``SiteStore`` takes a ``table`` with ``get``, ``create``, ``update_if`` and ``latest_version``. ``SiteCatalogue`` (``run_gate.py``) is the read
side the runner uses; this adds the writes a person's signed-in session makes, so ``papyrus agents set-rung`` saves through the same ``SiteStore``
the runner reads. Each write is one conditional mutation, so two admins saving at once cannot both succeed:

* ``create`` fails when the id exists (``KeyError``), so a version number is never reused;
* ``update_if`` moves ``SiteDocument.currentVersion`` only while it is still the version the save started from;
* ``latest_version`` is one query on the ``documentId`` index, highest version first, one row.
"""
from __future__ import annotations

import re
from typing import Any

from .run_gate import SITE_DOCUMENT_FIELDS, SITE_DOCUMENT_VERSION_FIELDS, SiteCatalogue

_CONDITION_FAILED = re.compile(r"conditional request failed|ConditionalCheckFailed", re.IGNORECASE)
_FIELDS = {"SiteDocument": SITE_DOCUMENT_FIELDS, "SiteDocumentVersion": SITE_DOCUMENT_VERSION_FIELDS}


def _failed_condition(error: Exception) -> bool:
    return bool(_CONDITION_FAILED.search(str(error)))


class SiteCatalogueTable(SiteCatalogue):
    def create(self, model: str, row: dict[str, Any]) -> None:
        mutation = (f"mutation Create{model}($input: Create{model}Input!, $condition: Model{model}ConditionInput) "
                    f"{{ create{model}(input: $input, condition: $condition) {{ id }} }}")
        try:
            self._client.graphql(mutation, {"input": row, "condition": {"id": {"attributeExists": False}}})
        except Exception as error:   # noqa: BLE001 - only a failed condition means the id exists; anything else is the caller's to see
            if _failed_condition(error):
                raise KeyError(row["id"]) from error
            raise

    def update_if(self, model: str, row_id: str, changes: dict[str, Any], expected: dict[str, Any]) -> bool:
        mutation = (f"mutation Update{model}If($input: Update{model}Input!, $condition: Model{model}ConditionInput) "
                    f"{{ update{model}(input: $input, condition: $condition) {{ id }} }}")
        condition = {name: {"eq": value} for name, value in expected.items()}
        try:
            self._client.graphql(mutation, {"input": {"id": row_id, **changes}, "condition": condition})
        except Exception as error:   # noqa: BLE001
            if _failed_condition(error):
                return False
            raise
        return True

    def latest_version(self, document_id: str) -> dict[str, Any] | None:
        query = ("query LatestSiteDocumentVersion($documentId: String!) { listSiteDocumentVersionsByDocument(documentId: $documentId, sortDirection: DESC, limit: 1) "
                 f"{{ items {{ {_FIELDS['SiteDocumentVersion']} }} }} }}")
        items = ((self._client.graphql(query, {"documentId": document_id}) or {}).get("listSiteDocumentVersionsByDocument") or {}).get("items") or []
        return items[0] if items else None
