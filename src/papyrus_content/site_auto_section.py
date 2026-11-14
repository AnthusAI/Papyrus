"""The automatic Section of an accepted Reference (docs/reference-auto-section.md).

When a Reference is accepted it is given a Section from the site's own Section list, by the site cyclotron's section selector (the same Jev decision
model and the same teach-from-editors loop as every site cyclotron classifier; its Sections and their rubrics come from the site's ``NewsroomSection``
records). A Section is set only when the selector is confident enough, and "confident enough" is learned per site from held-out editor choices:

* **Held-out evidence.** The approved Section proof (``references prove-site-sections``, ``cyclotron-section-proof/v1``) cross-validates the
  selector: every Reference an editor placed in a Section is decided once by a cyclotron taught only by the other folds. Its ``calibration`` holds one
  (confidence, agreed with the editor) pair per held-out Reference, and nothing else.
* **Learned threshold.** The threshold is the smallest confidence whose held-out decisions at or above it agree with the editors with a Wilson 95%
  lower bound of at least the target precision (``siteCyclotron.autoSection.precision``, default 0.9), the rule the automatic accept uses
  (``auto_accept.learn_threshold``). With too little or too disagreeing evidence there is no threshold and nothing is set; the reason is reported.
* **Never a guess.** Below the threshold no Section is set. A Section the machine set and whose basis no longer holds (a new decision below the
  threshold) is cleared by the machine; a person's never is.
* **People win.** A Section a person set, or a person's clear, is never changed (``person_owns_section``); the site function enforces the same rule.
  The machine's tag is recorded as ``auto:cyclotron`` with actor kind ``cyclotron``, its evidence as the reason and the selector decision it acted on,
  so editors see it and change or clear it like any automatic accept, and it never teaches the cyclotron.

Two entry points share one phase (``auto_section_phase``): the site sweep (``references decide-site-sections --apply``), which tags the References
accepted since its last pass (the on-accept path), and ``references auto-section``, the backfill. Both select from the accepted-status index, newest
first, and stop at the stored watermark; only a first pass (or ``--all``) reads the whole accepted partition, a named sweep.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .auto_accept import learn_threshold
from .catalog import _record
from .ids import knowledge_corpus_id, safe_id
from .reference_vote import CYCLOTRON

AUTO_SECTION_ACTOR = "auto:cyclotron"
STATE_PAYLOAD_KIND = "cyclotron-auto-section"
STATE_SCHEMA = "cyclotron-auto-section/v1"
ACCEPTED_INDEX = "referencesByCurationStatusKey"

MACHINE_SET_SECTION_MUTATION = """
mutation SetReferenceSectionAutomatically($referenceId: ID!, $sectionId: ID, $decisionRelationId: ID, $machineReason: String) {
  setReferenceSection(referenceId: $referenceId, sectionId: $sectionId, decisionRelationId: $decisionRelationId, machineReason: $machineReason) {
    ok
    referenceId
    sectionId
    previousSectionId
    changed
    status
    actorKind
    skipped
  }
}
"""


# --- the rules ------------------------------------------------------------------------------------------------------------------


def person_owns_section(reference: Mapping[str, Any]) -> bool:
    """True when someone other than the machine set or cleared the Reference's Section (the site function's ``personOwnsSection``).

    A person's set or clear records their actor kind; a section recorded with an accept before the actor kind existed has a section id and no kind,
    and is a person's too. Only a Section nobody touched, or one the machine set, may be changed by the machine.
    """
    kind = str(reference.get("curationSectionActorKind") or "").strip()
    if kind == CYCLOTRON:
        return False
    return bool(kind or str(reference.get("curationSectionId") or "").strip() or str(reference.get("curationSectionUpdatedBy") or "").strip())


def why_not_eligible(reference: Mapping[str, Any]) -> str | None:
    """Why the machine may not set this Reference's Section, or None when it may."""
    if reference.get("versionState", "current") != "current":
        return "not the current version"
    if reference.get("curationStatus") != "accepted":
        return "not accepted"
    if person_owns_section(reference):
        return "a person set or cleared its section"
    return None


def _metadata(relation: Mapping[str, Any]) -> dict[str, Any]:
    value = relation.get("metadata")
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def selector_decision(relations: Iterable[Mapping[str, Any]], reference: Mapping[str, Any], selector_id: str) -> Mapping[str, Any] | None:
    """The current decision of the site's current section selector about this version of the Reference, or None (never decided, decided about an
    older version, or decided by a selector for a Section list that has since changed)."""
    from .site_sweep import SITE_DECISION_RELATION

    lineage_id = reference.get("lineageId") or reference.get("id")
    for relation in relations:
        if (relation.get("predicate") == SITE_DECISION_RELATION and relation.get("relationState") == "current"
                and relation.get("subjectLineageId") == lineage_id and _metadata(relation).get("classifier") == selector_id
                and int(relation.get("subjectVersionNumber") or 0) == int(reference.get("versionNumber") or 0)):
            return relation
    return None


def calibration_from_proof(report: Mapping[str, Any] | None, *, model_identity: str | None, precision: float,
                           selector_id: str | None = None) -> dict[str, Any]:
    """The threshold learned from an approved Section proof's held-out selector decisions, or ``{"threshold": None, "reason"}``."""
    from .section_proof import SECTION_CALIBRATION_SCHEMA, SECTION_PROOF_SCHEMA

    if not report:
        return {"threshold": None, "reason": "no approved Section proof: run `papyrus references prove-site-sections --apply` and name its report in "
                                             "siteCyclotron.autoSection.proofPath"}
    if report.get("schema") != SECTION_PROOF_SCHEMA or report.get("dryRun"):
        return {"threshold": None, "reason": f"the Section proof is not a {SECTION_PROOF_SCHEMA} report that was run"}
    if model_identity and report.get("decisionModel") and report["decisionModel"] != model_identity:
        return {"threshold": None, "reason": f"the Section proof measured {report['decisionModel']}, but the cyclotron decides with {model_identity}; "
                                             "run the proof again"}
    proven_selector = (report.get("selector") or {}).get("classifierId")
    if selector_id and proven_selector and proven_selector != selector_id:
        return {"threshold": None, "reason": f"the Section proof measured {proven_selector}, a selector for another Section list than the site's "
                                             f"({selector_id}); run the proof again"}
    calibration = (report.get("selector") or {}).get("calibration") or {}
    if calibration.get("schema") != SECTION_CALIBRATION_SCHEMA or not calibration.get("pairs"):
        reason = (report.get("selector") or {}).get("reason") or "the Section proof holds no held-out selector decisions"
        return {"threshold": None, "reason": f"no calibration: {reason}"}
    pairs = [(float(confidence), bool(agreed)) for confidence, agreed in calibration["pairs"]]
    learned = learn_threshold(pairs, precision)
    if learned["threshold"] is None:
        learned["reason"] = learned["reason"].replace("editor votes on positive verdicts", "held-out editor Section choices")
    return {**learned, "heldOut": len(pairs), "proofId": report.get("proofId"), "decisionModel": report.get("decisionModel"),
            "targetPrecision": precision}


def reason_text(*, section_title: str, confidence: float, learned: Mapping[str, Any], relation: Mapping[str, Any]) -> str:
    metadata = _metadata(relation)
    return (f"Section set automatically by the site cyclotron's section selector ({metadata.get('cyclotronId')}, model version "
            f"{relation.get('modelVersion') or metadata.get('version')}): {confidence:.1%} sure this belongs in {section_title}, at or above the "
            f"{learned['threshold']:.1%} learned from {learned['heldOut']} held-out editor Section choices (the {learned['votes']} at or above it agreed "
            f"{learned['rate']:.1%}, 95% lower bound {learned['lowerBound']:.1%}, target {learned['targetPrecision']:.0%}; proof {learned.get('proofId')}). "
            "An editor can change or clear it.")


def proposal_for(reference: Mapping[str, Any], relation: Mapping[str, Any], learned: Mapping[str, Any],
                 sections_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """What the machine does with one eligible Reference given its current selector decision: ``set``, ``clear``, ``unchanged`` or ``leave``."""
    metadata = _metadata(relation)
    label = str(metadata.get("label") or "")
    probabilities = metadata.get("probabilities") or {}
    confidence = relation.get("confidence")
    if confidence is None:
        confidence = probabilities.get(label)
    confidence = float(confidence) if isinstance(confidence, (int, float)) else None
    section = sections_by_id.get(label)
    current = str(reference.get("curationSectionId") or "") or None
    machine_tagged = reference.get("curationSectionActorKind") == CYCLOTRON and current is not None
    confident = confidence is not None and learned.get("threshold") is not None and confidence >= learned["threshold"]
    top = sorted(((str(key), float(value)) for key, value in probabilities.items() if isinstance(value, (int, float))), key=lambda pair: -pair[1])[:3]
    base = {"referenceId": reference["id"], "lineageId": reference.get("lineageId") or reference["id"], "title": reference.get("title"),
            "medium": reference.get("medium"), "currentSectionId": current, "suggestedSectionId": label or None,
            "sectionTitle": (section or {}).get("title") or (section or {}).get("shortTitle"), "confidence": confidence,
            "threshold": learned.get("threshold"), "decisionRelationId": relation.get("id"), "modelVersion": relation.get("modelVersion"),
            "classifier": metadata.get("classifier"), "topProbabilities": [{"sectionId": key, "probability": round(value, 4)} for key, value in top]}
    if confident and section is not None:
        same = current == label and reference.get("curationSectionDecisionRelationId") == relation.get("id")
        return {**base, "action": "unchanged" if same else "set", "sectionId": label,
                "reason": reason_text(section_title=base["sectionTitle"] or label, confidence=confidence, learned=learned, relation=relation)}
    why = ("the suggested Section is not an enabled Section" if confident else
           f"below the learned threshold ({confidence:.1%} < {learned['threshold']:.1%})" if confidence is not None else "the decision has no confidence")
    if machine_tagged:
        return {**base, "action": "clear", "sectionId": None,
                "reason": f"Section cleared automatically: the site cyclotron's newest decision no longer supports it ({why})."}
    return {**base, "action": "leave", "sectionId": None, "reason": why}


def apply_proposal(client, proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Send one ``set`` or ``clear`` to the site function's automatic lane. It refuses quietly when a person owns the Section by now."""
    answer = client.graphql(MACHINE_SET_SECTION_MUTATION, {
        "referenceId": proposal["referenceId"], "sectionId": proposal.get("sectionId"),
        "decisionRelationId": proposal["decisionRelationId"], "machineReason": proposal["reason"]})
    saved = answer.get("setReferenceSection")
    if not isinstance(saved, Mapping) or not saved.get("ok"):
        raise RuntimeError(f"The automatic section was not saved for {proposal['lineageId']}.")
    return dict(saved)


# --- the watermark: what the last completed pass covered ------------------------------------------------------------------------


def state_payload_id(cyclotron_id: str) -> str:
    return f"knowledge-raw-payload-cyclotron-auto-section-{safe_id(cyclotron_id)}"


def state_record(cyclotron_id: str, state: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    return _record("KnowledgeRawPayload", {
        "id": state_payload_id(cyclotron_id), "ownerType": "cyclotron", "ownerId": safe_id(cyclotron_id), "payloadKind": STATE_PAYLOAD_KIND,
        "createdAt": now, "updatedAt": now, "payload": json.dumps({"schema": STATE_SCHEMA, **dict(state)}, sort_keys=True)})


def recorded_state(client, cyclotron_id: str) -> dict[str, Any] | None:
    from .relevance_sweep import _latest_payload

    for record in client.list_by_index("knowledgeRawPayloadsByOwner", safe_id(cyclotron_id)):
        if record.get("payloadKind") == STATE_PAYLOAD_KIND:
            return _latest_payload(client, record)
    return None


def candidates(client, corpus_id: str, *, since: str | None) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    """The accepted References the machine may give a Section, newest first, stopping at ``since`` (the last completed pass).

    Returns (candidates, skipped by reason, rows read). Reads the accepted-status index one page at a time; without ``since`` it reads the whole
    accepted partition (the named first sweep).
    """
    found: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    read = 0
    for row in client.iterate_newest_first(ACCEPTED_INDEX, f"{corpus_id}#accepted"):
        if since and str(row.get("updatedAt") or "") <= since:
            break
        read += 1
        reason = why_not_eligible(row)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        found.append(dict(row))
    return found, skipped, read


# --- the phase both entry points run ---------------------------------------------------------------------------------------------


@dataclass
class AutoSectionResult:
    dry_run: bool
    scope: str
    calibration: dict[str, Any] = field(default_factory=dict)
    read: int = 0
    candidates: int = 0
    decided: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    stopped_because: str | None = None
    warnings: list[str] = field(default_factory=list)
    watermark: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"dryRun": self.dry_run, "scope": self.scope, "calibration": self.calibration, "read": self.read, "candidates": self.candidates,
                "decided": self.decided, "counts": self.counts, "skipped": self.skipped, "proposals": self.proposals,
                "stoppedBecause": self.stopped_because, "warnings": self.warnings, "watermark": self.watermark}


def auto_section_phase(client, site, plan, *, references: Sequence[Mapping[str, Any]], learned: Mapping[str, Any],
                       sections: Sequence[Mapping[str, Any]], result: AutoSectionResult, now: Callable[[], str],
                       decisions_allowed: int | None) -> None:
    """Decide each candidate the selector has not decided in this version (one ``decide``), then set, clear or leave its Section."""
    from .relevance_sweep import _apply, reference_item
    from .site_cyclotron import enabled_sections_in_order, section_selector_classifier_id
    from .site_sweep import _site_decision_relations, site_decision_records

    enabled = enabled_sections_in_order(sections)
    sections_by_id = {str(section["id"]): section for section in enabled}
    selector_id = section_selector_classifier_id([str(section["id"]) for section in enabled])
    for reference in references:
        relations = _site_decision_relations(client, reference["lineageId"])
        relation = selector_decision(relations, reference, selector_id)
        if relation is None:
            if decisions_allowed is not None and result.decided >= decisions_allowed:
                result.stopped_because = "daily decision cap"
                result.warnings.append(f"{plan.definition.id} reached its daily decision cap; the next pass carries on.")
                break
            try:
                decision = asyncio.run(site.cyclotron.decide(site.model.prepare(reference_item(reference))))
            except ValueError as error:
                result.warnings.append(f"{reference['lineageId']}: {error}")
                continue
            records = site_decision_records(
                reference, decision.to_json(), cyclotron_id=plan.definition.id, classifier_questions=site.questions,
                classifier_labels=site.labels, classifier_positive_labels=site.positive_labels, now=now(),
                current_relations=relations, review_control=plan.review_control, provenance=site.provenance)
            if not result.dry_run:
                _apply(client, records)
            result.decided += 1
            relation = selector_decision([record["expected"] for record in records if record["modelName"] == "SemanticRelation"],
                                         reference, selector_id)
            if relation is None:
                result.warnings.append(f"{reference['lineageId']}: the decision has no section-selector answer.")
                continue
        proposal = proposal_for(reference, relation, learned, sections_by_id)
        if not result.dry_run and proposal["action"] in ("set", "clear"):
            saved = apply_proposal(client, proposal)
            if saved.get("skipped"):
                proposal = {**proposal, "action": "skipped", "reason": str(saved["skipped"])}
        result.counts[proposal["action"]] = result.counts.get(proposal["action"], 0) + 1
        result.proposals.append(proposal)


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_proof(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    from .env import PAPYRUS_ROOT

    candidate = Path(path)
    for resolved in (candidate, Path.cwd() / candidate, PAPYRUS_ROOT / candidate):
        if resolved.is_file():
            return json.loads(resolved.read_text(encoding="utf-8"))
    raise ValueError(f"siteCyclotron.autoSection.proofPath names {path}, which does not exist.")


def _selector_id(sections: Sequence[Mapping[str, Any]]) -> str:
    from .site_cyclotron import enabled_sections_in_order, section_selector_classifier_id

    return section_selector_classifier_id([str(section["id"]) for section in enabled_sections_in_order(sections)])


def _model_identity(plan, model) -> str | None:
    if model is not None:
        return getattr(model, "model_identity", None)
    from .relevance_cyclotron import decision_model_identity

    return decision_model_identity(plan)


def auto_section_in_sweep(client, site, plan, steering_config: Mapping[str, Any], *, corpus_id: str, sections: Sequence[Mapping[str, Any]],
                          now: Callable[[], str], decisions_allowed: int | None) -> dict[str, Any]:
    """The on-accept path: inside a writing site sweep, give a Section to the References accepted since the last pass."""
    policy = steering_config["siteCyclotron"].get("autoSection") or {}
    result = AutoSectionResult(dry_run=False, scope="changed")
    if not policy.get("enabled", True):
        result.stopped_because = "disabled"
        return result.to_json()
    learned = calibration_from_proof(_load_proof(policy.get("proofPath")), model_identity=getattr(site.model, "model_identity", None),
                                     precision=policy.get("precision", 0.9), selector_id=_selector_id(sections))
    result.calibration = learned
    if learned.get("threshold") is None:
        result.stopped_because = "no learned threshold"
        return result.to_json()
    _run(client, site, plan, learned=learned, sections=sections, corpus_id=corpus_id, result=result, now=now, decisions_allowed=decisions_allowed,
         since=(recorded_state(client, plan.definition.id) or {}).get("watermark"))
    return result.to_json()


def _run(client, site, plan, *, learned, sections, corpus_id, result: AutoSectionResult, now, decisions_allowed, since: str | None) -> None:
    from .relevance_sweep import _apply

    started = now()
    found, result.skipped, result.read = candidates(client, corpus_id, since=since)
    result.candidates = len(found)
    if found:
        auto_section_phase(client, site, plan, references=found, learned=learned, sections=sections, result=result, now=now,
                           decisions_allowed=decisions_allowed)
    if not result.dry_run and result.stopped_because is None:
        # Only a pass that reached the end moves the watermark; an interrupted one is carried on by the next, which repeats no decision and no write.
        result.watermark = started
        _apply(client, [state_record(plan.definition.id, {"watermark": started, "threshold": learned.get("threshold"),
                                                            "heldOut": learned.get("heldOut"), "proofId": learned.get("proofId"),
                                                            "counts": result.counts}, now=now())])


def run_auto_section(client, steering_config: Mapping[str, Any], doctrine: Sequence[Mapping[str, Any]], sections: Sequence[Mapping[str, Any]], *,
                     dry_run: bool, worker: str, scope: str = "changed", model=None, optimizer=None, snapshots=None,
                     now: Callable[[], str] | None = None) -> AutoSectionResult:
    """The backfill and the by-hand pass: the same phase as the sweep, on its own.

    ``scope`` ``changed`` starts after the last completed pass (all of the accepted partition the first time); ``all`` reads the whole accepted
    partition. A dry run decides in a throwaway copy of the store and writes nothing to the site, the bucket or the store.
    """
    from .relevance_sweep import S3SnapshotStore, _apply, _recorded_usage
    from .relevance_shadow import decisions_remaining_today, usage_record, utc_day
    from .site_classifier_set import plan_site_classifier_set
    from .site_cyclotron import build_site_cyclotron, enabled_sections_in_order
    from .site_sweep import _stored_site_specs, opened_site_cyclotron
    from .relevance_sweep import SNAPSHOT_NAME, SweepResult
    from .steering import require_corpus_config

    now = now or _now_text
    plan = build_site_cyclotron(steering_config, sections)
    policy = steering_config["siteCyclotron"].get("autoSection") or {}
    result = AutoSectionResult(dry_run=dry_run, scope=scope)
    if not plan.enabled or not policy.get("enabled", True):
        result.stopped_because = "disabled"
        result.warnings.append(f"{plan.definition.id} or its autoSection is switched off in the steering config; nothing was decided.")
        return result
    learned = calibration_from_proof(_load_proof(policy.get("proofPath")), model_identity=_model_identity(plan, model),
                                     precision=policy.get("precision", 0.9), selector_id=_selector_id(sections))
    result.calibration = learned
    if learned.get("threshold") is None:
        result.stopped_because = "no learned threshold"
        result.warnings.append(f"No Section is set: {learned['reason']}.")
        return result
    corpus = require_corpus_config(dict(steering_config), steering_config["canonicalTopicSet"]["corpusKey"], "canonicalTopicSet.corpusKey")
    corpus_id = knowledge_corpus_id(corpus)
    since = (recorded_state(client, plan.definition.id) or {}).get("watermark") if scope == "changed" else None
    today = utc_day(now())
    usage = _recorded_usage(client, plan.definition.id)
    allowed = decisions_remaining_today(usage, maximum_per_day=plan.max_decisions_per_day, today=today)
    snapshots = snapshots if snapshots is not None else (S3SnapshotStore() if plan.s3_prefix else None)
    snapshot_uri = f"{plan.s3_prefix.rstrip('/')}/{SNAPSHOT_NAME}" if plan.s3_prefix else None
    set_plan = plan_site_classifier_set(_stored_site_specs(Path(plan.local_path), snapshots, snapshot_uri), plan.definition.classifiers)
    enabled_section_ids = [str(section["id"]) for section in enabled_sections_in_order(sections)]
    sweep_result = SweepResult(applied=not dry_run)
    with opened_site_cyclotron(client, plan, steering_config, sections, doctrine, corpus_id=corpus_id, enabled_section_ids=enabled_section_ids,
                               set_plan=set_plan, worker=worker, model=model, optimizer=optimizer, snapshots=snapshots, now=now,
                               result=sweep_result, scratch=dry_run) as site:
        _run(client, site, plan, learned=learned, sections=sections, corpus_id=corpus_id, result=result, now=now, decisions_allowed=allowed,
             since=since)
        if not dry_run and plan.max_decisions_per_day is not None and result.decided:
            used = usage["decisions"] if usage and usage.get("day") == today else 0
            _apply(client, [usage_record(plan.definition.id, day=today, decisions=used + result.decided, now=now())])
    result.warnings.extend(sweep_result.warnings)
    return result


# --- the command -----------------------------------------------------------------------------------------------------------------


def format_lines(result: AutoSectionResult) -> list[str]:
    """The tab-separated lines the command prints: the calibration, one line per proposal, then the counts."""
    prefix = "references\tauto-section"
    calibration = result.calibration
    lines = [f"{prefix}\t{'dry-run' if result.dry_run else 'apply'}\tscope\t{result.scope}"]
    if calibration.get("threshold") is not None:
        lines.append(f"{prefix}\tthreshold\t{calibration['threshold']:.4f}\theld-out {calibration['heldOut']}\tagreement {calibration['rate']:.1%}"
                     f"\tlower bound {calibration['lowerBound']:.1%}\ttarget {calibration['targetPrecision']:.0%}\tproof {calibration.get('proofId')}")
    elif calibration:
        lines.append(f"{prefix}\tthreshold\tnone\t{calibration.get('reason')}")
    for proposal in result.proposals:
        confidence = "" if proposal.get("confidence") is None else f"{proposal['confidence']:.1%}"
        lines.append(f"{prefix}\t{proposal['action']}\t{proposal['lineageId']}\t{proposal.get('suggestedSectionId') or '(none)'}\t{confidence}"
                     f"\t{proposal.get('title') or ''}\t{proposal['reason']}")
    lines.append(f"{prefix}\tcounts\tread {result.read}\tcandidates {result.candidates}\tdecided {result.decided}\t"
                 + "\t".join(f"{key} {value}" for key, value in sorted(result.counts.items())))
    for reason, count in sorted(result.skipped.items()):
        lines.append(f"{prefix}\tnot-eligible\t{count}\t{reason}")
    if result.stopped_because:
        lines.append(f"{prefix}\tstopped\t{result.stopped_because}")
    lines.extend(f"{prefix}\twarning\t{warning}" for warning in result.warnings)
    return lines


def references_auto_section(flags: list[str]) -> None:
    """papyrus references auto-section [--config <steering.yml>] [--doctrine <doctrine.yml>] [--all] [--worker <name>] [--dry-run] [--json]

    Writes by default: gives each accepted Reference with no Section (and no person's clear) the Section the site cyclotron's selector chose, when
    it is at least as confident as the threshold learned from the approved Section proof. ``--dry-run`` decides in a throwaway copy of the store
    and prints what it would set, with the model's confidence and the evidence, writing nothing. ``--all`` reads the whole accepted partition
    instead of starting after the last completed pass. The Sections are the site's ``NewsroomSection`` records.
    """
    import os
    import socket

    from .graphql_authoring import create_authoring_client
    from .newsroom_doctrine import load_publication_doctrine_seed, require_explicit_doctrine
    from .options import parse_options
    from .reference_section import sections_of
    from .steering import require_steering_config

    options = parse_options(flags)
    dry_run = bool(options.get("dry-run"))
    if not dry_run:
        require_explicit_doctrine(options, "references auto-section")
    config_path = options.get("config") if isinstance(options.get("config"), str) else None
    steering_config = require_steering_config(config_path)
    if not steering_config.get("siteCyclotron"):
        raise ValueError("This publication's steering config has no siteCyclotron block; see docs/reference-auto-section.md.")
    doctrine_file = options.get("doctrine") if isinstance(options.get("doctrine"), str) else None
    doctrine = load_publication_doctrine_seed(doctrine_file)["doctrine"]
    client, _ = create_authoring_client()
    sections = [{**row, "enabled": row.get("enabled") is not False and row.get("enabledStatus") != "disabled"} for row in sections_of(client)]
    worker = options.get("worker") if isinstance(options.get("worker"), str) else f"{socket.gethostname()}:{os.getpid()}"
    result = run_auto_section(client, steering_config, doctrine, sections, dry_run=dry_run, worker=worker,
                              scope="all" if options.get("all") else "changed")
    if options.get("json"):
        print(json.dumps(result.to_json(), indent=2, sort_keys=True))
        return
    for line in format_lines(result):
        print(line)
