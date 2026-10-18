"""Adopting rows written before tenant scoping into one tenant.

Rows of the tenant models that carry no ``tenantId`` are invisible to a tenant
client, and Section rows used to be stored under the bare Section key. This
module finds those rows, builds the minimal writes that make them the tenant's
own (stamp ``tenantId`` and the tenant-prefixed index fields, give Sections
their tenant-scoped id), and applies them through the authoring client. Record
ids of items and media and every ``storagePath`` are left exactly as they are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tenancy import (
    TENANT_KEY_SEPARATOR,
    TENANT_MODELS,
    tenant_scoped_record_id,
    tenant_stamped_payload,
    validate_tenant_id,
)

ADOPTION_MODEL_ORDER = ("NewsroomSection", "Item", "PublishedItem", "MediaAsset", "PublishedMediaAsset")
SAMPLE_SIZE = 5
STAMPED_FIELDS_BY_MODEL = {
    "Item": ("typeStatus", "sectionStatus", "slug"),
    "PublishedItem": ("typeStatus", "sectionStatus", "slug"),
    "MediaAsset": (),
    "PublishedMediaAsset": (),
}


@dataclass
class ModelAdoptionPlan:
    model_name: str
    adopt: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    reid: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    already_adopted: list[str] = field(default_factory=list)
    other_tenant: list[str] = field(default_factory=list)
    conflicts: list[tuple[str, str]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "adopt": len(self.adopt),
            "reid": len(self.reid),
            "alreadyAdopted": len(self.already_adopted),
            "otherTenant": len(self.other_tenant),
            "conflicts": len(self.conflicts),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts(),
            "sample": {
                "adopt": [row_id for row_id, _ in self.adopt[:SAMPLE_SIZE]],
                "reid": [f"{bare} -> {scoped}" for bare, scoped, _ in self.reid[:SAMPLE_SIZE]],
                "otherTenant": self.other_tenant[:SAMPLE_SIZE],
                "conflicts": [f"{row_id}: {reason}" for row_id, reason in self.conflicts[:SAMPLE_SIZE]],
            },
        }


@dataclass
class AdoptionPlan:
    tenant_id: str
    models: list[ModelAdoptionPlan]

    @property
    def pending_writes(self) -> int:
        return sum(len(model.adopt) + len(model.reid) for model in self.models)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant": self.tenant_id,
            "pendingWrites": self.pending_writes,
            "models": {model.model_name: model.to_dict() for model in self.models},
        }


def adoption_payload(model_name: str, tenant_id: str, row: dict[str, Any]) -> dict[str, Any]:
    carried = {"id": row["id"]}
    for field_name in STAMPED_FIELDS_BY_MODEL.get(model_name, ()):
        if isinstance(row.get(field_name), str):
            carried[field_name] = row[field_name]
    stamped = tenant_stamped_payload(model_name, tenant_id, carried)
    if model_name in STAMPED_FIELDS_BY_MODEL and "slug" in stamped:
        stamped.pop("slug")
    return stamped


def row_already_matches(row: dict[str, Any], payload: dict[str, Any]) -> bool:
    return all(row.get(name) == value for name, value in payload.items())


def scoped_section_row(tenant_id: str, row: dict[str, Any]) -> dict[str, Any]:
    scoped = {name: value for name, value in row.items() if value is not None}
    scoped["id"] = tenant_scoped_record_id("NewsroomSection", tenant_id, row["id"])
    scoped["tenantId"] = tenant_id
    return scoped


def plan_section_adoption(tenant_id: str, rows: list[dict[str, Any]]) -> ModelAdoptionPlan:
    plan = ModelAdoptionPlan("NewsroomSection")
    prefix = f"{tenant_id}{TENANT_KEY_SEPARATOR}"
    stored_ids = {row["id"] for row in rows}
    for row in sorted(rows, key=lambda candidate: candidate["id"]):
        row_id = row["id"]
        owner = row.get("tenantId")
        if owner and owner != tenant_id:
            plan.other_tenant.append(row_id)
        elif row_id.startswith(prefix) and owner == tenant_id:
            plan.already_adopted.append(row_id)
        elif row_id.startswith(prefix):
            plan.adopt.append((row_id, {"id": row_id, "tenantId": tenant_id}))
        elif TENANT_KEY_SEPARATOR in row_id:
            plan.conflicts.append((row_id, "the id contains a tenant separator but not this tenant's prefix"))
        elif tenant_scoped_record_id("NewsroomSection", tenant_id, row_id) in stored_ids:
            plan.conflicts.append((row_id, "a tenant-scoped row already exists next to this bare row; resolve by hand"))
        else:
            plan.reid.append((row_id, tenant_scoped_record_id("NewsroomSection", tenant_id, row_id), scoped_section_row(tenant_id, row)))
    return plan


def plan_record_adoption(model_name: str, tenant_id: str, rows: list[dict[str, Any]]) -> ModelAdoptionPlan:
    plan = ModelAdoptionPlan(model_name)
    for row in sorted(rows, key=lambda candidate: candidate["id"]):
        owner = row.get("tenantId")
        if owner and owner != tenant_id:
            plan.other_tenant.append(row["id"])
            continue
        payload = adoption_payload(model_name, tenant_id, row)
        if row_already_matches(row, payload):
            plan.already_adopted.append(row["id"])
        else:
            plan.adopt.append((row["id"], payload))
    return plan


def plan_tenant_adoption(client, tenant_id: str) -> AdoptionPlan:
    validate_tenant_id(tenant_id)
    models = []
    for model_name in ADOPTION_MODEL_ORDER:
        rows = [row for row in client.list_records(model_name) if isinstance(row.get("id"), str)]
        if model_name == "NewsroomSection":
            models.append(plan_section_adoption(tenant_id, rows))
        else:
            models.append(plan_record_adoption(model_name, tenant_id, rows))
    return AdoptionPlan(tenant_id, models)


def apply_tenant_adoption(client, plan: AdoptionPlan) -> dict[str, int]:
    written = {"adopted": 0, "reidentified": 0}
    for model in plan.models:
        for _row_id, payload in model.adopt:
            client.update_record_unscoped(model.model_name, payload)
            written["adopted"] += 1
        for bare_id, _scoped_id, scoped_row in model.reid:
            client.create_record(model.model_name, scoped_row)
            client.delete_record(model.model_name, bare_id)
            written["reidentified"] += 1
    return written


def adopt_legacy_item_family(client, tenant_id: str, item_id: str) -> int:
    """Stamp one legacy item, its media and its published projection as the tenant's."""
    from .publishing import published_item_id_for

    written = 0
    item = client.get_record_unscoped("Item", item_id)
    if item is None:
        return written
    related: list[tuple[str, dict[str, Any]]] = [("Item", item)]
    related += [("MediaAsset", row) for row in client.list_by_index("mediaAssetsByItemAndSortKey", item_id)]
    published_id = published_item_id_for(item.get("lineageId") or item_id)
    published = client.get_record_unscoped("PublishedItem", published_id)
    if published is not None:
        related.append(("PublishedItem", published))
        related += [
            ("PublishedMediaAsset", row)
            for row in client.list_by_index("publishedMediaAssetsByItemAndSortKey", published_id)
        ]
    for model_name, row in related:
        if model_name not in TENANT_MODELS or (row.get("tenantId") and row.get("tenantId") != tenant_id):
            continue
        payload = adoption_payload(model_name, tenant_id, row)
        if not row_already_matches(row, payload):
            client.update_record_unscoped(model_name, payload)
            written += 1
    return written
