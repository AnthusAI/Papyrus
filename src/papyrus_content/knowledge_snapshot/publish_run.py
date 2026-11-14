"""Plan what ``papyrus knowledge publish-run`` writes. Pure: rows in, records out; the command applies them.

Three sources feed the plan:

* front-matter entities of published items: accepted nodes and confirmed ``mentions`` links. An AI research agent
  entered them, so each node is recorded as accepted by ``ai`` (``actors.py``), never by a person;
* extractor entities: a ``proposed`` mention makes a generated node, a ``resolved`` one links to the node its
  ``entity_key`` names; links start unconfirmed (``--confirm-resolved`` confirms a resolved mention of an accepted
  node). Typed relations between two accepted nodes become ``proposed`` relations until someone accepts them. All are
  created once and never changed by a later run. The one thing a later run does update on an existing node is the extractor's
  page answer (``pageAnswer``, see ``page_answer.py``), unless the node is rejected;
* clusters: one ``topic_cluster`` proposal per cluster uid.

A name resolves to an existing node of the same kind by case and white space insensitive name or alias. A rejected
node is never revived and never linked. Everything is keyed by deterministic ids, so a second run plans nothing new.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..tenant_knowledge_keys import SEMANTIC_NODE_FEED_KEY, global_key, tenant_unique_id
from ..categories_commands import with_version_fields
from ..categories_steering import semantic_relation_record
from ..ids import safe_id
from ..relation_types import normalize_relation_type_key
from ..semantic_node_writes import acceptance_mark_patch, acceptance_patch, create_only_record, derived_node_patch
from .actors import ACTOR_AI, Actor, ReviewMarks, decode_review
from .candidate_filter import CandidateFilter, Dropped
from .cluster_records import CLUSTER_KIND, cluster_proposal_id, proposal_record
from .keys import contains_email, entity_key, kind_key, name_identity
from .model import KIND_REFERENCE_DOCUMENT, LINK_EXTRACTOR, LINK_FRONT_MATTER, PublishedItem
from .page_answer import PAGE_FIELD, PageAnswer, decode_page_answer
from .run_input import ClusterRun, TypedItem

if TYPE_CHECKING:  # the duplicate check imports this module (through the registry), so it is imported where it is used
    from .entity_duplicates import DuplicateFinder, DuplicateHit

ACTOR = "Papyrus knowledge publish-run"
FRONT_MATTER_IMPORT_RUN = "knowledge-front-matter"
MENTIONS = "mentions"
ITEM_KIND = "item"
NODE_KIND = "semanticNode"
STATUS_ACCEPTED = "accepted"
STATUS_GENERATED = "generated"
STATUS_REJECTED = "rejected"
LINK_METADATA_KIND = "knowledge.item_mention"
REFERENCE_KIND = "reference"
REFERENCE_MENTION_METADATA = "knowledge.reference_mention"
RELATION_METADATA_KIND = "knowledge.node_relation"
RESOLUTION_ACTOR_NAME = "extractor resolution"


def json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


@dataclass
class PublishPlan:
    """``records`` are full rows to create or bring up to date; ``patches`` are partial updates of existing rows."""

    records: list[dict] = field(default_factory=list)
    patches: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: Monitor records imported by this plan (reference id) and the base models of each that the map could not place; the command saves them
    #: in the monitor ledger once the plan is applied (``monitor_ledger.py``).
    monitor_imported: dict[str, list[str]] = field(default_factory=dict)
    #: Reference id to the accepted entities a routed record's text names (``monitor_match.py``); the ledger hashes them.
    record_matches: dict[str, list[dict]] = field(default_factory=dict)
    #: Extractor candidates the candidate filter kept from becoming nodes, with the reason (``candidate_filter.py``).
    dropped: list[Dropped] = field(default_factory=list)
    #: Extractor candidates that duplicate an accepted entity (``entity_duplicates.py``): ``(what was done, sentence)``. A resolved one was linked to the entity
    #: and its name added as an alias; a proposed one made no node and no link, and a proposal was filed for a person.
    duplicates: list[tuple[str, str]] = field(default_factory=list)

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount


class NodeIndex:
    """Existing and planned node rows by kind and name identity (``keys.name_identity``) of their name or alias."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._by_name: dict[tuple[str, str], list[dict]] = {}
        self._by_key: dict[str, dict] = {}
        for row in rows:
            if row.get("versionState", "current") == "current":
                self.add(dict(row))

    def add(self, row: dict) -> None:
        for identifier in (row.get("nodeKey"), row.get("lineageId")):
            if identifier:
                self._by_key.setdefault(str(identifier), row)
        kind = kind_key(row.get("nodeKind") or "")
        for name in [row.get("displayName"), *(row.get("aliases") or ())]:
            normal = name_identity(name or "")
            if normal:
                self._by_name.setdefault((kind, normal), []).append(row)

    def rows(self) -> list[dict]:
        """The distinct current rows, existing and planned."""
        return list({id(row): row for rows in self._by_name.values() for row in rows}.values())

    def rows(self) -> list[dict]:
        """The distinct current rows, existing and planned."""
        return list({id(row): row for rows in self._by_name.values() for row in rows}.values())

    def by_key(self, key: str) -> dict | None:
        return self._by_key.get(key)

    def resolve(self, kind: str, name: str) -> dict | None:
        candidates = self._by_name.get((kind_key(kind), name_identity(name)), [])
        for status in (STATUS_ACCEPTED, STATUS_GENERATED):
            matches = sorted((row for row in candidates if row.get("status") == status), key=lambda row: str(row.get("id")))
            if matches:
                return matches[0]
        return next((row for row in candidates if row.get("status") == STATUS_REJECTED), None)


def node_lineage_id(node_key: str) -> str:
    return tenant_unique_id(f"semantic-node-{node_key}")


def new_node_row(kind: str, name: str, status: str, *, import_run_id: str, corpus_id: str | None, now: str, reason: str, page_answer: PageAnswer | None = None) -> dict:
    key = entity_key(kind, name)
    lineage_id = node_lineage_id(key)
    return with_version_fields(
        {
            **({PAGE_FIELD: page_answer.encode()} if page_answer else {}),
            "id": f"{lineage_id}-v1",
            "lineageId": lineage_id,
            "nodeKey": key,
            "nodeKind": kind_key(kind),
            "corpusId": corpus_id,
            "displayName": " ".join(name.split()),
            "aliases": [],
            "status": status,
            "importRunId": import_run_id,
            "createdAt": now,
            "newsroomFeedKey": global_key(SEMANTIC_NODE_FEED_KEY),
            "updatedAt": now,
        },
        now=now,
        actor=ACTOR,
        reason=reason,
    )


def mention_record(
    item: PublishedItem,
    node: Mapping[str, Any],
    *,
    source: str,
    confirmed: bool,
    import_run_id: str,
    now: str,
    extractor_state: str | None = None,
    run_id: str | None = None,
) -> dict:
    from_reference = item.kind == KIND_REFERENCE_DOCUMENT  # an entity extracted from a Reference's text cites the Reference, not an item
    metadata: dict[str, Any] = {"kind": REFERENCE_MENTION_METADATA if from_reference else LINK_METADATA_KIND, "linkSource": source, "confirmed": confirmed}
    if extractor_state:
        metadata["extractorState"] = extractor_state
    return semantic_relation_record(
        {
            "predicate": MENTIONS,
            "subjectKind": REFERENCE_KIND if from_reference else ITEM_KIND,
            "subjectId": item.item_id,
            "subjectLineageId": item.key,
            "subjectVersionNumber": None,
            "objectKind": NODE_KIND,
            "objectId": node["id"],
            "objectLineageId": node["lineageId"],
            "objectVersionNumber": node.get("versionNumber") or 1,
            "rank": 1,
            "classifierId": source,
            "sourceSnapshotId": run_id,
            "importRunId": import_run_id,
            "importedAt": now,
            "metadata": metadata,
        }
    )


def is_item_mention(row: Mapping[str, Any]) -> bool:
    return (
        row.get("predicate") == MENTIONS
        and row.get("subjectKind") == ITEM_KIND
        and row.get("objectKind") == NODE_KIND
        and row.get("relationState", "current") == "current"
    )


def is_reference_mention(row: Mapping[str, Any]) -> bool:
    """A mention the extractor made in a Reference document's text (not a monitor record's link, which has its own marker)."""
    return (
        row.get("predicate") == MENTIONS
        and row.get("subjectKind") == REFERENCE_KIND
        and row.get("objectKind") == NODE_KIND
        and row.get("relationState", "current") == "current"
        and json_object(row.get("metadata")).get("kind") == REFERENCE_MENTION_METADATA
    )


def is_extractor_mention(row: Mapping[str, Any]) -> bool:
    """A link the review confirms or rejects with its entity: from a published item, or from a Reference document."""
    return is_item_mention(row) or is_reference_mention(row)


def _usable(kind: str, name: str, plan: PublishPlan, where: str) -> bool:
    if not entity_key(kind, name):
        plan.warnings.append(f"{where}: an entity needs a kind and a name")
        return False
    if contains_email(name):
        plan.warnings.append(f"{where}: skipped an entity whose name holds an email address")
        return False
    return True


def plan_front_matter(
    items: list[PublishedItem],
    index: NodeIndex,
    existing_mentions: Iterable[Mapping[str, Any]],
    plan: PublishPlan,
    *,
    corpus_id: str | None,
    now: str,
    accepted_by: Actor,
) -> set[tuple[str, str]]:
    desired: set[tuple[str, str]] = set()
    reason = ReviewMarks(accepted_by=accepted_by).encode()
    for item in items:
        for entity in item.entities:
            if not _usable(entity.kind, entity.name, plan, item.key):
                continue
            node = index.resolve(entity.kind, entity.name)
            if node is None:
                node = new_node_row(
                    entity.kind, entity.name, STATUS_ACCEPTED, import_run_id=FRONT_MATTER_IMPORT_RUN, corpus_id=corpus_id, now=now, reason=reason
                )
                plan.records.append(create_only_record(node))
                plan.count("nodesCreated")
                index.add(node)
            elif node.get("status") == STATUS_REJECTED:
                plan.warnings.append(f"{item.key}: {entity.name!r} is a rejected entity; no link written")
                plan.count("linksSkippedRejected")
                continue
            elif node.get("status") == STATUS_GENERATED:
                plan.patches.append(acceptance_patch(node, reason=reason, now=now))
                node["status"] = STATUS_ACCEPTED
                node["changeReason"] = reason
                plan.count("nodesAccepted")
            elif node.get("importRunId") == FRONT_MATTER_IMPORT_RUN and decode_review(node.get("changeReason")).accepted_by is None:
                node["changeReason"] = reason
                plan.patches.append(acceptance_mark_patch(node, reason=reason, now=now))
                plan.count("nodesAcceptanceRecorded")
            pair = (item.key, node["lineageId"])
            if pair in desired:
                continue
            desired.add(pair)
            plan.records.append(
                {
                    "modelName": "SemanticRelation",
                    "expected": mention_record(item, node, source=LINK_FRONT_MATTER, confirmed=True, import_run_id=FRONT_MATTER_IMPORT_RUN, now=now)["expected"],
                }
            )
            plan.count("linksFrontMatter")
    planned_items = {item.key for item in items}
    for row in existing_mentions:
        metadata = json_object(row.get("metadata"))
        if (
            is_item_mention(row)
            and metadata.get("linkSource") == LINK_FRONT_MATTER
            and row.get("subjectLineageId") in planned_items
            and (row.get("subjectLineageId"), row.get("objectLineageId")) not in desired
        ):
            plan.patches.append({"modelName": "SemanticRelation", "expected": {"id": row["id"], "relationState": "superseded", "updatedAt": now}})
            plan.count("linksSuperseded")
    return desired


def relation_record(subject: Mapping[str, Any], predicate: str, target: Mapping[str, Any], *, import_run_id: str, run_id: str, now: str, state: str, score: float | None) -> dict:
    return semantic_relation_record(
        {
            "predicate": predicate,
            "subjectKind": NODE_KIND,
            "subjectId": subject["id"],
            "subjectLineageId": subject["lineageId"],
            "subjectVersionNumber": subject.get("versionNumber") or 1,
            "objectKind": NODE_KIND,
            "objectId": target["id"],
            "objectLineageId": target["lineageId"],
            "objectVersionNumber": target.get("versionNumber") or 1,
            "rank": 1,
            "classifierId": LINK_EXTRACTOR,
            "score": score,
            "sourceSnapshotId": run_id,
            "importRunId": import_run_id,
            "importedAt": now,
            "metadata": {"kind": RELATION_METADATA_KIND, "linkSource": LINK_EXTRACTOR, "confirmed": False, "extractorState": state},
        }
    )


def _settle_duplicate(
    hit: "DuplicateHit",
    entity: Any,
    index: NodeIndex,
    plan: PublishPlan,
    proposed: set[str],
    aliased: set[tuple[str, str]],
    *,
    corpus_id: str | None,
    import_run_id: str,
    now: str,
) -> dict | None:
    """What the duplicate check does with a candidate that duplicates an accepted entity: the entity to link the mention to (after adding the candidate's
    name to it as an alias), or ``None`` when a proposal was filed for a person instead (or none could be, and the report says why)."""
    from .entity_duplicates import RESOLVE, duplicate_proposal  # noqa: PLC0415
    from .entity_review import EntityReviewError, alias_patches  # noqa: PLC0415

    node = index.by_key(hit.key) or dict(hit.node)
    if hit.action == RESOLVE:
        try:
            patches = alias_patches(node, entity.text, index.rows(), actor=Actor(ACTOR_AI, RESOLUTION_ACTOR_NAME, now[:10]), now=now)
        except EntityReviewError:
            patches = None  # another entity of the kind holds the name, or the entity cannot take it: a person decides
        if patches is not None:
            pair = (str(node.get("lineageId")), name_identity(entity.text))
            if patches and pair not in aliased:
                aliased.add(pair)
                plan.patches.extend(patches)
                node["aliases"] = patches[0]["expected"]["aliases"]
                index.add(node)  # the name is the entity's from here on: the next mention of it resolves by name
                plan.count("duplicatesAliased")
            plan.duplicates.append(("resolved", hit.sentence()))
            plan.count("duplicatesResolved")
            return node
    record = None
    if corpus_id:
        record = duplicate_proposal(hit, entity.kind, None, corpus_id=corpus_id, import_run_id=import_run_id, now=now)
        if record["id"] not in proposed:
            proposed.add(record["id"])
            plan.records.append({"modelName": "SteeringProposal", "expected": record, "createOnly": True})
    else:
        plan.warnings.append(f"{entity.text!r} looks like {hit.key} but no --corpus-key or --corpus-id says where to file the proposal; no entity was made for it")
    plan.duplicates.append(("proposed" if record else "held", hit.sentence()))
    plan.count("duplicatesProposed")
    return None


def page_answer_of(entity: Any, run_id: str) -> PageAnswer | None:
    """The extractor's page answer of a proposed entity, when it gave a whole one (a resolved entity, or an older output file, has none)."""
    if entity.state != "proposed" or entity.page_score is None or entity.page_answer is None or entity.page_documents is None:
        return None
    return PageAnswer(entity.page_score, entity.page_answer, entity.page_documents, run_id)


def plan_extractor(
    typed: list[TypedItem],
    items: list[PublishedItem],
    index: NodeIndex,
    confirmed: set[tuple[str, str]],
    run_id: str,
    plan: PublishPlan,
    *,
    corpus_id: str | None,
    now: str,
    confirm_resolved: bool = False,
    candidate_filter: CandidateFilter | None = None,
    duplicates: "DuplicateFinder | None" = None,
) -> None:
    by_id = {item.item_id: item for item in items}
    proposed: set[str] = set()  # duplicate proposals planned by this run
    aliased: set[tuple[str, str]] = set()  # (entity lineage, name identity) pairs whose alias this run has planned
    import_run_id = f"typed-entities-run-{safe_id(run_id)}"
    planned: set[tuple[str, str]] = set()
    planned_relations: set[str] = set()
    resolution = Actor(actor=ACTOR_AI, name=RESOLUTION_ACTOR_NAME, on=now[:10]).to_dict()
    answered: set[str] = set()  # nodes whose page answer this run has written or planned
    unpublished = 0
    for typed_item in typed:
        item = by_id.get(typed_item.item_id)
        if item is None:
            unpublished += 1
            continue
        nodes_by_mention: dict[str, dict] = {}
        for entity in typed_item.entities:
            if not _usable(entity.kind, entity.text, plan, typed_item.item_id):
                continue
            if candidate_filter is not None and candidate_filter.is_rejected(entity.kind, entity.text):
                plan.count("linksSkippedRejected")
                continue  # a name somebody (a person, or the AI review) rejected: no node, no link, and the report says so
            node = None
            if entity.state == "resolved" and entity.entity_key:
                node = index.by_key(entity.entity_key)
                if node is None:
                    plan.warnings.append(f"{typed_item.item_id}: resolved entity key {entity.entity_key!r} names no entity; matched by name")
                    plan.count("resolvedKeysUnknown")
            existing = node is not None
            if node is None:
                node = index.resolve(entity.kind, entity.text)
                existing = node is not None
            if node is None and candidate_filter is not None and not candidate_filter.check(entity.kind, entity.text):
                continue  # a candidate that would be a new node and is a common word, a stop word or of an undeclared kind: no node, no link
            if node is None and duplicates is not None:
                hit = duplicates.find(entity.kind, entity.text)
                if hit is not None:
                    node = _settle_duplicate(hit, entity, index, plan, proposed, aliased, corpus_id=corpus_id, import_run_id=import_run_id, now=now)
                    if node is None:
                        continue  # a person decides: no node, no link
                    existing = True
            answer = page_answer_of(entity, run_id)
            if node is None:
                node = new_node_row(
                    entity.kind, entity.text, STATUS_GENERATED, import_run_id=import_run_id, corpus_id=corpus_id, now=now, reason=f"typed-entities:{run_id}", page_answer=answer
                )
                plan.records.append(create_only_record(node))
                plan.count("nodesGenerated")
                index.add(node)
                answered.add(node["lineageId"])
            elif node.get("status") == STATUS_REJECTED:
                plan.count("linksSkippedRejected")
                continue
            elif answer is not None and node["lineageId"] not in answered:
                answered.add(node["lineageId"])
                patch = None if answer.same_as(decode_page_answer(node.get(PAGE_FIELD))) else derived_node_patch(node, {PAGE_FIELD: answer.encode()}, now=now)
                if patch:  # a later run updates the extractor's answer; an editor's own decision is in changeReason and is never touched
                    plan.patches.append(patch)
                    node[PAGE_FIELD] = answer.encode()
                    plan.count("pageAnswersUpdated")
            nodes_by_mention[entity.id] = node
            pair = (item.key, node["lineageId"])
            if pair in confirmed or pair in planned:
                continue
            planned.add(pair)
            confirm = confirm_resolved and entity.state == "resolved" and existing and node.get("status") == STATUS_ACCEPTED
            record = mention_record(
                item, node, source=LINK_EXTRACTOR, confirmed=confirm, import_run_id=import_run_id, now=now, extractor_state=entity.state, run_id=run_id
            )["expected"]
            if confirm:
                record = {**record, "metadata": json.dumps({**json.loads(record["metadata"]), "confirmedBy": resolution}, sort_keys=True)}
                plan.count("linksConfirmedByResolution")
            plan.records.append({"modelName": "SemanticRelation", "expected": record, "createOnly": True})
            plan.count("linksExtractor")
        for relation in typed_item.relations:
            subject, target = nodes_by_mention.get(relation.subject), nodes_by_mention.get(relation.object)
            predicate = normalize_relation_type_key(relation.type)
            if subject is None or target is None or subject["lineageId"] == target["lineageId"] or not predicate or predicate == MENTIONS:
                plan.count("relationsSkipped")
                continue
            if subject.get("status") != STATUS_ACCEPTED or target.get("status") != STATUS_ACCEPTED:
                plan.count("relationsSkippedUnaccepted")
                continue
            record = relation_record(subject, predicate, target, import_run_id=import_run_id, run_id=run_id, now=now, state=relation.state, score=relation.score)["expected"]
            if record["id"] in planned_relations:
                continue
            planned_relations.add(record["id"])
            plan.records.append({"modelName": "SemanticRelation", "expected": record, "createOnly": True})
            plan.count("relationsProposed")
    if unpublished:
        plan.count("extractorItemsNotPublished", unpublished)
    if candidate_filter is not None:
        plan.dropped.extend(candidate_filter.dropped)
        for dropped in candidate_filter.dropped:
            plan.count(f"candidatesDropped.{dropped.reason}")


def plan_clusters(
    run: ClusterRun,
    existing: Mapping[str, Mapping[str, Any]],
    plan: PublishPlan,
    *,
    corpus_id: str,
    category_set_id: str | None,
    now: str,
) -> None:
    import_run_id = f"topic-cluster-run-{safe_id(run.run_id)}"
    for entry in run.clusters:
        current = existing.get(cluster_proposal_id(entry.uid))
        if current is not None and current.get("proposalKind") != CLUSTER_KIND:
            plan.warnings.append(f"{entry.uid}: id collides with a {current.get('proposalKind')} proposal; skipped")
            continue
        plan.records.append(
            {
                "modelName": "SteeringProposal",
                "expected": proposal_record(entry, run, current, corpus_id=corpus_id, category_set_id=category_set_id, import_run_id=import_run_id, now=now),
            }
        )
        plan.count("clustersContinued" if current is not None else "clustersNew")


def _duplicate_finder(node_rows: list[dict]) -> "DuplicateFinder":
    from .entity_duplicates import DuplicateFinder  # noqa: PLC0415

    return DuplicateFinder(node_rows)


def plan_publish_run(
    *,
    items: list[PublishedItem],
    node_rows: list[dict],
    mention_rows: list[dict],
    proposal_rows: list[dict],
    run: ClusterRun | None,
    corpus_id: str | None,
    category_set_id: str | None,
    now: str,
    include_front_matter: bool = True,
    confirm_resolved: bool = False,
    front_matter_actor_name: str | None = None,
    records: list | None = None,
    reference_documents: list[PublishedItem] | None = None,
    record_rows: list[dict] | None = None,
    record_rows_for: Callable[[list], list[dict]] | None = None,
    ledger: Any = None,
    candidate_filter: CandidateFilter | None = None,
    check_duplicates: bool = True,
) -> PublishPlan:
    """``records`` are monitor records (``monitor_records.py``) and ``record_rows`` the current relation rows of the records' links: together
    they add the structured entities and relations of the records (``monitor_import.py``). With a ``ledger`` (``monitor_ledger.py``) only the
    records that are new or changed since it was saved are imported, and ``record_rows_for(records)`` reads the relation rows of just those
    (it replaces ``record_rows``)."""
    plan = PublishPlan()
    index = NodeIndex(node_rows)
    confirmed: set[tuple[str, str]] = set()
    if include_front_matter:
        agent = Actor(actor=ACTOR_AI, name=front_matter_actor_name, on=now[:10])
        confirmed = plan_front_matter(items, index, mention_rows, plan, corpus_id=corpus_id, now=now, accepted_by=agent)
    if records:
        from .monitor_import import monitor_placement, plan_monitor_records  # noqa: PLC0415 - monitor_import imports this module
        from .monitor_match import match_records  # noqa: PLC0415

        plan.record_matches = match_records(records, index.rows())
        todo = ledger.changed(records, monitor_placement(records, index), plan.record_matches) if ledger is not None else records
        plan.count("recordsUnchanged", len(records) - len(todo))
        plan.count("recordsImported", len(todo))
        rows = record_rows_for(todo) if record_rows_for is not None and todo else (record_rows or [])
        plan_monitor_records(todo, index, rows, plan, corpus_id=corpus_id, now=now, matched=plan.record_matches)
    if run is not None:
        plan.warnings.extend(run.warnings)
        if run.entities:
            plan_extractor(
                run.entities, [*items, *(reference_documents or [])], index, confirmed, run.run_id, plan,
                corpus_id=corpus_id, now=now, confirm_resolved=confirm_resolved, candidate_filter=candidate_filter,
                duplicates=_duplicate_finder(node_rows) if check_duplicates else None,
            )
        if run.clusters:
            if not corpus_id:
                raise ValueError("Importing clusters needs --corpus-key or --corpus-id (a steering proposal belongs to a corpus).")
            plan_clusters(run, {row["id"]: row for row in proposal_rows}, plan, corpus_id=corpus_id, category_set_id=category_set_id, now=now)
    return plan
