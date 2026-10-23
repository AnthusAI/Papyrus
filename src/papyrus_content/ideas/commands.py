"""``papyrus ideas digest|synthesize``: the first version of the idea pipeline (docs/idea-pipeline.md).

Both run on this machine against the site named by PAPYRUS_GRAPHQL_ENDPOINT, with the operator's IAM credentials
(PAPYRUS_GRAPHQL_AUTH=iam) or a `papyrus login` session. ``synthesize --store proposals`` needs the editor session, because
filing a Proposal is not open to IAM.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..graphql_authoring import create_authoring_client
from ..options import normalize_string, parse_options
from ..papyrus_config import resolve_openai_api_key
from . import digest as digest_module
from . import synthesis
from .context import corpus_ids_for, hosted_corpora, load_context
from .dedupe import DEFAULT_THRESHOLD
from .pipeline import DEFAULT_MAXIMUM_COST_USD, RunRefused, render_report, synthesize
from .review import load_feedback
from .store import JSON, PROPOSALS, STORES, JsonStore, ProposalStore, assert_private, default_root

USAGE = (
    "Usage:\n"
    "  papyrus ideas digest --publication KEY [--since 7d] [--status accepted[,pending]] [--max-references N] [--excerpts]\n"
    "      [--out DIR] [--json]\n"
    "  papyrus ideas synthesize --publication KEY [--digest ID|PATH | --since 7d [--status ...] [--excerpts]] [--max 5]\n"
    "      [--store json|proposals] [--feedback FILE (manual override of review steering)] [--model gpt-6-luna] [--dedupe-threshold 0.5] [--max-cost-usd 0.50]\n"
    "      [--story-days 90] [--out DIR] [--report FILE] [--json]\n"
    "Ideas are private: JSON files under --out (default ~/.papyrus/ideas/KEY), or draft story_draft Proposals with --store proposals."
)


def _client_and_corpora(publication: str) -> tuple[Any, list[str]]:
    client, _ = create_authoring_client()
    return client, corpus_ids_for(hosted_corpora(client), publication)


def _publication(options: dict[str, Any]) -> str:
    publication = normalize_string(options.get("publication"))
    if not publication:
        raise ValueError("ideas commands need --publication KEY (the knowledge corpus key).")
    return publication


def _root(options: dict[str, Any], publication: str) -> Path:
    out = normalize_string(options.get("out"))
    return assert_private(Path(out)) if out else default_root(publication)


def _integer(options: dict[str, Any], key: str, default: int) -> int:
    value = normalize_string(options.get(key))
    if value is None:
        return default
    if not value.isdigit() or int(value) < 1:
        raise ValueError(f"--{key} must be a positive whole number.")
    return int(value)


def _number(options: dict[str, Any], key: str, default: float) -> float:
    value = normalize_string(options.get(key))
    try:
        return default if value is None else float(value)
    except ValueError as error:
        raise ValueError(f"--{key} must be a number.") from error


def _build_digest(client: Any, corpus_ids: list[str], publication: str, options: dict[str, Any]) -> dict[str, Any]:
    return digest_module.make_digest(
        client,
        publication=publication,
        corpus_ids=corpus_ids,
        since=normalize_string(options.get("since")) or digest_module.DEFAULT_WINDOW,
        statuses=digest_module.parse_statuses(normalize_string(options.get("status"))),
        maximum_references=_integer(options, "max-references", digest_module.DEFAULT_MAXIMUM_REFERENCES),
        excerpts=bool(options.get("excerpts")),
    )


def digest_command(flags: list[str]) -> None:
    options = parse_options(flags)
    publication = _publication(options)
    store = JsonStore(_root(options, publication))
    client, corpus_ids = _client_and_corpora(publication)
    digest = _build_digest(client, corpus_ids, publication, options)
    path = store.save_digest(digest)
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "ideas digest", "path": str(path), "digest": digest}, indent=2))
        return
    counts = digest["counts"]
    print(f"ideas\tdigest\t{digest['digestId']}\t{path}")
    print(f"window\t{digest['window']['since']}\t{digest['window']['until']}\tstatuses {','.join(digest['statuses'])}")
    print(f"references\tconsidered {counts['considered']}\tincluded {counts['included']}")
    for group in digest["groups"]:
        print(f"group\t{group['section']}\t{group['label']}\t{group['count']}")


def synthesize_command(flags: list[str]) -> None:
    options = parse_options(flags)
    publication = _publication(options)
    store_name = normalize_string(options.get("store")) or JSON
    if store_name not in STORES:
        raise ValueError(f"--store must be {' or '.join(STORES)}.")
    json_store = JsonStore(_root(options, publication))
    client, corpus_ids = _client_and_corpora(publication)
    reference = normalize_string(options.get("digest"))
    digest = json_store.load_digest(reference) if reference else _build_digest(client, corpus_ids, publication, options)
    if digest["publication"] != publication:
        raise ValueError(f"Digest {digest['digestId']} is for {digest['publication']}, not {publication}.")
    json_store.save_digest(digest)
    now = datetime.now(timezone.utc)
    context = load_context(client, now=now, story_days=_integer(options, "story-days", 90))
    api_key = resolve_openai_api_key()
    if not api_key:
        raise ValueError("Synthesis needs OPENAI_API_KEY (or openai.apiKey in the Papyrus config).")
    try:
        run = synthesize(
            digest=digest,
            context=context,
            json_store=json_store,
            transport=synthesis.openai_transport(api_key),
            proposal_store=ProposalStore(client) if store_name == PROPOSALS else None,
            review_client=client,
            feedback=load_feedback(normalize_string(options.get("feedback"))),
            model=normalize_string(options.get("model")) or synthesis.DEFAULT_MODEL,
            maximum=_integer(options, "max", synthesis.DEFAULT_MAXIMUM_IDEAS),
            threshold=_number(options, "dedupe-threshold", DEFAULT_THRESHOLD),
            maximum_cost_usd=_number(options, "max-cost-usd", DEFAULT_MAXIMUM_COST_USD),
            now=now,
        )
    except (RunRefused, synthesis.SynthesisError) as error:
        raise ValueError(str(error)) from error
    report = normalize_string(options.get("report"))
    if report:
        target = assert_private(Path(report))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_report(run, digest), encoding="utf-8")
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "ideas synthesize", "run": run}, indent=2))
        return
    inputs, usage = run["inputs"], run.get("usage") or {}
    print(f"ideas\tsynthesize\t{run['runId']}\t{run['store']}")
    print(f"inputs\treferences {inputs['references']}\tstories {inputs['stories']}\tdrafts {inputs['earlierDrafts']}\tdigest {digest['digestId']}")
    print(f"ideas\tproposed {run['proposed']}\tinvalid {len(run['invalid'])}\tduplicates {len(run['duplicates'])}\tcreated {run['ideasCreated']}")
    print(f"llm\t{run['model']}\tin {usage.get('inputTokens', 0)}\tout {usage.get('outputTokens', 0)}\tcost ${usage.get('costUsd', 0)}")
    review = run["review"]
    print(f"review\t{review['status']}\trequested {str(review['requested']).lower()}" + (f"\t{review['error']}" if review.get("error") else ""))
    print(f"steering\tentries {run['steering']['entries']}" + (f"\t{run['steering']['error']}" if run["steering"].get("error") else ""))
    for idea in run["ideas"]:
        print(f"idea\t{idea['ideaId']}\t{idea['section']}\t{idea['title']}")


COMMANDS = {"digest": digest_command, "synthesize": synthesize_command}


def ideas_command(command: str, flags: list[str]) -> None:
    handler = COMMANDS.get(command)
    if handler is None:
        print(USAGE, file=sys.stderr)
        raise ValueError(f"Unsupported papyrus ideas command: {command}")
    handler(flags)
