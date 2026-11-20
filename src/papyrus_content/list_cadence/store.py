"""Read and change the list settings document: the ``lists`` kind of the site store, with the guarantees of that store (body in S3, every version kept).

Only an admin who is a person changes it; an agent is blocked and an editor is not authorized. Every change carries a reason, which is the version's note. A change
checked against the version it started from: if another admin saved first nothing is written. Changing a list's time is one more version; it changes the schedule
entry at the next reconcile and the next send, and nothing already decided (``announce.py``).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

from papyrus_content.images.handlers import Caller
from papyrus_content.site_store import SiteSaveConflict, SiteStore

from .settings import ListSettingsError, fresh, validate_document, validate_list

KIND = "lists"


@dataclass(frozen=True)
class ListState:
    """A document and the version it is. Version 0 is a site that has never saved one: it has no lists."""
    version: int
    document: dict[str, Any]

    def get(self, list_id: str) -> dict[str, Any] | None:
        return self.document["lists"].get(list_id)


def may_change(caller: Caller) -> None:
    if caller.kind == "agent":
        raise ListSettingsError("blocked", "An agent may never change a list's settings, at any rung.")
    if not caller.is_admin:
        raise ListSettingsError("not_authorized", "Only an admin changes a list's settings.")


class ListSettingsStore:
    def __init__(self, site_store: SiteStore):
        self._store = site_store

    def read(self, tenant_id: str) -> ListState:
        version = self._store.current_version(tenant_id, KIND)
        if version == 0:
            return ListState(0, fresh())
        return ListState(version, validate_document(self._store.read_version(tenant_id, KIND, version)))

    def change(self, tenant_id: str, caller: Caller, reason: str, edit: Callable[[dict], None]) -> ListState:
        may_change(caller)
        if not isinstance(reason, str) or not reason.strip():
            raise ListSettingsError("invalid_input", "A change to a list needs a reason.")
        state = self.read(tenant_id)
        document = copy.deepcopy(state.document)
        edit(document)
        document = validate_document(document)
        if document == state.document:
            return state
        try:
            version = self._store.save(tenant_id, KIND, document, caller.subject, note=reason.strip(), expected_version=state.version)
        except SiteSaveConflict as error:
            raise ListSettingsError("stale_version", "The list settings changed while this change was being made; read them again.") from error
        return ListState(version, document)

    def set_list(self, tenant_id: str, caller: Caller, list_id: str, entry: dict[str, Any], *, reason: str) -> ListState:
        """Add a list, or replace one whole: a new list with a cadence and a time needs this and nothing else."""
        validate_list(list_id, entry)   # refused before anything is read or written

        def edit(document: dict) -> None:
            document["lists"][list_id] = entry

        return self.change(tenant_id, caller, reason, edit)

    def set_value(self, tenant_id: str, caller: Caller, list_id: str, field: str, value: Any, *, reason: str) -> ListState:
        """Change one field of a list (its time, its zone, its minimum rating). The whole list is checked again, so a change that breaks a rule is refused."""
        def edit(document: dict) -> None:
            if list_id not in document["lists"]:
                raise ListSettingsError("invalid_input", f"{list_id} is not a list of this site.")
            document["lists"][list_id][field] = value

        return self.change(tenant_id, caller, reason, edit)

    def remove_list(self, tenant_id: str, caller: Caller, list_id: str, *, reason: str) -> ListState:
        def edit(document: dict) -> None:
            if list_id not in document["lists"]:
                raise ListSettingsError("invalid_input", f"{list_id} is not a list of this site.")
            del document["lists"][list_id]

        return self.change(tenant_id, caller, reason, edit)
