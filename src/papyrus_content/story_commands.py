"""`papyrus stories ...`: the commands agents and operators use to record reporting work on a story."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .console_links import print_console_rows, story_links
from .audience_lenses import lens_lines, lens_payload, lens_step_states
from .graphql_authoring import create_authoring_client
from .newsroom_process import assess, next_lines, print_next_lines, print_reminder, reminder_assessment, step_lines, story_facts, warn_skipped
from .options import normalize_string, parse_boolean_option, parse_options, parse_repeated_option, resolve_mutation_apply
from .story_reporting import (
    STAGE_MOVES_KEY,
    STORY_MESSAGE_KINDS,
    advance_stage,
    append_story_message,
    create_story,
    move_story_stage,
    current_story_version,
    link_reference_to_story,
    mark_story_outline,
    published_story_version,
    repair_story_versions,
    save_story_version,
    story_messages,
    utc_now_iso,
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


def _version_author(options: dict, apply: bool, client) -> str:
    """Who a saved version names: the signed-in person (the session's label), or --author-label on the IAM lane, where it is required."""
    from .operator_errors import OperatorError
    from .user_auth_mode import user_auth_requested

    label = normalize_string(options.get("author-label"))
    if not user_auth_requested():
        if not label:
            raise ValueError("--author-label is required on the IAM lane, where there is no sign-in to name the author.")
        return label
    if not apply:
        return label or "the signed-in person"
    if label:
        print("stories\tsave-version\twarning\t--author-label is ignored: the version records the person who signed in.", file=sys.stderr)
    from .cli_user_auth import signed_in_label

    author = signed_in_label(client.endpoint)
    if not author:
        raise OperatorError("The version was not saved: the signed-in session names no one. Run `papyrus whoami` to check it.")
    return author


def stories_save_version(flags: list[str]) -> None:
    """papyrus stories save-version --story <lineage> --body-file <file> [--front-matter-file <file>] --reason <text> [--author-label <name>] [--stage <stage> | --advance] [--outline] [--no-check] [--images <dir> [--bucket <bucket>] [--identity-pool-id <id>]]

    Signed in, the version records the person who signed in (the label the session holds) as its author, as `link-reference` does;
    --author-label is ignored there (the backend does not verify a name, so the CLI never lets one be made up). On the IAM lane
    (an operator's AWS credentials) --author-label is required and is recorded as given.

    --images <dir> uploads every local picture the body uses (::image{src=...} and ![](...) whose path resolves under
    <dir>), plus a matching <name>.dark.<ext> or srcDark file, as the newsroom editor's "Insert image" would: the same
    MediaAsset rows and S3 objects (media/assets/<slug>/<file>), then saves the body with src (and srcDark) rewritten
    to the stored paths. Files over 10 MB, of a type other than PNG/JPEG/GIF/WebP/AVIF/SVG, or whose dark version has
    a different aspect ratio (over 0.5%) are rejected by name before anything is written; --dry-run prints the upload
    plan and writes nothing. Re-running is idempotent: a file whose content is already stored for the story keeps its exact
    srcPath, so the S3 key and the body reference do not change; a name that holds different content gets -2, -3 (never
    overwritten). MediaAsset rows are keyed by story VERSION (media-<version id>-<hash of srcPath>, as the editor and
    version carry-forward do), so each saved version has its own rows pointing at the same S3 objects. The path is
    media/assets/<slug>/<file> with the slug the story has when the file is first stored (a story without a slug has
    draft-unsectioned-<hash>, exactly what the editor uses). It does NOT move: publishing, set-slug and a later section
    change never rewrite media keys or body references (the body keeps the stored srcPath), so the path is stable after
    publish. Auth: both lanes work. With
    PAPYRUS_GRAPHQL_AUTH=iam the AWS credentials write to S3; with PAPYRUS_GRAPHQL_AUTH=user (editor or admin group)
    the signed-in ID token is traded for temporary credentials from the site's Cognito identity pool
    (--identity-pool-id, PAPYRUS_IDENTITY_POOL_ID, amplify_outputs.json, or the identity pool the signed-in site publishes in
    /.well-known/papyrus-site.json). Signed in, --bucket, PAPYRUS_MEDIA_BUCKET and --identity-pool-id win; otherwise the site's
    published media bucket and identity pool are used, so no outputs file is needed. A site that publishes neither (it runs an
    older Papyrus) fails with a message that says to pass the flags.
    """
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories save-version")
    lineage_id = _required_option(options, "story")
    body = _text_from_option_or_file(options, "body", "body-file")
    if body is None:
        raise ValueError("--body-file (or --body) is required.")
    images_dir = normalize_string(options.get("images"))
    client, _ = create_authoring_client()
    latest = current_story_version(client, lineage_id)
    front_matter = _text_from_option_or_file(options, "front-matter", "front-matter-file")
    if front_matter is None:
        metadata = latest.get("metadata")
        front_matter = (json.loads(metadata) if isinstance(metadata, str) and metadata else {}).get("frontMatterYaml")
    reason = _required_option(options, "reason")
    author = _version_author(options, apply, client)
    next_number = int(latest.get("versionNumber") or 1) + 1
    image_plan = None
    if images_dir:
        from .story_images import plan_story_images

        from .story_images import existing_assets

        stored = [
            row for version in story_versions(client, lineage_id)
            for row in client.list_by_index("mediaAssetsByItemAndSortKey", version["id"])
        ]
        image_plan = plan_story_images(body, Path(images_dir), slug=latest["slug"], existing=existing_assets(stored), front_matter=front_matter)
        body = image_plan.body
        if image_plan.front_matter is not None:
            front_matter = image_plan.front_matter
    header = f"stories\tsave-version\t{lineage_id}\tversion {next_number}\t"
    plan_output: list[str] = []
    if image_plan is not None:
        from .story_images import plan_lines
        from .story_reporting import planned_version_record_id

        plan_output = list(plan_lines(image_plan, planned_version_record_id(client, lineage_id)))
    if not apply:
        print(header + "dry run")
        for line in plan_output:
            print(line)
        return
    stage = normalize_string(options.get("stage"))
    if options.get("advance"):
        if stage:
            raise ValueError("Pass --stage or --advance, not both.")
        stage = advance_stage(latest.get("stage"))
    upload_output: list[str] = []
    if image_plan is not None and image_plan.images:
        from .story_images import open_media_store, upload_planned_images

        store = open_media_store(normalize_string(options.get("bucket")), normalize_string(options.get("identity-pool-id")))
        upload_output = [f"stories\tsave-version\timage-{outcome}\t{image.storage_path}" for image, outcome in upload_planned_images(image_plan, store)]
    record = save_story_version(
        client, lineage_id, front_matter_yaml=front_matter, body_markus=body, actor=author, change_reason=reason, stage=stage,
        media_rows=image_plan.media_rows if image_plan is not None else None,
    )
    print(header + "write")
    for line in [*plan_output, *upload_output]:
        print(line)
    print(f"stories\tsave-version\tsaved\t{record['id']}")
    print_console_rows("stories", "save-version", lambda base: story_links(base, lineage_id, record["id"], f"editor page of the version just saved (version {next_number})"))
    if options.get("outline"):
        mark_story_outline(client, record, actor=author)
        print(f"stories\tsave-version\toutline\t{record['id']}")
    if stage and stage != (latest.get("stage") or "idea"):
        from .story_triggers import deliver_from_environment

        deliver_from_environment(client, lineage_id)
    if not options.get("no-check"):
        from .editorial_commands import check_after_save

        check_after_save(record["id"])
    print_reminder(client, lineage_id)


def stories_versions(flags: list[str]) -> None:
    """papyrus stories versions --story <lineage>"""
    options = parse_options(flags)
    client, _ = create_authoring_client()
    for version in story_versions(client, _required_option(options, "story")):
        print("\t".join(["stories", "versions", str(version.get("versionNumber")), str(version.get("versionState")), str(version.get("versionCreatedAt") or version.get("updatedAt") or ""), str(version.get("versionCreatedBy") or ""), str(version.get("changeReason") or ""), str(version["id"])]))


def stories_repair_versions(flags: list[str]) -> None:
    """papyrus stories repair-versions --story <lineage> [--dry-run]

    Renumbers the lineage's records 1..n by creation order, chains previousVersionId, and leaves exactly one record
    current (the live one if published, else the newest). Content is not changed. Dry run unless applied."""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories repair-versions")
    lineage_id = _required_option(options, "story")
    client, _ = create_authoring_client()
    updates = repair_story_versions(client, lineage_id, apply=apply)
    for update in updates:
        print("\t".join(["stories", "repair-versions", str(update["id"]), json.dumps({k: v for k, v in update.items() if k != "id"})]))
    print(f"stories\trepair-versions\t{lineage_id}\t{len(updates)} record(s) {'updated' if apply else 'would change (dry run)'}")


def stories_head_index(flags: list[str]) -> None:
    """papyrus stories head-index [--apply] [--dry-run] [--stage <stage> ...] [--rate <writes per second>]

    Fills in, and checks, the head stage key on the site's story rows (docs/plans/story-head-stage-index.md): only the head row of each story
    carries headStageKey, so the head stage index holds one row per story. Reads the old stage index once, stage by stage, picks each story's head
    (the row marked current, else the one not superseded; the newest when a muddled story has several), sets the key on the head where it is
    missing or wrong and removes it from any other row that is not superseded. A superseded row is never written. Only rows that differ are
    written, each with its own updatedAt (no card jumps to the top of its column), at most --rate a second (default 5).

    A DRY RUN unless --apply: it prints one line per row it would change, the muddled stories to fix with `stories repair-versions`, and a summary
    (stories, heads to set, keys to remove, already right, muddled, no head, superseded with key). A dry run that reports 0 heads to set and 0 keys
    to remove is the health check. Run it again after --apply: it writes nothing. On a site whose data API has no headStageKey yet the dry run
    counts every head as needing it and --apply refuses (it needs the deploy that adds the head stage index)."""
    from .story_head_index import DEFAULT_RATE, run_head_index

    options = parse_options(flags)
    apply = parse_boolean_option(options.get("apply"), default=False, label="--apply")
    if apply and parse_boolean_option(options.get("dry-run"), default=False, label="--dry-run"):
        raise ValueError("Pass --apply or --dry-run, not both.")
    rate = float(options.get("rate") or DEFAULT_RATE)
    if rate <= 0 or rate > 25:
        raise ValueError("--rate must be more than 0 and at most 25 writes a second.")
    stages = tuple(parse_repeated_option(flags, "stage")) or None
    client, _ = create_authoring_client()
    run_head_index(client, apply=apply, stages=stages, rate=rate)


def stories_repair_image_paths(flags: list[str]) -> None:
    """papyrus stories repair-image-paths --story <lineage> [--write] [--bucket <bucket>] [--identity-pool-id <id>]

    Brings the pictures of a story saved with `save-version --images` before the one-key rule (a tenant site stored them at
    media/<tenant>/assets/<slug>/<file>) to media/assets/<slug>/<file>, the key the renditions are made and looked up under.
    Objects are copied inside the bucket, not uploaded again (a row whose object is already at media/<srcPath> is only re-pointed), and the story's
    MediaAsset and PublishedMediaAsset rows are pointed at the new keys; objects are never deleted. Dry run unless --write is given (the usual --dry-run default does not apply: this command only plans until told).
    Writing to the bucket needs the same access `save-version --images` does (the editor's temporary credentials when signed in).
    The copies make the bucket announce new objects, which is what makes the renditions; `papyrus ops content renditions --source
    assets/<slug>/<file>` asks for them again."""
    from .story_image_repair import apply_image_path_repair, plan_image_path_repair, plan_lines, story_media_rows, story_published_media_rows
    from .story_images import open_media_store

    options = parse_options(flags)
    if options.get("apply") is not None or options.get("dry-run") is not None:
        raise ValueError("stories repair-image-paths plans by default and writes only with --write; --apply and --dry-run are not used.")
    write = parse_boolean_option(options.get("write"), default=False, label="--write")
    lineage_id = _required_option(options, "story")
    client, _ = create_authoring_client()
    store = None
    try:
        store = open_media_store(normalize_string(options.get("bucket")), normalize_string(options.get("identity-pool-id")))
    except Exception as error:   # a plan can still be printed without the bucket; --write cannot
        if write:
            raise
        print(f"stories\trepair-image-paths\t{lineage_id}\tnote\tthe bucket was not checked: {error}")
    plan = plan_image_path_repair(
        story_media_rows(client, lineage_id), story_published_media_rows(client, lineage_id), exists=store.exists if store else None
    )
    for line in plan_lines(lineage_id, plan):
        print(line)
    if not plan.needed:
        print(f"stories\trepair-image-paths\t{lineage_id}\tnothing to repair\t{plan.already_canonical} picture row(s) already at media/<srcPath>")
        return
    if not write:
        copies = len(plan.copies) - len(plan.repoint_only)
        print(f"stories\trepair-image-paths\t{lineage_id}\tdry run\t{copies} object(s) to copy, {len(plan.row_updates)} media row(s) and {len(plan.published_row_updates)} published media row(s) to update; pass --write to do it")
        return
    results = apply_image_path_repair(client, store, plan)
    for kind, subject, outcome in results:
        print(f"stories\trepair-image-paths\t{lineage_id}\t{kind}-{outcome}\t{subject}")
    if any(outcome in ("source-missing", "left-alone") for _kind, _subject, outcome in results):
        raise SystemExit(1)


def stories_link_reference(flags: list[str]) -> None:
    """papyrus stories link-reference --story <lineage> --reference <reference id> --role consulted|cited|based_on [--author-label <name>] [--note <text>] [--citation-key <key>]

    Signed in, the link records the person who signed in (the label the session holds) as who added it; --author-label is ignored there, so a
    link never names someone else. On the IAM lane (an operator's AWS credentials) --author-label is required and is recorded as given.
    The `write` line prints only after the link was saved."""
    from .operator_errors import OperatorError
    from .user_auth_mode import user_auth_requested

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories link-reference")
    lineage_id = _required_option(options, "story")
    reference_id = _required_option(options, "reference")
    role = _required_option(options, "role")
    as_person = user_auth_requested()
    label = normalize_string(options.get("author-label"))
    if not as_person and not label:
        raise ValueError("--author-label is required on the IAM lane, where there is no sign-in to name the author.")
    if not apply:
        print(f"stories\tlink-reference\t{lineage_id}\t{reference_id}\t{role}\tdry run")
        return
    if as_person and label:
        print("stories\tlink-reference\twarning\t--author-label is ignored: the link records the person who signed in.", file=sys.stderr)
    client, _ = create_authoring_client()
    if as_person:
        from .cli_user_auth import signed_in_label

        author = signed_in_label(client.endpoint)
        if not author:
            raise OperatorError("The link was not saved: the signed-in session names no one. Run `papyrus whoami` to check it.")
    else:
        author = label
    result = link_reference_to_story(client, lineage_id, reference_id, role=role, actor=author, note=normalize_string(options.get("note")), citation_key=normalize_string(options.get("citation-key")))
    print(f"stories\tlink-reference\t{lineage_id}\t{reference_id}\t{role}\twrite")
    print(f"stories\tlink-reference\t{result['outcome']}\t{result['relationId']}")
    print_reminder(client, lineage_id)


def stories_link_story(flags: list[str]) -> None:
    """papyrus stories link-story --story <lineage|slug> (--to <lineage|slug> [--to ...] | --reference <reference id> [--reference ...]) [--note <text>] [--author-label <name>] [--no-rerender] [--dry-run] [--json]

    Links a story to one or more other stories (an article to related articles, a larger story to several posts) for its See also block. There is
    one relation, `see_also`, and it cannot be chosen: no relation name is accepted (`--relation see_also` is tolerated, anything else is refused).
    Every story must exist and none may be the story itself; all are checked before anything is written. The link is symmetric, so one that exists in
    either direction is reported as `exists` and nothing is written (safe to repeat). A line per target gives its title, type and stage; a target that
    is not published yet gets a warning on stderr, because the public See also block shows published stories only. Signed in, the link records the
    person who signed in (--author-label is ignored); on the IAM lane --author-label is required. The `write` line prints only after the link was
    saved. Links are only created: removing one is not a command yet (docs/story-reporting.md).

    ``--reference REFERENCE_ID`` (repeatable, with or without --to) links the story to an accepted Reference with the same `see_also` ("read this source too";
    directional, story to Reference). Every Reference must exist and be accepted, or nothing at all is written: only accepted References are shown on the
    page, and there is no override. A line per Reference gives its title, host and curation status.

    After a real write that created a link, the published stories whose page changed (both ends of a story link, the story of a Reference link) are re-rendered
    at once with no purge (`rerender  LINEAGE  no purge  ok`; visible within about five minutes). A failure is a warning, never a failed command; --no-rerender skips it."""
    from .operator_errors import OperatorError
    from .story_links import STORY_LINK_RELATION, check_official_relation, link_story_set, resolve_link_targets
    from .user_auth_mode import user_auth_requested

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories link-story")
    story_ref = _required_option(options, "story")
    reference_ids = parse_repeated_option(flags, "reference")
    if not parse_repeated_option(flags, "to") and not reference_ids:
        raise ValueError("--to or --reference is required (repeat either to link several).")
    check_official_relation(options.get("relation"))
    as_json = bool(options.get("json"))
    as_person = user_auth_requested()
    label = normalize_string(options.get("author-label"))
    if not as_person and not label:
        raise ValueError("--author-label is required on the IAM lane, where there is no sign-in to name the author.")
    client, _ = create_authoring_client()
    from .story_links import link_reference_set, resolve_link_references

    if parse_repeated_option(flags, "to"):
        story, others = resolve_link_targets(client, story_ref, parse_repeated_option(flags, "to"))
    else:
        from .story_links import resolve_story

        story, others = resolve_story(client, story_ref), []
    references = resolve_link_references(client, reference_ids)   # all checked before anything is written
    lineage_id = story.get("lineageId") or story["id"]
    author = None
    if apply:
        if as_person:
            if label:
                print("stories\tlink-story\twarning\t--author-label is ignored: the link records the person who signed in.", file=sys.stderr)
            from .cli_user_auth import signed_in_label

            author = signed_in_label(client.endpoint)
            if not author:
                raise OperatorError("The link was not saved: the signed-in session names no one. Run `papyrus whoami` to check it.")
        else:
            author = label

    def show(row: dict) -> None:
        if as_json:
            return
        print("\t".join(["stories", "link-story", lineage_id, row["lineageId"], STORY_LINK_RELATION, row["title"], f"type {row['type']}", f"stage {row['stage']}", row["outcome"]]))
        if row.get("warning"):
            print(f"stories\tlink-story\twarning\t{row['warning']}", file=sys.stderr)

    def show_reference(row: dict) -> None:
        if as_json:
            return
        print("\t".join(["stories", "link-story", lineage_id, row["referenceId"], STORY_LINK_RELATION, row["title"], f"host {row['host']}", f"status {row['status']}", row["outcome"]]))
        if row.get("warning"):
            print(f"stories\tlink-story\twarning\t{row['warning']}", file=sys.stderr)

    note = normalize_string(options.get("note"))
    rows = link_story_set(client, story, others, actor=author, note=note, apply=apply, on_row=show)
    reference_rows = link_reference_set(client, story, references, actor=author, note=note, apply=apply, on_row=show_reference)
    from .story_rerender import announce, progress_line, rerender_after_write

    wrote = [row for row in rows if row["outcome"] == "write"]
    changed = [lineage_id, *(row["lineageId"] for row in wrote)] if wrote or any(row["outcome"] == "write" for row in reference_rows) else []
    done = rerender_after_write(client, changed, enabled=apply and not parse_boolean_option(options.get("no-rerender"), default=False, label="--no-rerender"), progress=progress_line)
    if as_json:
        print(json.dumps({"ok": True, "story": lineage_id, "dryRun": not apply, "links": rows, "referenceLinks": reference_rows, "rerendered": done["rerendered"]}, indent=2))
    announce(done, quiet=as_json)



def _one_line(error: BaseException) -> str:
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    return lines[0] if lines else error.__class__.__name__


def stories_note(flags: list[str]) -> None:
    """papyrus stories note --story <lineage> --body <text>|--body-file <file> [--summary <text>] [--kind note|research_packet|reporting_context_packet|draft_note|editor_note] [--reference <reference lineage>] [--version <n>] [--author-label <name>]

    A person's note. Signed in, the newsroom stamps the author from your sign-in (``postMessage``); --author-label is ignored there.
    An AI agent never uses this: it records its work with `stories agent-note`. On the IAM lane (an operator's AWS credentials) --author-label
    is required and the message is written as a system message from an operator, not as a person."""
    from .operator_errors import GraphQLRequestError, OperatorError
    from .user_auth_mode import user_auth_requested

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories note")
    lineage_id = _required_option(options, "story")
    body = _text_from_option_or_file(options, "body", "body-file")
    if not body:
        raise ValueError("--body (or --body-file) is required.")
    kind = normalize_string(options.get("kind")) or "note"
    if kind not in STORY_MESSAGE_KINDS:
        raise ValueError(f"--kind must be one of {', '.join(STORY_MESSAGE_KINDS)}.")
    as_person = user_auth_requested()
    label = normalize_string(options.get("author-label"))
    if not as_person and not label:
        raise ValueError("--author-label is required on the IAM lane, where there is no sign-in to name the author.")
    summary = normalize_string(options.get("summary")) or body.strip().splitlines()[0][:140]
    version = normalize_string(options.get("version"))
    if not apply:
        print(f"stories\tnote\t{lineage_id}\t{kind}\tdry run")
        return
    if as_person and label:
        print("stories\tnote\twarning\t--author-label is ignored: the newsroom names the author from your sign-in.", file=sys.stderr)
    client, _ = create_authoring_client()
    try:
        message = append_story_message(
            client, lineage_id, body=body, summary=summary, author_label=None if as_person else label, message_kind=kind,
            reference_lineage_id=normalize_string(options.get("reference")), version_number=int(version) if version else None, as_person=as_person,
        )
    except GraphQLRequestError as error:
        raise OperatorError(f"The note was not saved: {_one_line(error)}") from error
    print(f"stories\tnote\t{lineage_id}\t{kind}\twrite")
    print(f"stories\tnote\tposted\t{message['id']}\t#{message['sequenceNumber']}")
    if message.get("threadWarning"):
        print(f"stories\tnote\twarning\tThe note is saved, but the conversation's summary line was not updated: {message['threadWarning']}", file=sys.stderr)


ADD_STORY_AGENT_NOTE_MUTATION = "mutation AddStoryAgentNote($input: AWSJSON!) { addStoryAgentNote(input: $input) }"


def stories_agent_note(flags: list[str]) -> None:
    """papyrus stories agent-note --story <lineage> --agent <name> --body <text>|--body-file <file> [--summary <text>] [--reference <reference lineage>] [--version <n>]

    An AI agent's note on a Story. It is kept as an attachment owned by the Story and shown labelled as AI; it is never a Message (Messages
    come only from people). The newsroom records who ran the agent from the sign-in; --agent is only a label. IAM lane: an operator's credentials."""
    from .operator_errors import GraphQLRequestError, OperatorError
    from .story_agent_notes import clean_agent_name, save_agent_note
    from .user_auth_mode import user_auth_requested

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories agent-note")
    lineage_id = _required_option(options, "story")
    agent = clean_agent_name(_required_option(options, "agent"))
    body = _text_from_option_or_file(options, "body", "body-file")
    if not body or not body.strip():
        raise ValueError("--body (or --body-file) is required.")
    summary = normalize_string(options.get("summary"))
    reference = normalize_string(options.get("reference"))
    version = normalize_string(options.get("version"))
    if not apply:
        print(f"stories\tagent-note\t{lineage_id}\t{agent}\tdry run")
        return
    client, _ = create_authoring_client()
    try:
        if user_auth_requested():
            payload = {"lineageId": lineage_id, "agent": agent, "body": body, "summary": summary, "referenceLineageId": reference, "versionNumber": int(version) if version else None}
            answer = client.graphql(ADD_STORY_AGENT_NOTE_MUTATION, {"input": json.dumps({key: value for key, value in payload.items() if value is not None})}).get("addStoryAgentNote")
            result = json.loads(answer) if isinstance(answer, str) else (answer or {})
            if result.get("ok") is not True:
                raise OperatorError("The agent note was not saved: " + "; ".join(str(entry.get("message") or entry) for entry in result.get("errors") or []) if result.get("errors") else "The agent note was not saved.")
        else:
            result = save_agent_note(client, lineage_id, agent=agent, body=body, summary=summary, reference_lineage_id=reference, version_number=int(version) if version else None, by_kind="operator")
    except GraphQLRequestError as error:
        raise OperatorError(f"The agent note was not saved: {_one_line(error)}") from error
    except ValueError as error:
        raise OperatorError(f"The agent note was not saved: {_one_line(error)}") from error
    print(f"stories\tagent-note\t{lineage_id}\t{agent}\twrite")
    print(f"stories\tagent-note\tsaved\t{result['attachmentId']}")


def stories_show(flags: list[str]) -> None:
    """papyrus stories show --story <lineage> [--bucket day|week|none] [--json]

    --json prints only the story, its `related` stories (either end of a link: title, type, stage, published, note) and `unofficialRelations`
    (item-to-item relations whose name is not the official `see_also`, which the See also block never shows). After the headline line, a `signals` line (type, section, bucket, stars, source, votes, words, published) and, for an editor rating, a `rating` line (ratedBy, ratedAt)."""
    options = parse_options(flags)
    lineage_id = _required_option(options, "story")
    client, _ = create_authoring_client()
    versions = story_versions(client, lineage_id)
    latest = current_story_version(client, lineage_id) if versions else {}
    if options.get("json"):
        from .story_links import related_references, related_stories, unofficial_item_relations

        print(json.dumps({"ok": True, "story": lineage_id, "title": latest.get("headline") or latest.get("title"), "type": latest.get("type"), "stage": latest.get("stage"),
                          "related": related_stories(client, lineage_id) if versions else [],
                          "relatedReferences": related_references(client, lineage_id) if versions else [],
                          "unofficialRelations": unofficial_item_relations(client, lineage_id) if versions else []}, indent=2))
        return
    print(f"stories\tshow\t{lineage_id}\t{latest.get('headline') or latest.get('title')}\tstage {latest.get('stage')}\tcurrent version {latest.get('versionNumber')} of {len(versions)}")
    metadata = latest.get("metadata")
    metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
    from .home_page.ordering import utc_today
    from .projection.standard.config import DEFAULT_STORY_BUCKET
    from .story_signals import signals

    if versions:
        print_console_rows("stories", "show", lambda base: story_links(base, lineage_id, latest["id"], f"editor page of the current version (version {latest.get('versionNumber')})"))
        signal = signals(latest, normalize_string(options.get("bucket")) or DEFAULT_STORY_BUCKET, utc_today())
        print("\t".join(["stories", "show", "signals", f"type {signal['type']}", f"section {signal['section']}", f"bucket {signal['bucket']}",
                         f"stars {signal['stars']}", f"source {signal['source']}", f"votes {signal['votes']}", f"words {signal['words']}", f"published {signal['published']}"]))
        if signal["source"] == "editor":
            print("\t".join(["stories", "show", "rating", f"ratedBy {signal['ratedBy']}", f"ratedAt {signal['ratedAt']}"]))
    for move in metadata.get(STAGE_MOVES_KEY) or []:
        print("\t".join(["stories", "show", "moved", str(move.get("at") or ""), f"{move.get('from')} -> {move.get('to')}", str(move.get("by") or ""), str(move.get("reason") or "")]))
    for reference in story_references(client, lineage_id):
        print(f"stories\tshow\treference\t{reference['referenceLineageId']}\t{reference['role']}\t{reference.get('citationKey') or ''}")
    if versions:
        from .story_links import related_stories, unofficial_item_relations

        for linked in related_stories(client, lineage_id):
            print("\t".join(["stories", "show", "related", linked["lineageId"], linked["title"], f"type {linked['type']}", f"stage {linked['stage']}", str(linked.get("note") or "")]))
        from .story_links import related_references

        for linked in related_references(client, lineage_id):
            print("\t".join(["stories", "show", "see-also-reference", linked["referenceId"], linked["title"], f"host {linked['host']}", f"status {linked['status']}", str(linked.get("note") or "")]))
        for odd in unofficial_item_relations(client, lineage_id):
            print("\t".join(["stories", "show", "unofficial-relation", odd["relationId"], odd["predicate"], odd["otherLineageId"], "seeded type" if odd["knownType"] else "unknown name",
                             "not shown as a Related story"]))
    for message in story_messages(client, lineage_id):
        summary = " ".join(str(message.get("summary") or message.get("content") or "").split())
        print("\t".join(["stories", "show", "message", str(message.get("createdAt") or ""), f"{message.get('authorLabel') or message.get('role') or 'unknown'} ({message.get('messageKind') or 'message'})", summary]))
    from .story_agent_notes import story_agent_notes

    for note in story_agent_notes(client, lineage_id) if versions else []:
        summary = " ".join(str(note.get("summary") or note.get("error") or "").split())
        print("\t".join(["stories", "show", "agent-note", str(note.get("createdAt") or ""), f"AI agent {note.get('agent') or 'unknown'}", summary]))


def stories_list(flags: list[str]) -> None:
    """papyrus stories list [--stage <stage>] [--section <id|slug|name>] [--type article|post] [--stars N | --min-stars N | --max-stars N]
    [--sort updated|stars|rank] [--bucket day|week|none] [--limit N]

    Read only. Every Story of the stage (or of every board stage), one line each, whether it is still a draft or already published: the same Stories the Stories
    board shows (a replaced, superseded version is never a Story of its own). The last line is `stories list N of TOTAL`: --limit N (default 50) prints the
    first N, so a TOTAL above N means more exist; raise --limit to see them. One line per Story: stories, list, lineage id (the id `stories show --story` takes), stage, section, title, then the signals the layouts use:
    stars (the effective quality rating, 0 unrated), source (editor|none), votes, bucket (the rolling window, week:0 is the last seven days), type, words,
    published (last-published date). Without --stage it lists every board stage except spiked and held. --sort updated (default) is newest change first;
    --sort stars is rated high to low, unrated last; --sort rank is what the Articles and Posts page shows first (newest bucket first, rated Stories first
    inside it): it uses the projection's own ranking code with the site's default bucket, or --bucket. --stars 0 finds unrated Stories; --min-stars and
    --max-stars match rated Stories only. Ratings are private newsroom data."""
    from .story_signals import list_stories, optional_stars

    options = parse_options(flags)
    limit = int(normalize_string(options.get("limit")) or 50)
    client, _ = create_authoring_client()
    stories, total = list_stories(
        client, stage=normalize_string(options.get("stage")), section=normalize_string(options.get("section")), story_type=normalize_string(options.get("type")),
        stars=optional_stars(options, "stars"), min_stars=optional_stars(options, "min-stars"), max_stars=optional_stars(options, "max-stars"),
        sort=normalize_string(options.get("sort")) or "updated", bucket=normalize_string(options.get("bucket")), limit=limit)
    for story in stories:
        print("\t".join(["stories", "list", str(story["lineageId"]), story["stage"], story["section"], story["title"], str(story["stars"]), story["source"],
                         str(story["votes"]), story["bucket"], story["type"], str(story["words"]), story["published"]]))
    print(f"stories\tlist\t{len(stories)} of {total}")


def stories_set_stars(flags: list[str]) -> None:
    """papyrus stories set-stars --story <lineage> --stars <0-5> [--agent <your name>] [--dry-run]

    Sets the editor's rating of a Story (1 to 5; 0 clears it) as the signed-in person, through the newsroom's setItemStars mutation (the one the console
    calls), which also re-renders the listing pages whose order changed. It does not republish the Story. It writes unless you pass --dry-run. It sets the
    editor value only; `stories show` also prints the effective rating, which can differ once votes are aggregated."""
    from .story_signals import set_story_stars, validated_stars

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories set-stars")
    lineage_id = _required_option(options, "story")
    if options.get("stars") is None or options.get("stars") is True:
        raise ValueError("stories set-stars requires --stars 0 to 5 (0 clears the rating).")
    stars = validated_stars(options["stars"])
    client, _ = create_authoring_client()
    result = set_story_stars(client, lineage_id, stars, apply=apply, agent=normalize_string(options.get("agent")))
    print("\t".join(["stories", "set-stars", lineage_id, f"previous {result['previous']}", f"stars {result['stars']}", "editor value",
                     "write" if result["applied"] else "dry-run: nothing sent"]))


def stories_next(flags: list[str]) -> None:
    """papyrus stories next --story <lineage> [--json]

    Read only. One answer about what remains (docs/story-procedure.md). The Story's stored checklist decides each step's state; the records only add a
    `hint` where they differ. Lines, tab-separated: `status` (complete, ready, blocked or stale; the number still to do; why), a `step` line per step
    (state done, skipped, not_applicable, not_done or stale), a `version` line per checklist step (the Story version it was recorded against and
    `current` or `STALE: recorded against vN, story is now vM`), `hint`, the stored `item` and `note` lines and the `checklist progress` line, then
    a `remaining` line per step still to do (in order), `next` (the first), `skipped` and one `lens` line per review step not current. A review lens
    or the copy edit recorded done against an earlier version is stale and remains until it is recorded again for the current version."""
    options = parse_options(flags)
    lineage_id = _required_option(options, "story")
    client, _ = create_authoring_client()
    facts = story_facts(client, lineage_id)
    from .newsroom_process import hint_lines, remaining_lines, resolve, status_lines, version_lines
    from .story_checklist import checklist_lines, progress_text, read_steps, steps_for_display, summary_of

    raw = read_steps(client, lineage_id)   # one index read by Story lineage
    assessment = resolve(assess(facts), raw, facts)   # the stored checklist decides; the records only hint
    stored = steps_for_display(raw, lineage_id)
    stale_count = len(assessment["stale"])
    states = {row["key"]: row["state"] for row in assessment["steps"] if row["source"] == "checklist"}   # the lens steps as resolved, stale included
    if options.get("json"):
        print(json.dumps({"ok": True, "story": lineage_id, **assessment, "lenses": lens_payload(states, lineage=lineage_id),
                          "currentVersion": facts["versionNumber"], "checklist": stored,
                          "progress": progress_text(summary_of(stored), stale_count) if stored else None}, indent=2))
        return
    print(f"stories\tnext\t{lineage_id}\tstage {assessment['stage']}")
    lines = (status_lines(assessment) + step_lines(assessment) + version_lines(assessment) + hint_lines(assessment) + checklist_lines(stored, stale_count)
             + remaining_lines(assessment) + next_lines(assessment) + lens_lines(states, lineage=lineage_id))
    for line in lines:
        print(line)


def stories_step(flags: list[str]) -> None:
    """papyrus stories step --story <lineage> --step <key> [--state done|skipped|not_applicable|open] [--reason TEXT] [--note TEXT] [--evidence TEXT] [--actor-label NAME] [--agent NAME] [--dry-run]

    Marks one step of the Story's checklist and records who did it and when. A skipped or not-applicable step needs --reason; a review step needs --note
    (the findings) to be done; only a person reopens a step (--state open). With --note and no --state it adds a note to the step and changes nothing
    else: notes accumulate (who, when, text), can be added to any step in any state, and are never edited or deleted. The change records the Story version it was made against;
    a done review or copy edit reads STALE in `stories next` once the Story has a newer version, until you record it again. --agent NAME says an agent made the change; without it the actor is a person."""
    from .story_checklist import ACTOR_AGENT, ACTOR_PERSON, ChecklistError, set_step

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories step")
    lineage_id = _required_option(options, "story")
    key = _required_option(options, "step")
    state = normalize_string(options.get("state"))
    if state is None and not normalize_string(options.get("note")):
        raise ValueError("--state is required (or --note alone, to add a note without changing the state).")
    agent = normalize_string(options.get("agent"))
    actor = {"kind": ACTOR_AGENT if agent else ACTOR_PERSON, "label": agent or normalize_string(options.get("actor-label")) or "papyrus-cli"}
    if not apply:
        print(f"stories\tstep\t{lineage_id}\t{key}\t{state or 'note'}\tdry run")
        return
    client, _ = create_authoring_client()
    if state is None:   # a note on its own: the step's state, reason and findings stay as they are
        from .story_checklist import add_note

        try:
            row = add_note(client, lineage_id, key, normalize_string(options.get("note")) or "", actor=actor)
        except ChecklistError as error:
            raise ValueError(str(error)) from error
        print(f"stories\tstep\t{lineage_id}\t{row['stepKey']}\tnote\twrite\t{len(row['notes'])} notes")
        return
    try:
        row = set_step(client, lineage_id, key, state, actor=actor, reason=normalize_string(options.get("reason")),
                       note=normalize_string(options.get("note")), evidence=normalize_string(options.get("evidence")))
    except ChecklistError as error:
        raise ValueError(str(error)) from error
    print(f"stories\tstep\t{lineage_id}\t{row['stepKey']}\t{row['state']}\twrite")


def stories_checklist_backfill(flags: list[str]) -> None:
    """papyrus stories checklist-backfill [--dry-run] [--stage STAGE ...] [--page-size N]

    The one-time sweep that gives every existing Story a checklist, published ones included (docs/story-procedure.md). Steps are marked done where a
    record proves them (including the publish step of a published Story) and left open otherwise; the four review lenses start open. A Story that
    already has a full checklist is left alone, so running it again is safe. Paged by stage, newest first. With --dry-run nothing is written and the
    counts say what would be."""
    from .story_checklist import backfill

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories checklist-backfill")
    stages = tuple(parse_repeated_option(flags, "stage")) or None
    client, _ = create_authoring_client()
    from . import request_meter

    with request_meter.sweep("stories-checklist-backfill"):   # a declared sweep: every Story, one stage at a time, in pages
        counts = backfill(client, apply=apply, stages=stages, page_size=int(options.get("page-size") or 50))
    print(f"stories\tchecklist-backfill\t{'write' if apply else 'dry run'}\t" + "\t".join(f"{name} {value}" for name, value in counts.items()))

def stories_lens_check(flags: list[str]) -> None:
    """papyrus stories lens-check --story <lineage> [--lens people|agents|search|social] [--static <web directory>] [--no-network] [--json]

    Read only; it writes nothing. Runs the checks of the four review lenses that code can run on the Story's current version and prints each finding
    with its state (Looks fine, Needs a look, Problem, Could not check), plain words and where to look. Four problems must be fixed before a lens
    step can close as done: an image with no alt text, a third-party image with no credit, a video with no title or no credit and a Markdown copy that differs from the source.
    --static names the site's web directory (it holds projection.json; default PAPYRUS_SITE_STATIC_DIR); without it the checks that need the site's
    settings say they could not be checked (docs/four-lens-review.md). The social lens fetches the planned share picture (status, type, format, size);
    --no-network skips that fetch and the check reports the picture as not verified."""
    from .audience_lenses import LENS_VERSION, STATE_LABELS
    from .lens_evidence import blockers, load_site, not_run, run_checks, story_from_row, summarize
    from .story_reporting import current_story_version
    from .story_types import SITE_STATIC_DIRECTORY_ENV

    options = parse_options(flags)
    lineage_id = _required_option(options, "story")
    lens = normalize_string(options.get("lens"))
    static = normalize_string(options.get("static")) or os.environ.get(SITE_STATIC_DIRECTORY_ENV, "").strip() or None
    client, _ = create_authoring_client()
    story = story_from_row(current_story_version(client, lineage_id))
    site = load_site(static)
    from .share_image_check import fetch_over_http

    findings = run_checks(story, site, lens=lens, fetch_image=None if options.get("no-network") else fetch_over_http)
    counts, problems, skipped = summarize(findings), blockers(findings), not_run(lens)
    if options.get("json"):
        print(json.dumps({"ok": True, "story": lineage_id, "versionId": story.version_id, "versionNumber": story.version_number, "lensVersion": LENS_VERSION,
                          "siteSettingsRead": site is not None, "findings": findings, "counts": counts, "problems": [row["check"] for row in problems], "notRun": skipped}, indent=2))
        return
    print(f"stories\tlens-check\t{lineage_id}\tversion {story.version_number}\t{story.version_id}\tlens definition {LENS_VERSION}")
    labels = dict(STATE_LABELS)
    labels["not_applicable"] = "Not applicable"
    for row in findings:
        print("\t".join(["finding", row["step"], row["check"], labels[row["state"]], row["severity"] or "n/a", row["message"]]))
    for step, found in counts.items():
        print("\t".join(["summary", step, *(f"{label}: {found.get(state, 0)}" for state, label in STATE_LABELS)]))
    for row in problems:
        print("\t".join(["blocked", row["step"], row["check"], "fix this before the step can close as done", row["message"]]))
    print(f"notrun\t{len(skipped)} checks were not run (they need a model, the rest of the site or a person): " + ", ".join(row["check"] for row in skipped))


SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def stories_set_slug(flags: list[str]) -> None:
    """papyrus stories set-slug --story <lineage|id> --slug <new> [--force] [--no-trigger] [--dry-run]"""
    from .projection_trigger import SKIP_LINE, item_task, projection_enabled, projection_requested, trigger_projection
    from .publishing import ItemFields, publish_item, published_item_id_for, save_item

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories set-slug")
    story = _required_option(options, "story")
    slug = _required_option(options, "slug")
    if not SLUG_PATTERN.match(slug):
        raise ValueError("--slug must be lowercase letters, digits and single hyphens (for example my-story-title).")
    client, _ = create_authoring_client()
    item = client.get_record("Item", story)
    lineage_id = (item.get("lineageId") or item["id"]) if item is not None else story
    if client.list_by_index("itemsByLineageAndVersion", lineage_id):
        # Always the live text (or, if never published, the working draft), never a superseded record.
        item = published_story_version(client, lineage_id) or current_story_version(client, lineage_id)
    if item is None:
        raise ValueError(f"No story found for {story}.")
    item_id = item["id"]
    if item.get("slug") == slug:
        print(f"stories\tset-slug\tunchanged\t{item_id}\t{slug}")
        return
    clashes = [
        row for row in client.list_by_index("itemBySlug", slug)
        if row.get("section") == item.get("section") and (row.get("lineageId") or row["id"]) != lineage_id
    ]
    if clashes:
        raise ValueError(f"Slug {slug!r} is already used by {clashes[0]['id']} in this publication section.")
    published = item.get("status") == "published" or client.get_record("PublishedItem", published_item_id_for(lineage_id)) is not None
    if published and not options.get("force"):
        raise ValueError(
            f"{item_id} is already published; changing its address needs --force "
            "(the old address is kept as a redirect)."
        )
    if published and apply:
        from .publish_gate import REQUIRED, publish_approval

        if publish_approval(client) == REQUIRED:
            raise ValueError("This site needs a person's approval to publish, and a new address republishes the story: change the address in the newsroom console.")
    if not apply:
        print(f"stories\tset-slug\t{item_id}\t{item.get('slug')} -> {slug}\tdry run")
        return
    metadata = item.get("metadata")
    metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
    aliases = list(item.get("aliases") or [])
    if published and item.get("slug") and item["slug"] not in aliases:
        aliases.append(item["slug"])
    fields = ItemFields(
        type=item["type"], slug=slug, section=item.get("section"), front_matter_yaml=metadata.get("frontMatterYaml"),
        body_markus=item.get("bodyMarkus") or "", aliases=aliases, id=item_id,
    )
    actor = normalize_string(options.get("author-label")) or "papyrus-cli"
    save_item(client, fields, actor=actor, allow_published_slug_change=published)
    print(f"stories\tset-slug\t{item_id}\t{item.get('slug')} -> {slug}\twrite")
    for sibling in client.list_by_index("itemsByLineageAndVersion", lineage_id):
        if sibling["id"] != item_id:  # a later draft must not publish under the old address
            client.update_record("Item", {"id": sibling["id"], "slug": slug, "aliases": aliases})
    print(f"stories\tset-slug\tsaved\t{item_id}\t{slug}")
    if not published:
        return
    publish_item(client, item_id, actor=actor)
    if not projection_requested():
        return
    if options.get("no-trigger"):
        print(SKIP_LINE)
    else:
        from .projection_trigger import trigger_projection_as_user
        from .user_auth_mode import user_auth_requested

        task = item_task(item_id, unpublished=False)
        outcome = trigger_projection_as_user(client, task) if user_auth_requested() else trigger_projection(task)
        print(f"stories\tset-slug\tprojection\t{json.dumps(outcome)}")


def chosen_story_type(options: dict[str, Any], *, static_directory: Path | None = None) -> str | None:
    """The ``--type`` of a command, checked: a lowercase Story type name that is not a system type, and, when the site's own list is known (a ``projection.json`` in
    ``PAPYRUS_SITE_STATIC_DIR`` or in ``./web``), one of the types the site offers. With no list the name is accepted with a note, never guessed."""
    from .story_types import SITE_STATIC_DIRECTORY_ENV, read_projection_settings, require_story_type, story_types_from_mapping

    raw = normalize_string(options.get("type"))
    if not raw:
        return None
    name = require_story_type(raw, "--type")
    directory = static_directory
    if directory is None:
        configured = (os.environ.get(SITE_STATIC_DIRECTORY_ENV) or "").strip()
        directory = Path(configured) if configured else (Path("web") if Path("web/projection.json").is_file() else None)
    offered = story_types_from_mapping(read_projection_settings(directory)).offered if directory is not None else ()
    if offered and name not in offered:
        raise ValueError(f"--type {name!r} is not one of this site's Story types ({', '.join(offered)}).")
    if not offered:
        print(f"stories\ttype\tnote\t{name} was not checked against the site's list of types (run from the site checkout or set {SITE_STATIC_DIRECTORY_ENV})")
    return name


def stories_set_type(flags: list[str]) -> None:
    """papyrus stories set-type --story <lineage|slug> --type <article|post|...> [--dry-run]

    Changes the type of a story that is not published yet (a draft, idea or in review). A published story is refused: its page lives at an address that
    depends on its type, so that change is not made from the CLI."""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories set-type")
    story = _required_option(options, "story")
    new_type = chosen_story_type({**options, "type": _required_option(options, "type")})
    client, _ = create_authoring_client()
    lineage_id = story
    if not story_versions(client, lineage_id):
        raise ValueError(f"No story found for {story}. Give the story's lineage id (see papyrus stories list).")
    if published_story_version(client, lineage_id) is not None:
        raise ValueError("That story is published, so its type cannot be changed here: its page address depends on the type. Take it down first (stories withdraw) or ask for the change in the newsroom.")
    latest = current_story_version(client, lineage_id)
    if latest.get("type") == new_type:
        print(f"stories\tset-type\tunchanged\t{lineage_id}\t{new_type}")
        return
    print(f"stories\tset-type\t{lineage_id}\t{latest.get('type')} -> {new_type}\t{'write' if apply else 'dry run'}")
    if not apply:
        return
    client.update_record("Item", {"id": latest["id"], "type": new_type, "typeStatus": f"{new_type}#{latest.get('status') or 'draft'}", "updatedAt": utc_now_iso()})
    print(f"stories\tset-type\tdone\t{latest['id']}\t{new_type}")


def stories_create(flags: list[str]) -> None:
    """papyrus stories create --title <text> [--type article|post|...] [--section <key>] [--stage idea|assignment|reporting] [--summary <text>] [--brief <text>] [--reference <reference id> ...] [--with-assignment]

    Each ``--reference`` is the Reference the story is based on: it is linked ``based_on`` (docs/reference-curation-pipeline.md)."""
    options = parse_options(flags)
    reference_ids = parse_repeated_option(flags, "reference")
    apply = resolve_mutation_apply(options, "stories create")
    title = _required_option(options, "title")
    stage = normalize_string(options.get("stage")) or "idea"
    if stage not in ("idea", "assignment", "reporting"):
        raise ValueError("--stage must be idea, assignment or reporting.")
    section_key = normalize_string(options.get("section"))
    summary = normalize_string(options.get("summary")) or title
    actor = normalize_string(options.get("actor-label")) or "papyrus-cli"
    story_type = chosen_story_type(options)
    if not apply:
        print(f"stories\tcreate\t{title}\tstage {stage}\ttype {story_type or 'site default'}\tdry run")
        if reference_ids:
            print(f"stories\tcreate\tbased on\t{len(reference_ids)} reference(s) would be attached: {', '.join(reference_ids)}")
        if options.get("with-assignment"):
            print("stories\tcreate\twith-assignment\ta reporting.candidate Assignment would also be opened (the Story's --type is not the Assignment's type)")
        return
    client, _ = create_authoring_client()
    item = create_story(client, title=title, section_key=section_key, stage=stage, summary=summary, actor=actor, item_type=story_type)
    lineage_id = item["lineageId"]
    print(f"stories\tcreate\t{title}\tstage {stage}\ttype {item.get('type')}\twrite")
    if item.get("type") == "untyped":
        print("stories\tcreate\twarning\tthis story has no type and cannot be published until it has one: run papyrus stories set-type --story <lineage> --type post|article")
    print(f"stories\tcreate\tcreated\t{item['id']}")
    print(f"stories\tcreate\tlineage\t{lineage_id}")
    print_console_rows("stories", "create", lambda base: story_links(base, lineage_id, item["id"], "editor page of the first version"))
    attached, unattached = [], []
    for reference_id in reference_ids:
        # The story record is passed in: the lineage index is eventually consistent and may not show a story created a moment ago.
        try:
            linked = link_reference_to_story(client, lineage_id, reference_id, role="based_on", actor=actor, story=item)
        except Exception as error:  # noqa: BLE001 - one bad Reference must not drop the others or the assignment
            unattached.append((reference_id, str(error).splitlines()[0] if str(error) else type(error).__name__))
            print(f"stories\tcreate\tnot attached\t{reference_id}\t{unattached[-1][1]}")
            continue
        attached.append(linked["referenceLineageId"])
        print(f"stories\tcreate\tbased on\t{linked['referenceLineageId']}")
    from .story_triggers import deliver_from_environment

    deliver_from_environment(client, lineage_id)   # a story created at a stage has entered it
    failure = None
    if options.get("with-assignment"):
        from .assignments_workflow import create_reporting_assignment

        # The Story's --type (article, post) is not the Assignment's type: this command only opens a reporting.candidate.
        assignment_options = {k: v for k, v in options.items() if k != "type"}
        try:
            create_reporting_assignment(client, {**assignment_options, "type": "reporting.candidate", "content-item": lineage_id, "summary": summary})
        except Exception as error:  # noqa: BLE001 - the Story and its References already exist; say so and exit non-zero
            failure = str(error).splitlines()[0] if str(error) else type(error).__name__
    print_reminder(client, lineage_id)
    if failure is not None or unattached:
        parts = [f"Story created (lineage {lineage_id}), references attached: {len(attached)}"]
        if unattached:
            parts.append("not attached: " + "; ".join(f"{ref} ({why})" for ref, why in unattached))
        if failure is not None:
            parts.append(f"assignment NOT created: {failure}")
        print("stories\tcreate\tsummary\t" + ", ".join(parts), file=sys.stderr)
        if failure is not None:
            print(f"stories\tcreate\tretry\tpapyrus assignments create-reporting --title {json.dumps(title)} --content-item {lineage_id}"
                  + (f" --section {section_key}" if section_key else ""), file=sys.stderr)
        if unattached:
            print(f"stories\tcreate\tretry\tpapyrus stories link-reference --story {lineage_id} --reference <id>", file=sys.stderr)
        raise SystemExit(1)


PUBLISHED_STAGE_WARNING = (
    "warning: moving a story to the published stage only changes its board stage. No page is published and nothing goes live. "
    "To publish it, run: papyrus ops content publish --id <item-id>"
)


def stories_move(flags: list[str]) -> None:
    """papyrus stories move --story <lineage> --stage <stage> [--reason <text>] [--author-label <name>]

    Only the board stage changes. With --stage published it prints a warning on stderr: no page is published;
    `papyrus ops content publish` does that."""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories move")
    lineage_id = _required_option(options, "story")
    stage = _required_option(options, "stage")
    from .content_item_lifecycle import require_content_item_stage

    require_content_item_stage(stage)
    if not apply:
        print(f"stories\tmove\t{lineage_id}\t{stage}\tdry run")
        if stage == "published":
            print(PUBLISHED_STAGE_WARNING, file=sys.stderr)
        return
    client, _ = create_authoring_client()
    result = move_story_stage(
        client, lineage_id, stage, actor=normalize_string(options.get("author-label")) or "papyrus-cli",
        reason=normalize_string(options.get("reason")),
    )
    print(f"stories\tmove\t{lineage_id}\t{stage}\twrite")
    if stage == "published":
        # stderr, so the tab-separated lines keep their format.
        print(PUBLISHED_STAGE_WARNING, file=sys.stderr)
    print(f"stories\tmove\t{'moved' if result['changed'] else 'unchanged'}\t{result['from']}\t{result['stage']}")
    if result["changed"]:
        from .story_triggers import deliver_from_environment

        deliver_from_environment(client, lineage_id)
    assessment = reminder_assessment(client, lineage_id, sync_checklist=True)
    if assessment is not None and result["changed"] and _moved_forward(result):
        warn_skipped(assessment)
    print_next_lines(assessment)


def _moved_forward(result: dict) -> bool:
    from .content_item_lifecycle import CONTENT_ITEM_STAGES

    ordered = [name for name in CONTENT_ITEM_STAGES if name not in ("held", "spiked")]
    return result["from"] in ordered and result["stage"] in ordered and ordered.index(result["stage"]) > ordered.index(result["from"])


def research_assignment_options(story: dict, lineage_id: str, direction: str, section: dict | None, *, actor: str, title: Any = None, kind: Any = None) -> dict:
    return {
        "title": normalize_string(title) or story.get("headline") or story.get("title"),
        "type": normalize_string(kind) or "research.multi",
        "content-item": lineage_id,
        "section": section["id"] if section else None,
        "instructions": direction.strip(),
        "direction": direction.strip(),
        "context-profile": "reporter",
        "actor-label": actor,
    }


RESEARCH_RUN_NOTE = ("The run searches the web, opens the sources it finds and reads as much of each as fits, then checks its claims against that text. "
                     "It cannot open pages behind a login or paywall; the packet lists them.")


def stories_assign_research(flags: list[str]) -> None:
    """papyrus stories assign-research --story <lineage> --direction TEXT|--direction-file FILE [--type research.multi] [--title TEXT] [--actor-label NAME] [--dry-run]

    An editor's research assignment on a Story: an Assignment working on the Story's lineage, in the Story's section, with the direction as its
    instructions. The run searches the web, opens the sources it finds and reads as much of each as fits the model's input; its packet says which it read. Its context profile is ``reporter`` (``papyrus assignments context-pack`` shows what the reporting agent is given). A Story at the
    idea stage moves to the assignment stage through the recorded stage move; a Story at any other stage stays where it is."""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories assign-research")
    lineage_id = _required_option(options, "story")
    direction = _text_from_option_or_file(options, "direction", "direction-file")
    if not direction or not direction.strip():
        raise ValueError("--direction (or --direction-file) is required.")
    client, _ = create_authoring_client()
    story = current_story_version(client, lineage_id)
    from .editorial_context import find_section
    from .section_ids import is_type_shaped
    from .assignments_workflow import create_research_assignment

    section_value = normalize_string(story.get("section"))
    section = find_section(client, section_value) if section_value and not is_type_shaped(section_value, story.get("type")) else None
    actor = normalize_string(options.get("actor-label")) or "papyrus-cli"
    result = create_research_assignment(client, {
        **options,
        **research_assignment_options(story, lineage_id, direction, section, actor=actor, title=options.get("title"), kind=options.get("type")),
    })
    print(f"stories\tassign-research\tnote\t{RESEARCH_RUN_NOTE}")
    moves = story.get("stage") == "idea"
    print(f"stories\tassign-research\t{lineage_id}\t{result['assignmentId']}\t{'moves the Story to assignment' if moves else 'Story stays at ' + str(story.get('stage'))}\t{'write' if apply else 'dry run'}")
    if apply and moves:
        moved = move_story_stage(client, lineage_id, "assignment", actor=actor, reason=f"Research assignment {result['assignmentId']} created")
        print(f"stories\tassign-research\tmoved\t{moved['from']}\t{moved['stage']}")
    if apply:
        print_reminder(client, lineage_id)


def stories_fire_triggers(flags: list[str]) -> None:
    """papyrus stories fire-triggers --story <lineage>: deliver the stage-entry triggers for the story's current stage and version.

    Safe to repeat: a story, stage and version that already started a run starts nothing. Use it after a move made in the console,
    or to retry a start that was deferred."""
    options = parse_options(flags)
    from .story_triggers import deliver_from_environment

    client, _ = create_authoring_client()
    deliver_from_environment(client, _required_option(options, "story"))
