from __future__ import annotations

from pathlib import Path

from .env import PAPYRUS_ROOT
from .graphql_authoring import create_authoring_client


ALLOWED_BACKEND_NODE_SCRIPT_FILES = {
    "scripts/test-newsroom-card-layout.cjs",
    "scripts/test-newsroom-session.cjs",
    "scripts/favicon/generate-favicon.mjs",
}


def check_backend_node_scripts(_flags: list[str]) -> None:
    scripts_dir = PAPYRUS_ROOT / "scripts"
    violations: list[str] = []
    for path in scripts_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".js", ".cjs", ".mjs"}:
            continue
        relative = path.relative_to(PAPYRUS_ROOT).as_posix()
        if relative.startswith("scripts/lib/"):
            violations.append(relative)
            continue
        if relative not in ALLOWED_BACKEND_NODE_SCRIPT_FILES:
            violations.append(relative)
    if violations:
        rendered = "\n".join(f"- {entry}" for entry in sorted(set(violations)))
        raise RuntimeError(
            "Backend Node utility policy violation: non-frontend JS scripts detected under scripts/.\n"
            "Allowed frontend JS scripts are limited to explicit UI/test/build harness files.\n"
            f"Violations:\n{rendered}"
        )
    print("policy\tbackend-node-scripts\tok")


REFERENCE_ACTION_SCHEMA_QUERY = """
query ReferenceActionSchemaContract {
  queryType: __type(name: "Query") { fields { name } }
  mutationType: __type(name: "Mutation") { fields { name } }
}
"""


def check_reference_action_contract(_flags: list[str]) -> None:
    client, _ = create_authoring_client()
    payload = client.graphql(REFERENCE_ACTION_SCHEMA_QUERY, {})
    mutation_fields = {
        entry.get("name")
        for entry in (payload.get("mutationType") or {}).get("fields") or []
        if isinstance(entry, dict) and entry.get("name")
    }
    query_fields = {
        entry.get("name")
        for entry in (payload.get("queryType") or {}).get("fields") or []
        if isinstance(entry, dict) and entry.get("name")
    }
    required_mutations = {
        "reviewReferenceCuration",
        "setReferenceQualityRating",
        "createReferenceNote",
        "moveReferenceCorpus",
        "startReferenceCuration",
    }
    required_queries = {
        "getReferenceCurationStatus",
    }
    missing_mutations = sorted(required_mutations - mutation_fields)
    missing_queries = sorted(required_queries - query_fields)
    if missing_mutations or missing_queries:
        details: list[str] = []
        if missing_mutations:
            details.append(f"missing mutations: {', '.join(missing_mutations)}")
        if missing_queries:
            details.append(f"missing queries: {', '.join(missing_queries)}")
        raise RuntimeError(
            "Reference action schema contract failed: "
            + "; ".join(details)
        )
    print("policy\treference-action-contract\tok")
