"""Draft a publication's web-search queries from its mission, editorial policy and Cyclotron relevance criteria.

`papyrus monitors web-queries --publication <id> [--write]` reads the publication's doctrine (read-only AppSync, IAM),
the criteria question the Cyclotron decides with (the lab's reviewed `<publication>-relevance.json`, when it is on this
machine), asks gpt-6-luna for 8 to 15 searches and prints them. `--write` stores them in the monitor's CONFIG (the one
AWS write here; leave it out to only review). `--out FILE` also saves the proposal as JSON.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from .monitoring_web_publications import DISTINCTIVE_ENTRY, WEB_PUBLICATIONS, monitor_id

MODEL = "gpt-6-luna"
MIN_QUERIES, MAX_QUERIES = 8, 15
DEFAULT_CRITERIA_DIR = Path.home() / "Projects" / "Cyclotron" / "infra" / "lab" / "criteria"
INSTRUCTIONS = (
    "You write web-search queries for a monitor that finds new articles for one publication. Reply with a JSON array of "
    f"{MIN_QUERIES} to {MAX_QUERIES} distinct strings and nothing else. Each query is a plain search-engine query of at most "
    "twelve words that a news search would answer with recent, substantive pieces on one topic the publication covers. "
    "Cover the publication's range of topics, not one topic many times. Use the criteria to aim at what the publication "
    "includes and away from what it excludes. No site: operators, no dates, no quotation marks around the whole query.")


def criteria_text(publication_id: str, directory: Path | None = None) -> str | None:
    path = Path(directory or DEFAULT_CRITERIA_DIR) / f"{publication_id}-relevance.json"
    try:
        return str(json.loads(path.read_text()).get("question") or "").strip() or None
    except (OSError, ValueError):
        return None


def doctrine(context: dict) -> dict:
    """Mission and policy texts out of a resolved editorial context pack."""
    found = {}
    for entry in context.get("entries") or []:
        if entry.get("scope") == "publication" and entry.get("kind") in ("mission", "policy"):
            found[entry["kind"]] = entry["text"]
    return found


def prompt(publication_id: str, site: str, mission: str | None, policy: str | None, criteria: str | None) -> str:
    parts = [f"Publication: {publication_id} ({site})"]
    for label, text in (("Mission", mission), ("Editorial policy", policy), ("Relevance criteria (what it includes and excludes)", criteria)):
        if text:
            parts.append(f"{label}:\n{text}")
    return "\n\n".join(parts)


def parse_queries(answer: str) -> list[str]:
    text = answer.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    queries = json.loads(text)
    if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
        raise ValueError("The model did not return a JSON array of strings")
    unique = list(dict.fromkeys(" ".join(q.split()) for q in queries if q.strip()))
    if not MIN_QUERIES <= len(unique) <= MAX_QUERIES:
        raise ValueError(f"The model returned {len(unique)} distinct queries; expected {MIN_QUERIES} to {MAX_QUERIES}")
    return unique


def openai_asker(api_key: str, transport=None) -> Callable[[str], str]:
    from .ideas import synthesis

    send = transport or synthesis.openai_transport(api_key)

    def ask(message: str) -> str:
        body = send(synthesis.RESPONSES_URL, {"Content-Type": "application/json"},
                    {"model": MODEL, "instructions": INSTRUCTIONS, "input": message, "max_output_tokens": 2000, "store": False})
        answer = synthesis.response_text(body)
        if not answer or not answer.strip():
            raise ValueError("The model returned no text")
        return answer
    return ask


def draft_queries(publication_id: str, site: str, mission, policy, criteria, ask: Callable[[str], str], attempts: int = 2) -> list[str]:
    message = prompt(publication_id, site, mission, policy, criteria)
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return parse_queries(ask(message))
        except ValueError as error:      # includes json.JSONDecodeError
            last = error
    raise ValueError(f"No usable queries for {publication_id}: {last}")


def router_publications(hn_router: dict) -> dict[str, dict]:
    from .monitoring_router import validate_router_publications

    entries = [*(hn_router.get("publications") or []), dict(DISTINCTIVE_ENTRY)]
    return {p["publicationId"]: p for p in validate_router_publications({"publications": entries})}


def read_hn_router() -> dict:
    import boto3

    ssm, dynamo = boto3.client("ssm"), boto3.resource("dynamodb")
    table = dynamo.Table(ssm.get_parameter(Name="/papyrus/monitoring/table-name")["Parameter"]["Value"])
    return table.get_item(Key={"pk": "MONITOR#hn", "sk": "CONFIG#router"}, ConsistentRead=True)["Item"]


def openai_key() -> str:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    parameter = (os.environ.get("PAPYRUS_OPENAI_KEY_PARAMETER") or "/papyrus/shipped/openai-api-key").strip()
    if not key:
        import boto3

        key = boto3.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"].strip()
    return key


def propose(publication_id: str, publications: dict, ask: Callable[[str], str], *, criteria_dir: Path | None = None,
            client_factory=None, resolve=None) -> dict:
    publication = publications[publication_id]
    from .editorial_context import resolve_editorial_context

    if client_factory is None:
        from .monitoring_router import make_appsync_client as client_factory
    pack = (resolve or resolve_editorial_context)(client_factory(publication["appsyncEndpoint"]),
                                                  endpoint=publication["appsyncEndpoint"], publication_key=publication["corpusKey"],
                                                  optional_publication_doctrine=True)
    texts = doctrine(pack)
    criteria = criteria_text(publication_id, criteria_dir)
    queries = draft_queries(publication_id, publication["site"], texts.get("mission"), texts.get("policy"), criteria, ask)
    return {"publicationId": publication_id, "monitorId": monitor_id(publication_id), "queries": queries,
            "basedOn": {"mission": "mission" in texts, "policy": "policy" in texts, "criteria": criteria is not None,
                        "contextHash": pack.get("contextHash")}}


def write_queries(publication_id: str, queries: list[str], *, enable: bool = False) -> None:
    """Store the queries in the monitor's CONFIG (an AWS write: only with --write). The config must already be seeded."""
    import boto3

    from .monitoring_cloud import _validate_config

    ssm, dynamo = boto3.client("ssm"), boto3.resource("dynamodb")
    table = dynamo.Table(ssm.get_parameter(Name="/papyrus/monitoring/table-name")["Parameter"]["Value"])
    key = {"pk": f"MONITOR#{monitor_id(publication_id)}", "sk": "CONFIG"}
    item = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not item:
        raise ValueError(f"{key['pk']} is not seeded; run infra/monitoring/seed_web_monitors.py first")
    item = {**item, "queries": queries, **({"enabled": True} if enable else {})}
    _validate_config(json.loads(json.dumps(item, default=int)))
    table.put_item(Item=item)


def command(args) -> int:
    publications = router_publications(read_hn_router())
    chosen = list(WEB_PUBLICATIONS) if args.all else [args.publication]
    ask = openai_asker(openai_key())
    proposals, failed = [], False
    for publication_id in chosen:
        try:
            proposal = propose(publication_id, publications, ask, criteria_dir=Path(args.criteria_dir) if args.criteria_dir else None)
        except Exception as error:   # noqa: BLE001 - one publication's failure must not hide the others
            print(f"{publication_id}: FAILED {type(error).__name__}: {str(error)[:300]}")
            failed = True
            continue
        proposals.append(proposal)
        print(f"{publication_id} ({', '.join(k for k, v in proposal['basedOn'].items() if v is True) or 'no doctrine'}):")
        for query in proposal["queries"]:
            print(f"  - {query}")
        if args.write:
            write_queries(publication_id, proposal["queries"], enable=args.enable)
            print(f"  stored in {proposal['monitorId']} CONFIG")
    if args.out:
        Path(args.out).write_text(json.dumps({p["publicationId"]: p for p in proposals}, indent=2) + "\n")
    return 1 if failed else 0
