from __future__ import annotations

import json

from .assignments_workflow import (
    apply_reporting_packet,
    apply_research_packet,
    backfill_content_items,
    backfill_section_indexes,
    demote_undrafted_content_items,
    migrate_content_item_stages,
    build_assignment_context,
    copywriting_output,
    create_reporting_assignment,
    create_research_assignment,
    intake_research_packet_proposals,
    list_assignment_events,
    list_assignment_research_packets,
    list_assignments_for_object,
    mutate_assignment,
    orphan_research_packets,
    process_assignment_queue,
    review_reporting_packet,
    run_copywriting_assignment,
    run_reporting_assignment,
    run_research_assignment,
    run_story_cycle,
    story_cycle_output,
)
from .multi_search_research import research_multi_command
from .tavily_deep_research import poll_tavily_deep_research_command, run_tavily_deep_research
from .automatic_assignments import (
    apply_automatic_assignment_cleanup,
    plan_automatic_assignment_cleanup,
)
from .graphql_authoring import create_authoring_client
from .options import parse_options, resolve_mutation_apply


def assignments_list(flags: list[str]) -> None:
    from .assignments_workflow import assignment_section_key, assignment_sort_key

    options = parse_options(flags)
    client, _ = create_authoring_client()
    assignments = client.list_records("Assignment")
    queue = options.get("queue")
    status = options.get("status")
    assignment_type = options.get("type")
    section = options.get("section")
    if queue:
        assignments = [row for row in assignments if row.get("queueKey") == queue]
    if status:
        assignments = [row for row in assignments if row.get("status") == status]
    if assignment_type:
        assignments = [row for row in assignments if row.get("assignmentTypeKey") == assignment_type]
    if section:
        assignments = [row for row in assignments if assignment_section_key(row) == section]
    assignments.sort(key=assignment_sort_key)
    for assignment in assignments:
        section_key = assignment_section_key(assignment) or ""
        print(
            f"{assignment.get('status')}\t{assignment.get('id')}\t{assignment.get('assignmentTypeKey')}\t"
            f"{assignment.get('queueKey')}\tsection={section_key}\t{assignment.get('title')}"
        )


def assignments_create_research(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = create_research_assignment(client, options)
    if options.get("json"):
        print(json.dumps({"ok": True, **result}, indent=2))


def assignments_create_reporting(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = create_reporting_assignment(client, options)
    if options.get("json"):
        print(json.dumps({"ok": True, **result}, indent=2))


def assignments_run_research(flags: list[str]) -> None:
    run_research_assignment(flags)


def assignments_run_tavily_deep_research(flags: list[str]) -> None:
    run_tavily_deep_research(flags)


def assignments_poll_tavily_deep_research(flags: list[str]) -> None:
    poll_tavily_deep_research_command(flags)


def assignments_research_multi(flags: list[str]) -> None:
    research_multi_command(flags)


def assignments_run_reporting(flags: list[str]) -> None:
    run_reporting_assignment(flags)


def assignments_apply_research_packet(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = apply_research_packet(client, options)
    if options.get("json"):
        print(json.dumps({"ok": True, **result}, indent=2))


def assignments_apply_reporting_packet(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = apply_reporting_packet(client, options)
    if options.get("json"):
        print(json.dumps({"ok": True, **result}, indent=2))


def assignments_intake_proposals(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = intake_research_packet_proposals(client, options)
    if options.get("json"):
        print(json.dumps({"ok": True, **result}, indent=2))
        return
    print(f"assignments\tprocess-proposals\tassignment\t{result['assignmentId']}")
    print(f"assignments\tprocess-proposals\tcatalog\t{result.get('catalogPath')}")
    print(f"assignments\tprocess-proposals\tregistered\t{result.get('registeredReferenceCount')}")


def assignments_research_intake_now(flags: list[str]) -> None:
    options = parse_options(flags)
    resolve_mutation_apply(options, "assignments process-research-now")
    if not options.get("assignment"):
        raise ValueError("assignments process-research-now requires --assignment <id>.")
    if not options.get("config"):
        raise ValueError("assignments process-research-now requires --config <steering.yml>.")
    if not options.get("corpus-key"):
        raise ValueError("assignments process-research-now requires --corpus-key <key>.")
    research_flags = [
        "--assignment",
        str(options["assignment"]),
        "--corpus-key",
        str(options["corpus-key"]),
        "--research-mode",
        str(options.get("research-mode") or "source_discovery"),
    ]
    if options.get("run-id"):
        research_flags.extend(["--run-id", f"{options['run-id']}-research"])
    run_research_assignment(research_flags)
    client, _ = create_authoring_client()
    intake_result = intake_research_packet_proposals(client, options)
    if options.get("json"):
        print(json.dumps({"ok": True, **intake_result}, indent=2))
        return
    print(f"assignments\tprocess-research-now\tassignment\t{intake_result['assignmentId']}")
    print(f"assignments\tprocess-research-now\tregistered\t{intake_result.get('registeredReferenceCount')}")


def assignments_run_story_cycle(flags: list[str]) -> None:
    run_story_cycle(flags)


def assignments_story_cycle_output(flags: list[str]) -> None:
    story_cycle_output(flags)


def assignments_orphan_research_packets(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    orphan_research_packets(client, options)


def assignments_backfill_section_indexes(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    backfill_section_indexes(client, options)


def assignments_backfill_content_items(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    backfill_content_items(client, options)


def assignments_demote_undrafted_content_items(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    demote_undrafted_content_items(client, options)


def assignments_migrate_content_item_stages(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    migrate_content_item_stages(client, options)


def assignments_for_object(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    list_assignments_for_object(client, options)


def assignments_build_context(flags: list[str]) -> None:
    build_assignment_context(flags)


def assignments_research_packets(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    list_assignment_research_packets(client, options)


def assignments_review_reporting_packet(flags: list[str]) -> None:
    options = parse_options(flags)
    client, auth = create_authoring_client()
    review_reporting_packet(client, auth, options)


def assignments_run_copywriting(flags: list[str]) -> None:
    options = parse_options(flags)
    client, auth = create_authoring_client()
    run_copywriting_assignment(client, auth, options)


def assignments_copywriting_output(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    copywriting_output(client, options)


def assignments_events(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    list_assignment_events(client, options)


def assignments_process_queue(flags: list[str]) -> None:
    options = parse_options(flags)
    client, auth = create_authoring_client()
    process_assignment_queue(client, auth, options)


def assignments_claim(flags: list[str]) -> None:
    mutate_assignment(*create_authoring_client(), "claim", parse_options(flags))


def assignments_release(flags: list[str]) -> None:
    mutate_assignment(*create_authoring_client(), "release", parse_options(flags))


def assignments_complete(flags: list[str]) -> None:
    mutate_assignment(*create_authoring_client(), "complete", parse_options(flags))


def assignments_cancel(flags: list[str]) -> None:
    mutate_assignment(*create_authoring_client(), "cancel", parse_options(flags))


def assignments_reopen(flags: list[str]) -> None:
    mutate_assignment(*create_authoring_client(), "reopen", parse_options(flags))


def assignments_cleanup_automatic(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "assignments cleanup-automatic")
    client, _ = create_authoring_client()
    deletions = plan_automatic_assignment_cleanup(
        assignments=client.list_records("Assignment"),
        assignment_events=client.safe_list_records("AssignmentEvent"),
        semantic_relations=client.safe_list_records("SemanticRelation"),
    )
    for model_name in ("Assignment", "AssignmentEvent", "SemanticRelation"):
        count = sum(1 for deletion in deletions if deletion["modelName"] == model_name)
        print(f"assignments\tcleanup-automatic\tplanned\t{model_name}\t{count}")
    for deletion in deletions:
        if deletion["modelName"] == "Assignment":
            print(f"assignment\t{deletion['id']}\t{deletion['assignmentTypeKey']}\t{deletion['status']}\t{deletion['title']}")
    if not apply:
        print("assignments\tcleanup-automatic\tapply\tskipped\tdry run; rerun without --dry-run to delete")
        return
    apply_automatic_assignment_cleanup(client, deletions, actor_label=options.get("actor") or "papyrus-cli")
    print(f"assignments\tcleanup-automatic\tdeleted\t{len(deletions)}")
