"""CLI entry for ``papyrus content backfill-tenant-id`` (see ``tenant_field_backfill``)."""

from __future__ import annotations

import json

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options
from .tenancy import TENANT_ID_ENVIRONMENT_VARIABLE, tenant_id_from_environment, validate_tenant_id
from .tenant_field_backfill import apply_tenant_id_backfill, plan_tenant_id_backfill


def backfill_tenant_from_options(options: dict) -> str:
    if tenant_id_from_environment():
        raise ValueError(
            f"content backfill-tenant-id reads every row, so {TENANT_ID_ENVIRONMENT_VARIABLE} must not be set; pass --tenant instead."
        )
    tenant_id = normalize_string(options.get("tenant"))
    if not tenant_id:
        raise ValueError("content backfill-tenant-id requires --tenant <id>.")
    return validate_tenant_id(tenant_id)


def content_backfill_tenant_id(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = bool(options.get("apply"))
    tenant_id = backfill_tenant_from_options(options)
    models = [name for name in (normalize_string(options.get("models")) or "").split(",") if name] or None
    client, _claims = create_authoring_client(None, site_tenant=False)
    plan = plan_tenant_id_backfill(client, tenant_id, models)
    payload = plan.to_dict()
    payload["mode"] = "applied" if apply else "dry run"
    if apply:
        payload["written"] = apply_tenant_id_backfill(client, plan)
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"content backfill-tenant-id for {tenant_id} ({payload['mode']}): pending writes {payload['pendingWrites']}")
    for model_name, report in payload["models"].items():
        counts = report["counts"]
        print(f"  {model_name}: rows {counts['rows']}, stamp {counts['stamp']}, already stamped {counts['alreadyStamped']}, "
              f"other tenant (untouched) {counts['otherTenant']}")
        for label, ids in report["sample"].items():
            if ids:
                print(f"    {label}: {', '.join(ids)}")
    print(f"  not reached by this command (the authoring client cannot list them; the backend's own functions write them): {', '.join(payload['notReached'])}")
    if apply:
        print(f"  written: {payload['written']}")
    else:
        print("  nothing was written; rerun with --apply to perform it.")
