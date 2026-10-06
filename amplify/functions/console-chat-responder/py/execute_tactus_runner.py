#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SEARCH_PATHS = [
    Path("/opt/papyrus/src"),
    Path.cwd() / "src",
]
for root in SEARCH_PATHS:
    if root.exists() and str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _error(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }


def _docs_index() -> dict[str, Any]:
    try:
        from papyrus_newsroom.tactus_runtime import DOCS  # type: ignore
    except Exception as exc:
        return _error("runner_unavailable", f"Unable to import papyrus_newsroom.tactus_runtime: {exc}")

    entries: list[dict[str, str]] = []
    for doc in DOCS.values():
        entries.append(
            {
                "id": str(doc.get("id") or ""),
                "title": str(doc.get("title") or ""),
                "summary": str(doc.get("summary") or ""),
                "namespace": str(doc.get("namespace") or ""),
            }
        )
    entries.sort(key=lambda entry: entry["id"])
    return {"entries": entries}


def _coerce_web_ui_context(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    web_path = str(payload.get("webPath") or payload.get("web_path") or "").strip()
    papyrus_location_uri = str(
        payload.get("papyrusLocationUri") or payload.get("papyrus_location_uri") or ""
    ).strip()
    if not web_path and not papyrus_location_uri:
        return None
    context = dict(payload)
    if web_path:
        context["webPath"] = web_path
    if papyrus_location_uri:
        context["papyrusLocationUri"] = papyrus_location_uri
    return context


def _execute_tactus(arguments: dict[str, Any], web_ui_context: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        from papyrus_newsroom.tactus_runtime import execute_tactus_harnessed  # type: ignore
    except Exception as exc:
        return _error("runner_unavailable", f"Unable to import papyrus_newsroom.tactus_runtime: {exc}")

    try:
        return execute_tactus_harnessed(
            str(arguments.get("tactus") or ""),
            harness=str(arguments.get("harness") or "raw"),
            assignment_id=str(arguments.get("assignment_id") or arguments.get("assignmentId") or ""),
            assignment_item_json=str(arguments.get("assignment_item_json") or arguments.get("assignmentItemJson") or ""),
            corpus_key=str(arguments.get("corpus_key") or arguments.get("corpusKey") or ""),
            max_evidence_items=int(arguments.get("max_evidence_items") or arguments.get("maxEvidenceItems") or 20),
            research_mode=str(arguments.get("research_mode") or arguments.get("researchMode") or ""),
            web_ui_context=web_ui_context,
        )
    except Exception as exc:
        return _error("tactus_execution_failed", f"Unexpected error: {exc}")


def main() -> None:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    mode = str(payload.get("mode") or "").strip()

    if mode == "docs_index":
        print(json.dumps(_docs_index()))
        return

    if mode == "execute_tactus":
        args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        web_ui_context = _coerce_web_ui_context(payload.get("webUi") or payload.get("web_ui"))
        print(json.dumps(_execute_tactus(args, web_ui_context=web_ui_context)))
        return

    print(json.dumps(_error("invalid_mode", f"Unsupported mode: {mode}")))


if __name__ == "__main__":
    main()
