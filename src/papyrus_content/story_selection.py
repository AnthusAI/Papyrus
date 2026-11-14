"""Natural selection for ideas: the editor agent reads a section's ideas against what the publication stands for and what it has published, and picks only the best.

``select_ideas`` makes one model call per section from the editor's context pack (docs/idea-selection.md). Picking none is a normal result. A rate limit caps the
new Stories in a section: it counts every Story that left the idea stage in the window, by a person or by this step, and at the limit no model is called. A pick
starts research on the Story, recorded and reversible: a person can move it back or spike it. A declined idea stays at the idea stage with the reason on the version,
and is not read again until it has a new version or someone asks with ``again``. Nothing here spikes an idea or writes a Message."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .assignments_workflow import create_research_assignment
from .editorial_context import _body, find_section
from .ideas.items import generated_of
from .newsroom_context_pack import DEFAULT_MAX_CHARACTERS, IDEA_STAGE, IN_PROGRESS_STAGES, Situation, _json_object, build_context_pack, fill, _entry, section_stories
from .reference_stars import latest_stars
from .story_commands import research_assignment_options
from .story_reporting import move_story_stage, to_aws_json

ACTOR = "automation:idea-selection"
PICKED = "picked"
DECLINED = "declined"
OVER_LIMIT = "over_limit"
RECENT_RULE = re.compile(r"^(\d+)(d|s)$")

Llm = Callable[[str, str, dict], dict]


@dataclass(frozen=True)
class SelectionSettings:
    """What "recent" means and how fast new Stories may start. Every one is meant to be experimented with; a run records the values it used."""

    recent_section: Mapping[str, int] = field(default_factory=lambda: {"days": 30})
    recent_site: Mapping[str, int] = field(default_factory=lambda: {"days": 30})
    max_new_stories: int = 1
    per_days: int = 1

    def recorded(self) -> dict[str, Any]:
        return {"recentSection": dict(self.recent_section), "recentSite": dict(self.recent_site), "maxNewStories": self.max_new_stories, "perDays": self.per_days}


def parse_recent(text: str) -> dict[str, int]:
    """``30d`` is thirty days; ``5s`` is the five newest Stories."""
    match = RECENT_RULE.match(str(text).strip())
    if not match:
        raise ValueError(f"Recent is a number of days (30d) or of Stories (5s), not {text!r}.")
    return {"days" if match.group(2) == "d" else "stories": int(match.group(1))}


INSTRUCTIONS = """Choose which of the ideas below this publication should work on now. Be very picky. Most ideas should be declined, and declining all of them is a good answer when none is good enough.

Compare each idea against the publication's mission and policy, the section's mission and policy and kill criteria, and what has recently been published in the section and across the site, and against the Stories already in progress and the other ideas. Pick an idea only when it serves the mission, adds something the publication has not already said, and is worth the reporting it will take. Decline an idea that repeats published or in-progress work, that only summarizes one source, that a kill criterion rules out, or that is merely interesting. Of two ideas on the same subject, pick at most one.

An editor's stars are a strong signal about direction, but they are not a pick. At most {room} of these may be picked now; that is a ceiling, not a target.

Give a decision for every idea, using its handle. List picks first, best first. `reason` is one or two sentences naming what the idea was compared against. For a pick, `direction` tells the reporter what to find out; for a decline, leave it empty."""

SCHEMA = {
    "type": "json_schema", "name": "idea_selection", "strict": True,
    "schema": {"type": "object", "additionalProperties": False, "required": ["decisions"],
               "properties": {"decisions": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["handle", "verdict", "reason", "direction"],
                   "properties": {"handle": {"type": "string"}, "verdict": {"type": "string", "enum": ["pick", "decline"]},
                                  "reason": {"type": "string"}, "direction": {"type": "string"}}}}}},
}


def _moment(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def new_stories_in_window(rows: list[dict[str, Any]], *, cutoff: str) -> list[str]:
    """Stories that left the idea stage since the cutoff, whoever moved them: the rate is of new Stories, not of this step's picks."""
    return [str(row.get("lineageId") or row["id"]) for row in rows
            if any(isinstance(move, dict) and move.get("from") == IDEA_STAGE and str(move.get("at") or "") >= cutoff
                   for move in _json_object(row.get("metadata")).get("stageMoves") or [])]


def undecided_ideas(rows: list[dict[str, Any]], *, again: bool) -> list[dict[str, Any]]:
    """Ideas in the section the step has not decided on in this version, an editor's stars first, then the newest."""
    ideas = [row for row in rows if (row.get("stage") or IDEA_STAGE) == IDEA_STAGE
             and (again or (_json_object(row.get("metadata")).get("selection") or {}).get("versionId") != row["id"])]
    newest = sorted(sorted(ideas, key=lambda row: str(row["id"])), key=lambda row: str(row.get("updatedAt") or row.get("createdAt") or ""), reverse=True)
    return sorted(newest, key=lambda row: -((latest_stars(row) or {}).get("stars") or 0))


def candidate_entries(ideas: list[dict[str, Any]]) -> list[Any]:
    entries = []
    for index, row in enumerate(ideas, start=1):
        stars = latest_stars(row)
        lines = [f"### I{index}: {row.get('headline') or row.get('title') or '(no title)'}", row.get("deck") or "",
                 f"Started by: {'the idea pipeline' if generated_of(row) is not None else 'a person'}",
                 f"Editor stars: {stars['stars']}" if stars else "", _body(row)]
        entries.append(_entry("idea", f"I{index}", "\n".join(line for line in lines if line), row=row))
    return entries


def record_decision(client: Any, row: dict[str, Any], decision: Mapping[str, Any], *, now: str, settings: SelectionSettings, context_hash: str) -> None:
    metadata = _json_object(row.get("metadata"))
    metadata["selection"] = {"verdict": decision["verdict"], "reason": decision["reason"], "at": now, "by": ACTOR, "versionId": row["id"],
                             "contextHash": context_hash, "settings": settings.recorded()}
    client.update_record("Item", {"id": row["id"], "metadata": to_aws_json(metadata)})


def start_research(client: Any, row: dict[str, Any], section: Mapping[str, Any] | None, direction: str) -> str:
    lineage = str(row.get("lineageId") or row["id"])
    result = create_research_assignment(client, research_assignment_options(row, lineage, direction, dict(section) if section else None, actor=ACTOR))
    move_story_stage(client, lineage, "assignment", actor=ACTOR, reason=f"Picked by the editor agent. Research assignment {result['assignmentId']}.")
    return str(result["assignmentId"])


def select_ideas(client: Any, section_id: str, *, llm: Llm, settings: SelectionSettings, apply: bool, again: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    section = find_section(client, section_id)
    if section is None:
        raise ValueError(f"Section not found: {section_id}")
    situation = Situation(client, lineage=None, assignment=None, direction=None, section_id=section_id)
    started_rows = section_stories(situation, (*IN_PROGRESS_STAGES, "published"))
    cutoff = _moment(now - timedelta(days=settings.per_days))
    started = new_stories_in_window(started_rows, cutoff=cutoff)
    room = max(settings.max_new_stories - len(started), 0)
    outcome: dict[str, Any] = {"section": section["id"], "settings": settings.recorded(), "startedInWindow": started, "room": room, "decisions": [], "notRead": 0, "contextHash": None}
    ideas = undecided_ideas(section_stories(situation, (IDEA_STAGE,)), again=again)
    outcome["ideas"] = len(ideas)
    if not room or not ideas:
        outcome["stopped"] = "rate limit reached" if not room else "no idea to decide on"
        return outcome
    pack = build_context_pack(client, profile="editor", section_id=section_id, now=now,
                              recent={"desk_published": dict(settings.recent_section), "publication_published": dict(settings.recent_site)})
    entries, _, _ = fill(candidate_entries(ideas), DEFAULT_MAX_CHARACTERS)
    outcome["notRead"] = len(ideas) - len(entries)
    outcome["contextHash"] = pack["contextHash"]
    user = pack["user"] + "\n\n## The ideas to choose among\n\n" + "\n\n".join(entry["text"] for entry in entries)
    answer = llm(pack["system"] + "\n\n" + INSTRUCTIONS.replace("{room}", str(room)), user, SCHEMA)
    by_handle = {entry["id"]: entry["row"] for entry in entries}
    moment = _moment(now)
    picks = 0
    seen: set[str] = set()
    for item in answer.get("decisions") or []:
        handle = str(item.get("handle"))
        if handle not in by_handle or handle in seen:
            continue
        seen.add(handle)
        row = by_handle[handle]
        verdict, reason, direction = DECLINED, str(item.get("reason") or "").strip(), str(item.get("direction") or "").strip()
        if item.get("verdict") == "pick":
            if picks >= room:
                verdict = OVER_LIMIT
            elif not direction:
                verdict, reason = DECLINED, f"Picked with no direction for the reporter, so not started. {reason}"
            else:
                verdict = PICKED
                picks += 1
        decision = {"lineage": str(row.get("lineageId") or row["id"]), "title": row.get("headline") or row.get("title"), "verdict": verdict, "reason": reason, "direction": direction if verdict == PICKED else ""}
        if apply and verdict != OVER_LIMIT:
            record_decision(client, row, decision, now=moment, settings=settings, context_hash=pack["contextHash"])
            if verdict == PICKED:
                decision["assignmentId"] = start_research(client, row, section, direction)
        outcome["decisions"].append(decision)
    outcome["notDecided"] = len(by_handle) - len(seen)
    return outcome


def select_command(flags: list[str]) -> None:
    """papyrus ideas select (--section <id> | --all-sections) [--recent-section 30d|5s] [--recent-site 30d|5s] [--max-new-stories 1] [--per-days 1] [--again] [--dry-run] [--json]

    The editor agent reads the section's ideas and picks only the best (docs/idea-selection.md). A pick starts research on the Story. --dry-run calls the model and writes nothing."""
    from .graphql_authoring import create_authoring_client
    from .model_defaults import DEFAULT_LLM_MODEL
    from .multi_search_research import openai_llm

    parser = argparse.ArgumentParser(prog="papyrus ideas select")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--section")
    scope.add_argument("--all-sections", action="store_true")
    parser.add_argument("--recent-section", type=parse_recent, default={"days": 30})
    parser.add_argument("--recent-site", type=parse_recent, default={"days": 30})
    parser.add_argument("--max-new-stories", type=int, default=1)
    parser.add_argument("--per-days", type=int, default=1)
    parser.add_argument("--again", action="store_true", help="Decide again on ideas already declined in this version.")
    parser.add_argument("--model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(flags)
    settings = SelectionSettings(recent_section=args.recent_section, recent_site=args.recent_site, max_new_stories=args.max_new_stories, per_days=args.per_days)
    client, _ = create_authoring_client()
    llm = openai_llm(model=args.model)
    sections = [args.section] if args.section else [row["id"] for row in client.safe_list_records("NewsroomSection") if row.get("enabled") is not False]
    outcomes = [select_ideas(client, section, llm=llm, settings=settings, apply=not args.dry_run, again=args.again) for section in sections]
    if args.json:
        print(json.dumps(outcomes, indent=2, ensure_ascii=False))
        return
    for outcome in outcomes:
        print(f"ideas\tselect\t{outcome['section']}\t{outcome['ideas']} ideas\troom for {outcome['room']}\t{outcome.get('stopped') or ''}\t{'dry run' if args.dry_run else 'write'}")
        for decision in outcome["decisions"]:
            print("\t".join(["ideas", "select", decision["verdict"], decision["lineage"], str(decision["title"]), decision["reason"]]))
        if outcome["notRead"]:
            print(f"warning: {outcome['notRead']} ideas did not fit and were not read; the next pass reads them.", file=sys.stderr)
