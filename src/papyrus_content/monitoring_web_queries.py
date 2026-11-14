"""Draft a publication's web-search queries: one per enabled newsroom section, plus one for the whole site.

`papyrus monitors web-queries --publication <id>` (or `--all`) reads each enabled `NewsroomSection` of the publication's backend
(its `editorialMission`, `editorialPolicy`, `assignmentGuidance` and `killCriteria`; read-only AppSync, IAM) and the publication's own
mission and policy, asks gpt-6-luna for one query per section and one for the site, and prints what it would change: the old
queries to retire and the new ones to add. Nothing is written without `--execute`.

The queries are drafted once. No schedule regenerates them: a later run drafts only what is missing (a section added since) and
retires only drafted queries whose section is gone. A section keeps its query when it is renamed (the record holds the section's
id). Editor-written queries (`origin: editor`) are kept unless `--retire-editor` is given. Retiring sets `status: retired` (never
searched, history kept); nothing is deleted. A new query is searched only once approved (`--approved-by`).
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Callable

from .monitoring_web_publications import DISTINCTIVE_ENTRY, ROUTER_PUBLICATION, WEB_PUBLICATIONS, monitor_id

MODEL = "gpt-6-luna"
ACTOR = "papyrus monitors web-queries"
RETIRED_LEGACY = "Replaced by one query per section and one for the site (Ryan, 2026-11-02)."
RETIRED_ORPHAN = "Its section is no longer enabled."
SECTION_TEXTS = (("Mission", "editorialMission"), ("Editorial policy", "editorialPolicy"),
                 ("Assignment guidance", "assignmentGuidance"), ("Kill criteria (what does not belong)", "killCriteria"))
INSTRUCTIONS = (
    "You write one web-search query for a monitor that finds new articles for one publication. Reply with one JSON object "
    "{\"query\": string, \"rationale\": string} and nothing else. The rationale is one sentence on what the query is meant to find. "
    "The query is a plain search-engine query of at most twelve words that a news search would answer with recent, substantive "
    "pieces on the one topic you are given. When you are given a section, aim at what that section's mission, policy and guidance "
    "include and away from what its kill criteria exclude, and stay on that section's own topic. When you are given the whole site, "
    "write the query for the publication's overall subject, not for any one section. No site: operators, no dates, no quotation "
    "marks around the whole query.")


# --- reading the backend -------------------------------------------------------------------------------------------------

def doctrine(context: dict) -> dict:
    """Mission and policy texts out of a resolved editorial context pack."""
    found = {}
    for entry in context.get("entries") or []:
        if entry.get("scope") == "publication" and entry.get("kind") in ("mission", "policy"):
            found[entry["kind"]] = entry["text"]
    return found


def enabled_sections(rows: list[dict]) -> list[dict]:
    """The enabled `NewsroomSection`s in the newsroom's own order."""
    return sorted((r for r in rows if r.get("enabled") is True), key=lambda r: (int(r.get("sortOrder") or 0), str(r["id"])))


def scopes_for(site: str, sections: list[dict]) -> list[dict]:
    """What needs a query: each enabled section, then the site. `flags` says when a section had little to draft from."""
    scopes = []
    for section in sections:
        texts = {label: str(section.get(key) or "").strip() for label, key in SECTION_TEXTS}
        texts = {label: text for label, text in texts.items() if text}
        flags = [] if texts.get("Mission") else ["no-section-mission"] if texts else ["title-only"]
        scopes.append({"scope": "section", "sectionId": section["id"], "title": str(section.get("title") or section["id"]),
                       "texts": texts, "flags": flags})
    return scopes


def scope_key(record: dict) -> tuple | None:
    """Which scope a query record answers: ("site",), ("section", id), or None for a legacy topic query."""
    if record.get("scope") == "site":
        return ("site",)
    if record.get("sectionId"):
        return ("section", record["sectionId"])
    return None


# --- drafting ------------------------------------------------------------------------------------------------------------

def prompt(site: str, scope: dict, other_sections: list[str]) -> str:
    if scope["scope"] == "site":
        parts = [f"Publication: {site}", "Write the query for the whole site."]
    else:
        parts = [f"Publication: {site}", f"Section: {scope['title']}"]
    for label, text in scope["texts"].items():
        parts.append(f"{label}:\n{text}")
    if scope["scope"] == "section" and not scope["texts"]:
        parts.append("The section has no written mission or policy: draft from its title and say so in the rationale.")
    elif scope["scope"] == "section" and "Mission" not in scope["texts"]:
        parts.append("The section has no written mission: draft from the rest and say so in the rationale.")
    others = [t for t in other_sections if t != scope.get("title")]
    if others:
        parts.append("The publication's other sections have their own queries: " + ", ".join(others) + ".")
    return "\n\n".join(parts)


def parse_query(answer: str) -> dict:
    """`{"text", "rationale"}` from the model's JSON answer: exactly one query."""
    text = answer.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    row = json.loads(text)
    if isinstance(row, list) and len(row) == 1:
        row = row[0]
    if not isinstance(row, dict) or not isinstance(row.get("query"), str):
        raise ValueError("The model did not return one JSON {query, rationale} object")
    query = " ".join(row["query"].split())
    if not query:
        raise ValueError("The model returned an empty query")
    return {"text": query, "rationale": " ".join(str(row.get("rationale") or "").split())}


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


def draft_query(message: str, ask: Callable[[str], str], attempts: int = 2) -> dict:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return parse_query(ask(message))
        except ValueError as error:      # includes json.JSONDecodeError
            last = error
    raise ValueError(f"No usable query: {last}")


def draft(site: str, scopes: list[dict], ask: Callable[[str], str]) -> list[dict]:
    """One drafted query per scope, each with its scope and flags."""
    titles = [s["title"] for s in scopes if s["scope"] == "section"]
    drafted = []
    for scope in scopes:
        label = "the site" if scope["scope"] == "site" else f"section {scope['sectionId']}"
        try:
            query = draft_query(prompt(site, scope, titles), ask)
        except ValueError as error:
            raise ValueError(f"{label}: {error}") from None
        drafted.append({**query, "scope": scope["scope"], "flags": scope["flags"],
                        **({"sectionId": scope["sectionId"], "sectionTitle": scope["title"]} if scope["scope"] == "section" else {})})
    return drafted


# --- the plan: what to retire, keep and add -----------------------------------------------------------------------------

def plan_changes(existing: list[dict], scopes: list[dict], *, retire_editor: bool = False) -> dict:
    """Compare a monitor's `QUERY#` records with the scopes it needs.

    - `retire`: active or paused drafted queries with no scope (the old topic queries), drafted queries whose section is no
      longer enabled, and (only with `retire_editor`) editor queries.
    - `keep`: everything else that is not retired; a drafted query whose scope is still needed covers it, so it is not drafted again.
    - `missing`: the scopes no kept query covers: the only ones the model is asked about.
    - `unapproved`: kept drafted queries not yet approved (searched only once they are).
    """
    wanted = {("site",), *(("section", s["sectionId"]) for s in scopes if s["scope"] == "section")}
    retire, keep, covered = [], [], set()
    for record in sorted(existing, key=lambda r: r["id"]):
        if record.get("status") == "retired":
            continue
        if record.get("origin") == "editor":
            (retire if retire_editor else keep).append(record)
            continue
        key = scope_key(record)
        if key is None:
            retire.append({**record, "_reason": RETIRED_LEGACY})
        elif key in wanted:
            keep.append(record)
            covered.add(key)
        else:
            retire.append({**record, "_reason": RETIRED_ORPHAN})
    if retire_editor:
        retire = [({**r, "_reason": "Retired on request (--retire-editor)."} if "_reason" not in r else r) for r in retire]
    missing = [s for s in scopes if (("site",) if s["scope"] == "site" else ("section", s["sectionId"])) not in covered]
    unapproved = [r for r in keep if r.get("origin") == "drafted" and r.get("status") == "active" and not r.get("approvedBy")]
    return {"retire": retire, "keep": keep, "missing": missing, "unapproved": unapproved}


def site_scope(texts: dict) -> dict:
    """The site's scope, from its publication mission and policy; refused when it has neither."""
    found = {label: texts[kind] for label, kind in (("Mission", "mission"), ("Editorial policy", "policy")) if texts.get(kind)}
    if not found:
        raise ValueError("The publication has no mission or policy to draft the site query from")
    return {"scope": "site", "title": "the whole site", "texts": found, "flags": []}


def propose(publication_id: str, publications: dict, table, ask: Callable[[str], str], *, retire_editor: bool = False,
            client_factory=None, resolve=None) -> dict:
    """Read the backend and the monitor's queries; draft only the missing scopes. Writes nothing."""
    from .editorial_context import resolve_editorial_context
    from .monitoring_cloud import DynamoStore

    if client_factory is None:
        from .monitoring_router import make_appsync_client as client_factory
    router_id = ROUTER_PUBLICATION.get(publication_id, publication_id)
    publication = publications[router_id]
    endpoint = publication["appsyncEndpoint"]
    tenant = router_id if publication_id in ROUTER_PUBLICATION else None
    pack = (resolve or resolve_editorial_context)(client_factory(endpoint, None), endpoint=endpoint, publication_key=publication["corpusKey"],
                                                  optional_publication_doctrine=True)
    texts = doctrine(pack)
    sections = enabled_sections(client_factory(endpoint, tenant).safe_list_records("NewsroomSection"))
    scopes = [*scopes_for(publication["site"], sections), site_scope(texts)]
    existing = DynamoStore(table).list_queries(monitor_id(publication_id))
    plan = plan_changes(existing, scopes, retire_editor=retire_editor)
    added = draft(publication["site"], plan["missing"], ask) if plan["missing"] else []
    return {"publicationId": publication_id, "monitorId": monitor_id(publication_id), "sections": len(sections),
            "retire": plan["retire"], "keep": plan["keep"], "unapproved": plan["unapproved"], "queries": added,
            "basedOn": {"mission": "mission" in texts, "policy": "policy" in texts, "contextHash": pack.get("contextHash")}}


# --- the write ------------------------------------------------------------------------------------------------------------

def execute(table, proposal: dict, *, approved_by: str | None = None, now_iso: str | None = None) -> dict:
    """Apply a proposal to the monitor's `QUERY#` records (an AWS write: only with --execute). Retired queries keep every field
    and gain a history entry; new ones are written once (a query that exists is left alone); with `approved_by`, the new ones and
    the kept unapproved drafted ones are approved. Returns the counts."""
    from .monitoring_web import query_record

    monitor = proposal["monitorId"]
    if not table.get_item(Key={"pk": f"MONITOR#{monitor}", "sk": "CONFIG"}, ConsistentRead=True).get("Item"):
        raise ValueError(f"MONITOR#{monitor} is not seeded; run infra/monitoring/seed_web_monitors.py first")
    now = now_iso or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    by = approved_by or ACTOR
    done = {"retired": 0, "added": 0, "approved": 0}
    for record in proposal["retire"]:
        reason = record.pop("_reason", RETIRED_LEGACY)
        history = [*record.get("history", []), {"at": now, "by": by, "change": "retired", "before": record.get("status"),
                                                 "after": "retired", "reason": reason}]
        table.put_item(Item={**record, "status": "retired", "retiredAt": now, "history": history})
        done["retired"] += 1
    for query in proposal["queries"]:
        record = {**query_record(monitor, query["text"], query["rationale"], origin="drafted", created_by=MODEL, now_iso=now,
                                 approved_by=approved_by),
                  "scope": query["scope"], **({"sectionId": query["sectionId"], "sectionTitle": query["sectionTitle"]}
                                              if query["scope"] == "section" else {}),
                  **({"flags": query["flags"]} if query.get("flags") else {})}
        try:
            table.put_item(Item=record, ConditionExpression="attribute_not_exists(pk)")
            done["added"] += 1
        except Exception as error:   # noqa: BLE001 - only "already exists" is expected
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
    if approved_by:
        for record in proposal["unapproved"]:
            history = [*record.get("history", []), {"at": now, "by": approved_by, "change": "approved", "reason": "Approved with the per-section queries."}]
            table.put_item(Item={**record, "approvedBy": approved_by, "approvedAt": now, "history": history})
            done["approved"] += 1
    return done


# --- the command ----------------------------------------------------------------------------------------------------------

def router_publications(hn_router: dict) -> dict[str, dict]:
    from .monitoring_router import validate_router_publications

    entries = [*(hn_router.get("publications") or []), dict(DISTINCTIVE_ENTRY)]
    return {p["publicationId"]: p for p in validate_router_publications({"publications": entries})}


def monitoring_table():
    import boto3

    ssm, dynamo = boto3.client("ssm"), boto3.resource("dynamodb")
    return dynamo.Table(ssm.get_parameter(Name="/papyrus/monitoring/table-name")["Parameter"]["Value"])


def read_hn_router(table=None) -> dict:
    table = table or monitoring_table()
    return table.get_item(Key={"pk": "MONITOR#hn", "sk": "CONFIG#router"}, ConsistentRead=True)["Item"]


def openai_key() -> str:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    parameter = (os.environ.get("PAPYRUS_OPENAI_KEY_PARAMETER") or "/papyrus/shipped/openai-api-key").strip()
    if not key:
        import boto3

        key = boto3.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"].strip()
    return key


def describe(proposal: dict, *, executing: bool, approved: bool) -> list[str]:
    """The plan as printed lines: per site, what retires and what is added, and the searches a day it leaves."""
    lines = [f"{proposal['publicationId']} ({proposal['sections']} enabled sections):"]
    for record in proposal["retire"]:
        lines.append(f"  retire {record['id']} [{record.get('origin')}] {record['text']}")
    for query in proposal["queries"]:
        where = "site" if query["scope"] == "site" else f"section {query['sectionId']}"
        flag = f" [{', '.join(query['flags'])}]" if query.get("flags") else ""
        lines += [f"  add    ({where}){flag} {query['text']}", f"           {query['rationale']}"]
    for record in proposal["unapproved"]:
        lines.append(f"  kept, awaiting approval: {record['text']}")
    kept = [r for r in proposal["keep"] if r.get("status") == "active"]
    approved_after = approved or (not proposal["queries"] and all(r.get("approvedBy") for r in kept))
    total = len(kept) + len(proposal["queries"])
    lines.append(f"  after: {len(kept)} kept + {len(proposal['queries'])} added = {total} active queries, about {total} paid searches a day"
                 + ("" if approved_after else " once approved (none is searched until approved)"))
    return lines


def command(args) -> int:
    table = monitoring_table()
    publications = router_publications(read_hn_router(table))
    chosen = list(WEB_PUBLICATIONS) if args.all else [args.publication]
    ask = openai_asker(openai_key())
    proposals, failed = [], False
    if args.execute and not args.approved_by:
        print("note: without --approved-by the new queries are stored unapproved, so these sites are not searched until they are approved")
    for publication_id in chosen:
        try:
            proposal = propose(publication_id, publications, table, ask, retire_editor=args.retire_editor)
        except Exception as error:   # noqa: BLE001 - one publication's failure must not hide the others
            print(f"{publication_id}: FAILED {type(error).__name__}: {str(error)[:300]}")
            failed = True
            continue
        proposals.append(proposal)
        print("\n".join(describe(proposal, executing=args.execute, approved=bool(args.approved_by))))
        if args.execute:
            done = execute(table, {**proposal, "retire": [dict(r) for r in proposal["retire"]]}, approved_by=args.approved_by)
            print(f"  executed: retired {done['retired']}, added {done['added']}, approved {done['approved']} in {proposal['monitorId']}")
    if args.out:
        Path(args.out).write_text(json.dumps({p["publicationId"]: p for p in proposals}, indent=2, default=str) + "\n")
    if not args.execute:
        print("\nDry run: nothing was written. Add --execute to retire the old queries and write the new ones.")
    return 1 if failed else 0
