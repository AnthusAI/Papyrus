"""Stamping ``tenantId`` on rows written without one (PPY-8f9462): ``papyrus content backfill-tenant-id``.

Every model in ``TENANT_FIELD_MODELS`` carries an optional ``tenantId``, and the sparse ``tenantId`` index of each (``list<Models>ByTenant``)
holds only the rows that carry it. Rows written before the Python client stamped every write (it did so only when a deploy flag was set, and
no deploy set it) have none, so ``list_tenant_rows`` cannot see them: ``agents apply`` finds an agent's automation "missing" and the Today page
lists none. This command writes the tenant on those rows, once.

* A dry run unless ``--apply``. It reads ``id`` and ``tenantId`` of every row of each model (one named sweep, paged, only those two fields)
  and writes nothing.
* It writes ``tenantId`` and nothing else, so a row's own ``updatedAt`` and every other field stay as they were. Running it again writes
  nothing, and its dry run is the health check.
* A row that already names this tenant is left; a row that names another tenant is never touched and is listed.
* It reaches the models the authoring client can list and update. The others (``unreachable_models``) are written by the backend's own
  functions and cannot be listed by this client; they are named in the report so the gap is never silent, and need their own backfill.
* ``--models Automation`` stamps one model alone: what ``agents apply`` needs first, in two writes, before the large tables.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import request_meter
from .graphql_authoring import LIST_DEFINITIONS, MUTATIONS
from .tenancy import TENANT_FIELD, TENANT_FIELD_MODELS, validate_tenant_id

SWEEP_NAME = "tenant-id-backfill"
SAMPLE_SIZE = 5


def reachable_models() -> list[str]:
    """The tenant-field models the authoring client can list and update, in a fixed order."""
    return sorted(model for model in TENANT_FIELD_MODELS if model in LIST_DEFINITIONS and model in MUTATIONS)


def unreachable_models() -> list[str]:
    return sorted(TENANT_FIELD_MODELS - set(reachable_models()))


@dataclass
class ModelBackfill:
    model_name: str
    stamp: list[str] = field(default_factory=list)
    already: int = 0
    other_tenant: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {"rows": len(self.stamp) + self.already + len(self.other_tenant), "stamp": len(self.stamp), "alreadyStamped": self.already,
                "otherTenant": len(self.other_tenant)}

    def to_dict(self) -> dict[str, Any]:
        return {"counts": self.counts(), "sample": {"stamp": self.stamp[:SAMPLE_SIZE], "otherTenant": self.other_tenant[:SAMPLE_SIZE]}}


@dataclass
class BackfillPlan:
    tenant_id: str
    models: list[ModelBackfill]

    @property
    def pending_writes(self) -> int:
        return sum(len(model.stamp) for model in self.models)

    def to_dict(self) -> dict[str, Any]:
        return {"tenant": self.tenant_id, "pendingWrites": self.pending_writes,
                "models": {model.model_name: model.to_dict() for model in self.models}, "notReached": unreachable_models()}


def plan_model(model_name: str, tenant_id: str, owners: list[dict[str, Any]]) -> ModelBackfill:
    plan = ModelBackfill(model_name)
    for row in sorted((row for row in owners if isinstance(row.get("id"), str)), key=lambda candidate: candidate["id"]):
        owner = row.get(TENANT_FIELD)
        if not owner:
            plan.stamp.append(row["id"])
        elif owner == tenant_id:
            plan.already += 1
        else:
            plan.other_tenant.append(row["id"])
    return plan


def plan_tenant_id_backfill(client, tenant_id: str, models: list[str] | None = None) -> BackfillPlan:
    validate_tenant_id(tenant_id)
    chosen = models or reachable_models()
    unknown = [model for model in chosen if model not in reachable_models()]
    if unknown:
        raise ValueError(f"{', '.join(unknown)} cannot be backfilled by this command. It covers: {', '.join(reachable_models())}.")
    with request_meter.sweep(SWEEP_NAME):
        return BackfillPlan(tenant_id, [plan_model(model, tenant_id, client.list_row_owners(model)) for model in chosen])


def apply_tenant_id_backfill(client, plan: BackfillPlan) -> dict[str, int]:
    """Write ``tenantId`` on each planned row. Each write names the row's id and the tenant only."""
    written: dict[str, int] = {}
    with request_meter.sweep(SWEEP_NAME):
        for model in plan.models:
            for row_id in model.stamp:
                client.update_record_unscoped(model.model_name, {"id": row_id, TENANT_FIELD: plan.tenant_id})
            if model.stamp:
                written[model.model_name] = len(model.stamp)
    return written
