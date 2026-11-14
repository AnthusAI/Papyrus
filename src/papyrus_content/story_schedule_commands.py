"""`papyrus stories schedule` and `papyrus stories schedule-list` (docs/scheduled-publishing.md). Both ask the site's ``scheduleItem`` mutation to run an operation of
``story_schedule.OPERATIONS``, the table the console and the MCP tools use too."""

from __future__ import annotations

import json
from typing import Any

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_boolean_option, parse_options, resolve_mutation_apply
from .story_schedule import call_remote, refused_message


def _when(entry: dict[str, Any]) -> str:
    return f"{entry.get('label') or entry.get('scheduledPublishAt')} ({entry.get('scheduledPublishAt')})" if entry.get("label") else str(entry.get("scheduledPublishAt"))


def schedule_line(entry: dict[str, Any]) -> list[str]:
    """The columns that describe one schedule, after ``stories <command> <verb> <lineage>``."""
    columns = [str(entry.get("title") or ""), f"version {entry.get('versionNumber')}", str(entry.get("state")), _when(entry), f"by {entry.get('scheduledBy') or 'unknown'}"]
    if entry.get("message"):
        columns.append(str(entry["message"]))
    return columns


def stories_schedule(flags: list[str]) -> None:
    """papyrus stories schedule --story LINEAGE (--at TIME | --clear) [--item VERSION_ID] [--dry-run] [--json]

    Pins the Story's newest version to a time: at that time the site publishes exactly that version once, by the normal publish path (the Story keeps its first
    publication date; the version records who scheduled it). TIME is an ISO time with an offset or Z (2026-11-13T09:00:00-05:00), or without one (2026-11-13 09:00),
    which is read in the publication's time zone. A wall-clock time that does not exist there (the spring-forward gap) is refused; one that happens twice asks you to
    type the offset. If a newer version is saved first, nothing is published and the editors are told. --clear removes the Story's schedule. A Story has one schedule:
    scheduling again moves it. Writes unless --dry-run (which checks everything and writes nothing). It needs the site's publication time zone (publication.timeZone)."""
    options = parse_options(flags)
    story = normalize_string(options.get("story"))
    if not story:
        raise ValueError("--story is required.")
    clear = parse_boolean_option(options.get("clear"), default=False, label="--clear")
    at = normalize_string(options.get("at"))
    if clear == bool(at):
        raise ValueError("Give --at TIME to schedule, or --clear to remove the schedule.")
    dry_run = not resolve_mutation_apply(options, "stories schedule")
    arguments: dict[str, Any] = {"storyLineageId": story, **({"clear": True} if clear else {"at": at}), **({"itemId": normalize_string(options.get("item"))} if options.get("item") else {}),
                                 **({"dryRun": True} if dry_run else {})}
    client, _ = create_authoring_client()
    response = call_remote(client, "schedule", arguments)
    if response.get("ok") is False:
        raise ValueError(f"stories schedule refused: {refused_message(response)}")
    if options.get("json"):
        print(json.dumps(response, indent=2))
        return
    mode = "dry run" if dry_run else "write"
    if clear:
        print("\t".join(["stories", "schedule", "cleared" if not dry_run else "would clear", story, ", ".join(response.get("itemIds") or []), mode]))
        return
    print("\t".join(["stories", "schedule", "scheduled" if not dry_run else "would schedule", story, response.get("title") or "", f"version {response.get('versionNumber')}",
                     _when(response), f"by {response.get('scheduledBy')}", mode]))
    for note in response.get("notes") or []:
        print(f"stories\tschedule\tnote\t{story}\t{note}")
    for replaced in response.get("replaced") or []:
        print(f"stories\tschedule\treplaced\t{story}\tthe earlier schedule of {replaced}")


def stories_schedule_list(flags: list[str]) -> None:
    """papyrus stories schedule-list [--story LINEAGE] [--from TIME] [--to TIME] [--state scheduled|publishing|blocked|overdue ...] [--json]

    Read only. The Story's schedule (--story) or every schedule of the site between --from and --to (inclusive; both optional), soonest first, from the schedule index:
    one line each with the Story, version, state, time and who scheduled it. State `overdue` is a version whose time has passed and that has not published; `blocked`
    is one a newer version superseded. TIME is read as `schedule --at` reads it."""
    from .options import parse_repeated_option

    options = parse_options(flags)
    arguments: dict[str, Any] = {}
    for flag, name in (("story", "storyLineageId"), ("from", "from"), ("to", "to")):
        if normalize_string(options.get(flag)):
            arguments[name] = normalize_string(options.get(flag))
    states = parse_repeated_option(flags, "state")
    if states:
        arguments["states"] = list(states)
    client, _ = create_authoring_client()
    response = call_remote(client, "schedule_list", arguments)
    if response.get("ok") is False:
        raise ValueError(f"stories schedule-list refused: {refused_message(response)}")
    if options.get("json"):
        print(json.dumps(response, indent=2))
        return
    for entry in response.get("schedules") or []:
        print("\t".join(["stories", "schedule-list", str(entry.get("lineageId")), *schedule_line(entry)]))
    print(f"stories\tschedule-list\t{len(response.get('schedules') or [])} schedules\tnow {response.get('now')}\tpublication time zone {response.get('timeZone') or 'not set'}")
