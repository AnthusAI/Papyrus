"""The site cyclotron: one shared cyclotron with a classifier per Section and a Section selector.

Each enabled newsroom Section has a binary classifier that answers whether a
Reference fits that Section, and one multi-class classifier chooses the
Section for a Reference. The classifier set is derived from the Section list,
never configured by hand, so Section curation stays the single place the list
is maintained. The model, optimizer and review program come from the
publication's ``relevanceCyclotron`` block, and the Section classifiers learn
only from the explicit Section decisions of people.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from .ids import safe_id
from .relevance_cyclotron import FIELD as RELEVANCE_FIELD
from .learning_classifiers import (LINK_CLASSIFIER_ID, LINK_LABELS, LINK_POSITIVE_LABEL, LINK_QUESTION, PACK_CLASSIFIER_ID, PACK_LABELS,
                                   PACK_POSITIVE_LABEL, PACK_QUESTION, learning_seed_rubrics)
from .relevance_cyclotron import RelevanceCyclotronPlan, _refuse_secrets, _string

FIELD = "siteCyclotron"
SECTION_FIT_LABELS = ("fits", "does-not-fit")
SECTION_FIT_POSITIVE_LABEL = "fits"
SECTION_SELECTOR_CLASSIFIER_PREFIX = "section-selector-"
SECTION_FIT_CLASSIFIER_PREFIX = "section-fit-"
SECTION_SELECTOR_QUESTION = "Which newsroom Section is the best home for this candidate source?"
SITE_CYCLOTRON_FIELDS = {"cyclotronId", "enabled", "maxDecisionsPerDay", "approvedProofPath", "store"}


def normalize_site_cyclotron_config(raw: Any, relevance_block: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Validate the steering config's ``siteCyclotron`` block; None when absent."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{FIELD} must be an object.")
    if relevance_block is None:
        raise ValueError(f"{FIELD} needs a {RELEVANCE_FIELD} block: it reuses its decision model, optimizer and review program.")
    _refuse_secrets(raw, FIELD)
    unknown = sorted(set(raw) - SITE_CYCLOTRON_FIELDS)
    if unknown:
        raise ValueError(f"{FIELD} has unknown fields: {', '.join(unknown)}.")
    cyclotron_id = _string(raw.get("cyclotronId", f"{relevance_block['cyclotronId']}-sections"), f"{FIELD}.cyclotronId")
    if cyclotron_id == relevance_block["cyclotronId"]:
        raise ValueError(f"{FIELD}.cyclotronId must differ from {RELEVANCE_FIELD}.cyclotronId.")
    enabled = raw.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError(f"{FIELD}.enabled must be true or false.")
    maximum_per_day = raw.get("maxDecisionsPerDay")
    if maximum_per_day is not None and (type(maximum_per_day) is not int or maximum_per_day < 1):
        raise ValueError(f"{FIELD}.maxDecisionsPerDay must be a positive integer.")
    approved_proof_path = raw.get("approvedProofPath")
    if approved_proof_path is not None and (not isinstance(approved_proof_path, str) or not approved_proof_path.strip()):
        raise ValueError(f"{FIELD}.approvedProofPath must be a file path.")
    store = raw.get("store") or {}
    if not isinstance(store, dict) or set(store) - {"localPath", "s3Prefix"}:
        raise ValueError(f"{FIELD}.store fields are localPath and s3Prefix.")
    s3_prefix = store.get("s3Prefix")
    if s3_prefix is not None and (not isinstance(s3_prefix, str) or not s3_prefix.startswith("s3://")):
        raise ValueError(f"{FIELD}.store.s3Prefix must be an s3:// prefix in the private media bucket.")
    return {
        "cyclotronId": cyclotron_id,
        "enabled": enabled,
        "maxDecisionsPerDay": maximum_per_day,
        "approvedProofPath": approved_proof_path,
        "store": {"localPath": _string(store.get("localPath", f"var/cyclotrons/{cyclotron_id}"), f"{FIELD}.store.localPath"),
                  "s3Prefix": s3_prefix},
    }


def tenant_site_cyclotron_steering(steering_config: Mapping[str, Any], tenant_id: str | None) -> Mapping[str, Any]:
    """The steering config with the site cyclotron's id, local store and S3 prefix made the tenant's own.

    Everything keyed by the cyclotron id (the sweep Assignment, the
    ``site_decision_is`` classifier keys, the usage and agreement records)
    follows from the scoped id. The relevance block and the approved proof
    stay shared. Without a tenant the steering config is returned untouched.
    """
    if not tenant_id:
        return steering_config
    site_block = steering_config.get(FIELD)
    if not site_block:
        raise ValueError(f"This publication's steering config has no {FIELD} block.")
    store = site_block["store"]
    scoped_store = {"localPath": f"{store['localPath'].rstrip('/')}-{tenant_id}",
                    "s3Prefix": f"{store['s3Prefix'].rstrip('/')}-{tenant_id}" if store.get("s3Prefix") else None}
    scoped_block = {**site_block, "cyclotronId": f"{site_block['cyclotronId']}-{tenant_id}", "store": scoped_store}
    return {**steering_config, FIELD: scoped_block}


def newsroom_sections_of_tenant(client, tenant_id: str) -> list[dict[str, Any]]:
    """The tenant's own Section rows, read through its tenant-scoped client."""
    sections = [dict(row) for row in client.list_records("NewsroomSection")]
    if not sections:
        raise ValueError(f"Tenant {tenant_id} has no newsroom Sections; run `papyrus newsroom import-sections --tenant {tenant_id}` first.")
    return sections


def enabled_sections_in_order(sections: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    enabled = [section for section in sections if section.get("enabled", True)]
    return sorted(enabled, key=lambda section: (int(section.get("sortOrder") or 0), str(section["id"])))


def section_fit_classifier_id(section_id: str) -> str:
    return f"{SECTION_FIT_CLASSIFIER_PREFIX}{safe_id(section_id)}"


def section_selector_classifier_id(section_ids: Sequence[str]) -> str:
    """The selector's id names its Section set, because a classifier's labels can never change once it exists."""
    fingerprint = hashlib.sha256("\n".join(sorted(section_ids)).encode("utf-8")).hexdigest()[:8]
    return f"{SECTION_SELECTOR_CLASSIFIER_PREFIX}{fingerprint}"


def is_section_selector_classifier_id(classifier_id: str) -> bool:
    return classifier_id.startswith(SECTION_SELECTOR_CLASSIFIER_PREFIX)


def section_fit_question(section: Mapping[str, Any]) -> str:
    return f"Does this candidate source belong in the {section['id']} section?"


def section_seed_rubric(section: Mapping[str, Any]) -> str:
    lines = [f"Section: {section['title']}", f"Mission: {section['editorialMission']}",
             f"Policy: {section['editorialPolicy']}"]
    if section.get("assignmentGuidance"):
        lines.append(f"Assignment guidance: {section['assignmentGuidance']}")
    if section.get("killCriteria"):
        lines.append(f"Reject when: {section['killCriteria']}")
    return "\n".join(lines)


def selector_seed_rubric(sections: Sequence[Mapping[str, Any]]) -> str:
    descriptions = [f"- {section['id']}: {section['title']}. {section['editorialMission']}" for section in sections]
    return "Choose the one Section whose mission fits best:\n" + "\n".join(descriptions)


def learning_classifier_specs() -> list[Any]:
    """The two learning classifiers, derived like the Section classifiers: nothing to configure. They learn only from decisions people made."""
    from decision_flywheel import ClassifierSpec

    return [ClassifierSpec(LINK_CLASSIFIER_ID, LINK_LABELS, LINK_QUESTION, positive_label=LINK_POSITIVE_LABEL),
            ClassifierSpec(PACK_CLASSIFIER_ID, PACK_LABELS, PACK_QUESTION, positive_label=PACK_POSITIVE_LABEL)]


def site_classifier_specs(sections: Sequence[Mapping[str, Any]], include_learning: bool = False) -> list[Any]:
    """The Section classifiers and selector; with ``include_learning`` also ``reference-link-fit`` and ``idea-pack-fit``.

    The sweep decides every classifier of the definition on each pending Reference, so it keeps the Section-only set until it can skip the
    learning classifiers."""
    from decision_flywheel import ClassifierSpec

    ordered = enabled_sections_in_order(sections)
    if not ordered:
        raise ValueError("The site cyclotron needs at least one enabled Section.")
    specs = [ClassifierSpec(section_fit_classifier_id(section["id"]), SECTION_FIT_LABELS, section_fit_question(section),
                            positive_label=SECTION_FIT_POSITIVE_LABEL) for section in ordered]
    if len(ordered) >= 2:
        selector_labels = tuple(sorted(str(section["id"]) for section in ordered))
        specs.append(ClassifierSpec(section_selector_classifier_id(selector_labels), selector_labels,
                                    SECTION_SELECTOR_QUESTION))
    return specs + learning_classifier_specs() if include_learning else specs


def build_site_cyclotron(steering_config: Mapping[str, Any], sections: Sequence[Mapping[str, Any]],
                         include_learning: bool = False) -> RelevanceCyclotronPlan:
    """Build the site cyclotron's plan from the steering config and the current Section list. No model call."""
    from decision_flywheel import CyclotronDefinition, ReviewProgram

    from .relevance_cyclotron import REVIEW_PROGRAM_FIELDS

    site_block = steering_config.get(FIELD)
    relevance_block = steering_config.get(RELEVANCE_FIELD)
    if not site_block:
        raise ValueError(f"This publication's steering config has no {FIELD} block.")
    if not relevance_block:
        raise ValueError(f"This publication's steering config has no {RELEVANCE_FIELD} block.")
    ordered = enabled_sections_in_order(sections)
    specs = site_classifier_specs(sections, include_learning)
    seed_rubrics = {section_fit_classifier_id(section["id"]): section_seed_rubric(section) for section in ordered}
    if len(ordered) >= 2:
        seed_rubrics[section_selector_classifier_id([str(section["id"]) for section in ordered])] = selector_seed_rubric(ordered)
    if include_learning:
        seed_rubrics.update(learning_seed_rubrics())
    definition = CyclotronDefinition(site_block["cyclotronId"], tuple(specs), seed=f"{site_block['cyclotronId']}-v1")
    program = ReviewProgram(**{REVIEW_PROGRAM_FIELDS[key]: (tuple(value) if key == "rates" else value)
                               for key, value in relevance_block["reviewProgram"].items()})
    return RelevanceCyclotronPlan(definition, seed_rubrics, program, dict(relevance_block["decisionModel"]),
                                  dict(relevance_block["optimizer"]) if relevance_block["optimizer"] else None,
                                  site_block["store"]["localPath"], site_block["store"]["s3Prefix"],
                                  relevance_block["maxRequestsPerSweep"], relevance_block["reviewControl"],
                                  site_block["enabled"], site_block["maxDecisionsPerDay"],
                                  site_block["approvedProofPath"])
