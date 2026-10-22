"""CLI entries: ``papyrus knowledge publish-run | snapshot | entities list|accept|reject|rename|describe``."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..graphql_authoring import create_authoring_client
from ..ids import knowledge_corpus_id
from ..options import normalize_string, parse_options
from ..project_commands import _context_for
from ..projection.engine import project_all
from ..projection.writers import LocalDirectoryWriter, request_paths_for_key
from ..reader_steering.snapshot import encoded
from ..reader_steering.task import snapshot_key
from ..records import apply_record_changes, build_record_change_from_current
from .builder import CLUSTERS_FILE, ENTITY_DIRECTORY, INDEX_FILE, build_files
from .entity_review import (
    REVIEW_STATUSES,
    EntityReviewError,
    accept_patches,
    describe_patches,
    find_node,
    reject_patches,
    rename_patches,
)
from .loaders import (
    beats_from_categories,
    beats_from_config,
    category_names,
    clusters_of,
    current_nodes,
    entity_node,
    links_and_relations,
    load_records_file,
    published_items,
    relations_of_nodes,
)
from .model import UNACCEPTED_HIDE, UNACCEPTED_UNNAMED, KnowledgeData, SnapshotOptions
from .publish_run import STATUS_ACCEPTED, PublishPlan, is_item_mention, plan_publish_run
from .run_input import load_run_directory
from .weeks import current_monday, parse_day

ACTOR = "Papyrus content CLI"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _no_url(_summary) -> None:
    return None


def url_resolver(projector: Any):
    """The canonical request path of an item's page, as the site's projector places it."""
    policy = getattr(projector, "policy", None)

    def resolve(summary) -> str | None:
        keys = projector.item_page_paths(summary)
        if not keys:
            return None
        return policy.url_for_key(keys[0]) if policy is not None else request_paths_for_key(keys[0])[0]

    return resolve


def plan_changes(client: Any, plan: PublishPlan) -> list[dict]:
    changes: list[dict] = []
    for record in plan.records:
        model, expected = record["modelName"], record["expected"]
        current = client.get_record(model, expected["id"])
        if record.get("createOnly") and current is not None:
            changes.append({"modelName": model, "expected": current, "current": current, "action": "noop"})
        else:
            changes.append(build_record_change_from_current(model, expected, current))
    for patch in plan.patches:
        changes.append({"modelName": patch["modelName"], "expected": patch["expected"], "current": None, "action": "update"})
    return changes


def _print_plan(label: str, plan: PublishPlan, changes: list[dict], apply: bool, as_json: bool) -> None:
    actions = Counter((change["modelName"], change["action"]) for change in changes)
    if as_json:
        print(
            json.dumps(
                {
                    "mode": "apply" if apply else "dry-run",
                    "counts": plan.counts,
                    "changes": {f"{model}:{action}": count for (model, action), count in sorted(actions.items())},
                    "warnings": plan.warnings,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(f"knowledge\t{label}\tmode\t{'apply' if apply else 'dry-run'}")
    for name, count in sorted(plan.counts.items()):
        print(f"knowledge\t{label}\tplan\t{name}\t{count}")
    for (model, action), count in sorted(actions.items()):
        print(f"knowledge\t{label}\tchanges\t{model}\t{action}\t{count}")
    for warning in plan.warnings[:20]:
        print(f"knowledge\t{label}\twarning\t{warning}")
    if len(plan.warnings) > 20:
        print(f"knowledge\t{label}\twarning\t... and {len(plan.warnings) - 20} more")
    if not apply:
        print(f"knowledge\t{label}\tapply\tskipped\tpass --apply to write")


def knowledge_publish_run(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = options.get("apply") is True
    run_dir = normalize_string(options.get("run-dir"))
    run = load_run_directory(Path(run_dir)) if run_dir else None
    if run is None and options.get("skip-front-matter"):
        raise ValueError("Nothing to import: pass --run-dir DIR, or drop --skip-front-matter.")
    corpus_id = normalize_string(options.get("corpus-id")) or (
        knowledge_corpus_id({"key": options["corpus-key"]}) if normalize_string(options.get("corpus-key")) else None
    )
    client, _ = create_authoring_client()
    items = published_items(client.list_published_item_summaries(), _no_url)
    node_rows = current_nodes(client.list_records("SemanticNode"))
    accepted = [row for row in node_rows if row.get("status") == STATUS_ACCEPTED]
    mention_rows = [row for row in relations_of_nodes(client, accepted) if is_item_mention(row)]
    proposal_rows = client.list_records("SteeringProposal") if run is not None and run.clusters else []
    plan = plan_publish_run(
        items=items,
        node_rows=node_rows,
        mention_rows=mention_rows,
        proposal_rows=proposal_rows,
        run=run,
        corpus_id=corpus_id,
        category_set_id=normalize_string(options.get("category-set")),
        now=utc_now(),
        include_front_matter=not options.get("skip-front-matter"),
    )
    changes = plan_changes(client, plan)
    _print_plan("publish-run", plan, changes, apply, bool(options.get("json")))
    if apply:
        apply_record_changes(client, changes)
        if not options.get("json"):
            print(f"knowledge\tpublish-run\tapplied\t{sum(1 for change in changes if change['action'] != 'noop')}")


def _snapshot_options(options: dict[str, Any]) -> SnapshotOptions:
    unaccepted = normalize_string(options.get("unaccepted-clusters")) or UNACCEPTED_HIDE
    if unaccepted not in (UNACCEPTED_HIDE, UNACCEPTED_UNNAMED):
        raise ValueError("--unaccepted-clusters must be hide or unnamed.")
    as_of = parse_day(options["as-of"]) if normalize_string(options.get("as-of")) else current_monday(datetime.now(timezone.utc).date())
    return SnapshotOptions(
        as_of=as_of,
        entity_href_template=normalize_string(options.get("entity-href")),
        cluster_href_template=normalize_string(options.get("cluster-href")),
        unaccepted_clusters=unaccepted,
        maker_kind=normalize_string(options.get("maker-kind")) or "maker",
    )


def load_knowledge_data(client: Any, projector: Any, options: dict[str, Any]) -> KnowledgeData:
    items = published_items(client.list_published_item_summaries(), url_resolver(projector))
    node_rows = current_nodes(client.list_records("SemanticNode"))
    accepted = [row for row in node_rows if row.get("status") == STATUS_ACCEPTED]
    links, relations = links_and_relations(relations_of_nodes(client, accepted))
    proposals = [row for row in client.list_records("SteeringProposal") if row.get("proposalKind") == "topic_cluster"]
    category_rows = client.list_records("Category") if proposals or options.get("beats-category-set") else []
    clusters = clusters_of(proposals, category_names(category_rows), items)
    beats = []
    if options.get("beats-config") and options.get("beats-category-set"):
        raise ValueError("Pass one beat source: --beats-config or --beats-category-set.")
    if options.get("beats-config"):
        beats = beats_from_config(json.loads(Path(options["beats-config"]).read_text(encoding="utf-8")), items)
    elif options.get("beats-category-set"):
        beats = beats_from_categories(category_rows, options["beats-category-set"], clusters, items, normalize_string(options.get("beat-href")))
    return KnowledgeData(
        items=tuple(items),
        nodes=tuple(entity_node(row) for row in accepted),
        links=tuple(links),
        relations=tuple(relations),
        clusters=tuple(clusters),
        beats=tuple(beats),
    )


def write_files(context: Any, files: dict[str, dict], *, projector: Any = None) -> dict[str, list[str]]:
    """Put each file under the site's URL policy; leave a file whose bytes are unchanged; delete entity files that no
    longer have an entity; purge what changed."""
    written: list[str] = []
    unchanged: list[str] = []
    bodies = {snapshot_key(projector, site_key): encoded(payload) for site_key, payload in files.items()}
    for key in sorted(bodies):
        if context.writer.get(key) == bodies[key]:
            unchanged.append(key)
            continue
        context.writer.put(key, bodies[key])
        written.append(key)
    prefix = snapshot_key(projector, ENTITY_DIRECTORY + "/")
    deleted = [stored.key for stored in context.writer.list(prefix) if stored.key not in bodies]
    for key in deleted:
        context.writer.delete(key)
    purge_error = None
    purged: list[str] = []
    if getattr(context, "invalidate", None) is not None and (written or deleted):
        try:
            purged = context.invalidate(written + deleted)
        except Exception as error:  # noqa: BLE001
            purge_error = type(error).__name__
    return {"written": written, "unchanged": unchanged, "deleted": deleted, "purged": purged, "purgeError": [purge_error] if purge_error else []}


class _OfflineContext:
    def __init__(self, directory: str) -> None:
        self.writer = LocalDirectoryWriter(Path(directory))
        self.invalidate = None
        self.projector = None


def knowledge_snapshot(flags: list[str]) -> None:
    options = parse_options(flags)
    snapshot_options = _snapshot_options(options)
    records_file = normalize_string(options.get("records"))
    if records_file:
        if not options.get("out") or options.get("reproject") or options.get("site-bucket"):
            raise ValueError("--records builds offline: pass --out DIR, and not --site-bucket or --reproject.")
        context: Any = _OfflineContext(options["out"])
        data = load_records_file(records_file)
        client = None
    else:
        if not options.get("out") and not options.get("site-bucket"):
            raise ValueError("Pass --out DIR (a local directory) or --site-bucket NAME (the site store).")
        if options.get("out") and options.get("site-bucket"):
            raise ValueError("Pass --out or --site-bucket, not both.")
        client, _ = create_authoring_client()
        if options.get("site-bucket"):
            options["bucket"] = options["site-bucket"]
        context = _context_for(client, options)
        data = load_knowledge_data(client, context.projector, options)
    files = build_files(data, snapshot_options)
    outcome = write_files(context, files, projector=context.projector)
    entities = sum(1 for key in files if key.startswith(ENTITY_DIRECTORY + "/"))
    index = files[INDEX_FILE]
    result = {
        "asOf": snapshot_options.as_of.isoformat(),
        "entities": entities,
        "beats": len(index["beats"]),
        "clusters": len(files[CLUSTERS_FILE]["clusters"]),
        "trending": len(index["trending"]),
        "written": len(outcome["written"]),
        "unchanged": len(outcome["unchanged"]),
        "deleted": len(outcome["deleted"]),
        "purged": len(outcome["purged"]),
        "purgeError": outcome["purgeError"][0] if outcome["purgeError"] else None,
    }
    if options.get("json"):
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"knowledge\tsnapshot\tasOf {result['asOf']}\t{result['entities']} entities\t{result['beats']} beats\t"
            f"{result['clusters']} clusters\t{result['trending']} trending"
        )
        print(f"knowledge\tsnapshot\t{result['written']} written\t{result['unchanged']} unchanged\t{result['deleted']} deleted\t{result['purged']} purged")
        if result["purgeError"]:
            print(f"knowledge\tsnapshot\twarning\tedge purge failed: {result['purgeError']}")
    if options.get("reproject"):
        report = project_all(context)
        payload = report.to_dict()
        print(f"Projected: {payload['written']} written, {payload['deleted']} deleted, {payload['redirectsWritten']} redirects, {payload['invalidated']} invalidation paths")
        for error in report.errors:
            print(f"error: {error}")
        if not report.ok:
            raise SystemExit(1)


def _entity_row(row: dict) -> str:
    return "\t".join(
        [
            str(row.get("nodeKey") or ""),
            str(row.get("status") or ""),
            str(row.get("nodeKind") or ""),
            str(row.get("displayName") or ""),
            str(row.get("id") or ""),
        ]
    )


def knowledge_entities_list(flags: list[str]) -> None:
    options = parse_options(flags)
    status = normalize_string(options.get("status")) or "generated"
    if status != "all" and status not in REVIEW_STATUSES:
        raise ValueError("--status must be accepted, generated, rejected or all.")
    kind = normalize_string(options.get("kind"))
    query = (normalize_string(options.get("query")) or "").casefold()
    import_run = normalize_string(options.get("import-run"))
    limit = int(options.get("limit") or 100)
    client, _ = create_authoring_client()
    rows = [
        row
        for row in current_nodes(client.list_records("SemanticNode"))
        if (status == "all" or row.get("status") == status)
        and (not kind or row.get("nodeKind") == kind)
        and (not import_run or row.get("importRunId") == import_run)
        and (not query or query in str(row.get("displayName") or "").casefold())
    ]
    rows.sort(key=lambda row: (str(row.get("nodeKind")), str(row.get("displayName") or "").casefold(), row["id"]))
    shown = rows[:limit]
    if options.get("counts"):
        for row in shown:
            links, _ = links_and_relations(relations_of_nodes(client, [row]))
            confirmed = sum(1 for link in links if link.confirmed and link.node_lineage_id == row.get("lineageId"))
            unconfirmed = sum(1 for link in links if not link.confirmed and link.node_lineage_id == row.get("lineageId"))
            print(_entity_row(row) + f"\t{confirmed} confirmed\t{unconfirmed} unconfirmed")
    else:
        for row in shown:
            print(_entity_row(row))
    print(f"knowledge\tentities\tlist\t{len(shown)} of {len(rows)}")


def _review(flags: list[str], name: str, build) -> None:
    options = parse_options(flags)
    identifier = normalize_string(options.get("key"))
    if not identifier:
        raise ValueError(f"knowledge entities {name} requires --key <node key, id or lineage id>.")
    client, _ = create_authoring_client()
    rows = client.list_records("SemanticNode")
    try:
        node = find_node(rows, identifier)
        patches = build(options, node, client, rows)
    except EntityReviewError as error:
        raise ValueError(str(error)) from error
    dry_run = options.get("dry-run") is True
    print(f"knowledge\tentities\t{name}\t{node['nodeKey']}\t{node.get('status')}\t{'dry-run' if dry_run else 'apply'}")
    for patch in patches:
        print(f"knowledge\tentities\t{name}\tupdate\t{patch['modelName']}\t{patch['expected']['id']}")
    if not patches:
        print(f"knowledge\tentities\t{name}\tnothing to change")
    if not dry_run:
        apply_record_changes(client, [{"modelName": patch["modelName"], "expected": patch["expected"], "current": None, "action": "update"} for patch in patches])


def knowledge_entities_accept(flags: list[str]) -> None:
    def build(options, node, client, _rows):
        mentions = [row for row in relations_of_nodes(client, [node]) if is_item_mention(row)]
        return accept_patches(node, mentions, actor=normalize_string(options.get("actor")) or ACTOR, now=utc_now(), confirm_links=not options.get("keep-links-unconfirmed"))

    _review(flags, "accept", build)


def knowledge_entities_reject(flags: list[str]) -> None:
    _review(flags, "reject", lambda options, node, client, rows: reject_patches(node, now=utc_now()))


def knowledge_entities_rename(flags: list[str]) -> None:
    def build(options, node, client, rows):
        name = normalize_string(options.get("name"))
        if not name:
            raise EntityReviewError("knowledge entities rename requires --name <new name>.")
        return rename_patches(node, name, rows, now=utc_now())

    _review(flags, "rename", build)


def knowledge_entities_describe(flags: list[str]) -> None:
    def build(options, node, client, rows):
        text = normalize_string(options.get("text"))
        if not text:
            raise EntityReviewError("knowledge entities describe requires --text <description>.")
        return describe_patches(
            node, text, reviewed=bool(options.get("reviewed")), today=datetime.now(timezone.utc).date().isoformat(), now=utc_now()
        )

    _review(flags, "describe", build)


KNOWLEDGE_COMMANDS = {
    "publish-run": knowledge_publish_run,
    "snapshot": knowledge_snapshot,
    "entities-list": knowledge_entities_list,
    "entities-accept": knowledge_entities_accept,
    "entities-reject": knowledge_entities_reject,
    "entities-rename": knowledge_entities_rename,
    "entities-describe": knowledge_entities_describe,
}
