"""`papyrus stories retire`: take a Story's page down and redirect its address to another Story.

Merging two Stories into one article leaves the retired Story's public addresses with nothing to say. This command

* refuses unless the target is a published Story of this site, is not the Story itself and is not retired (no loop, no chain),
* unpublishes the Story (the page goes; every version stays) and moves it to the ``retired`` stage, recording where it went in the
  head row's ``metadata.retiredInto``, and
* leaves the rest to the projection (``projection/retired.py``): it removes the Story from listings, the sitemap, the feeds and the
  public data, and writes a permanent redirect from every address the Story was served at (its current address, its aliases, the
  addresses of earlier published versions, its Markdown twin) to the target's address. The redirects keep pointing at the target's
  current address when that changes.

``--undo`` clears the record and publishes the retired version again; the projection then removes the redirects. Nothing is deleted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .content_item_lifecycle import CONTENT_ITEM_STAGES, RETIRED_INTO_KEY, RETIRED_STAGE, head_stage_fields, is_story_item_type
from .markus_export import item_output_path
from .publishing import _parse_json_object, published_item_id_for, unpublish_item, utc_now_iso
from .record_helpers import to_aws_json
from .story_reporting import current_story_version, published_story_version, story_versions

DEFAULT_ACTOR = "papyrus-cli"
UNRETIRED_KEY = "unretired"


class RetireRefused(ValueError):
    """The retirement is not allowed; nothing was written."""


@dataclass
class RetirePlan:
    lineage_id: str
    head_id: str
    live_id: str | None
    slug: str
    item_type: str
    target_lineage: str | None = None
    target_slug: str | None = None
    undo: bool = False
    #: ``(label, text)`` lines for the dry run and the report: what changes, in order.
    changes: list[tuple[str, str]] = field(default_factory=list)
    #: The content path of each version that was served, plus aliases: where the redirects come from.
    served: list[str] = field(default_factory=list)
    #: The ids of those versions, recorded in ``metadata.retiredInto.versionIds`` for the projection (the live one stops saying it was published).
    version_ids: list[str] = field(default_factory=list)
    unchanged: bool = False
    #: The ids of the versions that carry a schedule: retiring removes them first, so a scheduled publish cannot bring the retired Story back.
    scheduled: list[str] = field(default_factory=list)
    republish: bool = False
    note: str | None = None


def _resolve_lineage(client, reference: str, what: str) -> str:
    row = client.get_record("Item", reference)
    lineage_id = (row.get("lineageId") or row["id"]) if row is not None else reference
    if not client.list_by_index("itemsByLineageAndVersion", lineage_id):
        raise RetireRefused(f"No story found for {what} {reference!r} in this site.")
    return lineage_id


def _retired_into(row: dict[str, Any]) -> dict[str, Any] | None:
    info = _parse_json_object(row.get("metadata")).get(RETIRED_INTO_KEY)
    return info if row.get("stage") == RETIRED_STAGE and isinstance(info, dict) and info.get("toLineageId") else None


def _was_published(row: dict[str, Any]) -> bool:
    """A version that was live: the published row, or one that recorded when it went live (``publishedAt`` alone proves nothing: every version carries the Story's
    first publication, and a draft takes it from its front matter date). ``changeReason`` ``publish`` / ``unpublish`` marks the versions published before publishing
    stopped overwriting it."""
    return row.get("status") == "published" or bool(row.get("versionPublishedAt")) or row.get("changeReason") in ("publish", "unpublish")


def _served_rows(versions: list[dict[str, Any]], head: dict[str, Any], live: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every version that was served, the live one and the head (whose address the story has now)."""
    return [row for row in versions if _was_published(row) or row["id"] in {head["id"], (live or {}).get("id")}]


def served_addresses(versions: list[dict[str, Any]], head: dict[str, Any], live: dict[str, Any] | None) -> list[str]:
    """The content paths of every version that was served and every alias: the addresses the projection redirects (it expands each to the request paths)."""
    found: list[str] = []
    for row in _served_rows(versions, head, live):
        found.append(item_output_path(row))
        found.extend(str(alias) for alias in row.get("aliases") or [])
    return list(dict.fromkeys(found))


def check_target(client, story_lineage: str, target_ref: str) -> tuple[str, dict[str, Any]]:
    """The target's lineage and head row, or ``RetireRefused``: it must be a published Story of this site, not the Story itself, and not retired."""
    target = _resolve_lineage(client, target_ref, "--redirect-to")
    if target == story_lineage:
        raise RetireRefused("--redirect-to is the story itself: a story cannot redirect to itself.")
    head = current_story_version(client, target)
    if _retired_into(head) is not None:
        raise RetireRefused(
            f"{target} is retired and redirects to {_retired_into(head)['toLineageId']}; redirect to that story instead "
            "(a redirect never points at another redirect)."
        )
    if client.get_record("PublishedItem", published_item_id_for(target)) is None:
        raise RetireRefused(f"{target} is not published, so its address would be a 404. Publish it first, or choose a published story.")
    live = published_story_version(client, target)
    if not is_story_item_type((live or head).get("type")):
        raise RetireRefused(f"{target} is not a story (type {(live or head).get('type')!r}).")
    return target, live or head


def plan_retire(client, story: str, redirect_to: str | None, *, undo: bool = False) -> RetirePlan:
    lineage_id = _resolve_lineage(client, story, "--story")
    versions = story_versions(client, lineage_id)
    head = current_story_version(client, lineage_id)
    live = published_story_version(client, lineage_id)
    plan = RetirePlan(lineage_id, head["id"], live["id"] if live else None, str(head.get("slug") or lineage_id), str(head.get("type") or ""), undo=undo)
    info = _retired_into(head)
    if undo:
        if info is None:
            raise RetireRefused(f"{lineage_id} is not retired; there is nothing to undo.")
        plan.target_lineage = str(info["toLineageId"])
        live_id = info.get("liveItemId")
        restorable = next((row for row in versions if row["id"] == live_id), None) if live_id else None
        plan.republish = restorable is not None and restorable["id"] == head["id"]
        plan.live_id = restorable["id"] if restorable else None
        plan.changes.append(("clear", f"metadata.{RETIRED_INTO_KEY} (kept as metadata.{UNRETIRED_KEY}) and move {head['id']} out of {RETIRED_STAGE}"))
        if plan.republish:
            plan.changes.append(("publish", f"{head['id']} (the version that was live); the projection then rebuilds its page and removes its redirects"))
        else:
            plan.note = (
                f"{lineage_id} has a newer working version than the one that was live, so nothing is republished. "
                f"The redirects go; publish when ready: papyrus ops content publish --id {head['id']}"
            )
            plan.changes.append(("keep", "the story unpublished (a newer working version exists)"))
        return plan

    if not redirect_to:
        raise RetireRefused("--redirect-to is required (the story whose address replaces this one).")
    if not is_story_item_type(head.get("type")):
        raise RetireRefused(f"{lineage_id} is not a story (type {head.get('type')!r}).")
    target, target_row = check_target(client, lineage_id, redirect_to)
    plan.target_lineage, plan.target_slug = target, str(target_row.get("slug") or target)
    plan.served = served_addresses(versions, head, live)
    plan.version_ids = [row["id"] for row in _served_rows(versions, head, live)]
    if info is None and live is None and not any(_was_published(row) for row in versions):
        raise RetireRefused(f"{lineage_id} was never published, so it has no address to redirect. Spike it instead: papyrus stories move --story {lineage_id} --stage spiked")
    if info is not None and info["toLineageId"] == target:
        plan.unchanged = True
        return plan
    from .story_schedule import scheduled_versions

    plan.scheduled = [row["id"] for row in scheduled_versions(client, lineage_id)]
    if plan.scheduled:
        plan.changes.append(("unschedule", f"{', '.join(plan.scheduled)} (a scheduled publish would otherwise bring the Story back)"))
    if live is not None:
        plan.changes.append(("unpublish", f"{live['id']} (the page comes down; every version stays)"))
    plan.changes.append(("retire", f"{head['id']}: stage {head.get('stage')} -> {RETIRED_STAGE}, metadata.{RETIRED_INTO_KEY} -> {target}"))
    plan.changes.append(("projection", "listings, the sitemap, the feeds and the public data drop the story; the projection writes a permanent redirect from each address below to the target's address"))
    return plan


def apply_retire(client, plan: RetirePlan, *, actor: str = DEFAULT_ACTOR, now: str | None = None) -> None:
    """Write the plan. Never deletes a record."""
    now = now or utc_now_iso()
    if plan.unchanged:
        return
    head = client.get_record("Item", plan.head_id) or {}
    metadata = _parse_json_object(head.get("metadata"))
    if plan.undo:
        info = metadata.pop(RETIRED_INTO_KEY, None) or {}
        metadata[UNRETIRED_KEY] = {**info, "at": now, "by": actor}
        previous = info.get("previousStage")
        stage = previous if previous in CONTENT_ITEM_STAGES and previous != "published" else "copywriting"
        client.update_record(
            "Item",
            {"id": plan.head_id, "stage": stage, **head_stage_fields({**head, "stage": stage}), "metadata": to_aws_json(metadata), "versionCreatedAt": now,
             "versionCreatedBy": actor, "changeReason": "restored from retired"},
        )
        if plan.republish:
            from .publishing import publish_item

            publish_item(client, plan.head_id, actor=actor, now=now)
        return
    if plan.live_id:
        unpublish_item(client, plan.live_id, actor=actor, now=now)
    earlier = metadata.get(RETIRED_INTO_KEY) if head.get("stage") == RETIRED_STAGE else None   # a new target for a retired story keeps what the first retirement recorded
    earlier = earlier if isinstance(earlier, dict) else {}
    metadata[RETIRED_INTO_KEY] = {
        "toLineageId": plan.target_lineage,
        "liveItemId": earlier.get("liveItemId") or plan.live_id or plan.head_id,
        "versionIds": list(dict.fromkeys([*(earlier.get("versionIds") or []), *plan.version_ids])),
        "previousStage": earlier.get("previousStage") or head.get("stage"),
        "at": now,
        "by": actor,
    }
    client.update_record(
        "Item",
        {"id": plan.head_id, "stage": RETIRED_STAGE, **head_stage_fields({**head, "stage": RETIRED_STAGE}), "metadata": to_aws_json(metadata),
         "versionCreatedAt": now, "versionCreatedBy": actor, "changeReason": f"retired into {plan.target_lineage}"},
    )


def print_plan(plan: RetirePlan, *, dry_run: bool) -> None:
    verb = "dry run" if dry_run else "write"
    action = "undo" if plan.undo else "retire"
    if plan.unchanged:
        print(f"stories\tretire\tunchanged\t{plan.lineage_id}\talready redirects to {plan.target_lineage}")
        return
    target = f"\t-> {plan.target_lineage}" if plan.target_lineage else ""
    print(f"stories\tretire\t{action}\t{plan.lineage_id}\t{plan.slug} ({plan.item_type}){target}\t{verb}")
    for label, text in plan.changes:
        print(f"stories\tretire\t{'would ' if dry_run else ''}{label}\t{text}")
    for path in plan.served:
        print(f"stories\tretire\t{'would ' if dry_run else ''}redirect\t{path}\t-> {plan.target_slug or plan.target_lineage}\t301 (and its .md twin)")
    if plan.note:
        print(f"stories\tretire\tnote\t{plan.note}")


def stories_retire(flags: list[str]) -> None:
    """papyrus stories retire --story LINEAGE|ID --redirect-to LINEAGE|ID [--no-trigger] [--dry-run] | --story LINEAGE|ID --undo [--no-trigger] [--dry-run]"""
    from .graphql_authoring import create_authoring_client
    from .options import normalize_string, parse_options, resolve_mutation_apply
    from .projection_trigger import SKIP_LINE, item_task, projection_requested, trigger_projection, trigger_projection_as_user
    from .publish_stages import invalidated_stage, projected_stage
    from .user_auth_mode import user_auth_requested

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories retire")
    story = normalize_string(options.get("story"))
    if not story:
        raise ValueError("--story is required.")
    undo = bool(options.get("undo"))
    redirect_to = normalize_string(options.get("redirect-to"))
    if undo and redirect_to:
        raise ValueError("--undo restores the story; it takes no --redirect-to.")
    client, claims = create_authoring_client()
    actor = normalize_string((claims or {}).get("sub")) or DEFAULT_ACTOR
    try:
        plan = plan_retire(client, story, redirect_to, undo=undo)
    except RetireRefused as error:
        raise ValueError(str(error)) from error
    if apply and not plan.unchanged and plan.republish:
        from .publish_gate import REQUIRED, publish_approval

        if publish_approval(client) == REQUIRED:
            raise ValueError("This site needs a person's approval to publish, and an undo republishes the story: restore it from the newsroom console.")
    print_plan(plan, dry_run=not apply)
    if not apply or plan.unchanged:
        return
    if plan.scheduled:
        from .story_schedule import call_remote, refused_message

        removed = call_remote(client, "schedule", {"storyLineageId": plan.lineage_id, "clear": True})
        if removed.get("ok") is False:
            raise ValueError(f"stories retire stopped before changing anything: the schedule could not be removed: {refused_message(removed)}")
        print(f"stories\tretire\tunscheduled\t{plan.lineage_id}\t{', '.join(removed.get('itemIds') or [])}")
    apply_retire(client, plan, actor=actor)
    print(f"stories\tretire\tsaved\t{plan.lineage_id}")
    if not projection_requested():
        return
    if options.get("no-trigger"):
        print(SKIP_LINE)
        return
    published = bool(undo and plan.republish)
    task = item_task(plan.live_id or plan.head_id if published else plan.head_id, unpublished=not published)
    outcome = trigger_projection_as_user(client, task) if user_auth_requested() else trigger_projection(task)
    print(f"stories\tretire\tprojection\t{json.dumps(outcome)}")
    stage, invalidated = projected_stage(outcome), invalidated_stage(outcome)
    for page in stage.get("pages") or []:
        print(f"stories\tretire\tpage\t{page}")
    for path in invalidated.get("paths") or []:
        print(f"stories\tretire\tpurged\t{path}")
    for path in invalidated.get("skippedPaths") or []:
        print(f"stories\tretire\tNOT purged\t{path}")
    if outcome.get("ok") is False:
        raise SystemExit(1)
