"""The editor's outline and the copywriter's draft: one model call each, from the standard context pack (docs/story-procedure.md).

``write_outline`` and ``write_draft`` take the model as ``llm`` and write nothing unless ``apply`` is true. Neither publishes. A draft that cites a key it
was not given, or cites nothing when it could, is refused and nothing is saved: citations are the one thing here that can be checked without a model.
Whether the claims are true of their sources is the next step of the procedure (fact_check), not this one."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping
from typing import Any

import yaml

from .newsroom_context_pack import WHOLE_MAX_CHARACTERS, build_context_pack, clean_title, _day, _json_object
from .newsroom_process import assess, print_reminder, story_facts
from .story_reporting import current_reference, current_story_version, link_reference_to_story, mark_story_outline, save_story_version, story_references

AUTHOR = "AI"
CITATION = re.compile(r"\[@([A-Za-z0-9_-]+)\]")
BIBLIOGRAPHY = '::citations{format="apa"}'
STAGES_BEFORE_COPYWRITING = ("idea", "assignment", "reporting")

Llm = Callable[[str, str, dict], dict]

OUTLINE_INSTRUCTIONS = """Write the outline for this Story from what the research found. Say in `enough` whether the research can carry a Story, and in `why` the reason in one sentence. `outline` is Markdown: the point of the Story, then its sections in order, each saying what it claims and which sources carry it, by title. A claim marked as needing a check, unchecked or rejected cannot carry a section. Keep the Story's subject: the idea and the editor's directions define it. Use all the research, not only the newest, and do not narrow the Story to one case unless an editor's direction says to; when you think it should be narrowed, say so in `why` and leave that to the editor. `still_thin` lists what is missing, each as something a reporter could go and find. Write no reader-facing prose."""

OUTLINE_SCHEMA = {
    "type": "json_schema", "name": "story_outline", "strict": True,
    "schema": {"type": "object", "additionalProperties": False, "required": ["enough", "why", "outline", "still_thin"],
               "properties": {"enough": {"type": "boolean"}, "why": {"type": "string"}, "outline": {"type": "string"},
                              "still_thin": {"type": "array", "items": {"type": "string"}}}},
}

DRAFT_INSTRUCTIONS = """Write the draft of this Story. `body` is Markdown without the title. Cite each outside claim at the point of use as [@key], using only the keys listed under "Citation keys". `title`, `deck` and `blurb` are reader-facing: the blurb is two or three lines for listings. Use the breadth of the Story's References; do not rest it on one source when others carry it. `evidence_gaps` lists what you left out or could not support, for the editor; it is empty only when nothing is missing. What the newsroom has not checked goes there and never in the body: readers are told what the sources show and what they do not establish, not what we have yet to do."""

DRAFT_SCHEMA = {
    "type": "json_schema", "name": "story_draft", "strict": True,
    "schema": {"type": "object", "additionalProperties": False, "required": ["title", "deck", "blurb", "body", "evidence_gaps"],
               "properties": {"title": {"type": "string"}, "deck": {"type": "string"}, "blurb": {"type": "string"}, "body": {"type": "string"},
                              "evidence_gaps": {"type": "array", "items": {"type": "string"}}}},
}


def citable_references(client: Any, lineage: str) -> dict[str, dict[str, Any]]:
    """The Story's References by citation key: the key a link already has, else one made from the Reference's lineage, so it is the same on the next draft. A rejected Reference is not citable."""
    found: dict[str, dict[str, Any]] = {}
    for link in story_references(client, lineage):
        reference_lineage = str(link.get("referenceLineageId") or "")
        row = current_reference(client, reference_lineage) if reference_lineage else None
        if row is None or row.get("curationStatus") == "rejected":
            continue
        key = str(link.get("citationKey") or "") or "ref-" + re.sub(r"[^a-z0-9]", "", reference_lineage.lower())[-10:]
        found[key] = {"referenceId": str(row["id"]), "url": row.get("sourceUri"), "title": clean_title(row.get("title"), row.get("sourceUri")),
                      "published": _day(row.get("sourcePublishedAt"))}
    return found


def citation_handles(citable: Mapping[str, Any]) -> dict[str, str]:
    """Short handles for the model, which copies them more reliably than the stored keys. They mean something only within one call."""
    return {f"R{index}": key for index, key in enumerate(sorted(citable), start=1)}


def citation_block(citable: Mapping[str, Mapping[str, Any]], handles: Mapping[str, str]) -> str:
    lines = [f"{handle}: {' | '.join(str(part) for part in (citable[key]['title'], citable[key]['url'], citable[key]['published']) if part)}" for handle, key in handles.items()]
    return "## Citation keys\n\n" + "\n".join(lines)


def csl_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "webpage", "title": row["title"] or row["url"], "URL": row["url"]}
    if row["published"]:
        entry["issued"] = {"date-parts": [[int(part) for part in str(row["published"]).split("-")]]}
    return entry


def checked_citations(body: str, citable: Mapping[str, Any], handles: Mapping[str, str]) -> tuple[str, list[str]]:
    """The body with each handle replaced by its stored key, and the keys it cites. Refuses a handle it was not given, or no citation at all when there could be one."""
    used = list(dict.fromkeys(CITATION.findall(body)))
    unknown = [handle for handle in used if handle not in handles]
    if unknown:
        raise ValueError(f"The draft cites keys it was not given, so nothing was saved: {', '.join(unknown)}.")
    if citable and not used:
        raise ValueError("The draft cites nothing although the Story has References, so nothing was saved.")
    return CITATION.sub(lambda match: f"[@{handles[match.group(1)]}]", body), [handles[handle] for handle in used]


def front_matter_of(row: Mapping[str, Any]) -> str | None:
    return _json_object(row.get("metadata")).get("frontMatterYaml")


def write_outline(client: Any, lineage: str, *, llm: Llm, apply: bool, direction: str | None = None) -> dict[str, Any]:
    pack = build_context_pack(client, profile="editor", story_lineage_id=lineage, direction=direction, max_characters=WHOLE_MAX_CHARACTERS)
    result = llm(pack["system"] + "\n\n" + OUTLINE_INSTRUCTIONS, pack["user"], OUTLINE_SCHEMA)
    thin = [str(item).strip() for item in result.get("still_thin") or [] if str(item).strip()]
    body = str(result["outline"]).strip()
    if thin:
        body += "\n\n## Still thin\n\n" + "\n".join(f"- {item}" for item in thin)
    outcome = {"enough": bool(result["enough"]), "why": str(result["why"]), "body": body, "stillThin": thin, "contextHash": pack["contextHash"], "warnings": pack["warnings"]}
    if apply:
        reason = f"Outline by AI. {'Enough research' if outcome['enough'] else 'Not enough research'}: {outcome['why']} Context {pack['contextHash'][:12]}."
        record = save_story_version(client, lineage, front_matter_yaml=front_matter_of(current_story_version(client, lineage)), body_markus=body, actor=AUTHOR, change_reason=reason)
        mark_story_outline(client, record, actor=AUTHOR)
        outcome["versionId"] = record["id"]
    return outcome


def write_draft(client: Any, lineage: str, *, llm: Llm, apply: bool, direction: str | None = None) -> dict[str, Any]:
    pack = build_context_pack(client, profile="copywriter", story_lineage_id=lineage, direction=direction, max_characters=WHOLE_MAX_CHARACTERS)
    citable = citable_references(client, lineage)
    handles = citation_handles(citable)
    user = pack["user"] + "\n\n" + citation_block(citable, handles)
    result = llm(pack["system"] + "\n\n" + DRAFT_INSTRUCTIONS, user, DRAFT_SCHEMA)
    body, used = checked_citations(str(result["body"]).strip(), citable, handles)
    if BIBLIOGRAPHY not in body:
        body += "\n\n" + BIBLIOGRAPHY
    gaps = [str(item).strip() for item in result.get("evidence_gaps") or [] if str(item).strip()]
    story = current_story_version(client, lineage)
    front = yaml.safe_load(front_matter_of(story) or "") or {}
    front.update({"title": result["title"], "deck": result["deck"], "blurb": result["blurb"], "citations": {key: csl_entry(citable[key]) for key in used}})
    if "headline" in front:
        front["headline"] = result["title"]
    outcome = {"title": result["title"], "deck": result["deck"], "blurb": result["blurb"], "body": body, "cited": used, "evidenceGaps": gaps,
               "contextHash": pack["contextHash"], "warnings": pack["warnings"]}
    if apply:
        stage = "copywriting" if (story.get("stage") or "idea") in STAGES_BEFORE_COPYWRITING else None
        reason = f"Draft by AI. Context {pack['contextHash'][:12]}." + (f" Evidence gaps: {'; '.join(gaps)}" if gaps else "")
        record = save_story_version(client, lineage, front_matter_yaml=yaml.safe_dump(front, sort_keys=False, allow_unicode=True), body_markus=body, actor=AUTHOR,
                                    change_reason=reason, stage=stage)
        for key in used:
            link_reference_to_story(client, lineage, citable[key]["referenceId"], role="cited", actor=AUTHOR, citation_key=key)
        outcome.update(versionId=record["id"], moved=bool(stage))
    return outcome


def warn_missing_steps(client: Any, lineage: str, keys: tuple[str, ...]) -> None:
    """Skipped steps warn and never refuse."""
    for row in assess(story_facts(client, lineage))["steps"]:
        if row["key"] in keys and row["state"] != "done":
            print(f"warning: step '{row['key']}' ({row['title']}) is not done; going on anyway.", file=sys.stderr)


def _command(name: str, flags: list[str]) -> tuple[argparse.Namespace, Any, Llm]:
    from .graphql_authoring import create_authoring_client
    from .model_defaults import DEFAULT_LLM_MODEL
    from .multi_search_research import openai_llm

    parser = argparse.ArgumentParser(prog=f"papyrus stories {name}")
    parser.add_argument("--story", required=True)
    parser.add_argument("--direction", help="The editor's direction for this pass.")
    parser.add_argument("--model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--dry-run", action="store_true", help="Call the model and print the result; save nothing.")
    args = parser.parse_args(flags)
    client, _ = create_authoring_client()
    return args, client, openai_llm(model=args.model)


def stories_outline(flags: list[str]) -> None:
    """papyrus stories outline --story <lineage> [--direction TEXT] [--dry-run]

    The editor's outline, after the research: a model call from the editor's context pack, saved as a new version marked as the outline. Never moves or publishes the Story."""
    args, client, llm = _command("outline", flags)
    warn_missing_steps(client, args.story, ("research",))
    outcome = write_outline(client, args.story, llm=llm, apply=not args.dry_run, direction=args.direction)
    print(f"stories\toutline\t{args.story}\t{'enough research' if outcome['enough'] else 'not enough research'}\t{outcome['why']}\t{'write' if not args.dry_run else 'dry run'}")
    for warning in outcome["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    if args.dry_run:
        print(outcome["body"])
        return
    print(f"stories\toutline\tsaved\t{outcome['versionId']}")
    print_reminder(client, args.story)


def stories_draft(flags: list[str]) -> None:
    """papyrus stories draft --story <lineage> [--direction TEXT] [--dry-run]

    The copywriter's draft: a model call from the copywriter's context pack, saved as a new version, moved to copywriting if it was earlier, its cited References marked, and checked as every save is. Never publishes."""
    from .editorial_commands import check_after_save
    from .story_triggers import deliver_from_environment

    args, client, llm = _command("draft", flags)
    warn_missing_steps(client, args.story, ("research", "outline"))
    outcome = write_draft(client, args.story, llm=llm, apply=not args.dry_run, direction=args.direction)
    print(f"stories\tdraft\t{args.story}\t{outcome['title']}\t{len(outcome['cited'])} cited\t{'write' if not args.dry_run else 'dry run'}")
    for warning in outcome["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    for gap in outcome["evidenceGaps"]:
        print(f"stories\tdraft\tgap\t{gap}")
    if args.dry_run:
        print(json.dumps({key: outcome[key] for key in ("title", "deck", "blurb")}, ensure_ascii=False))
        print(outcome["body"])
        return
    print(f"stories\tdraft\tsaved\t{outcome['versionId']}")
    if outcome["moved"]:
        deliver_from_environment(client, args.story)
    check_after_save(outcome["versionId"])
    print_reminder(client, args.story)
