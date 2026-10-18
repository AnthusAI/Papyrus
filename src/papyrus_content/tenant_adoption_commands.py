"""CLI entry for ``papyrus content adopt-tenant-data``."""

from __future__ import annotations

import json

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options
from .tenancy import TENANT_ID_ENVIRONMENT_VARIABLE, tenant_id_from_environment, validate_tenant_id
from .tenant_adoption import apply_tenant_adoption, plan_tenant_adoption


def adoption_tenant_from_options(options: dict) -> str:
    if tenant_id_from_environment():
        raise ValueError(
            f"content adopt-tenant-data reads every row, so {TENANT_ID_ENVIRONMENT_VARIABLE} must not be set; pass --tenant instead."
        )
    tenant_id = normalize_string(options.get("tenant"))
    if not tenant_id:
        raise ValueError("content adopt-tenant-data requires --tenant <id>.")
    return validate_tenant_id(tenant_id)


def content_adopt_tenant_data(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = bool(options.get("apply"))
    tenant_id = adoption_tenant_from_options(options)
    client, _claims = create_authoring_client(None)
    plan = plan_tenant_adoption(client, tenant_id)
    payload = plan.to_dict()
    payload["mode"] = "applied" if apply else "dry run"
    if apply:
        payload["written"] = apply_tenant_adoption(client, plan)
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"content adopt-tenant-data for {tenant_id} ({payload['mode']}): pending writes {payload['pendingWrites']}")
    for model_name, report in payload["models"].items():
        counts = report["counts"]
        print(
            f"  {model_name}: adopt {counts['adopt']}, re-id {counts['reid']}, "
            f"already adopted {counts['alreadyAdopted']}, other tenant (untouched) {counts['otherTenant']}, "
            f"conflicts (untouched) {counts['conflicts']}"
        )
        for label, ids in report["sample"].items():
            if ids:
                print(f"    {label}: {', '.join(ids)}")
    if apply:
        print(f"  written: {payload['written']}")
    else:
        print("  nothing was written; rerun with --apply to perform it.")
