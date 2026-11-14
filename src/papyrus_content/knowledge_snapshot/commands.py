"""CLI entries: ``papyrus knowledge publish-run | snapshot | archive | entities ... | clusters ... | relations ...``.

Every command that reads or writes the CMS takes ``--auth user|iam`` and ``--amplify-outputs FILE`` (or the
``PAPYRUS_GRAPHQL_AUTH`` and ``PAPYRUS_GRAPHQL_ENDPOINT`` variables), says on stderr which lane and endpoint it uses,
and never switches lanes by itself.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import json
import os
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from ..knowledge_wiki.kinds import public_kinds_of
from ..env import graphql_endpoint
from ..graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from ..ids import knowledge_corpus_id
from ..options import normalize_string, parse_options
from ..project_commands import _context_for, _projection_environment
from ..projection.engine import project_all
from ..projection.runtime import load_projector
from ..projection.writers import LocalDirectoryWriter, request_paths_for_key
from ..reader_steering.snapshot import encoded
from ..reader_steering.task import snapshot_key
from ..categories_steering import semantic_state_key
from ..records import apply_record_changes, build_record_change_from_current
from .actors import Actor, actor_from_options, clean_name
from .archive import HISTORY_DIRECTORY, ArchiveError, archive_entry, build_entry
from .builder import CLUSTERS_FILE, CLUSTERS_HISTORY_FILE, ENTITY_DIRECTORY, INDEX_FILE, SCHEMA_VERSION, build_files
from .cluster_history import valid_weeks, weeks_from_archive
from .cluster_review import (
    ClusterReviewError,
    accept_cluster_patches,
    find_cluster,
    name_cluster_patches,
    reject_cluster_patches,
)
from .cluster_records import CLUSTER_KIND, decode_metadata
from .entity_review import (
    REVIEW_STATUSES,
    EntityReviewError,
    accept_description_patches,
    accept_patches,
    alias_patches,
    describe_patches,
    find_node,
    page_decision_patches,
    reject_patches,
    rename_patches,
)
from .entity_add import DISAMBIGUATION_LINEAGE, DISAMBIGUATION_NAME, add_plan, disambiguation_plan
from .entity_duplicates import find_duplicate_pairs
from .entity_merge import merge_plan
from .entity_retype import retype_plan
from .keys import kind_key
from .page_answer import page_label, page_order_key
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
from .monitor_import import is_record_mention, is_record_relation
from .monitor_ledger import MonitorLedger
from .monitor_records import (
    biblicus_record_id,
    load_monitor_records,
    parse_sources,
    read_records,
    record_as_item,
    write_records,
)
from .parallel import DEFAULT_WORKERS, map_with_clients, worker_count
from .publish_run import STATUS_ACCEPTED, PublishPlan, is_extractor_mention, plan_publish_run
from .entity_extraction import ExtractionError, JevClient, RegistryMatcher, build_output, criteria_of, decide, describe_publication, find_candidates
from .registry import build_registry, read_vocabulary_kinds
from .topic_config import english_stop_words, read_extra_stop_words, render, topic_modeling_configuration
from .relation_review import (
    RELATION_STATES,
    RelationReviewError,
    accept_relation_patches,
    find_relation,
    is_node_relation,
    reject_relation_patches,
    review_state,
)
from .corpus_export import DEFAULT_TYPES, biblicus_item_id, export_items, render_record, write_export
from .candidate_filter import CandidateFilter, load_stop_words, rejected_keys, vocabulary_kinds
from .reference_documents import (
    S3TextStore,
    load_accepted_reference_documents,
    biblicus_reference_id,
    export_reference_documents,
    load_reference_documents,
    read_documents_file,
    write_documents_file,
)
from .run_input import load_run, translate_item_ids
from .weeks import current_monday, parse_day

AUTH_LANES = ("user", "iam")
PAGE_CHOICES = {"yes": True, "no": False, "machine": None}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def endpoint_of_outputs(path: str) -> str:
    try:
        outputs = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read --amplify-outputs {path}: {error}") from error
    endpoint = (outputs.get("data") or {}).get("url") or outputs.get("aws_appsync_graphqlEndpoint")
    if not endpoint:
        raise ValueError(f"{path} holds no GraphQL endpoint (data.url).")
    return str(endpoint)


def select_backend(options: dict[str, Any]) -> None:
    """Apply ``--auth`` and ``--amplify-outputs`` to this process, the way an operator selects a lane on purpose."""
    lane = normalize_string(options.get("auth"))
    if lane:
        if lane not in AUTH_LANES:
            raise ValueError("--auth must be user or iam.")
        os.environ["PAPYRUS_GRAPHQL_AUTH"] = lane
    outputs = normalize_string(options.get("amplify-outputs"))
    if outputs:
        os.environ["PAPYRUS_GRAPHQL_ENDPOINT"] = endpoint_of_outputs(outputs)


def announce_backend() -> None:
    """One line on stderr: the lane and the AppSync host a command is about to use."""
    from ..user_auth_mode import user_auth_requested

    try:
        host = urlparse(graphql_endpoint()).netloc
    except ValueError:
        host = "unknown"
    print(f"knowledge\tauth\t{'user' if user_auth_requested() else 'iam'}\t{host}", file=sys.stderr)


def authoring_client(options: dict[str, Any]) -> Any:
    select_backend(options)
    client, _ = create_authoring_client()
    announce_backend()
    return client


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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


def new_client() -> Any:
    """A client of its own for a worker thread (a client keeps one connection and is not shared between threads)."""
    client, _ = create_authoring_client()
    return client


def worker_clients(client: Any) -> Any:
    """The factory of worker clients for ``client``: ``new_client`` when ``client`` is a real GraphQL client, else ``None`` (a stand-in cannot be
    cloned, so the work stays on it, one request after another)."""
    return new_client if isinstance(client, PapyrusGraphQLAuthoringClient) else None


def plan_changes(client: Any, plan: PublishPlan, *, workers: int = 1, client_factory: Any = None, known_rows: Iterable[Mapping[str, Any]] = ()) -> list[dict]:
    """What applying ``plan`` would do, read record by record (a point read each, spread over ``workers`` clients). ``known_rows`` are relation rows
    the command has just read through an index (they carry every field a point read does); a planned relation among them is compared
    with that row and costs no request."""
    known = {row["id"]: row for row in known_rows if row.get("relationState", "current") == "current"}

    def read(reader: Any, record: dict) -> dict | None:
        if record["modelName"] == "SemanticRelation" and record["expected"]["id"] in known:
            return known[record["expected"]["id"]]
        return reader.get_record(record["modelName"], record["expected"]["id"])

    current = map_with_clients(plan.records, read, client=client, client_factory=client_factory, workers=workers)
    changes: list[dict] = []
    for record, existing in zip(plan.records, current):
        model, expected = record["modelName"], record["expected"]
        if record.get("createOnly") and existing is not None:
            changes.append({"modelName": model, "expected": existing, "current": existing, "action": "noop", "createOnly": True})
        else:
            change = build_record_change_from_current(model, expected, existing)
            if record.get("createOnly"):
                change["createOnly"] = True
            changes.append(change)
    for patch in plan.patches:
        changes.append({"modelName": patch["modelName"], "expected": patch["expected"], "current": None, "action": "update"})
    return changes


def apply_changes(client: Any, changes: list[dict], *, workers: int = 1, client_factory: Any = None) -> None:
    """Applies ``changes``: entities first, then everything that points at them, each group over ``workers`` clients. The writes are
    independent (deterministic ids, create-only where a repeat must not overwrite), so their order inside a group does not matter."""
    entities = [change for change in changes if change["modelName"] == "SemanticNode"]
    rest = [change for change in changes if change["modelName"] != "SemanticNode"]
    for group in (entities, rest):
        apply_record_changes(client, group, max_parallel=workers if client_factory is not None else 1, client_factory=client_factory)


def mention_rows_of_items(client: Any, items: list, *, workers: int = 1, client_factory: Any = None) -> list[dict]:
    """The current links of the published items, read through the subject-state index: one query per item."""
    pages = map_with_clients(
        items, lambda reader, item: reader.list_semantic_relations_by_subject_state(semantic_state_key("item", item.key)), client=client, client_factory=client_factory, workers=workers
    )
    seen = {row["id"]: row for rows in pages for row in rows}
    return sorted(seen.values(), key=lambda row: row["id"])


def record_rows_of(client: Any, records: list, *, workers: int = 1, client_factory: Any = None) -> list[dict]:
    """The current links of monitor records, read through the subject-state index: one query per record."""
    pages = map_with_clients(
        records, lambda reader, record: reader.list_semantic_relations_by_subject_state(semantic_state_key("reference", record.lineage_id)), client=client, client_factory=client_factory, workers=workers
    )
    seen = {row["id"]: row for rows in pages for row in rows if is_record_mention(row) or is_record_relation(row)}
    return sorted(seen.values(), key=lambda row: row["id"])


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
                    "dropped": [dropped.to_dict() for dropped in plan.dropped],
                    "duplicates": [{"done": done, "why": why} for done, why in plan.duplicates],
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
    for dropped in plan.dropped:
        print(f"knowledge\t{label}\tdropped\t{dropped.kind}\t{dropped.name}\t{dropped.reason}")
    for done, why in plan.duplicates:
        print(f"knowledge\t{label}\tduplicate\t{done}\t{why}")
    for warning in plan.warnings[:20]:
        print(f"knowledge\t{label}\twarning\t{warning}")
    if len(plan.warnings) > 20:
        print(f"knowledge\t{label}\twarning\t... and {len(plan.warnings) - 20} more")
    if not apply:
        print(f"knowledge\t{label}\tapply\tskipped\tpass --apply to write")


def _path_option(options: dict[str, Any], name: str) -> Path | None:
    value = normalize_string(options.get(name))
    return Path(value) if value else None


def _candidate_filter(run: Any, options: dict[str, Any], node_rows: list[dict]) -> CandidateFilter | None:
    """The filter of the extractor's candidates (``candidate_filter.py``). With ``--stop-words`` or ``--vocabulary`` it is built from the site's
    files and learned from the run's own extraction; without them only the rejected names are filtered, as before."""
    if run is None or not run.entities:
        return None
    stop_words_file, vocabulary_file = _path_option(options, "stop-words"), _path_option(options, "vocabulary")
    if stop_words_file is None and vocabulary_file is None:
        candidate_filter = CandidateFilter()
    else:
        stop_words = load_stop_words(stop_words_file if stop_words_file and stop_words_file.exists() else None)
        kinds = vocabulary_kinds(vocabulary_file.read_text(encoding="utf-8")) if vocabulary_file else None
        candidate_filter = CandidateFilter.learn(run.entities, stop_words=stop_words, kinds=kinds)
    candidate_filter.rejected = rejected_keys(node_rows)
    return candidate_filter


def knowledge_publish_run(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = options.get("apply") is True
    run = load_run(_path_option(options, "identity"), _path_option(options, "trends"), _path_option(options, "entities"))
    if run is None and options.get("skip-front-matter"):
        raise ValueError("Nothing to import: pass --identity, --entities, or drop --skip-front-matter.")
    corpus_id = normalize_string(options.get("corpus-id")) or (
        knowledge_corpus_id({"key": options["corpus-key"]}) if normalize_string(options.get("corpus-key")) else None
    )
    agent_name = clean_name(options.get("actor-name"))
    workers = worker_count(options.get("parallel"))
    client = authoring_client(options)
    items = published_items(client.list_published_item_summaries(), _no_url)
    records = read_records(options["monitor-records"]) if normalize_string(options.get("monitor-records")) else []
    ledger_path = _path_option(options, "monitor-ledger") if records else None
    ledger = None if options.get("monitor-full") else (MonitorLedger.read(ledger_path) if ledger_path else None)
    documents = read_documents_file(options["reference-documents"]) if normalize_string(options.get("reference-documents")) else []
    if run is not None:
        known = {biblicus_item_id(item.item_id): item.item_id for item in items}
        known.update({biblicus_record_id(record.reference_id): record.reference_id for record in records})
        known.update({biblicus_reference_id(document.reference_id): document.reference_id for document in documents})
        run = translate_item_ids(run, known)
    node_rows = current_nodes(client.list_records("SemanticNode"))
    mention_rows = mention_rows_of_items(client, items, workers=workers, client_factory=worker_clients(client))
    proposal_rows = client.list_records("SteeringProposal") if run is not None and run.clusters else []
    record_rows_read: list[dict] = []

    def read_record_rows(todo: list) -> list[dict]:
        record_rows_read.extend(record_rows_of(client, todo, workers=workers, client_factory=worker_clients(client)))
        return record_rows_read

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
        confirm_resolved=bool(options.get("confirm-resolved")),
        front_matter_actor_name=agent_name,
        records=records,
        reference_documents=[document.as_item() for document in documents],
        record_rows_for=read_record_rows,
        ledger=ledger,
        candidate_filter=_candidate_filter(run, options, node_rows),
    )
    changes = plan_changes(client, plan, workers=workers, client_factory=worker_clients(client), known_rows=[*mention_rows, *record_rows_read])
    _print_plan("publish-run", plan, changes, apply, bool(options.get("json")))
    if apply:
        apply_changes(client, changes, workers=workers, client_factory=worker_clients(client))
        if ledger_path and records:  # only after everything was written: a failed run leaves the ledger as it was
            (ledger or MonitorLedger()).after_import(records, plan.monitor_imported, plan.record_matches).write(ledger_path)
        if not options.get("json"):
            print(f"knowledge\tpublish-run\tapplied\t{sum(1 for change in changes if change['action'] != 'noop')}")


@dataclass
class AcceptedDocuments:
    """The accepted-only selection of Reference documents (``--reference-documents-accepted``)."""

    documents: list
    store: Any
    without_text: list[dict[str, str]]
    accepted_ids: list[str]
    skipped: list[str] = field(default_factory=list)


def _accepted_reference_documents(client: Any, options: dict[str, Any]) -> AcceptedDocuments | None:
    if not options.get("reference-documents-accepted"):
        return None
    if normalize_string(options.get("reference-documents-bucket")):
        raise ValueError("Pass --reference-documents-accepted or --reference-documents-bucket, not both: they choose the documents in different ways.")
    corpus_key = normalize_string(options.get("corpus-key"))
    if not corpus_key:
        raise ValueError("--reference-documents-accepted needs --corpus-key (the publication's knowledge corpus key).")
    corpus_id = knowledge_corpus_id({"key": corpus_key})
    documents, without_text, store = load_accepted_reference_documents(client, corpus_id=corpus_id)
    accepted_ids = [str(row["id"]) for row in store.references]
    return AcceptedDocuments(documents, store, without_text, accepted_ids)


def _no_accepted_documents_message(accepted: AcceptedDocuments) -> str:
    reasons = "; ".join(f"{entry['referenceId']}: {entry['reason']}" for entry in accepted.without_text[:10])
    more = f" (and {len(accepted.without_text) - 10} more)" if len(accepted.without_text) > 10 else ""
    return (
        f"--reference-documents-accepted found no accepted Reference with a text to read ({len(accepted.accepted_ids)} accepted). Nothing was written "
        f"and no earlier file or state was removed. {reasons}{more}"
    ).strip()


def knowledge_corpus_export(flags: list[str]) -> None:
    options = parse_options(flags)
    out = _path_option(options, "out")
    if out is None:
        raise ValueError("Pass --out DIR: the folder that receives <item id>.md, normally <corpus>/raw/papyrus.")
    types = tuple(part.strip() for part in (normalize_string(options.get("types")) or ",".join(DEFAULT_TYPES)).split(",") if part.strip())
    sources = parse_sources(options.get("monitor-sources"))
    client = authoring_client(options)
    projector = load_projector(_projection_environment(options))
    items = export_items(client.list_records("PublishedItem"), url_resolver(projector), types)
    accepted = _accepted_reference_documents(client, options)
    records, warnings = [], []
    if sources:
        corpus_key = normalize_string(options.get("corpus-key"))
        if not corpus_key:
            raise ValueError("--monitor-sources needs --corpus-key (the publication's knowledge corpus key).")
        as_of = parse_day(options["as-of"]) if normalize_string(options.get("as-of")) else current_monday(datetime.now(timezone.utc).date())
        weeks = _whole(options.get("monitor-weeks"), "--monitor-weeks", None)  # absent: all history
        records, warnings = load_monitor_records(
            client, corpus_id=knowledge_corpus_id({"key": corpus_key}), sources=sources, as_of=as_of, weeks=weeks,
        )
        if accepted is not None:  # an accepted Reference is a document in this mode; counted as a record too it would hide its entities' pages
            documented = {document.reference_id for document in accepted.documents}
            records = [record for record in records if record.reference_id not in documented]
        if normalize_string(options.get("monitor-records-out")):
            write_records(Path(options["monitor-records-out"]), records, as_of=as_of, sources=sources)
    in_topic_model = bool(options.get("records-in-topic-model"))
    reference_files = []
    reference_counts: dict[str, int] = {}
    bucket = normalize_string(options.get("reference-documents-bucket"))
    keep: frozenset[str] = frozenset()
    if accepted is not None:
        reference_files, reference_counts = export_reference_documents(
            accepted.documents, accepted.store, out, skipped=accepted.skipped,
            on_progress=lambda done, total: print(f"knowledge\tcorpus-export\treference documents {done}/{total}", flush=True),
        )
        kept = {file.item_id for file in reference_files}
        accepted.without_text.extend(
            {"referenceId": reference_id, "reason": accepted.store.reason_not_a_document(reference_id)} for reference_id in accepted.skipped
        )
        if not reference_files:
            raise ValueError(_no_accepted_documents_message(accepted))
        keep = frozenset(f"ref-{reference_id}.md" for reference_id in accepted.accepted_ids)  # a Reference still accepted keeps its earlier file
        reference_counts["leftStubs"] = len(accepted.without_text)
        if normalize_string(options.get("reference-documents-out")):
            write_documents_file(Path(options["reference-documents-out"]), [d for d in accepted.documents if d.reference_id in kept], accepted.without_text)
    elif bucket:  # explicit and opt-in: the corpus's own References with extracted text are documents (records stay data)
        corpus_key = normalize_string(options.get("corpus-key"))
        if not corpus_key:
            raise ValueError("--reference-documents-bucket needs --corpus-key (the publication's knowledge corpus key).")
        extractor = normalize_string(options.get("reference-documents-extractor")) or "markitdown"
        store = S3TextStore(bucket, corpus_key, extractor)
        documents, left = load_reference_documents(client, corpus_id=knowledge_corpus_id({"key": corpus_key}), texts=store.list_texts())
        reference_files, reference_counts = export_reference_documents(
            documents, store, out, on_progress=lambda done, total: print(f"knowledge\tcorpus-export\treference documents {done}/{total}", flush=True)
        )
        reference_counts.update({f"left{name.capitalize()}": count for name, count in left.items()})
        kept = {file.item_id for file in reference_files}
        if normalize_string(options.get("reference-documents-out")):
            write_documents_file(Path(options["reference-documents-out"]), [document for document in documents if document.reference_id in kept])
    counts = write_export(items, out, [render_record(record) for record in records] if in_topic_model else [], reference_files, keep)
    counts.update({f"reference{name[0].upper()}{name[1:]}": count for name, count in reference_counts.items()})
    if records and not in_topic_model:  # data for counts and relations only: the topic model reads the site's own items
        counts["recordsAsData"] = len(records)
    for warning in warnings[:20]:
        print(f"knowledge\tcorpus-export\twarning\t{warning}", file=sys.stderr)
    without_text = accepted.without_text if accepted is not None else []
    if options.get("json"):
        print(json.dumps({"out": str(out), "types": list(types), **counts, **({"referenceWithoutText": without_text} if accepted is not None else {})}, indent=2, sort_keys=True))
        return
    monitor = f"{counts['records']} monitor records\t" if "records" in counts else (f"{counts['recordsAsData']} monitor records (data only, not in the corpus)\t" if "recordsAsData" in counts else "")
    if "referenceDocuments" in counts:
        monitor += f"{counts['referenceDocuments']} reference documents ({counts['referenceDownloaded']} downloaded, {counts['referenceReused']} unchanged, {counts['referenceLeftStubs']} without text)\t"
    print(f"knowledge\tcorpus-export\t{counts['items']} items\t{monitor}{counts['undated']} undated\t{counts['removed']} removed\t{out}")
    for entry in without_text:
        print(f"knowledge\tcorpus-export\treference-without-text\t{entry['referenceId']}\t{entry['reason']}")


def _whole(value: Any, flag: str, default: int | None) -> int | None:
    text = normalize_string(value)
    if text is None:
        return default
    if not text.isdigit() or int(text) < 1:
        raise ValueError(f"{flag} must be a whole number of at least 1.")
    return int(text)


def _concept_kinds(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    kinds = tuple(dict.fromkeys(kind_key(part) for part in str(value).split(",") if kind_key(part))) if value is not True else ()
    if not kinds:
        raise ValueError("--concept-kinds takes a comma separated list of kinds, such as task,technique,concept.")
    return kinds


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
        concept_kinds=_concept_kinds(options.get("concept-kinds")),
        public_kinds=public_kinds_of(options),
    )


def based_template(projector: Any, template: str | None) -> str | None:
    """A site-relative href template (``/concepts/{key}/``) under the site's base path (``/posts/concepts/{key}/``).

    A template that already starts with the base path is taken as written."""
    policy = getattr(projector, "policy", None)
    if not template or policy is None or not policy.root or not template.startswith("/"):
        return template
    return template if template.startswith("/" + policy.root) else policy.path(template)


def load_knowledge_data(client: Any, projector: Any, options: dict[str, Any]) -> KnowledgeData:
    items = published_items(client.list_published_item_summaries(), url_resolver(projector))
    if normalize_string(options.get("reference-documents")):  # Reference documents count as dated sources that cite their Reference's address
        items = [*items, *(document.as_item() for document in read_documents_file(options["reference-documents"]))]
    if normalize_string(options.get("monitor-records")):  # monitor records count in the data; they are never pages
        items = [*items, *(record_as_item(record) for record in read_records(options["monitor-records"]))]
    node_rows = current_nodes(client.list_records("SemanticNode"))
    accepted = [row for row in node_rows if row.get("status") == STATUS_ACCEPTED]
    links, relations = links_and_relations(relations_of_nodes(client, accepted, workers=worker_count(options.get("parallel")), client_factory=worker_clients(client)))
    proposals = [row for row in client.list_records("SteeringProposal") if row.get("proposalKind") == "topic_cluster"]
    category_rows = client.list_records("Category") if proposals or options.get("beats-category-set") else []
    clusters = clusters_of(proposals, category_names(category_rows), items)
    beats = []
    if options.get("beats-config") and options.get("beats-category-set"):
        raise ValueError("Pass one beat source: --beats-config or --beats-category-set.")
    if options.get("beats-config"):
        beats = beats_from_config(json.loads(Path(options["beats-config"]).read_text(encoding="utf-8")), items)
    elif options.get("beats-category-set"):
        beats = beats_from_categories(
            category_rows, options["beats-category-set"], clusters, items, based_template(projector, normalize_string(options.get("beat-href")))
        )
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


def _snapshot_inputs(options: dict[str, Any]) -> tuple[Any, KnowledgeData, SnapshotOptions]:
    """The destination, the records and the options that `snapshot` and `archive` share."""
    snapshot_options = _snapshot_options(options)
    records_file = normalize_string(options.get("records"))
    if records_file:
        if not options.get("out") or options.get("reproject") or options.get("site-bucket"):
            raise ValueError("--records builds offline: pass --out DIR, and not --site-bucket or --reproject.")
        return _OfflineContext(options["out"]), load_records_file(records_file), snapshot_options
    if not options.get("out") and not options.get("site-bucket"):
        raise ValueError("Pass --out DIR (a local directory) or --site-bucket NAME (the site store).")
    if options.get("out") and options.get("site-bucket"):
        raise ValueError("Pass --out or --site-bucket, not both.")
    client = authoring_client(options)
    if options.get("site-bucket"):
        options["bucket"] = options["site-bucket"]
    context = _context_for(client, options)
    data = load_knowledge_data(client, context.projector, options)
    snapshot_options = dataclasses.replace(
        snapshot_options,
        entity_href_template=based_template(context.projector, snapshot_options.entity_href_template),
        cluster_href_template=based_template(context.projector, snapshot_options.cluster_href_template),
    )
    return context, data, snapshot_options


def previous_cluster_history(context: Any, snapshot_options: SnapshotOptions) -> dict | None:
    """The stored ``clusters-history.json``, to carry forward. Without a usable one, the weeks of the weekly archive entries
    (``history/<asOf>.json``) are the backfill; with neither there is no previous history."""
    writer, projector = context.writer, getattr(context, "projector", None)
    stored = writer.get(snapshot_key(projector, CLUSTERS_HISTORY_FILE))
    if stored is not None:
        try:
            document = json.loads(stored)
        except ValueError:
            document = None
        if valid_weeks(document, SCHEMA_VERSION) is not None:
            return document
    prefix = snapshot_key(projector, HISTORY_DIRECTORY + "/")
    entries = []
    for stored_object in sorted(writer.list(prefix), key=lambda candidate: candidate.key):
        name = stored_object.key[len(prefix):]
        if len(name) != len("YYYY-MM-DD.json") or not name.endswith(".json"):
            continue
        try:
            entry = json.loads(writer.get(stored_object.key))
        except (TypeError, ValueError):
            continue
        if isinstance(entry, dict) and entry.get("asOf") and isinstance(entry.get("clusters"), list):
            entries.append(entry)
    if not entries:
        return None
    return {"schemaVersion": SCHEMA_VERSION, "weeks": weeks_from_archive(entries, include_unnamed=snapshot_options.unaccepted_clusters == UNACCEPTED_UNNAMED)}


def knowledge_snapshot(flags: list[str]) -> None:
    options = parse_options(flags)
    context, data, snapshot_options = _snapshot_inputs(options)
    files = build_files(data, snapshot_options, previous_cluster_history(context, snapshot_options))
    with context.leased() if hasattr(context, "leased") else nullcontext():
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


def knowledge_archive(flags: list[str]) -> None:
    """Archive this week's snapshot with the cluster identity of the latest run (see ``archive.py``)."""
    options = parse_options(flags)
    if options.get("reproject"):
        raise ValueError("archive never re-projects pages; run `papyrus knowledge snapshot --reproject` for that.")
    context, data, snapshot_options = _snapshot_inputs(options)
    files = build_files(data, snapshot_options)
    try:
        entry = build_entry(files, data, snapshot_options.as_of, utc_now())
        outcome = archive_entry(context, entry, replace=bool(options.get("replace")))
    except ArchiveError as error:
        print(f"knowledge\tarchive\trefused\t{error}", file=sys.stderr)
        raise SystemExit(1) from error
    result = {
        "asOf": entry["asOf"],
        "runId": entry["runId"],
        "outcome": outcome["outcome"],
        "counts": entry["counts"],
        "written": len(outcome["written"]),
        "purged": len(outcome["purged"]),
        "purgeError": outcome["purgeError"],
    }
    if options.get("json"):
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    counts = entry["counts"]
    print(
        f"knowledge\tarchive\t{result['outcome']}\tasOf {result['asOf']}\trun {result['runId']}\t"
        f"{counts['entities']} entities\t{counts['topics']} topics\t{counts['clusters']} clusters"
    )
    print(f"knowledge\tarchive\t{result['written']} written\t{result['purged']} purged")
    if result["purgeError"]:
        print(f"knowledge\tarchive\twarning\tedge purge failed: {result['purgeError']}")


def _entity_row(row: dict) -> str:
    return "\t".join(
        [
            str(row.get("nodeKey") or ""),
            str(row.get("status") or ""),
            str(row.get("nodeKind") or ""),
            str(row.get("displayName") or ""),
            str(row.get("id") or ""),
            page_label(row),
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
    client = authoring_client(options)
    # With --import-run the nodes of that run come from the import-run index; otherwise the list is every current node.
    nodes = client.list_semantic_nodes_by_import_run_and_node_key(import_run) if import_run else client.list_records("SemanticNode")
    rows = [
        row
        for row in current_nodes(nodes)
        if (status == "all" or row.get("status") == status)
        and (not kind or row.get("nodeKind") == kind)
        and (not import_run or row.get("importRunId") == import_run)
        and (not query or query in str(row.get("displayName") or "").casefold())
    ]
    rows.sort(key=page_order_key)  # the highest page score first, the document count beside it; no threshold
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


def _actor_label(actor: Actor) -> str:
    return f"{actor.actor}:{actor.name}" if actor.name else actor.actor


def _apply_patches(client: Any, options: dict[str, Any], patches: list[dict], *, group: str, name: str, subject: str, status: str, actor: Actor) -> None:
    dry_run = options.get("dry-run") is True
    print(f"knowledge\t{group}\t{name}\t{subject}\t{status}\t{'dry-run' if dry_run else 'apply'}\t{_actor_label(actor)}")
    for patch in patches:
        print(f"knowledge\t{group}\t{name}\tupdate\t{patch['modelName']}\t{patch['expected']['id']}")
    if not patches:
        print(f"knowledge\t{group}\t{name}\tnothing to change")
    if not dry_run and patches:
        write_patches(client, patches)


def write_patches(client: Any, patches: list[dict]) -> None:
    """Write review patches. A signed-in person's token cannot write the graph directly (the model rules allow AWS credentials only, which is why
    these failed with "Failed to apply update SemanticNode"), so on that lane the site's ``applyKnowledgeReview`` mutation checks and writes them and
    records that the review came from the CLI. With AWS credentials (``--auth iam``) they are written to the models, as before."""
    from ..signed_in_concepts import apply_review_patches, on_signed_in_lane  # noqa: PLC0415

    if on_signed_in_lane(client):
        answer = apply_review_patches(client, patches)
        print(f"knowledge\treview\tapplied\t{answer['applied']}\tvia {answer['origin'] or 'the site'}")
        return
    apply_record_changes(client, [{"modelName": patch["modelName"], "expected": patch["expected"], "current": None, "action": "update"} for patch in patches])


def _review(flags: list[str], name: str, build) -> None:
    options = parse_options(flags)
    identifier = normalize_string(options.get("key"))
    if not identifier:
        raise ValueError(f"knowledge entities {name} requires --key <node key, id or lineage id>.")
    actor = actor_from_options(options, today(), command=f"knowledge entities {name}")
    client = authoring_client(options)
    rows = client.list_records("SemanticNode")
    try:
        node = find_node(rows, identifier)
        patches = build(options, node, client, rows, actor)
    except EntityReviewError as error:
        raise ValueError(str(error)) from error
    _apply_patches(client, options, patches, group="entities", name=name, subject=node["nodeKey"], status=str(node.get("status")), actor=actor)


def knowledge_entities_accept(flags: list[str]) -> None:
    def build(options, node, client, _rows, actor):
        mentions = [row for row in relations_of_nodes(client, [node]) if is_extractor_mention(row)]
        return accept_patches(node, mentions, actor=actor, now=utc_now(), confirm_links=not options.get("keep-links-unconfirmed"))

    _review(flags, "accept", build)


def knowledge_entities_reject(flags: list[str]) -> None:
    _review(flags, "reject", lambda options, node, client, rows, actor: reject_patches(node, actor=actor, now=utc_now()))


def knowledge_entities_rename(flags: list[str]) -> None:
    def build(options, node, client, rows, actor):
        name = normalize_string(options.get("name"))
        if not name:
            raise EntityReviewError("knowledge entities rename requires --name <new name>.")
        return rename_patches(node, name, rows, now=utc_now())

    _review(flags, "rename", build)


def knowledge_entities_alias(flags: list[str]) -> None:
    def build(options, node, client, rows, actor):
        name = normalize_string(options.get("add"))
        if not name:
            raise EntityReviewError("knowledge entities alias requires --add <name>.")
        return alias_patches(node, name, rows, actor=actor, now=utc_now())

    _review(flags, "alias", build)


def knowledge_entities_describe(flags: list[str]) -> None:
    def build(options, node, client, rows, actor):
        text = normalize_string(options.get("text"))
        if not text:
            raise EntityReviewError("knowledge entities describe requires --text <description>.")
        return describe_patches(node, text, actor=actor, now=utc_now())

    _review(flags, "describe", build)


def knowledge_entities_page(flags: list[str]) -> None:
    """papyrus knowledge entities page --key K --set yes|no|machine --actor ai|human [--actor-name N] [--dry-run]

    An editor's decision whether the concept has a public page of its own, against the extractor's answer: ``yes`` gives it a page, ``no`` takes it away,
    ``machine`` hands the decision back to the extractor's answer. A knowledge run never changes it. The page appears or goes with the next ``wiki sync``."""
    def build(options, node, client, rows, actor):
        choice = (normalize_string(options.get("set")) or "").casefold()
        if choice not in PAGE_CHOICES:
            raise EntityReviewError("knowledge entities page requires --set yes, no or machine.")
        return page_decision_patches(node, PAGE_CHOICES[choice], actor=actor, now=utc_now())

    _review(flags, "page", build)


def knowledge_entities_accept_description(flags: list[str]) -> None:
    """papyrus knowledge entities accept-description --key K --actor human [--actor-name N] [--dry-run]

    A person accepts the description the entity already has, as it stands, so the wiki publishes it instead of the factual line. Only a person: the
    command refuses ``--actor ai``. To accept words you typed yourself, ``knowledge entities describe --text ... --actor human`` does it in one step."""
    def build(options, node, client, rows, actor):
        return accept_description_patches(node, actor=actor, now=utc_now())

    _review(flags, "accept-description", build)


def knowledge_entities_link(flags: list[str]) -> None:
    """papyrus knowledge entities link --key CONCEPT --to CONCEPT --note TEXT [--dry-run]"""
    from ..signed_in_concepts import knowledge_entities_link as link  # noqa: PLC0415

    select_backend(parse_options(flags))
    link(flags)


def _migration_changes(client: Any, records: list[dict], patches: list[dict]) -> list[dict]:
    """The changes a migration makes: its records against what is stored, and its partial updates."""
    return [
        build_record_change_from_current(record["modelName"], record["expected"], client.get_record(record["modelName"], record["expected"]["id"]))
        for record in records
    ] + [{"modelName": patch["modelName"], "expected": patch["expected"], "current": None, "action": "update"} for patch in patches]


def _print_changes(name: str, changes: list[dict]) -> None:
    for (model, action), count in sorted(Counter((change["modelName"], change["action"]) for change in changes).items()):
        print(f"knowledge\tentities\t{name}\tchanges\t{model}\t{action}\t{count}")


def knowledge_entities_retype(flags: list[str]) -> None:
    options = parse_options(flags)
    identifier = normalize_string(options.get("key"))
    kind = normalize_string(options.get("kind"))
    if not identifier or not kind:
        raise ValueError("knowledge entities retype requires --key <node key, id or lineage id> and --kind <new kind>.")
    actor = actor_from_options(options, today(), command="knowledge entities retype")
    client = authoring_client(options)
    rows = client.list_records("SemanticNode")
    try:
        node = find_node(rows, identifier)
        records, patches, new_key = retype_plan(node, kind, rows, relations_of_nodes(client, [node]), actor=actor, now=utc_now())
    except EntityReviewError as error:
        raise ValueError(str(error)) from error
    dry_run = options.get("dry-run") is True
    print(f"knowledge\tentities\tretype\t{node['nodeKey']} -> {new_key}\t{node.get('status')}\t{'dry-run' if dry_run else 'apply'}\t{_actor_label(actor)}")
    changes = _migration_changes(client, records, patches)
    _print_changes("retype", changes)
    if not dry_run:
        apply_record_changes(client, changes)


def knowledge_entities_merge(flags: list[str]) -> None:
    """papyrus knowledge entities merge --from KEY --into KEY --actor ai|human [--actor-name N] [--dry-run]

    Merge a duplicate entity (--from) into the entity that stays (--into): the duplicate is superseded, its name and aliases become aliases of the survivor, and
    its item mentions and relations move to the survivor (``entity_merge.py``). Needs AWS credentials (``--auth iam``), like ``retype``. Afterwards: ``entities registry``,
    ``snapshot``, then ``wiki sync``; the duplicate's page is left as it is (the sync never takes a page down)."""
    options = parse_options(flags)
    duplicate_id, survivor_id = normalize_string(options.get("from")), normalize_string(options.get("into"))
    if not duplicate_id or not survivor_id:
        raise ValueError("knowledge entities merge requires --from <the duplicate's node key, id or lineage id> and --into <the entity that stays>.")
    actor = actor_from_options(options, today(), command="knowledge entities merge")
    client = authoring_client(options)
    rows = client.list_records("SemanticNode")
    try:
        duplicate, survivor = find_node(rows, duplicate_id), find_node(rows, survivor_id)
        records, patches = merge_plan(duplicate, survivor, rows, relations_of_nodes(client, [duplicate, survivor]), actor=actor, now=utc_now())
    except EntityReviewError as error:
        raise ValueError(str(error)) from error
    dry_run = options.get("dry-run") is True
    print(f"knowledge\tentities\tmerge\t{duplicate['nodeKey']} -> {survivor['nodeKey']}\t{survivor.get('status')}\t{'dry-run' if dry_run else 'apply'}\t{_actor_label(actor)}")
    changes = _migration_changes(client, records, patches)
    _print_changes("merge", changes)
    print(f"knowledge\tentities\tmerge\tnext\tentities registry, snapshot, then `knowledge wiki sync`; the page of {duplicate['nodeKey']} is left as it is, since the sync never takes a page down")
    if not dry_run:
        apply_record_changes(client, changes)


def knowledge_entities_duplicates(flags: list[str]) -> None:
    """papyrus knowledge entities duplicates [--kind KIND] [--json]

    Read only. The pairs of accepted entities in which one duplicates the other by the duplicate rules (``entity_duplicates.py``), each with the rule, what the rule
    says to do (resolve or propose) and the merge command that would join them. The report a person reads before a cleanup."""
    options = parse_options(flags)
    kind = kind_key(normalize_string(options.get("kind")) or "")
    pairs = [
        (hit, node)
        for hit, node in find_duplicate_pairs(authoring_client(options).list_records("SemanticNode"))
        if not kind or kind_key(node.get("nodeKind") or "") == kind
    ]
    if options.get("json"):
        print(json.dumps([{"duplicate": node["nodeKey"], "into": hit.key, "rule": hit.rule, "action": hit.action, "why": hit.sentence()} for hit, node in pairs], indent=2, sort_keys=True))
        return
    for hit, node in pairs:
        print(f"knowledge\tentities\tduplicates\t{node['nodeKey']}\t{hit.key}\t{hit.rule}\t{hit.action}\tmerge --from {node['nodeKey']} --into {hit.key}")
    print(f"knowledge\tentities\tduplicates\t{len(pairs)} pairs")


def _alias_values(flags: list[str]) -> list[str]:
    """Every ``--alias NAME`` in the flags, in order (``parse_options`` keeps only the last of a repeated flag)."""
    return [flags[index + 1] for index, flag in enumerate(flags[:-1]) if flag == "--alias" and not flags[index + 1].startswith("--")]


def knowledge_entities_add(flags: list[str]) -> None:
    """papyrus knowledge entities add --kind KIND --name NAME [--alias A ...] --actor ai|human [--actor-name N] [--corpus-key K | --corpus-id ID] [--dry-run]

    Create the accepted entity (or find it), add every alias, and tag the standard Disambiguation concept on it and on the entities it shares a name with when the
    name is ambiguous across kinds (``entity_add.py``). Refuses a name that duplicates an accepted entity (``entity_duplicates.py``). Needs AWS credentials (``--auth iam``)."""
    options = parse_options(flags)
    kind, name = normalize_string(options.get("kind")), normalize_string(options.get("name"))
    if not kind or kind is True or not name or name is True:
        raise ValueError("knowledge entities add requires --kind <kind> and --name <name> (and --alias <name> once for each other name).")
    actor = actor_from_options(options, today(), command="knowledge entities add")
    corpus_id = normalize_string(options.get("corpus-id")) or (knowledge_corpus_id({"key": options["corpus-key"]}) if normalize_string(options.get("corpus-key")) else None)
    client = authoring_client(options)
    rows = client.list_records("SemanticNode")
    try:
        plan = add_plan(kind, name, _alias_values(flags), rows, actor=actor, now=utc_now(), corpus_id=corpus_id)
    except EntityReviewError as error:
        raise ValueError(str(error)) from error
    dry_run = options.get("dry-run") is True
    tags = disambiguation_plan(plan)
    print(f"knowledge\tentities\tadd\t{plan.node['nodeKey']}\t{'created' if plan.created else 'found'}\t{plan.node.get('status')}\t{'dry-run' if dry_run else 'apply'}\t{_actor_label(actor)}")
    changes = _migration_changes(client, plan.records, plan.patches)
    _print_changes("add", changes)
    for ambiguity in plan.ambiguities:
        print(f"knowledge\tentities\tadd\tambiguous\t{ambiguity.name}\talso " + ", ".join(str(other.get("nodeKey")) for other in ambiguity.others))
    for lineage, _concept, note in tags:
        print(f"knowledge\tentities\tadd\ttag\t{DISAMBIGUATION_NAME}\t{lineage}\t{note}")
    if dry_run:
        return
    apply_record_changes(client, changes)
    if tags:
        _tag_disambiguation(client, rows, tags)


def _tag_disambiguation(client: Any, rows: list[dict], tags: list[tuple[str, str, str]]) -> None:
    """Make the Disambiguation concept if the site has none, then the concept link from each entity to it, with the words that say what is ambiguous."""
    from ..signed_in_concepts import create_concept_link, create_editor_concept  # noqa: PLC0415

    exists = any(row.get("lineageId") == DISAMBIGUATION_LINEAGE and row.get("versionState", "current") == "current" and row.get("status") != "rejected" for row in rows)
    if not exists:
        create_editor_concept(client, DISAMBIGUATION_NAME, DISAMBIGUATION_NAME)
    for subject, concept, note in tags:
        answer = create_concept_link(client, subject=subject, object_=concept, note=note)
        print(f"knowledge\tentities\tadd\ttagged\t{subject}\t{answer.get('outcome')}\t{answer.get('relationId')}")


def knowledge_entities_registry(flags: list[str]) -> None:
    options = parse_options(flags)
    out = _path_option(options, "out")
    if out is None:
        raise ValueError("Pass --out FILE: the registry JSON for `papyrus knowledge extract-entities --registry`.")
    vocabulary_file = _path_option(options, "vocabulary")
    vocabulary = read_vocabulary_kinds(vocabulary_file) if vocabulary_file else None
    client = authoring_client(options)
    registry, warnings = build_registry(client.list_records("SemanticNode"), vocabulary)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(registry, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    for warning in warnings:
        print(f"knowledge\tentities\tregistry\twarning\t{warning}", file=sys.stderr)
    aliases = sum(len(entry["aliases"]) for entry in registry)
    outside = sum(1 for warning in warnings if "which the vocabulary does not have" in warning)
    print(f"knowledge\tentities\tregistry\t{len(registry)} entities\t{aliases} aliases\t{len(warnings) - outside} ambiguous\t{outside} outside the vocabulary\t{out}")


def knowledge_extract_entities(flags: list[str]) -> None:
    """Find the entities in the extracted texts of a corpus: a text pass for candidate names, three Jev questions per name (``entity_extraction.py``)."""
    options = parse_options(flags)
    corpus, out, vocabulary_file = _path_option(options, "corpus"), _path_option(options, "out"), _path_option(options, "vocabulary")
    snapshot = normalize_string(options.get("extraction-snapshot"))
    if corpus is None or out is None or vocabulary_file is None or not snapshot or ":" not in snapshot:
        raise ValueError("Pass --corpus DIR --extraction-snapshot EXTRACTOR:SNAPSHOT --vocabulary FILE --out DIR [--registry FILE] [--cache FILE] [--usage-out FILE].")
    extractor, _colon, snapshot_id = snapshot.partition(":")
    texts = corpus / "extracted" / extractor / snapshot_id / "text"
    if not texts.is_dir():
        raise ValueError(f"No extracted texts at {texts}.")
    registry_file = _path_option(options, "registry")
    cache = _path_option(options, "cache") or corpus / "analysis" / "entity-decisions" / "cache.jsonl"
    vocabulary = yaml.safe_load(vocabulary_file.read_text(encoding="utf-8")) or {}
    try:
        criteria = criteria_of(vocabulary)
        client = JevClient(os.environ.get("TYPESAFE_API_KEY", "").strip())
        documents = {path.stem: path.read_text(encoding="utf-8") for path in sorted(texts.glob("*.txt"))}
        matcher = RegistryMatcher(json.loads(registry_file.read_text(encoding="utf-8")) if registry_file else [])
        candidates = {key: found for key, found in find_candidates(documents, english_stop_words()).items() if not matcher.knows(found["name"])}
        publication = describe_publication(vocabulary)
        decisions, usage, undecided = decide(candidates, criteria, lambda name, passages: client.ask(name, passages, criteria, publication), publication=publication, model=client.model, cache_path=cache)
    except ExtractionError as error:
        raise ValueError(str(error)) from error
    usage_out = _path_option(options, "usage-out")
    if usage_out:  # written before anything can fail, so the stage's cost counts the calls that were paid for
        usage_out.parent.mkdir(parents=True, exist_ok=True)
        usage_out.write_text(json.dumps(usage), encoding="utf-8")
    print(f"knowledge\textract-entities\t{len(documents)} documents\t{len(candidates)} names\t{len(usage)} asked\t{len(candidates) - len(usage) - undecided} cached\t{undecided} undecided", file=sys.stderr)
    if undecided:
        raise ValueError(f"Jev gave no answer for {undecided} names ({dict(client.failures)}); the answers it gave are cached, so run again.")
    output = build_output(documents, candidates, decisions, matcher, vocabulary, model=client.model)
    out.mkdir(parents=True, exist_ok=True)
    (out / "output.json").write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = output["summary"]
    print(f"knowledge\textract-entities\t{summary['entities']} mentions\t{summary['resolved']} resolved\t{summary['items']} items\t{out / 'output.json'}")


def knowledge_topic_config(flags: list[str]) -> None:
    options = parse_options(flags)
    out = _path_option(options, "out")
    if out is None:
        raise ValueError("Pass --out FILE: the topic-modeling configuration for `biblicus analyze topics --configuration`.")
    stop_words_file = _path_option(options, "stop-words")
    extra = read_extra_stop_words(stop_words_file) if stop_words_file else []
    configuration = topic_modeling_configuration(extra)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(configuration), encoding="utf-8")
    listed = len(configuration["bertopic_analysis"]["vectorizer"]["stop_words"])
    print(f"knowledge\ttopic-config\t{len(extra)} extra stop words\t{listed} stop words in all\t{out}")


def _cluster_row(row: dict) -> str:
    metadata = decode_metadata(row.get("summary")) or {}
    accepted_by = metadata.get("acceptedBy") or {}
    return "\t".join(
        [
            str(metadata.get("clusterUid") or row.get("graphEntityId") or ""),
            str(row.get("status") or ""),
            str(row.get("displayName") or ""),
            ", ".join(metadata.get("topTerms") or [])[:60],
            f"{accepted_by.get('actor')}:{accepted_by.get('name') or ''}" if accepted_by else "",
            str(row.get("id") or ""),
        ]
    )


def knowledge_clusters_list(flags: list[str]) -> None:
    options = parse_options(flags)
    status = normalize_string(options.get("status")) or "proposed"
    limit = int(options.get("limit") or 100)
    client = authoring_client(options)
    rows = [
        row
        for row in client.list_records("SteeringProposal")
        if row.get("proposalKind") == CLUSTER_KIND and decode_metadata(row.get("summary")) is not None and (status == "all" or row.get("status") == status)
    ]
    rows.sort(key=lambda row: (str(row.get("displayName") or row.get("title") or "").casefold(), row["id"]))
    for row in rows[:limit]:
        print(_cluster_row(row))
    print(f"knowledge\tclusters\tlist\t{min(limit, len(rows))} of {len(rows)}")


def _review_cluster(flags: list[str], name: str, build) -> None:
    options = parse_options(flags)
    identifier = normalize_string(options.get("uid"))
    if not identifier:
        raise ValueError(f"knowledge clusters {name} requires --uid <cluster uid or proposal id>.")
    actor = actor_from_options(options, today(), command=f"knowledge clusters {name}")
    client = authoring_client(options)
    try:
        proposal = find_cluster(client.list_records("SteeringProposal"), identifier)
        patches = build(options, proposal, actor)
    except ClusterReviewError as error:
        raise ValueError(str(error)) from error
    _apply_patches(client, options, patches, group="clusters", name=name, subject=identifier, status=str(proposal.get("status")), actor=actor)


def knowledge_clusters_accept(flags: list[str]) -> None:
    _review_cluster(flags, "accept", lambda options, proposal, actor: accept_cluster_patches(proposal, normalize_string(options.get("name")), actor, now=utc_now()))


def knowledge_clusters_name(flags: list[str]) -> None:
    def build(options, proposal, actor):
        name = normalize_string(options.get("name"))
        if not name:
            raise ClusterReviewError("knowledge clusters name requires --name <cluster name>.")
        return name_cluster_patches(proposal, name, now=utc_now())

    _review_cluster(flags, "name", build)


def knowledge_clusters_reject(flags: list[str]) -> None:
    _review_cluster(flags, "reject", lambda options, proposal, actor: reject_cluster_patches(proposal, actor, now=utc_now()))


def _node_relations(client: Any) -> list[dict]:
    accepted = [row for row in current_nodes(client.list_records("SemanticNode")) if row.get("status") == STATUS_ACCEPTED]
    return [row for row in relations_of_nodes(client, accepted, workers=DEFAULT_WORKERS, client_factory=worker_clients(client)) if is_node_relation(row)]


def knowledge_relations_list(flags: list[str]) -> None:
    options = parse_options(flags)
    state = normalize_string(options.get("state")) or "proposed"
    if state != "all" and state not in RELATION_STATES:
        raise ValueError("--state must be proposed, accepted, rejected or all.")
    limit = int(options.get("limit") or 100)
    client = authoring_client(options)
    rows = [row for row in _node_relations(client) if state == "all" or review_state(row) == state]
    rows.sort(key=lambda row: (str(row.get("predicate")), row["id"]))
    for row in rows[:limit]:
        print("\t".join([str(row["id"]), review_state(row), str(row.get("predicate")), str(row.get("subjectLineageId")), str(row.get("objectLineageId"))]))
    print(f"knowledge\trelations\tlist\t{min(limit, len(rows))} of {len(rows)}")


def _review_relation(flags: list[str], name: str, build) -> None:
    options = parse_options(flags)
    identifier = normalize_string(options.get("id"))
    if not identifier:
        raise ValueError(f"knowledge relations {name} requires --id <relation id>.")
    actor = actor_from_options(options, today(), command=f"knowledge relations {name}")
    client = authoring_client(options)
    try:
        row = find_relation(_node_relations(client), identifier)
        patches = build(row, actor)
    except RelationReviewError as error:
        raise ValueError(str(error)) from error
    _apply_patches(client, options, patches, group="relations", name=name, subject=identifier, status=review_state(row), actor=actor)


def knowledge_relations_accept(flags: list[str]) -> None:
    _review_relation(flags, "accept", lambda row, actor: accept_relation_patches(row, actor, now=utc_now()))


def knowledge_relations_reject(flags: list[str]) -> None:
    _review_relation(flags, "reject", lambda row, actor: reject_relation_patches(row, actor, now=utc_now()))


def knowledge_cloud_run(flags: list[str]) -> None:
    from ..knowledge_cloud.command import knowledge_cloud_run as run

    run(flags)


def knowledge_runs(flags: list[str]) -> None:
    from ..knowledge_cloud.runs import knowledge_runs as runs

    runs(flags)


def knowledge_run_undo(flags: list[str]) -> None:
    from ..knowledge_cloud.undo import knowledge_run_undo as undo  # noqa: PLC0415

    undo(flags)


def knowledge_run_restore(flags: list[str]) -> None:
    from ..knowledge_cloud.undo import knowledge_run_restore as restore  # noqa: PLC0415

    restore(flags)


KNOWLEDGE_COMMANDS = {
    "cloud-run": knowledge_cloud_run,
    "run-undo": knowledge_run_undo,
    "run-restore": knowledge_run_restore,
    "runs": knowledge_runs,
    "corpus-export": knowledge_corpus_export,
    "publish-run": knowledge_publish_run,
    "snapshot": knowledge_snapshot,
    "archive": knowledge_archive,
    "entities-list": knowledge_entities_list,
    "entities-accept": knowledge_entities_accept,
    "entities-reject": knowledge_entities_reject,
    "entities-rename": knowledge_entities_rename,
    "entities-describe": knowledge_entities_describe,
    "entities-alias": knowledge_entities_alias,
    "entities-accept-description": knowledge_entities_accept_description,
    "entities-page": knowledge_entities_page,
    "entities-link": knowledge_entities_link,
    "entities-retype": knowledge_entities_retype,
    "entities-add": knowledge_entities_add,
    "entities-merge": knowledge_entities_merge,
    "entities-duplicates": knowledge_entities_duplicates,
    "entities-registry": knowledge_entities_registry,
    "extract-entities": knowledge_extract_entities,
    "topic-config": knowledge_topic_config,
    "clusters-list": knowledge_clusters_list,
    "clusters-accept": knowledge_clusters_accept,
    "clusters-name": knowledge_clusters_name,
    "clusters-reject": knowledge_clusters_reject,
    "relations-list": knowledge_relations_list,
    "relations-accept": knowledge_relations_accept,
    "relations-reject": knowledge_relations_reject,
}
