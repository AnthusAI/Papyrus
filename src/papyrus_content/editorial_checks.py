"""Editorial checks: Papyrus's editorial policies, checked by Limatus.

Papyrus owns the policies (``EditorialPolicy``), the settings
(``EditorialCheckSettings``) and the editors' decisions (``EditorialFeedback``).
For each request a Limatus policy pack is composed from the stored policies --
publication policies plus the article's desk policies, where a desk policy
replaces a publication policy with the same key -- and Limatus is called.

The editorial-checks plugin's function routes its GraphQL fields through
``handle``; the ``papyrus editorial`` CLI uses the same operations.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import limatus
from limatus.packs import builtin_pack

PUBLICATION_SCOPE = "publication"
SETTINGS_ID = "settings"
DEFAULT_SETTINGS: dict[str, Any] = {
    "lanes": {"rules": True, "classifier": True},
    "classifierModel": "jev-latest",
    "rewriteModel": "gpt-6-luna",
    "deadlineSeconds": 20,
    "maxInputTokens": 500_000,
    "maxExamplesPerQuestion": 4,
    "guidance": "",
    "publishWarning": True,
    "checkWhileTyping": True,
}
POLICY_FIELDS = ("policyKey", "scope", "version", "title", "guidance", "severity", "enabled", "detectors", "examples", "rewriteGuidance", "source")


class EditorialStore(Protocol):
    def list_policies(self) -> list[dict[str, Any]]: ...
    def get_settings(self) -> dict[str, Any] | None: ...
    def list_feedback(self) -> list[dict[str, Any]]: ...
    def create_policy(self, record: dict[str, Any]) -> None: ...
    def update_policy(self, record: dict[str, Any]) -> None: ...


_DEFAULT = object()


@dataclass
class Services:
    store: EditorialStore
    decision_model: Any = _DEFAULT
    generator: Any = _DEFAULT
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    last_check_request: dict[str, Any] | None = field(default=None, init=False)

    def limatus_kwargs(self, name: str) -> dict[str, Any]:
        value = getattr(self, name)
        return {} if value is _DEFAULT else {name: value}


# --- provider keys ------------------------------------------------------------------

PROVIDER_KEYS = ("TYPESAFE_API_KEY", "OPENAI_API_KEY")


def load_provider_keys(
    env: Any = None,
    *,
    read_parameter: Callable[[str], str] | None = None,
) -> None:
    """Put the real provider keys into the environment Limatus reads.

    Amplify hands a Python function each secret() as a placeholder plus an
    AMPLIFY_SSM_ENV_CONFIG map of SSM paths; only Node functions resolve them
    automatically. A key that cannot be resolved is removed, so its lane
    reports "not configured" instead of sending the placeholder to a provider.
    """
    from .amplify_ssm_secrets import _is_amplify_secret_placeholder, _read_ssm_secret

    env = os.environ if env is None else env
    read = read_parameter or _read_ssm_secret
    try:
        config = json.loads(env.get("AMPLIFY_SSM_ENV_CONFIG") or "{}")
    except json.JSONDecodeError:
        config = {}
    for name in PROVIDER_KEYS:
        current = (env.get(name) or "").strip()
        if current and not _is_amplify_secret_placeholder(current):
            continue
        entry = config.get(name) if isinstance(config, dict) else None
        resolved = None
        for path in ((entry or {}).get("path"), (entry or {}).get("sharedPath")):
            if not path:
                continue
            try:
                resolved = (read(path) or "").strip() or None
            except Exception:
                resolved = None
            if resolved:
                break
        if resolved:
            env[name] = resolved
        else:
            env.pop(name, None)


# --- records ----------------------------------------------------------------------


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value) if isinstance(value, str) else value


def policy_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """A stored EditorialPolicy as a Limatus policy (its key becomes the policy id)."""
    policy = {
        "id": record["policyKey"],
        "version": int(record.get("version") or 1),
        "title": record["title"],
        "guidance": record["guidance"],
        "severity": record["severity"],
        "enabled": bool(record.get("enabled", True)),
        "detectors": _json(record.get("detectors"), []),
    }
    examples = _json(record.get("examples"), None)
    if examples:
        policy["examples"] = examples
    if record.get("rewriteGuidance"):
        policy["rewriteGuidance"] = record["rewriteGuidance"]
    return policy


def record_from_policy(policy: dict[str, Any], *, scope: str, source: str, version: int = 1) -> dict[str, Any]:
    return {
        "id": policy_record_id(policy["id"], scope),
        "policyKey": policy["id"],
        "scope": scope,
        "version": version,
        "title": policy["title"],
        "guidance": policy["guidance"],
        "severity": policy["severity"],
        "enabled": policy.get("enabled", True),
        "detectors": policy.get("detectors", []),
        "examples": policy.get("examples"),
        "rewriteGuidance": policy.get("rewriteGuidance"),
        "source": source,
    }


def policy_record_id(policy_key: str, scope: str) -> str:
    return f"{scope}#{policy_key}"


def settings_from(store: EditorialStore) -> dict[str, Any]:
    stored = store.get_settings()
    values = _json((stored or {}).get("settings"), {})
    settings = {**DEFAULT_SETTINGS, **values}
    settings["lanes"] = {**DEFAULT_SETTINGS["lanes"], **values.get("lanes", {})}
    return settings


def compose_pack(records: list[dict[str, Any]], section: str | None, settings: dict[str, Any]) -> dict[str, Any]:
    """Publication policies, replaced key by key by the section's own policies."""
    chosen: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("scope") == PUBLICATION_SCOPE:
            chosen.setdefault(record["policyKey"], record)
    for record in records:
        if section and record.get("scope") == section:
            chosen[record["policyKey"]] = record
    policies = [policy_from_record(chosen[key]) for key in sorted(chosen)]
    fingerprint = hashlib.sha256(json.dumps([(p["id"], p["version"]) for p in policies]).encode()).hexdigest()[:12]
    pack: dict[str, Any] = {
        "schemaVersion": 1,
        "packId": "papyrus",
        "version": f"{section or PUBLICATION_SCOPE}-{fingerprint}",
        "policies": policies,
    }
    if settings.get("guidance"):
        pack["guidance"] = settings["guidance"]
    return pack


# --- operations -------------------------------------------------------------------


def check_editorial(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    settings = settings_from(services.store)
    pack = compose_pack(services.store.list_policies(), arguments.get("section"), settings)
    examples = [
        {"policyId": f["policyId"], "detectorId": f["detectorId"], "text": f["text"], "violates": f["decision"] != "dismissed"}
        for f in services.store.list_feedback()
        if f.get("text") and f.get("lane") == "classifier"
    ]
    classifier: dict[str, Any] = {
        "model": settings["classifierModel"],
        "deadlineSeconds": settings["deadlineSeconds"],
        "maxInputTokens": settings["maxInputTokens"],
        "maxExamplesPerQuestion": settings["maxExamplesPerQuestion"],
    }
    if examples:
        classifier["examples"] = examples
    request = {
        "schemaVersion": 1,
        "content": {"format": arguments.get("format") or "markus", "text": arguments["body"]},
        "pack": pack,
        "options": {"lanes": settings["lanes"], "classifier": classifier},
    }
    services.last_check_request = request
    return limatus.check(request, **services.limatus_kwargs("decision_model"))


def suggest_rewrite(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    settings = settings_from(services.store)
    request: dict[str, Any] = {
        "schemaVersion": 1,
        "content": {"format": arguments.get("format") or "markus", "text": arguments["body"]},
        "pack": compose_pack(services.store.list_policies(), arguments.get("section"), settings),
        "options": {"model": settings["rewriteModel"], "count": 3},
    }
    if arguments.get("note"):
        request["options"]["instructions"] = arguments["note"]
    finding, selection = _json(arguments.get("finding"), None), _json(arguments.get("selection"), None)
    if finding:
        request["finding"] = finding
    else:
        request["selection"] = selection
    return limatus.suggest(request, **services.limatus_kwargs("generator"))


def draft_questions(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    settings = settings_from(services.store)
    policy: dict[str, Any] = {"title": arguments["title"], "guidance": arguments["guidance"]}
    examples = _json(arguments.get("examples"), None)
    if examples:
        policy["examples"] = examples
    request = {"schemaVersion": 1, "policy": policy, "options": {"model": settings["rewriteModel"]}}
    return limatus.draft_questions(request, **services.limatus_kwargs("generator"))


def try_policy(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    settings = settings_from(services.store)
    policy = _json(arguments["policy"], {})
    request = {
        "schemaVersion": 1,
        "content": {"format": arguments.get("format") or "markus", "text": arguments["text"]},
        "pack": {"schemaVersion": 1, "packId": "papyrus-try", "version": "draft", "policies": [policy]},
        "options": {"classifier": {"model": settings["classifierModel"], "deadlineSeconds": settings["deadlineSeconds"]}},
    }
    return limatus.check(request, **services.limatus_kwargs("decision_model"))


def import_starter_pack(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    name = arguments["name"]
    existing = {policy_record_id(r["policyKey"], r["scope"]) for r in services.store.list_policies()}
    created = skipped = 0
    for policy in builtin_pack(name)["policies"]:
        record = record_from_policy(policy, scope=PUBLICATION_SCOPE, source=f"starter:{name}")
        if record["id"] in existing:
            skipped += 1
            continue
        services.store.create_policy(record)
        created += 1
    return {"created": created, "skipped": skipped}


def recalibrate(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    labels = [
        {"policyId": f["policyId"], "detectorId": f["detectorId"], "probability": float(f["probability"]), "violates": f["decision"] != "dismissed"}
        for f in services.store.list_feedback()
        if f.get("lane") == "classifier" and f.get("probability") is not None
    ]
    if not labels:
        return {"updated": 0, "detectors": []}
    calibration = limatus.calibrate({"schemaVersion": 1, "labels": labels})
    by_key = {(d["policyId"], d["detectorId"]): d for d in calibration["detectors"] if "calibration" in d}
    updated = 0
    for record in services.store.list_policies():
        detectors = _json(record.get("detectors"), [])
        changed = False
        for detector in detectors:
            fit = by_key.get((record["policyKey"], detector.get("id")))
            if fit and detector.get("lane") == "classifier" and detector.get("calibration") != fit["calibration"]:
                detector["calibration"] = fit["calibration"]
                changed = True
        if changed:
            services.store.update_policy({**record, "detectors": detectors, "version": int(record.get("version") or 1) + 1})
            updated += 1
    return {"updated": updated, "detectors": calibration["detectors"]}


OPERATIONS: dict[str, Callable[[dict[str, Any], Services], dict[str, Any]]] = {
    "checkEditorial": check_editorial,
    "suggestEditorialRewrite": suggest_rewrite,
    "draftEditorialQuestions": draft_questions,
    "tryEditorialPolicy": try_policy,
    "importEditorialStarterPack": import_starter_pack,
    "recalibrateEditorialPolicies": recalibrate,
}


def handle(field_name: str, arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    operation = OPERATIONS.get(field_name)
    if operation is None:
        raise ValueError(f"Unknown editorial-checks operation {field_name}")
    try:
        return operation(arguments, services)
    except limatus.ContractValidationError as error:
        raise ValueError(str(error)) from error


# --- GraphQL store ----------------------------------------------------------------

_POLICY_SELECTION = "id policyKey scope version title guidance severity enabled detectors examples rewriteGuidance source"
LIST_POLICIES = f"query ListEditorialPolicies($nextToken: String) {{ listEditorialPolicies(limit: 500, nextToken: $nextToken) {{ items {{ {_POLICY_SELECTION} }} nextToken }} }}"
GET_SETTINGS = "query GetEditorialCheckSettings($id: ID!) { getEditorialCheckSettings(id: $id) { id settings } }"
LIST_FEEDBACK = "query ListEditorialFeedbacks($nextToken: String) { listEditorialFeedbacks(limit: 1000, nextToken: $nextToken) { items { policyId detectorId lane probability decision text } nextToken } }"
CREATE_POLICY = "mutation CreateEditorialPolicy($input: CreateEditorialPolicyInput!) { createEditorialPolicy(input: $input) { id } }"
UPDATE_POLICY = "mutation UpdateEditorialPolicy($input: UpdateEditorialPolicyInput!) { updateEditorialPolicy(input: $input) { id } }"


class GraphQLEditorialStore:
    """The plugin's models through AppSync, signed the Papyrus way (IAM for functions and the CLI)."""

    def __init__(self, execute: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None) -> None:
        if execute is None:
            from .graphql_http import execute_graphql

            execute = execute_graphql
        self._execute = execute

    def _list(self, query: str, field_name: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token = None
        while True:
            page = self._execute(query, {"nextToken": token})[field_name]
            items.extend(page["items"])
            token = page.get("nextToken")
            if not token:
                return items

    def list_policies(self) -> list[dict[str, Any]]:
        return self._list(LIST_POLICIES, "listEditorialPolicies")

    def get_settings(self) -> dict[str, Any] | None:
        return self._execute(GET_SETTINGS, {"id": SETTINGS_ID})["getEditorialCheckSettings"]

    def list_feedback(self) -> list[dict[str, Any]]:
        return self._list(LIST_FEEDBACK, "listEditorialFeedbacks")

    def create_policy(self, record: dict[str, Any]) -> None:
        self._execute(CREATE_POLICY, {"input": policy_input(record)})

    def update_policy(self, record: dict[str, Any]) -> None:
        self._execute(UPDATE_POLICY, {"input": policy_input(record)})


def policy_input(record: dict[str, Any]) -> dict[str, Any]:
    """A policy record as GraphQL input: JSON fields as strings."""
    payload = {"id": record["id"], **{key: record.get(key) for key in POLICY_FIELDS}}
    for key in ("detectors", "examples"):
        if payload[key] is not None and not isinstance(payload[key], str):
            payload[key] = json.dumps(payload[key])
    return payload
