"""The decide-site-sections sweep: the candidate pipeline's hook into the site cyclotron.

One sweep, run by a worker, mirrors the relevance sweep for the site plan:

1. Claims the site cyclotron's ``cyclotron.site`` Assignment (one writer).
2. Restores the cyclotron store from the private media bucket when this worker
   has no local copy.
3. Teaches the cyclotron from explicit human Section labels only: a Reference
   a person accepted into a Section teaches the selector that Section, teaches
   that Section's fit classifier ``fits`` and every other Section's fit
   classifier ``does-not-fit``. This assumes a Reference belongs to a single
   Section. Agents and unknown actors never teach.
4. Decides every current pending ``Reference`` with one ``decide`` call that
   answers every classifier, and records each classifier's answer as its own
   ``site_decision_is`` relation superseding the previous current one.
5. Records the shadow agreement per classifier, saves the store, releases the claim.

Every result is a suggestion. The sweep never changes a Reference's curation status.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .auto_decision_gate import auto_decision_gate, load_approved_proof
from .assignments import active_claim_held_by_different_assignee
from .catalog import _record, semantic_relation_record
from .ids import hash_short, knowledge_corpus_id, safe_id
from .relevance_cyclotron import decision_model_from_environment, optimizer_from_environment
from .reference_vote import latest_vote
from .relevance_decisions import human_section_for_review
from .relevance_shadow import (decisions_remaining_today, live_agreement, shadow_agreement_record, usage_record,
                               utc_day, SHADOW_AGREEMENT_SCHEMA)
from .relevance_sweep import (REVIEWED_STATUSES, SNAPSHOT_NAME, AssignmentClaimLease, CyclotronClaimed, S3SnapshotStore,
                              SweepResult, _HeldLease, _apply, _current, _recorded_usage,
                              reference_item)
from .site_classifier_set import (apply_site_classifier_set, definition_with_classifiers, plan_site_classifier_set,
                                  stored_active_specs)
from .site_cyclotron import (SECTION_FIT_POSITIVE_LABEL, SECTION_FIT_LABELS, build_site_cyclotron,
                             enabled_sections_in_order, is_section_selector_classifier_id, section_fit_classifier_id,
                             section_selector_classifier_id)
from .steering import require_corpus_config

SITE_SWEEP_ASSIGNMENT_TYPE = "cyclotron.site"
SITE_DECISION_RELATION = "site_decision_is"
SITE_DECISION_NODE_KIND = "siteDecision"
SECTION_DOES_NOT_FIT_LABEL = SECTION_FIT_LABELS[1]


def site_sweep_assignment_id(cyclotron_id: str) -> str:
    return f"assignment-{safe_id(SITE_SWEEP_ASSIGNMENT_TYPE)}-{safe_id(cyclotron_id)}"


def ensure_site_sweep_assignment(client, cyclotron_id: str, corpus_id: str, now: str) -> str:
    assignment_id = site_sweep_assignment_id(cyclotron_id)
    if client.get_record("Assignment", assignment_id) is None:
        queue_key = f"{SITE_SWEEP_ASSIGNMENT_TYPE}#{corpus_id}"
        client.upsert("Assignment", {
            "id": assignment_id, "assignmentTypeKey": SITE_SWEEP_ASSIGNMENT_TYPE, "queueKey": queue_key,
            "queueStatusKey": f"{queue_key}#open", "status": "open", "priority": 50,
            "title": f"Site cyclotron sweep ({cyclotron_id})",
            "brief": "Suggest a Section for pending candidate references and teach the site cyclotron from editors' Section choices.",
            "corpusId": corpus_id, "createdBy": "papyrus-cyclotron", "createdAt": now, "updatedAt": now,
            "newsroomFeedKey": "assignments",
        })
    return assignment_id


def site_classifier_key(cyclotron_id: str, classifier: str) -> str:
    return f"{cyclotron_id}/{classifier}"


def human_labels_for_section(section_id: str, enabled_section_ids: Sequence[str]) -> dict[str, str]:
    """The label every classifier learns from a person placing a Reference in one Section.

    Assumes a Reference belongs to a single Section: it fits the chosen
    Section and does not fit any other.
    """
    labels = {section_fit_classifier_id(other): SECTION_FIT_POSITIVE_LABEL if other == section_id
              else SECTION_DOES_NOT_FIT_LABEL for other in enabled_section_ids}
    if len(enabled_section_ids) >= 2:
        labels[section_selector_classifier_id(enabled_section_ids)] = section_id
    return labels


def site_decision_node_key(classifier: str, label: str) -> str:
    return f"site.{safe_id(classifier)}.{safe_id(label)}"


def site_decision_node_lineage_id(classifier: str, label: str) -> str:
    return f"semantic-node-{safe_id(site_decision_node_key(classifier, label))}"


def site_decision_node_record(classifier: str, label: str, *, now: str) -> dict[str, Any]:
    key = site_decision_node_key(classifier, label)
    display = f"Site decision {classifier}: {label}"
    description = f"The site cyclotron's {classifier} classifier decided {label} for a candidate source."
    lineage_id = site_decision_node_lineage_id(classifier, label)
    return _record("SemanticNode", {
        "id": f"{lineage_id}-v1", "lineageId": lineage_id, "versionNumber": 1, "versionState": "current",
        "versionCreatedAt": now, "versionCreatedBy": "papyrus-cyclotron", "changeReason": "siteDecision-seed",
        "contentHash": hash_short([key, SITE_DECISION_NODE_KIND, display, description]),
        "nodeKey": key, "nodeKind": SITE_DECISION_NODE_KIND, "displayName": display, "description": description,
        "aliases": [label], "status": "accepted", "createdAt": now, "updatedAt": now, "newsroomFeedKey": "semanticNodes",
    })


def site_decision_records(reference: Mapping[str, Any], decision: Mapping[str, Any], *, cyclotron_id: str,
                          classifier_questions: Mapping[str, str], classifier_labels: Mapping[str, Sequence[str]],
                          classifier_positive_labels: Mapping[str, str | None], now: str,
                          current_relations: Sequence[Mapping[str, Any]] = (), review_control: str | None = None,
                          provenance: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Records for one decision: a relation per classifier, superseding every earlier current relation of the cyclotron, retired classifiers' included."""
    records: list[dict[str, Any]] = []
    new_relation_ids: set[str] = set()
    lineage_id = reference.get("lineageId") or reference["id"]
    review = decision["review"]
    for classifier, result in decision["classifiers"].items():
        label = result["label"]
        probabilities = result.get("probabilities") or {}
        positive_label = classifier_positive_labels.get(classifier)
        key = site_classifier_key(cyclotron_id, classifier)
        node_lineage_id = site_decision_node_lineage_id(classifier, label)
        relation = semantic_relation_record({
            "predicate": SITE_DECISION_RELATION,
            "subjectKind": "reference",
            "subjectId": reference["id"],
            "subjectLineageId": lineage_id,
            "subjectVersionNumber": reference.get("versionNumber"),
            "objectKind": "semanticNode",
            "objectId": f"{node_lineage_id}-v1",
            "objectLineageId": node_lineage_id,
            "objectVersionNumber": 1,
            "score": probabilities.get(positive_label or label, result.get("confidence")),
            "confidence": result.get("confidence"),
            "rank": 1,
            "classifierId": key,
            "modelVersion": str(result["version"]),
            "reviewRecommended": bool(review["selected"]),
            "importedAt": now,
            "metadata": {
                "decisionId": decision["decisionId"],
                "cyclotronId": cyclotron_id,
                "classifier": classifier,
                "label": label,
                "probabilities": probabilities,
                "version": result["version"],
                "fingerprint": result.get("fingerprint"),
                "reviewReason": review.get("reason"),
                "reviewDetail": review.get("detail"),
                "propensity": review.get("propensity"),
                "decidedAt": decision.get("createdAt"),
                "question": classifier_questions.get(classifier),
                "labels": list(classifier_labels.get(classifier) or probabilities),
                "positiveLabel": positive_label,
                "reviewControl": review_control,
                **({"provenance": dict(provenance)} if provenance else {}),
            },
        })
        relation["expected"]["id"] = f"semantic-relation-{hash_short([SITE_DECISION_RELATION, decision['decisionId'], classifier])}"
        new_relation_ids.add(relation["expected"]["id"])
        records.append(site_decision_node_record(classifier, label, now=now))
        records.append(relation)
    records.extend(
        _record("SemanticRelation", {**{name: value for name, value in existing.items() if not name.startswith("__")},
                                     "relationState": "superseded", "updatedAt": now})
        for existing in current_relations
        if existing.get("predicate") == SITE_DECISION_RELATION and existing.get("relationState") == "current"
        and existing.get("subjectLineageId") == lineage_id and existing.get("id") not in new_relation_ids
        and existing.get("classifierId", "").startswith(f"{cyclotron_id}/"))
    return records


def current_site_decisions(relations: Sequence[Mapping[str, Any]], reference_lineage_id: str) -> dict[str, Mapping[str, Any]]:
    """The current site decision relation of a reference lineage, by classifier id."""
    current: dict[str, Mapping[str, Any]] = {}
    for relation in relations:
        if (relation.get("predicate") != SITE_DECISION_RELATION or relation.get("relationState") != "current"
                or relation.get("subjectLineageId") != reference_lineage_id):
            continue
        classifier = json.loads(relation.get("metadata") or "{}").get("classifier")
        if classifier in current:
            raise ValueError(f"Reference {reference_lineage_id} has two current site decisions for {classifier}.")
        current[classifier] = relation
    return current


def _site_decision_relations(client, lineage_id: str) -> list[dict[str, Any]]:
    return [relation for relation in client.list_by_index("semanticRelationsBySubjectState", f"reference#{lineage_id}#current")
            if relation.get("predicate") == SITE_DECISION_RELATION]


def _decision_id_of(decisions: Mapping[str, Mapping[str, Any]]) -> str | None:
    for relation in decisions.values():
        decision_id = json.loads(relation.get("metadata") or "{}").get("decisionId")
        if decision_id:
            return decision_id
    return None


def site_provenance(plan, cyclotron, doctrine: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    taught = sorted((str(row["item"].id), str(row["classifier"]), str(row["label"]))
                    for row in cyclotron.labels())
    primed = sorted(str(identifier) for addition in cyclotron.priming_additions()
                    for identifiers in addition.get("examples", {}).values() for identifier in identifiers)
    classifiers = {spec.id: {"question": spec.question, "labels": list(spec.labels)} for spec in plan.definition.classifiers}
    doctrine_text = json.dumps({"rubrics": dict(plan.seed_rubrics), "classifiers": classifiers,
                                "doctrine": list(doctrine)}, sort_keys=True, default=str)
    return {
        "classifiers": sorted(classifiers),
        "doctrineFingerprint": hashlib.sha256(doctrine_text.encode("utf-8")).hexdigest()[:16],
        "teachingFingerprint": hashlib.sha256(json.dumps([taught, primed]).encode("utf-8")).hexdigest()[:16],
        "teachingLabels": len(taught),
        "primingExamples": len(primed),
    }


def _human_section_references(client, corpus_id: str, enabled_section_ids: Sequence[str]):
    """Each reviewed Reference a person explicitly placed in a Section: (reference, section id)."""
    placed = []
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            section_id = human_section_for_review(reference, enabled_section_ids)
            if section_id is not None:
                placed.append((reference, section_id))
    return placed


def _live_site_agreement(client, plan, corpus_id: str, enabled_section_ids: Sequence[str], now: str,
                         stopped_because: str | None = None) -> dict[str, Any]:
    """Per-classifier agreement of earlier suggestions with later explicit human Section decisions."""
    outcomes: dict[str, list[tuple[str, str]]] = {spec.id: [] for spec in plan.definition.classifiers}
    placed = _human_section_references(client, corpus_id, enabled_section_ids)
    for reference, section_id in placed:
        reviewed_at = str(latest_vote(reference)["createdAt"] or "")
        decisions = current_site_decisions(_site_decision_relations(client, reference["lineageId"]), reference["lineageId"])
        for classifier, human_label in human_labels_for_section(section_id, enabled_section_ids).items():
            relation = decisions.get(classifier)
            if relation is None:
                continue
            metadata = json.loads(relation.get("metadata") or "{}")
            suggested_at = str(metadata.get("decidedAt") or relation.get("importedAt") or "")
            if not suggested_at or not reviewed_at or suggested_at >= reviewed_at:
                continue
            outcomes[classifier].append((human_label, metadata.get("label")))
    classifiers = {}
    for spec in plan.definition.classifiers:
        if is_section_selector_classifier_id(spec.id):
            correct = sum(1 for human, suggested in outcomes[spec.id] if human == suggested)
            classifiers[spec.id] = {"comparisons": len(outcomes[spec.id]), "decided": len(outcomes[spec.id]),
                                    "correct": correct,
                                    "agreement": correct / len(outcomes[spec.id]) if outcomes[spec.id] else None}
        else:
            classifiers[spec.id] = live_agreement(
                [{"editorLabel": human, "suggestedLabel": suggested} for human, suggested in outcomes[spec.id]],
                positive_label=SECTION_FIT_POSITIVE_LABEL, now=now)
    selector = next((value for identifier, value in classifiers.items() if is_section_selector_classifier_id(identifier)), None)
    gate_labels = len(placed)
    return {"schema": SHADOW_AGREEMENT_SCHEMA, "positiveLabel": None, "computedAt": now,
            "comparisons": (selector or {}).get("comparisons", 0), "decided": (selector or {}).get("decided", 0),
            "agreement": (selector or {}).get("agreement"),
            "selectorAccuracy": (selector or {}).get("agreement"),
            "classifiers": classifiers,
            "autoDecision": auto_decision_gate(load_approved_proof(plan.approved_proof_path),
                                               human_label_count=gate_labels, now=now),
            "loop": {"enabled": plan.enabled, "stoppedBecause": stopped_because, "lastSweepAt": now,
                     "maxDecisionsPerDay": plan.max_decisions_per_day}}


def _teach_from_human_sections(client, cyclotron, plan, corpus_id: str, enabled_section_ids: Sequence[str],
                               warnings: list[str]) -> tuple[int, int]:
    """Send each explicit human Section choice to the cyclotron. Returns (primed, reviewed).

    A Reference the cyclotron never decided teaches as a priming example; a
    decided one teaches through one checklist review of every classifier.
    Idempotent: examples the store holds and review ids already recorded change nothing.
    """
    from decision_flywheel import Item, LabeledItem

    primed = reviewed = 0
    for reference, section_id in _human_section_references(client, corpus_id, enabled_section_ids):
        labels = human_labels_for_section(section_id, enabled_section_ids)
        latest = latest_vote(reference)
        decisions = current_site_decisions(_site_decision_relations(client, reference["lineageId"]), reference["lineageId"])
        decision_id = _decision_id_of(decisions)
        if decision_id is None:
            note = str(reference.get("curationStatusReason") or "").strip()
            item = reference_item({**reference, "curationStatusReason": None})
            examples = {classifier: [LabeledItem(Item(item.id, item.values), label, "trusted",
                                                 {"human_feedback": note} if note else {})]
                        for classifier, label in labels.items()}
            examples = {classifier: values for classifier, values in examples.items() if classifier in cyclotron.specs}
            try:
                outcome = asyncio.run(cyclotron.add_priming_examples(
                    examples, added_by=str(latest["authorLabel"] or "newsroom editor")))
            except ValueError as error:
                warnings.append(f"{reference['lineageId']}: {error}")
                continue
            primed += 1 if outcome["added"] else 0
            continue
        labels = {classifier: label for classifier, label in labels.items()
                  if classifier in cyclotron.specs and classifier in decisions}
        try:
            asyncio.run(cyclotron.review(
                decision_id, labels=labels, explanation=reference.get("curationStatusReason"),
                reason_code=latest["reasonCode"], reviewer=latest["authorLabel"], review_id=latest["id"]))
        except ValueError as error:
            warnings.append(f"{reference['lineageId']}: {error}")
            continue
        reviewed += 1
    return primed, reviewed


def _prime_added_classifiers(client, cyclotron, corpus_id: str, enabled_section_ids: Sequence[str],
                             added_classifier_ids: Sequence[str], warnings: list[str]) -> int:
    """Teach newly added classifiers from the Section choices people made before they existed.

    A classifier cannot review a decision made before it was added, so it
    learns from those choices as priming examples instead.
    """
    from decision_flywheel import Item, LabeledItem

    primed = 0
    for reference, section_id in _human_section_references(client, corpus_id, enabled_section_ids):
        labels = {classifier: label for classifier, label in human_labels_for_section(section_id, enabled_section_ids).items()
                  if classifier in added_classifier_ids}
        if not labels:
            continue
        note = str(reference.get("curationStatusReason") or "").strip()
        item = reference_item({**reference, "curationStatusReason": None})
        examples = {classifier: [LabeledItem(Item(item.id, item.values), label, "trusted",
                                             {"human_feedback": note} if note else {})]
                    for classifier, label in labels.items()}
        try:
            outcome = asyncio.run(cyclotron.add_priming_examples(
                examples, added_by=str(latest_vote(reference)["authorLabel"] or "newsroom editor")))
        except ValueError as error:
            warnings.append(f"{reference['lineageId']}: {error}")
            continue
        primed += 1 if outcome["added"] else 0
    return primed


def _stored_site_specs(local: Path, snapshots, snapshot_uri: str | None):
    """The classifiers the stored cyclotron has: the local store, else the snapshot in the bucket. None when neither exists."""
    from decision_flywheel import Cyclotron

    local_specs = stored_active_specs(local)
    if local_specs is not None or not (snapshots and snapshot_uri):
        return local_specs
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / SNAPSHOT_NAME
        if not snapshots.download(snapshot_uri, archive):
            return None
        Cyclotron.restore(archive, Path(scratch) / "restored", lease=_HeldLease())
        return stored_active_specs(Path(scratch) / "restored")


def run_decide_site_sections(client, steering_config: Mapping[str, Any], doctrine: Sequence[Mapping[str, Any]],
                             sections: Sequence[Mapping[str, Any]], *, apply: bool, worker: str,
                             max_count: int | None = None, model=None, optimizer=None, snapshots=None,
                             now: Callable[[], str] | None = None) -> SweepResult:
    """Run one site sweep: suggest a Section decision per classifier for each pending Reference."""
    now = now or (lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    plan = build_site_cyclotron(steering_config, sections)
    enabled_section_ids = [str(section["id"]) for section in enabled_sections_in_order(sections)]
    corpus = require_corpus_config(dict(steering_config), steering_config["canonicalTopicSet"]["corpusKey"],
                                   "canonicalTopicSet.corpusKey")
    corpus_id = knowledge_corpus_id(corpus)
    pending = _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#pending"))
    pending.sort(key=lambda reference: str(reference.get("importedAt") or reference.get("createdAt") or ""))
    if max_count is not None:
        pending = pending[:max_count]
    result = SweepResult(applied=apply)
    if not plan.enabled:
        result.stopped_because = "disabled"
        result.warnings.append(f"{plan.definition.id} is switched off in the steering config; nothing was decided.")
        if apply:
            result.live_agreement = _live_site_agreement(client, plan, corpus_id, enabled_section_ids, now(),
                                                         result.stopped_because)
            _apply(client, [shadow_agreement_record(plan.definition.id, result.live_agreement, now=now())])
        return result
    today = utc_day(now())
    recorded_usage = _recorded_usage(client, plan.definition.id)
    decisions_allowed = decisions_remaining_today(recorded_usage, maximum_per_day=plan.max_decisions_per_day, today=today)
    result.pending = [reference["lineageId"] for reference in pending]
    snapshots = snapshots if snapshots is not None else (S3SnapshotStore() if plan.s3_prefix else None)
    local = Path(plan.local_path)
    snapshot_uri = f"{plan.s3_prefix.rstrip('/')}/{SNAPSHOT_NAME}" if plan.s3_prefix else None
    set_plan = plan_site_classifier_set(_stored_site_specs(local, snapshots, snapshot_uri), plan.definition.classifiers)
    result.classifier_set = set_plan.to_json()
    if not set_plan.unchanged:
        result.warnings.extend(f"Section parity would {line}." for line in set_plan.describe())
    if not apply:
        return result

    from .editorial_model_context import classification_model
    model = classification_model(model if model is not None else decision_model_from_environment(plan),
                                 client, steering_config, sections)
    model.verify_context()

    from decision_flywheel import Cyclotron

    assignment_id = ensure_site_sweep_assignment(client, plan.definition.id, corpus_id, now())
    lease = AssignmentClaimLease(client, assignment_id, worker)
    lease.acquire()
    try:
        if snapshots and snapshot_uri and not (local / "cyclotron.sqlite3").exists():
            with tempfile.TemporaryDirectory() as scratch:
                archive = Path(scratch) / SNAPSHOT_NAME
                if snapshots.download(snapshot_uri, archive):
                    Cyclotron.restore(archive, local, lease=_HeldLease())
        optimizer = optimizer if optimizer is not None else optimizer_from_environment(plan)
        stored_specs = stored_active_specs(local)
        opening_definition = definition_with_classifiers(plan.definition, stored_specs) if stored_specs else plan.definition
        cyclotron = Cyclotron.open(local, opening_definition, model, optimizer, lease=_HeldLease(),
                                   max_requests=plan.max_requests, review_program=plan.review_program,
                                   seed_rubrics={identifier: rubric for identifier, rubric in plan.seed_rubrics.items()
                                                 if identifier in {spec.id for spec in opening_definition.classifiers}})
        try:
            if not set_plan.unchanged:
                asyncio.run(apply_site_classifier_set(cyclotron, set_plan, plan.seed_rubrics))
                result.primed_from_human_reviews += _prime_added_classifiers(
                    client, cyclotron, corpus_id, enabled_section_ids, [spec.id for spec in set_plan.added], result.warnings)
            primed_by_teaching, result.reviews = _teach_from_human_sections(
                client, cyclotron, plan, corpus_id, enabled_section_ids, result.warnings)
            result.primed_from_human_reviews += primed_by_teaching
            provenance = site_provenance(plan, cyclotron, doctrine)
            questions = {spec.id: spec.question for spec in plan.definition.classifiers}
            labels = {spec.id: spec.labels for spec in plan.definition.classifiers}
            positive_labels = {spec.id: spec.positive_label for spec in plan.definition.classifiers}
            records: list[dict[str, Any]] = []
            for reference in pending:
                if decisions_allowed is not None and result.decided >= decisions_allowed:
                    result.stopped_because = "daily decision cap"
                    result.warnings.append(
                        f"{plan.definition.id} reached its cap of {plan.max_decisions_per_day} decisions today.")
                    break
                decision = asyncio.run(cyclotron.decide(model.prepare(reference_item(reference))))
                current_relations = _site_decision_relations(client, reference["lineageId"])
                existing = current_site_decisions(current_relations, reference["lineageId"])
                if set(existing) == set(decision.results) and all(
                        json.loads(relation.get("metadata") or "{}").get("decisionId") == decision.decision_id
                        for relation in existing.values()):
                    continue
                records.extend(site_decision_records(
                    reference, decision.to_json(), cyclotron_id=plan.definition.id, classifier_questions=questions,
                    classifier_labels=labels, classifier_positive_labels=positive_labels, now=now(),
                    current_relations=current_relations, review_control=plan.review_control, provenance=provenance))
                result.decided += 1
            result.live_agreement = _live_site_agreement(client, plan, corpus_id, enabled_section_ids, now(),
                                                         result.stopped_because)
            records.append(shadow_agreement_record(plan.definition.id, result.live_agreement, now=now()))
            if plan.max_decisions_per_day is not None:
                already_decided_today = recorded_usage["decisions"] if recorded_usage and recorded_usage.get("day") == today else 0
                records.append(usage_record(plan.definition.id, day=today,
                                            decisions=already_decided_today + result.decided, now=now()))
            _apply(client, records)
            if snapshots and snapshot_uri:
                with tempfile.TemporaryDirectory() as scratch:
                    archive = Path(scratch) / SNAPSHOT_NAME
                    cyclotron.snapshot(archive)
                    snapshots.upload(archive, snapshot_uri)
        finally:
            cyclotron.close()
    finally:
        lease.release()
    return result


def default_sections_path(config_path: str | None) -> str:
    """corpora/<publication>-newsroom-sections.yml, the publication named by the steering config's file name."""
    from .env import PAPYRUS_ROOT

    stem = Path(config_path).name.removesuffix(".yml").removesuffix(".yaml").removesuffix("-steering") if config_path else "papyrus"
    return str(PAPYRUS_ROOT / "corpora" / f"{stem}-newsroom-sections.yml")


def references_decide_site_sections(flags: list[str]) -> None:
    """papyrus references decide-site-sections [--config <steering.yml>] [--doctrine <doctrine.yml>]
    [--sections-file <newsroom-sections.yml>] [--tenant <id>] [--max-count N] [--worker <name>] [--apply] [--json]

    Dry run by default: lists the pending references a sweep would decide and
    makes no model call. ``--apply`` runs the sweep. With ``--tenant`` (or
    PAPYRUS_TENANT_ID) the Sections are that tenant's NewsroomSection rows and
    the cyclotron, its stores, Assignment and decisions are the tenant's own.
    """
    import os
    import socket

    from .graphql_authoring import create_authoring_client
    from .newsroom_doctrine import describe_doctrine_choice, load_publication_doctrine_seed, require_explicit_doctrine
    from .newsroom_sections import load_newsroom_section_seeds
    from .options import parse_options
    from .site_cyclotron import newsroom_sections_of_tenant, tenant_site_cyclotron_steering
    from .steering import require_steering_config
    from .tenancy import tenant_id_from_options

    options = parse_options(flags)
    if options.get("apply"):
        require_explicit_doctrine(options, "references decide-site-sections --apply")
    tenant_id = tenant_id_from_options(options)
    config_path = options.get("config") if isinstance(options.get("config"), str) else None
    steering_config = require_steering_config(config_path)
    if not steering_config.get("siteCyclotron"):
        raise ValueError("This publication's steering config has no siteCyclotron block; see docs/cyclotron-priming.md.")
    steering_config = tenant_site_cyclotron_steering(steering_config, tenant_id)
    doctrine_file = options.get("doctrine") if isinstance(options.get("doctrine"), str) else None
    doctrine_choice = describe_doctrine_choice(doctrine_file)
    doctrine = load_publication_doctrine_seed(doctrine_file)["doctrine"]
    if tenant_id:
        client, _ = create_authoring_client(tenant_id)
        sections = newsroom_sections_of_tenant(client, tenant_id)
    else:
        sections_file = options.get("sections-file") if isinstance(options.get("sections-file"), str) \
            else default_sections_path(config_path)
        sections = load_newsroom_section_seeds(sections_file)
        client, _ = create_authoring_client()
    max_count = int(options["max-count"]) if options.get("max-count") not in (None, True) else None
    worker = options.get("worker") if isinstance(options.get("worker"), str) else f"{socket.gethostname()}:{os.getpid()}"
    try:
        result = run_decide_site_sections(client, steering_config, doctrine, sections, apply=bool(options.get("apply")),
                                          worker=worker, max_count=max_count)
    except CyclotronClaimed as error:
        raise SystemExit(f"references\tdecide-site-sections\terror\t{error}") from error
    if options.get("json"):
        print(json.dumps({**result.to_json(), "doctrine": doctrine_choice}, indent=2, sort_keys=True))
        return
    action = "apply" if result.applied else "dry-run"
    kind = "default" if doctrine_choice["isDefault"] else "explicit"
    print(f"references\tdecide-site-sections\tdoctrine\t{kind}\t{doctrine_choice['path']}\t{doctrine_choice['firstMissionLine']}")
    print(f"references\tdecide-site-sections\t{action}\tpending\t{len(result.pending)}")
    if result.applied:
        print(f"references\tdecide-site-sections\tdecided\t{result.decided}")
        print(f"references\tdecide-site-sections\treviews-sent\t{result.reviews}")
        print(f"references\tdecide-site-sections\tprimed\t{result.primed_from_human_reviews}")
    for warning in result.warnings:
        print(f"references\tdecide-site-sections\twarning\t{warning}")
