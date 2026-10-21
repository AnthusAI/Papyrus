"""`papyrus stories ...`: the commands agents and operators use to record reporting work on a story."""

from __future__ import annotations

import json
from pathlib import Path

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options, resolve_mutation_apply
from .story_reporting import (
    STORY_MESSAGE_KINDS,
    advance_stage,
    append_story_message,
    move_story_stage,
    latest_story_version,
    link_reference_to_story,
    save_story_version,
    story_references,
    story_versions,
)


def _required_option(options: dict, name: str) -> str:
    value = normalize_string(options.get(name))
    if not value:
        raise ValueError(f"--{name} is required.")
    return value


def _text_from_option_or_file(options: dict, text_name: str, file_name: str) -> str | None:
    text = options.get(text_name)
    if isinstance(text, str):
        return text
    path = normalize_string(options.get(file_name))
    return Path(path).read_text(encoding="utf-8") if path else None


def stories_save_version(flags: list[str]) -> None:
    """papyrus stories save-version --story <lineage> --body-file <file> [--front-matter-file <file>] --reason <text> --author-label <name> [--stage <stage> | --advance] [--no-check]"""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories save-version")
    lineage_id = _required_option(options, "story")
    body = _text_from_option_or_file(options, "body", "body-file")
    if body is None:
        raise ValueError("--body-file (or --body) is required.")
    client, _ = create_authoring_client()
    latest = latest_story_version(client, lineage_id)
    front_matter = _text_from_option_or_file(options, "front-matter", "front-matter-file")
    if front_matter is None:
        metadata = latest.get("metadata")
        front_matter = (json.loads(metadata) if isinstance(metadata, str) and metadata else {}).get("frontMatterYaml")
    reason = _required_option(options, "reason")
    author = _required_option(options, "author-label")
    next_number = int(latest.get("versionNumber") or 1) + 1
    print(f"stories\tsave-version\t{lineage_id}\tversion {next_number}\t{'write' if apply else 'dry run'}")
    if not apply:
        return
    stage = normalize_string(options.get("stage"))
    if options.get("advance"):
        if stage:
            raise ValueError("Pass --stage or --advance, not both.")
        stage = advance_stage(latest.get("stage"))
    record = save_story_version(client, lineage_id, front_matter_yaml=front_matter, body_markus=body, actor=author, change_reason=reason, stage=stage)
    print(f"stories\tsave-version\tsaved\t{record['id']}")
    if not options.get("no-check"):
        from .editorial_commands import check_after_save

        check_after_save(record["id"])


def stories_versions(flags: list[str]) -> None:
    """papyrus stories versions --story <lineage>"""
    options = parse_options(flags)
    client, _ = create_authoring_client()
    for version in story_versions(client, _required_option(options, "story")):
        print("\t".join(["stories", "versions", str(version.get("versionNumber")), str(version.get("versionState")), str(version.get("versionCreatedAt") or version.get("updatedAt") or ""), str(version.get("versionCreatedBy") or ""), str(version.get("changeReason") or ""), str(version["id"])]))


def stories_link_reference(flags: list[str]) -> None:
    """papyrus stories link-reference --story <lineage> --reference <reference id> --role consulted|cited --author-label <name> [--note <text>] [--citation-key <key>]"""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories link-reference")
    lineage_id = _required_option(options, "story")
    reference_id = _required_option(options, "reference")
    role = _required_option(options, "role")
    author = _required_option(options, "author-label")
    print(f"stories\tlink-reference\t{lineage_id}\t{reference_id}\t{role}\t{'write' if apply else 'dry run'}")
    if not apply:
        return
    client, _ = create_authoring_client()
    result = link_reference_to_story(client, lineage_id, reference_id, role=role, actor=author, note=normalize_string(options.get("note")), citation_key=normalize_string(options.get("citation-key")))
    print(f"stories\tlink-reference\t{result['outcome']}\t{result['relationId']}")


def stories_note(flags: list[str]) -> None:
    """papyrus stories note --story <lineage> --body <text>|--body-file <file> --author-label <name> [--summary <text>] [--kind note|research_packet|reporting_context_packet|draft_note|editor_note] [--reference <reference lineage>] [--version <n>]"""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories note")
    lineage_id = _required_option(options, "story")
    body = _text_from_option_or_file(options, "body", "body-file")
    if not body:
        raise ValueError("--body (or --body-file) is required.")
    author = _required_option(options, "author-label")
    kind = normalize_string(options.get("kind")) or "note"
    if kind not in STORY_MESSAGE_KINDS:
        raise ValueError(f"--kind must be one of {', '.join(STORY_MESSAGE_KINDS)}.")
    summary = normalize_string(options.get("summary")) or body.strip().splitlines()[0][:140]
    version = normalize_string(options.get("version"))
    print(f"stories\tnote\t{lineage_id}\t{kind}\t{'write' if apply else 'dry run'}")
    if not apply:
        return
    client, _ = create_authoring_client()
    message = append_story_message(client, lineage_id, body=body, summary=summary, author_label=author, message_kind=kind, reference_lineage_id=normalize_string(options.get("reference")), version_number=int(version) if version else None)
    print(f"stories\tnote\tposted\t{message['id']}\t#{message['sequenceNumber']}")


def stories_show(flags: list[str]) -> None:
    """papyrus stories show --story <lineage>"""
    options = parse_options(flags)
    lineage_id = _required_option(options, "story")
    client, _ = create_authoring_client()
    versions = story_versions(client, lineage_id)
    latest = versions[0] if versions else {}
    print(f"stories\tshow\t{lineage_id}\t{latest.get('headline') or latest.get('title')}\tstage {latest.get('stage')}\tlatest version {latest.get('versionNumber')} of {len(versions)}")
    for reference in story_references(client, lineage_id):
        print(f"stories\tshow\treference\t{reference['referenceLineageId']}\t{reference['role']}\t{reference.get('citationKey') or ''}")


def stories_create(flags: list[str]) -> None:
    """papyrus stories create --title <text> [--section <key>] [--stage idea|assignment|reporting] [--summary <text>] [--brief <text>] [--with-assignment]"""
    from datetime import datetime, timezone

    from .content_item_lifecycle import build_new_content_item_version, content_item_lineage_id_for_first_work
    from .records import apply_record_changes, build_record_changes

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories create")
    title = _required_option(options, "title")
    stage = normalize_string(options.get("stage")) or "idea"
    if stage not in ("idea", "assignment", "reporting"):
        raise ValueError("--stage must be idea, assignment or reporting.")
    section_key = normalize_string(options.get("section"))
    summary = normalize_string(options.get("summary")) or title
    actor = normalize_string(options.get("actor-label")) or "papyrus-cli"
    now = datetime.now(timezone.utc).isoformat()
    lineage_id = content_item_lineage_id_for_first_work(title=title, first_assignment_id=f"story-create-{now}")
    item = build_new_content_item_version(
        lineage_id=lineage_id, title=title, summary=summary, section_key=section_key, stage=stage, actor_label=actor, now=now
    )
    client, _ = create_authoring_client()
    if section_key and not client.get_record("NewsroomSection", section_key):
        raise ValueError(f"Unknown NewsroomSection for --section {section_key}.")
    print(f"stories\tcreate\t{lineage_id}\tstage {stage}\t{'write' if apply else 'dry run'}")
    if not apply:
        if options.get("with-assignment"):
            print("stories\tcreate\twith-assignment\ta reporting.candidate Assignment would also be opened")
        return
    apply_record_changes(client, build_record_changes(client, [{"modelName": "Item", "expected": item}]))
    print(f"stories\tcreate\tcreated\t{item['id']}")
    if options.get("with-assignment"):
        from .assignments_workflow import create_reporting_assignment

        create_reporting_assignment(client, {**options, "content-item": lineage_id, "summary": summary})


def stories_move(flags: list[str]) -> None:
    """papyrus stories move --story <lineage> --stage <stage> [--reason <text>] [--author-label <name>]"""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories move")
    lineage_id = _required_option(options, "story")
    stage = _required_option(options, "stage")
    from .content_item_lifecycle import require_content_item_stage

    require_content_item_stage(stage)
    print(f"stories\tmove\t{lineage_id}\t{stage}\t{'write' if apply else 'dry run'}")
    if not apply:
        return
    client, _ = create_authoring_client()
    result = move_story_stage(
        client, lineage_id, stage, actor=normalize_string(options.get("author-label")) or "papyrus-cli",
        reason=normalize_string(options.get("reason")),
    )
    print(f"stories\tmove\t{'moved' if result['changed'] else 'unchanged'}\t{result['from']}\t{result['stage']}")
