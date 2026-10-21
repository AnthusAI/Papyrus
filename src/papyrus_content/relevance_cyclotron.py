"""The publication's relevance cyclotron: configuration and construction.

One installation is one publication, and it has at most one relevance
cyclotron. It decides whether a pending ``Reference`` (a candidate source)
should become a reference for this publication. The decision question and
labels are the cyclotron definition; the publication doctrine seeds the first
rubric, which the LLM optimizer may refine. Provider keys come from the
environment, never from configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

DEFAULT_QUESTION = "Should this candidate source become a reference for this publication?"
DEFAULT_DECISION_MODELS = {"jev": "jev-1.13.0"}
BATCHED_DECISION_PROVIDERS = frozenset({"jev"})
OPTIMIZER_PROVIDERS = frozenset({"openai"})
DEFAULT_OPTIMIZER = {"provider": "openai", "model": "gpt-6-luna", "maxCalls": 10}
REVIEW_PROGRAM_FIELDS = {
    "rates": "rates",
    "auditShare": "audit_share",
    "confidenceThreshold": "confidence_threshold",
    "targetAccuracy": "target_accuracy",
    "maxGapPoints": "max_gap_points",
    "window": "window",
    "windowsRequired": "windows_required",
    "calibrationWindow": "calibration_window",
    "minWindowLabels": "min_window_labels",
}
SECRET_WORDS = ("key", "token", "secret", "password", "credential")
NOT_SECRET_FIELDS = frozenset({"corpusKey"})
FIELD = "relevanceCyclotron"
DEFAULT_AUTO_REJECT = {"enabled": False, "minimumRejectProbability": 0.95, "maxRejectsPerSweep": 10}


def normalize_relevance_cyclotron_config(raw: Any) -> dict[str, Any] | None:
    """Validate the steering config's ``relevanceCyclotron`` block; None when absent."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{FIELD} must be an object.")
    _refuse_secrets(raw, FIELD)
    known = {"cyclotronId", "classifierId", "question", "labels", "positiveLabel", "decisionModel",
             "optimizer", "store", "maxRequestsPerSweep", "reviewProgram", "reviewControl", "enabled",
             "maxDecisionsPerDay", "approvedProofPath", "autoReject", "corpusKey"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"{FIELD} has unknown fields: {', '.join(unknown)}.")
    labels = raw.get("labels", ["include", "exclude"])
    if (not isinstance(labels, list) or len(labels) != 2 or len(set(labels)) != 2
            or not all(isinstance(label, str) and label.strip() for label in labels)):
        raise ValueError(f"{FIELD}.labels must be two distinct labels, for example [include, exclude].")
    positive = raw.get("positiveLabel", labels[0])
    if positive not in labels:
        raise ValueError(f"{FIELD}.positiveLabel must be one of {FIELD}.labels ({', '.join(labels)}).")
    # Thumbs fit a two-class decision with a declared positive label; per-class
    # buttons are the general case (Ryan, 2026-10-09).
    review_control = raw.get("reviewControl", "thumbs" if len(labels) == 2 and positive else "labels")
    if review_control not in ("thumbs", "labels"):
        raise ValueError(f"{FIELD}.reviewControl must be thumbs or labels.")
    decision_model = raw.get("decisionModel") or {}
    provider = _string(decision_model.get("provider", "jev"), f"{FIELD}.decisionModel.provider")
    if provider not in BATCHED_DECISION_PROVIDERS:
        raise ValueError(f"{FIELD}.decisionModel.provider must be a batched decision model "
                         f"({', '.join(sorted(BATCHED_DECISION_PROVIDERS))}); a cyclotron asks its classifiers in one request.")
    model = _string(decision_model.get("model", DEFAULT_DECISION_MODELS.get(provider, "")),
                    f"{FIELD}.decisionModel.model")
    optimizer = raw.get("optimizer", DEFAULT_OPTIMIZER)
    if optimizer is not None:
        if not isinstance(optimizer, dict):
            raise ValueError(f"{FIELD}.optimizer must be an object or null.")
        optimizer_provider = _string(optimizer.get("provider", DEFAULT_OPTIMIZER["provider"]), f"{FIELD}.optimizer.provider")
        if optimizer_provider not in OPTIMIZER_PROVIDERS:
            raise ValueError(f"{FIELD}.optimizer.provider must be one of {', '.join(sorted(OPTIMIZER_PROVIDERS))}.")
        max_calls = optimizer.get("maxCalls", DEFAULT_OPTIMIZER["maxCalls"])
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError(f"{FIELD}.optimizer.maxCalls must be a positive integer.")
        optimizer = {"provider": optimizer_provider,
                     "model": _string(optimizer.get("model", DEFAULT_OPTIMIZER["model"]), f"{FIELD}.optimizer.model"),
                     "maxCalls": max_calls}
    store = raw.get("store") or {}
    if not isinstance(store, dict):
        raise ValueError(f"{FIELD}.store must be an object.")
    cyclotron_id = _string(raw.get("cyclotronId", "papyrus-relevance"), f"{FIELD}.cyclotronId")
    s3_prefix = store.get("s3Prefix")
    if s3_prefix is not None and (not isinstance(s3_prefix, str) or not s3_prefix.startswith("s3://")):
        raise ValueError(f"{FIELD}.store.s3Prefix must be an s3:// prefix in the private media bucket.")
    max_requests = raw.get("maxRequestsPerSweep", 200)
    if type(max_requests) is not int or max_requests < 1:
        raise ValueError(f"{FIELD}.maxRequestsPerSweep must be a positive integer.")
    enabled = raw.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError(f"{FIELD}.enabled must be true or false.")
    max_decisions_per_day = raw.get("maxDecisionsPerDay")
    if max_decisions_per_day is not None and (type(max_decisions_per_day) is not int or max_decisions_per_day < 1):
        raise ValueError(f"{FIELD}.maxDecisionsPerDay must be a positive integer.")
    approved_proof_path = raw.get("approvedProofPath")
    if approved_proof_path is not None and (not isinstance(approved_proof_path, str) or not approved_proof_path.strip()):
        raise ValueError(f"{FIELD}.approvedProofPath must be a file path.")
    auto_reject = _normalize_auto_reject(raw.get("autoReject"))
    corpus_key = None if raw.get("corpusKey") is None else _string(raw["corpusKey"], f"{FIELD}.corpusKey")
    program = raw.get("reviewProgram") or {}
    if not isinstance(program, dict) or set(program) - set(REVIEW_PROGRAM_FIELDS):
        raise ValueError(f"{FIELD}.reviewProgram fields are {', '.join(REVIEW_PROGRAM_FIELDS)}.")
    return {
        "cyclotronId": cyclotron_id,
        "classifierId": _string(raw.get("classifierId", "relevant"), f"{FIELD}.classifierId"),
        "question": _string(raw.get("question", DEFAULT_QUESTION), f"{FIELD}.question"),
        "labels": list(labels),
        "positiveLabel": positive,
        "decisionModel": {"provider": provider, "model": model},
        "optimizer": optimizer,
        "store": {"localPath": _string(store.get("localPath", f"var/cyclotrons/{cyclotron_id}"), f"{FIELD}.store.localPath"),
                  "s3Prefix": s3_prefix},
        "maxRequestsPerSweep": max_requests,
        "reviewProgram": dict(program),
        "reviewControl": review_control,
        "enabled": enabled,
        "maxDecisionsPerDay": max_decisions_per_day,
        "approvedProofPath": approved_proof_path,
        "autoReject": auto_reject,
        "corpusKey": corpus_key,
    }


def _normalize_auto_reject(raw: Any) -> dict[str, Any]:
    if raw is None:
        return dict(DEFAULT_AUTO_REJECT)
    path = f"{FIELD}.autoReject"
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object.")
    unknown = sorted(set(raw) - set(DEFAULT_AUTO_REJECT))
    if unknown:
        raise ValueError(f"{path} has unknown fields: {', '.join(unknown)}.")
    enabled = raw.get("enabled", DEFAULT_AUTO_REJECT["enabled"])
    if type(enabled) is not bool:
        raise ValueError(f"{path}.enabled must be true or false.")
    minimum = raw.get("minimumRejectProbability", DEFAULT_AUTO_REJECT["minimumRejectProbability"])
    if type(minimum) not in (int, float) or not 0.5 < minimum <= 1:
        raise ValueError(f"{path}.minimumRejectProbability must be a number above 0.5 and at most 1.")
    maximum = raw.get("maxRejectsPerSweep", DEFAULT_AUTO_REJECT["maxRejectsPerSweep"])
    if type(maximum) is not int or maximum < 1:
        raise ValueError(f"{path}.maxRejectsPerSweep must be a positive integer.")
    return {"enabled": enabled, "minimumRejectProbability": float(minimum), "maxRejectsPerSweep": maximum}


def doctrine_seed_rubric(doctrine: Sequence[Mapping[str, Any]]) -> str:
    """The first rubric: the publication's mission and policies, in order."""
    titles = {"mission": "Publication mission", "policy": "Publication policies"}
    parts = []
    for kind in ("mission", "policy"):
        lines = [line.strip() for entry in doctrine if entry.get("kind") == kind
                 for line in (entry.get("body") or []) if isinstance(line, str) and line.strip()]
        if lines:
            parts.append(titles[kind] + ":\n" + "\n".join(f"- {line}" for line in lines))
    if not parts:
        raise ValueError("Publication doctrine has no mission or policy text to seed the relevance rubric.")
    return "\n\n".join(parts)


@dataclass(frozen=True)
class RelevanceCyclotronPlan:
    """Everything needed to open the publication's relevance cyclotron."""
    definition: Any
    seed_rubrics: Mapping[str, str]
    review_program: Any
    decision_model: Mapping[str, str]
    optimizer: Mapping[str, Any] | None
    local_path: str
    s3_prefix: str | None
    max_requests: int
    review_control: str = "labels"
    enabled: bool = True
    max_decisions_per_day: int | None = None
    approved_proof_path: str | None = None
    auto_reject: Mapping[str, Any] = field(default_factory=lambda: dict(DEFAULT_AUTO_REJECT))


def build_relevance_cyclotron(steering_config: Mapping[str, Any], doctrine: Sequence[Mapping[str, Any]]) -> RelevanceCyclotronPlan:
    """Build the plan from a loaded steering config and the current doctrine. No model call."""
    from decision_flywheel import ClassifierSpec, CyclotronDefinition, ReviewProgram

    block = steering_config.get(FIELD)
    if not block:
        raise ValueError(f"This publication's steering config has no {FIELD} block.")
    classifier = ClassifierSpec(block["classifierId"], tuple(block["labels"]), block["question"],
                                positive_label=block["positiveLabel"])
    definition = CyclotronDefinition(block["cyclotronId"], (classifier,), seed=f"{block['cyclotronId']}-v1")
    program = ReviewProgram(**{REVIEW_PROGRAM_FIELDS[key]: (tuple(value) if key == "rates" else value)
                               for key, value in block["reviewProgram"].items()})
    return RelevanceCyclotronPlan(definition, {classifier.id: doctrine_seed_rubric(doctrine)}, program,
                                  dict(block["decisionModel"]), dict(block["optimizer"]) if block["optimizer"] else None,
                                  block["store"]["localPath"], block["store"]["s3Prefix"], block["maxRequestsPerSweep"],
                                  block["reviewControl"], block.get("enabled", True), block.get("maxDecisionsPerDay"),
                                  block.get("approvedProofPath"), dict(block.get("autoReject") or DEFAULT_AUTO_REJECT))


def decision_model_identity(plan: RelevanceCyclotronPlan) -> str:
    """The configured decision model's identity, without constructing a client (stores are keyed by it)."""
    if plan.decision_model["provider"] == "jev":
        from decision_flywheel.adapters.jev import JevConfiguration
        return JevConfiguration(model=plan.decision_model["model"]).model_identity
    raise ValueError(f"Unsupported decision model provider: {plan.decision_model['provider']}")


def decision_model_from_environment(plan: RelevanceCyclotronPlan):
    """The configured batched decision model, with its key read from the environment."""
    if plan.decision_model["provider"] == "jev":
        from decision_flywheel.adapters.jev import JevAdapter, JevConfiguration
        return JevAdapter.from_environment(configuration=JevConfiguration(model=plan.decision_model["model"]))
    raise ValueError(f"Unsupported decision model provider: {plan.decision_model['provider']}")


def optimizer_from_environment(plan: RelevanceCyclotronPlan):
    """The configured LLM optimizer, or None to decide and record only."""
    if plan.optimizer is None:
        return None
    if plan.optimizer["provider"] == "openai":
        from decision_flywheel import OptimizerAgent
        from decision_flywheel.adapters.openai_optimizer import OpenAIOptimizer
        return OptimizerAgent(OpenAIOptimizer.from_environment(model=plan.optimizer["model"],
                                                               max_calls=plan.optimizer["maxCalls"]))
    raise ValueError(f"Unsupported optimizer provider: {plan.optimizer['provider']}")


def _refuse_secrets(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) not in NOT_SECRET_FIELDS and any(word in str(key).lower() for word in SECRET_WORDS):
                raise ValueError(f"{path}.{key} looks like a credential; provider keys come from the environment, "
                                 "never from the steering config.")
            _refuse_secrets(child, f"{path}.{key}")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()
