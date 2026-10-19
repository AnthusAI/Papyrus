from __future__ import annotations

import json

from .edition_planning import (
    apply_edition_planning_plan,
    build_edition_planning_command_plan,
    load_edition_planning_state,
    print_edition_planning_summary,
    verify_edition_planning_plan,
    write_edition_planning_report,
)
from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .papyrus_config import require_editions_enabled
from .options import normalize_string, parse_options, resolve_mutation_apply


def editions_plan(flags: list[str]) -> None:
    require_editions_enabled("editions plan")
    options = parse_options(flags)
    client, _ = create_authoring_client()
    plan, report = build_edition_planning_command_plan(client, options)
    print_edition_planning_summary(plan, report, "dry-run")


def editions_dispatch_research(flags: list[str]) -> None:
    _dispatch_edition_planning(flags, reporting=False)


def editions_dispatch_reporting(flags: list[str]) -> None:
    options = parse_options(flags)
    options["assignment-type"] = "reporting"
    _dispatch_edition_planning_from_options(options, reporting=True)


def editions_purge(flags: list[str]) -> None:
    options = parse_options(flags)
    mode = normalize_string(options.get("mode"))
    if mode not in {"edition-only", "edition-and-items"}:
        raise ValueError("editions purge requires --mode edition-only|edition-and-items.")
    purge_all = bool(options.get("all"))
    edition_selector = normalize_string(options.get("edition"))
    if purge_all and edition_selector:
        raise ValueError("editions purge accepts either --all or --edition, not both.")
    if not purge_all and not edition_selector:
        raise ValueError("editions purge requires --edition <id|slug|date> or --all.")
    apply = resolve_mutation_apply(options, "editions purge")
    client, _ = create_authoring_client()
    plan = build_edition_purge_plan(client, mode=mode, purge_all=purge_all, edition_selector=edition_selector)
    if not apply:
        targeted = sorted(plan.get("targetEditionLineageIds") or [])
        counts = {model: len(plan.get("ids", {}).get(model) or []) for model in ("Edition", "EditionItem", "PublishedEdition", "PublishedEditionItem")}
        print(f"editions-purge\tmode\t{mode}")
        print(f"editions-purge\tselector\t{'all' if purge_all else edition_selector}")
        print(f"editions-purge\ttargeted-lineages\t{len(targeted)}")
        for model_name, count in counts.items():
            if count:
                print(f"editions-purge\twould-delete\t{model_name}\t{count}")
        print("editions-purge\tapply\tskipped\tuse without --dry-run to delete")
        return
    result = apply_edition_purge_plan(client, plan)
    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "editions purge",
                    "mode": mode,
                    "selector": "all" if purge_all else edition_selector,
                    "targetedEditionLineages": sorted(plan.get("targetEditionLineageIds") or []),
                    "deleted": result["deleted"],
                    "skipped": result["skipped"],
                },
                indent=2,
            )
        )
        return
    print(f"editions-purge\tmode\t{mode}")
    print(f"editions-purge\tselector\t{'all' if purge_all else edition_selector}")
    print(f"editions-purge\ttargeted-lineages\t{len(plan.get('targetEditionLineageIds') or [])}")
    for model_name, deleted in result["deleted"].items():
        print(f"editions-purge\tdeleted\t{model_name}\t{deleted}")
    for model_name, reason in result["skipped"].items():
        print(f"editions-purge\tskipped\t{model_name}\t{reason}")


def _dispatch_edition_planning(flags: list[str], *, reporting: bool) -> None:
    options = parse_options(flags)
    if reporting:
        options["assignment-type"] = "reporting"
    _dispatch_edition_planning_from_options(options, reporting=reporting)


def _dispatch_edition_planning_from_options(options: dict, *, reporting: bool) -> None:
    require_editions_enabled("editions dispatch-reporting" if reporting else "editions dispatch-research")
    apply = resolve_mutation_apply(
        options,
        "editions dispatch-reporting" if reporting else "editions dispatch-research",
    )
    client, _ = create_authoring_client()
    plan, report = build_edition_planning_command_plan(client, options)
    if not apply:
        print_edition_planning_summary(plan, report, "dry-run")
        label = "reporting" if reporting else "research"
        print(f"edition-planning\tapply\tskipped\tuse --dry-run to preview {label} Assignment and SemanticRelation writes")
        return
    apply_result = apply_edition_planning_plan(client, plan)
    refreshed = load_edition_planning_state(client)
    verification = verify_edition_planning_plan(refreshed, plan)
    apply_report = write_edition_planning_report(
        plan,
        {"mode": "apply", "plan": plan, "applyResult": apply_result, "verification": verification},
        output_dir=report.get("outputDir"),
        filename="dispatch-report.json" if not reporting else "dispatch-reporting-report.json",
    )
    print_edition_planning_summary(plan, apply_report, "apply")
    print(f"edition-planning\tapplied\t{apply_result['applied']}")
    print(f"edition-planning\tverification\t{'ok' if verification.get('ok') else 'failed'}")
    if verification.get("failures"):
        for failure in verification["failures"]:
            print(f"failure\t{failure}")
        raise RuntimeError("Edition planning verification failed.")


def build_edition_purge_plan(
    client: PapyrusGraphQLAuthoringClient,
    *,
    mode: str,
    purge_all: bool,
    edition_selector: str | None,
) -> dict:
    editions = client.safe_list_records("Edition")
    published_editions = client.safe_list_records("PublishedEdition")
    edition_items = client.safe_list_records("EditionItem")
    published_edition_items = client.safe_list_records("PublishedEditionItem")
    target_lineages = _resolve_edition_purge_lineages(
        editions=editions,
        published_editions=published_editions,
        purge_all=purge_all,
        edition_selector=edition_selector,
    )
    if not target_lineages:
        return {"mode": mode, "targetEditionLineageIds": set(), "ids": {}}
    target_edition_ids = {
        row["id"]
        for row in editions
        if (row.get("lineageId") or row.get("id")) in target_lineages
    }
    target_published_edition_ids = {
        row["id"]
        for row in published_editions
        if (row.get("editionLineageId") or row.get("sourceEditionId")) in target_lineages
        or row.get("sourceEditionId") in target_edition_ids
    }
    target_edition_item_ids = {
        row["id"]
        for row in edition_items
        if row.get("editionId") in target_edition_ids or row.get("editionLineageId") in target_lineages
    }
    target_published_edition_item_ids = {
        row["id"]
        for row in published_edition_items
        if row.get("publishedEditionId") in target_published_edition_ids
        or row.get("editionLineageId") in target_lineages
        or row.get("sourceEditionId") in target_edition_ids
    }
    ids = {
        "Edition": target_edition_ids,
        "PublishedEdition": target_published_edition_ids,
        "EditionItem": target_edition_item_ids,
        "PublishedEditionItem": target_published_edition_item_ids,
        "Item": set(),
        "PublishedItem": set(),
        "MediaAsset": set(),
        "PublishedMediaAsset": set(),
        "ItemTag": set(),
        "Tag": set(),
    }
    if mode == "edition-only":
        return {"mode": mode, "targetEditionLineageIds": target_lineages, "ids": ids}
    item_lineages = {
        row.get("itemLineageId") or row.get("itemId")
        for row in edition_items
        if row.get("id") in target_edition_item_ids
    } | {
        row.get("itemLineageId") or row.get("sourceItemId")
        for row in published_edition_items
        if row.get("id") in target_published_edition_item_ids
    }
    item_lineages = {lineage for lineage in item_lineages if lineage}
    items = client.safe_list_records("Item")
    published_items = client.safe_list_records("PublishedItem")
    ids["Item"] = {
        row["id"]
        for row in items
        if (row.get("lineageId") or row.get("id")) in item_lineages
    }
    ids["PublishedItem"] = {
        row["id"]
        for row in published_items
        if (row.get("itemLineageId") or row.get("sourceItemId")) in item_lineages
    }
    return {"mode": mode, "targetEditionLineageIds": target_lineages, "ids": ids}


def apply_edition_purge_plan(client: PapyrusGraphQLAuthoringClient, plan: dict) -> dict:
    deleted: dict[str, int] = {}
    skipped: dict[str, str] = {}
    if not plan.get("targetEditionLineageIds"):
        return {"deleted": deleted, "skipped": skipped}
    delete_order = (
        ["PublishedEditionItem", "EditionItem", "PublishedEdition", "Edition"]
        if plan.get("mode") == "edition-only"
        else ["PublishedEditionItem", "EditionItem", "PublishedItem", "Item", "PublishedEdition", "Edition"]
    )
    for model_name in delete_order:
        ids = sorted(plan.get("ids", {}).get(model_name) or [])
        if not ids:
            deleted[model_name] = 0
            continue
        try:
            count = 0
            for record_id in ids:
                client.delete_record(model_name, record_id)
                count += 1
            deleted[model_name] = count
        except RuntimeError as error:
            skipped[model_name] = str(error)
            deleted[model_name] = 0
    return {"deleted": deleted, "skipped": skipped}


def _resolve_edition_purge_lineages(
    *,
    editions: list[dict],
    published_editions: list[dict],
    purge_all: bool,
    edition_selector: str | None,
) -> set[str]:
    if purge_all:
        return {
            lineage
            for row in [*editions, *published_editions]
            for lineage in (row.get("lineageId"), row.get("editionLineageId"), row.get("id"))
            if lineage
        }
    selector = normalize_string(edition_selector)
    if not selector:
        return set()
    matches = [
        row.get("lineageId") or row.get("editionLineageId") or row.get("id")
        for row in [*editions, *published_editions]
        if selector
        in {
            normalize_string(row.get("id")),
            normalize_string(row.get("slug")),
            normalize_string(row.get("editionDate")),
            normalize_string(row.get("lineageId")),
            normalize_string(row.get("editionLineageId")),
            normalize_string(row.get("sourceEditionId")),
        }
    ]
    return {lineage for lineage in matches if lineage}
