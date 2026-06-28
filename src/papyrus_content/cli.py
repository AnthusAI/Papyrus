from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .accession import (
    build_reference_accession_assignment_records,
    execute_reference_accession_assignment,
    find_reference_for_source_accession,
    next_reference_source_command,
    print_reference_accession_assignment_summary,
    require_corpus_config_by_id_or_key,
    reference_accession_assignment_id,
)
from .analysis_commands import (
    analysis_create_reindex_assignment,
    analysis_doctor_entity_graph,
    analysis_entity_graph_preflight,
    analysis_execute_assignment,
    analysis_graph_artifacts,
    analysis_import_graph_artifact,
    analysis_publish_graph_snapshot,
    analysis_reindex_plan,
    analysis_run_now,
)
from .auth_commands import refresh_jwt
from .batch_commands import register_catalog_batches, run_post_ingestion_enrichment_batches
from .analysis_profiles import analysis_profiles, validate_analysis_profiles
from .assignments import apply_assignment_action
from .assignments_commands import (
    assignments_apply_reporting_packet,
    assignments_apply_research_packet,
    assignments_backfill_section_indexes,
    assignments_build_context,
    assignments_cancel,
    assignments_claim,
    assignments_complete,
    assignments_copywriting_output,
    assignments_create_research,
    assignments_create_reporting,
    assignments_events,
    assignments_for_object,
    assignments_intake_proposals,
    assignments_list,
    assignments_orphan_research_packets,
    assignments_process_queue,
    assignments_release,
    assignments_reopen,
    assignments_research_intake_now,
    assignments_research_packets,
    assignments_review_reporting_packet,
    assignments_run_copywriting,
    assignments_run_reporting,
    assignments_run_research,
    assignments_run_tavily_deep_research,
    assignments_poll_tavily_deep_research,
    assignments_run_story_cycle,
    assignments_story_cycle_output,
)
from .editions_commands import (
    editions_dispatch_reporting,
    editions_dispatch_research,
    editions_plan,
    editions_purge,
)
from .categories_commands import (
    categories_draft_add_topic,
    categories_draft_archive_topic,
    categories_draft_create,
    categories_draft_promote,
    categories_draft_update_topic,
    categories_export_category_set,
    categories_export_category_tree,
    categories_export_classifier_seed_manifest,
    categories_export_lexical_steering,
    categories_export_steering_feedback,
    categories_import_config,
    categories_import_projection,
    categories_import_steering,
    categories_rebuild_roots,
    categories_rebuild_roots_promote,
    categories_review_proposal,
    categories_reset,
    categories_run_curation_cycle,
    categories_sandbox_steering_config,
)
from .content_commands import content_inspect, content_list, content_schema_check
from .item_content_commands import (
    content_backfill_item_body_attachments,
    content_scrub_item_inline_body,
)
from .dev_tests import run_category_mapper_tests, run_identifier_backfill_tests
from .messages_commands import (
    messages_backfill_message_body,
    messages_backfill_insight_message_body,
    messages_export_legacy_comments,
    messages_import_legacy_comments,
    messages_repair_insight_titles,
    messages_scrub_inline_content,
)
from .model_defaults import (
    DEFAULT_REFERENCE_FILTER_MODEL,
    DEFAULT_REFERENCE_SUMMARY_MODEL,
)
from .relations_commands import relations_backfill, relations_import_types
from .references_commands import (
    references_attach_extracted_text,
    references_backfill_corpus_storage_paths,
    references_backfill_reviewed_feed_key,
    references_create_doi_backfill_assignment,
    references_create_identifier_backfill_assignment,
    references_curate_recent,
    references_discover_citation_led,
    references_doi_backfill_now,
    references_execute_doi_backfill,
    references_execute_identifier_backfill,
    references_export_analysis_manifest,
    references_export_scope_training,
    references_extract_text_now,
    references_find_pdf_url_text_queue,
    references_find_url_text,
    references_fetch_pdf_url_text_queue,
    references_recount_citation_counts,
    references_process_dedupe_identifiers,
    references_process_resolve_citation_stubs,
    references_filter_extracted_text,
    references_fetch_url_text,
    references_generate_metadata_from_text,
    references_identifier_backfill_now,
    references_label,
    references_labels,
    references_list_predictions,
    references_review_classification,
    references_review_curation,
    references_unlabel,
)
from .catalog import (
    assert_reference_catalog_plan_safety,
    build_prepared_reference_catalog,
    build_reference_catalog_registration_records,
    catalog_items,
)
from .corpora import (
    build_corpus_status,
    build_corpus_sync_plan,
    next_corpus_bootstrap_command,
    print_corpus_status,
    print_corpus_worker_bootstrap,
    run_or_print_corpus_sync_plan,
)
from .env import PAPYRUS_ROOT, graphql_endpoint, load_dotenv, storage_bucket_from_amplify_outputs
from .graphql_authoring import create_authoring_client
from .ids import knowledge_corpus_id
from .newsroom_commands import (
    newsroom_backfill_feed_fields,
    newsroom_backfill_operational_indexes,
    newsroom_import_doctrine,
    newsroom_import_sections,
    newsroom_prune_attachments,
    newsroom_repair_message_status,
    newsroom_purge_planning,
    newsroom_recount_summary,
    newsroom_seed_required_procedures,
)
from .newsroom_summary import (
    update_newsroom_summary_after_assignment_creates,
    update_newsroom_summary_after_extracted_text_attachments,
    update_newsroom_summary_after_reference_registration,
)
from .options import normalize_non_negative_integer, normalize_string, parse_boolean_option, parse_options, resolve_mutation_apply
from .policy_checks import check_backend_node_scripts, check_reference_action_contract
from .records import apply_record_changes, build_record_changes
from .reference_policy import (
    normalize_reference_curation_status,
    normalize_reference_rejection_reason_code,
)
from .source_readiness import (
    SOURCE_READINESS_STATES,
    SOURCE_TEXT_STATES,
    build_extraction_index,
    build_reference_source_status_rows,
    reference_source_readiness,
)
from .seed_edition import seed_edition_content
from .steering import (
    load_steering_config,
    require_corpus_config,
    require_steering_config,
    resolve_classifier_for_corpus,
    selected_corpus_configs,
)


PORTED_COMMANDS = frozenset(
    {
        "content:inspect",
        "content:schema-check",
        "content:list",
        "content:seed-edition",
        "content:backfill-item-body-attachments",
        "content:scrub-item-inline-body",
        "corpora:status",
        "corpora:worker-bootstrap",
        "corpora:sync-from-cloud",
        "corpora:sync-to-cloud",
        "references:make-catalog",
        "references:prepare-catalog",
        "references:create-from-catalog",
        "references:create-from-catalog-split",
        "references:process-status",
        "references:process-create-accession-assignments",
        "references:process-accession-now",
        "references:review-curation",
        "references:list-predictions",
        "references:review-classification",
        "references:label",
        "references:unlabel",
        "references:labels",
        "references:find-fetch-url-text",
        "references:find-fetch-pdf-queue",
        "references:find-discover-citation-led",
        "references:curate-recent",
        "references:process-extract-text-now",
        "references:process-attach-extracted-text",
        "references:process-fetch-url-text",
        "references:process-fetch-pdf-queue",
        "references:process-recount-citation-counts",
        "references:process-dedupe-identifiers",
        "references:find-resolve-citation-stubs",
        "references:process-filter-text",
        "references:process-generate-metadata",
        "references:create-doi-backfill-assignment",
        "references:doi-backfill-now",
        "references:execute-doi-backfill",
        "references:create-identifier-backfill-assignment",
        "references:identifier-backfill-now",
        "references:execute-identifier-backfill",
        "references:export-analysis-manifest",
        "references:export-scope-training",
        "references:backfill-reviewed-feed-key",
        "references:backfill-corpus-storage-paths",
        "assignments:list",
        "assignments:create-research",
        "assignments:create-reporting",
        "assignments:run-research",
        "assignments:run-tavily-deep-research",
        "assignments:poll-tavily-deep-research",
        "assignments:run-reporting",
        "assignments:apply-research-packet",
        "assignments:apply-reporting-packet",
        "assignments:process-proposals",
        "assignments:process-research-now",
        "assignments:run-story-cycle",
        "assignments:story-cycle-output",
        "assignments:orphan-research-packets",
        "assignments:backfill-section-indexes",
        "assignments:for-object",
        "assignments:build-context",
        "assignments:research-packets",
        "assignments:review-reporting-packet",
        "assignments:run-copywriting",
        "assignments:copywriting-output",
        "assignments:events",
        "assignments:process-queue",
        "assignments:claim",
        "assignments:release",
        "assignments:complete",
        "assignments:cancel",
        "assignments:reopen",
        "editions:plan",
        "editions:dispatch-research",
        "editions:dispatch-reporting",
        "editions:purge",
        "analysis:profiles",
        "analysis:validate-profiles",
        "analysis:reindex-plan",
        "analysis:preview-reindex",
        "analysis:create-reindex-assignment",
        "analysis:run-now",
        "analysis:execute-assignment",
        "analysis:entity-graph-preflight",
        "analysis:graph-artifacts",
        "analysis:publish-graph-snapshot",
        "analysis:import-graph-artifact",
        "analysis:doctor-entity-graph",
        "newsroom:recount-summary",
        "newsroom:repair-message-status",
        "newsroom:prune-attachments",
        "newsroom:backfill-feed-fields",
        "newsroom:backfill-operational-indexes",
        "newsroom:import-sections",
        "newsroom:import-doctrine",
        "newsroom:seed-required-procedures",
        "newsroom:purge-planning",
        "relations:import-types",
        "relations:backfill",
        "ontology:preflight",
        "ontology:rank",
        "ontology:status",
        "ontology:explain",
        "ontology:profile",
        "ontology:associate",
        "ontology:dedupe",
        "ontology:recompute-authority",
        "ontology:doctor",
        "messages:export-legacy-comments",
        "messages:import-legacy-comments",
        "messages:backfill-message-body",
        "messages:backfill-insight-message-body",
        "messages:repair-insight-titles",
        "messages:scrub-inline-content",
        "categories:import-steering",
        "categories:import-config",
        "categories:sandbox-steering-config",
        "categories:export-category-set",
        "categories:export-category-tree",
        "categories:export-steering-feedback",
        "categories:export-lexical-steering",
        "categories:export-classifier-seed-manifest",
        "categories:import-projection",
        "categories:draft-create",
        "categories:draft-add-topic",
        "categories:draft-update-topic",
        "categories:draft-archive-topic",
        "categories:draft-promote",
        "categories:rebuild-roots",
        "categories:rebuild-roots-promote",
        "categories:review-proposal",
        "categories:reset",
        "categories:run-curation-cycle",
        "auth:refresh-jwt",
        "batch:register-catalog",
        "batch:enrich-references",
        "test:category-mappers",
        "test:doi-backfill",
        "test:identifier-backfill",
        "policy:check-backend-node-scripts",
        "policy:check-reference-action-contract",
    }
)


def is_ported_command(group: str, command: str) -> bool:
    return f"{group}:{command}" in PORTED_COMMANDS


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        print_usage()
        return 1
    group, command, *rest = args
    try:
        dispatch(group, command, rest)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


def dispatch(group: str, command: str, flags: list[str]) -> None:
    route = f"{group}:{command}"
    if not is_ported_command(group, command):
        raise ValueError(f"Unsupported papyrus command: {group} {command}")
    if route == "content:inspect":
        content_inspect(flags)
    elif route == "content:schema-check":
        content_schema_check(flags)
    elif route == "content:list":
        positional = [token for token in flags if not token.startswith("--")]
        content_list(positional[0] if positional else None, flags)
    elif route == "content:seed-edition":
        seed_edition_content(flags)
    elif route == "content:backfill-item-body-attachments":
        content_backfill_item_body_attachments(flags)
    elif route == "content:scrub-item-inline-body":
        content_scrub_item_inline_body(flags)
    elif route == "corpora:status":
        corpora_status(flags)
    elif route == "corpora:worker-bootstrap":
        corpora_worker_bootstrap(flags)
    elif route == "corpora:sync-from-cloud":
        corpora_sync(flags, direction="from-cloud")
    elif route == "corpora:sync-to-cloud":
        corpora_sync(flags, direction="to-cloud")
    elif route == "references:make-catalog":
        references_make_catalog(flags)
    elif route == "references:prepare-catalog":
        references_prepare_catalog(flags)
    elif route == "references:create-from-catalog":
        references_register_catalog(flags)
    elif route == "references:create-from-catalog-split":
        references_register_catalog_split(flags)
    elif route == "references:process-status":
        require_reference_process_runtime("references process-status")
        references_source_status(flags)
    elif route == "references:process-create-accession-assignments":
        require_reference_process_runtime("references process-create-accession-assignments")
        references_create_accession_assignments(flags)
    elif route == "references:process-accession-now":
        require_reference_process_runtime("references process-accession-now")
        references_accession_now(flags)
    elif route == "references:review-curation":
        references_review_curation(flags)
    elif route == "references:list-predictions":
        references_list_predictions(flags)
    elif route == "references:review-classification":
        references_review_classification(flags)
    elif route == "references:label":
        references_label(flags)
    elif route == "references:unlabel":
        references_unlabel(flags)
    elif route == "references:labels":
        references_labels(flags)
    elif route == "references:find-fetch-url-text":
        require_reference_process_runtime("references find-fetch-url-text")
        references_find_url_text(flags)
    elif route == "references:find-fetch-pdf-queue":
        require_reference_process_runtime("references find-fetch-pdf-queue")
        references_find_pdf_url_text_queue(flags)
    elif route == "references:find-discover-citation-led":
        references_discover_citation_led(flags)
    elif route == "references:curate-recent":
        references_curate_recent(flags)
    elif route == "references:process-extract-text-now":
        require_reference_process_runtime("references process-extract-text-now")
        references_extract_text_now(flags)
    elif route == "references:process-attach-extracted-text":
        require_reference_process_runtime("references process-attach-extracted-text")
        references_attach_extracted_text(flags)
    elif route == "references:process-fetch-url-text":
        require_reference_process_runtime("references process-fetch-url-text")
        references_fetch_url_text(flags)
    elif route == "references:process-fetch-pdf-queue":
        require_reference_process_runtime("references process-fetch-pdf-queue")
        references_fetch_pdf_url_text_queue(flags)
    elif route == "references:process-recount-citation-counts":
        require_reference_process_runtime("references process-recount-citation-counts")
        references_recount_citation_counts(flags)
    elif route == "references:process-dedupe-identifiers":
        require_reference_process_runtime("references process-dedupe-identifiers")
        references_process_dedupe_identifiers(flags)
    elif route == "references:find-resolve-citation-stubs":
        require_reference_process_runtime("references find-resolve-citation-stubs")
        references_process_resolve_citation_stubs(flags)
    elif route == "references:process-filter-text":
        require_reference_process_runtime("references process-filter-text")
        references_filter_extracted_text(flags)
    elif route == "references:process-generate-metadata":
        require_reference_process_runtime("references process-generate-metadata")
        references_generate_metadata_from_text(flags)
    elif route == "references:create-doi-backfill-assignment":
        references_create_doi_backfill_assignment(flags)
    elif route == "references:doi-backfill-now":
        references_doi_backfill_now(flags)
    elif route == "references:execute-doi-backfill":
        references_execute_doi_backfill(flags)
    elif route == "references:create-identifier-backfill-assignment":
        references_create_identifier_backfill_assignment(flags)
    elif route == "references:identifier-backfill-now":
        references_identifier_backfill_now(flags)
    elif route == "references:execute-identifier-backfill":
        references_execute_identifier_backfill(flags)
    elif route == "references:export-analysis-manifest":
        references_export_analysis_manifest(flags)
    elif route == "references:export-scope-training":
        references_export_scope_training(flags)
    elif route == "references:backfill-reviewed-feed-key":
        references_backfill_reviewed_feed_key(flags)
    elif route == "references:backfill-corpus-storage-paths":
        references_backfill_corpus_storage_paths(flags)
    elif route == "assignments:list":
        assignments_list(flags)
    elif route == "assignments:create-research":
        assignments_create_research(flags)
    elif route == "assignments:create-reporting":
        assignments_create_reporting(flags)
    elif route == "assignments:run-research":
        assignments_run_research(flags)
    elif route == "assignments:run-tavily-deep-research":
        assignments_run_tavily_deep_research(flags)
    elif route == "assignments:poll-tavily-deep-research":
        assignments_poll_tavily_deep_research(flags)
    elif route == "assignments:run-reporting":
        assignments_run_reporting(flags)
    elif route == "assignments:apply-research-packet":
        assignments_apply_research_packet(flags)
    elif route == "assignments:apply-reporting-packet":
        assignments_apply_reporting_packet(flags)
    elif route == "assignments:process-proposals":
        assignments_intake_proposals(flags)
    elif route == "assignments:process-research-now":
        assignments_research_intake_now(flags)
    elif route == "assignments:run-story-cycle":
        assignments_run_story_cycle(flags)
    elif route == "assignments:story-cycle-output":
        assignments_story_cycle_output(flags)
    elif route == "assignments:orphan-research-packets":
        assignments_orphan_research_packets(flags)
    elif route == "assignments:backfill-section-indexes":
        assignments_backfill_section_indexes(flags)
    elif route == "assignments:for-object":
        assignments_for_object(flags)
    elif route == "assignments:build-context":
        assignments_build_context(flags)
    elif route == "assignments:research-packets":
        assignments_research_packets(flags)
    elif route == "assignments:review-reporting-packet":
        assignments_review_reporting_packet(flags)
    elif route == "assignments:run-copywriting":
        assignments_run_copywriting(flags)
    elif route == "assignments:copywriting-output":
        assignments_copywriting_output(flags)
    elif route == "assignments:events":
        assignments_events(flags)
    elif route == "assignments:process-queue":
        assignments_process_queue(flags)
    elif route == "assignments:claim":
        assignments_claim(flags)
    elif route == "assignments:release":
        assignments_release(flags)
    elif route == "assignments:complete":
        assignments_complete(flags)
    elif route == "assignments:cancel":
        assignments_cancel(flags)
    elif route == "assignments:reopen":
        assignments_reopen(flags)
    elif route == "editions:plan":
        editions_plan(flags)
    elif route == "editions:dispatch-research":
        editions_dispatch_research(flags)
    elif route == "editions:dispatch-reporting":
        editions_dispatch_reporting(flags)
    elif route == "editions:purge":
        editions_purge(flags)
    elif route == "analysis:profiles":
        analysis_profiles(flags)
    elif route == "analysis:validate-profiles":
        validate_analysis_profiles(flags)
    elif route in {"analysis:reindex-plan", "analysis:preview-reindex"}:
        analysis_reindex_plan(flags)
    elif route == "analysis:create-reindex-assignment":
        analysis_create_reindex_assignment(flags)
    elif route == "analysis:run-now":
        analysis_run_now(flags)
    elif route == "analysis:execute-assignment":
        analysis_execute_assignment(flags)
    elif route == "analysis:entity-graph-preflight":
        analysis_entity_graph_preflight(flags)
    elif route == "analysis:graph-artifacts":
        analysis_graph_artifacts(flags)
    elif route == "analysis:publish-graph-snapshot":
        analysis_publish_graph_snapshot(flags)
    elif route == "analysis:import-graph-artifact":
        analysis_import_graph_artifact(flags)
    elif route == "analysis:doctor-entity-graph":
        analysis_doctor_entity_graph(flags)
    elif route == "newsroom:recount-summary":
        newsroom_recount_summary(flags)
    elif route == "newsroom:repair-message-status":
        newsroom_repair_message_status(flags)
    elif route == "newsroom:prune-attachments":
        newsroom_prune_attachments(flags)
    elif route == "newsroom:backfill-feed-fields":
        newsroom_backfill_feed_fields(flags)
    elif route == "newsroom:backfill-operational-indexes":
        newsroom_backfill_operational_indexes(flags)
    elif route == "newsroom:import-sections":
        newsroom_import_sections(flags)
    elif route == "newsroom:import-doctrine":
        newsroom_import_doctrine(flags)
    elif route == "newsroom:seed-required-procedures":
        newsroom_seed_required_procedures(flags)
    elif route == "newsroom:purge-planning":
        newsroom_purge_planning(flags)
    elif route == "relations:import-types":
        relations_import_types(flags)
    elif route == "relations:backfill":
        relations_backfill(flags)
    elif route.startswith("ontology:"):
        from .ontology_enrichment import (
            ontology_associate,
            ontology_dedupe,
            ontology_doctor,
            ontology_explain,
            ontology_preflight,
            ontology_profile,
            ontology_rank,
            ontology_recompute_authority,
            ontology_status,
        )

        if route == "ontology:preflight":
            ontology_preflight(flags)
        elif route == "ontology:rank":
            ontology_rank(flags)
        elif route == "ontology:status":
            ontology_status(flags)
        elif route == "ontology:explain":
            ontology_explain(flags)
        elif route == "ontology:profile":
            ontology_profile(flags)
        elif route == "ontology:associate":
            ontology_associate(flags)
        elif route == "ontology:dedupe":
            ontology_dedupe(flags)
        elif route == "ontology:recompute-authority":
            ontology_recompute_authority(flags)
        elif route == "ontology:doctor":
            ontology_doctor(flags)
        else:
            raise ValueError(f"Unsupported ontology command: {route}")
    elif route == "messages:export-legacy-comments":
        messages_export_legacy_comments(flags)
    elif route == "messages:import-legacy-comments":
        messages_import_legacy_comments(flags)
    elif route == "messages:backfill-message-body":
        messages_backfill_message_body(flags)
    elif route == "messages:backfill-insight-message-body":
        messages_backfill_insight_message_body(flags)
    elif route == "messages:repair-insight-titles":
        messages_repair_insight_titles(flags)
    elif route == "messages:scrub-inline-content":
        messages_scrub_inline_content(flags)
    elif route == "categories:import-steering":
        categories_import_steering(flags)
    elif route == "categories:import-config":
        categories_import_config(flags)
    elif route == "categories:sandbox-steering-config":
        categories_sandbox_steering_config(flags)
    elif route == "categories:export-category-set":
        categories_export_category_set(flags)
    elif route == "categories:export-category-tree":
        categories_export_category_tree(flags)
    elif route == "categories:export-steering-feedback":
        categories_export_steering_feedback(flags)
    elif route == "categories:export-lexical-steering":
        categories_export_lexical_steering(flags)
    elif route == "categories:export-classifier-seed-manifest":
        categories_export_classifier_seed_manifest(flags)
    elif route == "categories:import-projection":
        categories_import_projection(flags)
    elif route == "categories:draft-create":
        categories_draft_create(flags)
    elif route == "categories:draft-add-topic":
        categories_draft_add_topic(flags)
    elif route == "categories:draft-update-topic":
        categories_draft_update_topic(flags)
    elif route == "categories:draft-archive-topic":
        categories_draft_archive_topic(flags)
    elif route == "categories:draft-promote":
        categories_draft_promote(flags)
    elif route == "categories:rebuild-roots":
        categories_rebuild_roots(flags)
    elif route == "categories:rebuild-roots-promote":
        categories_rebuild_roots_promote(flags)
    elif route == "categories:review-proposal":
        categories_review_proposal(flags)
    elif route == "categories:reset":
        categories_reset(flags)
    elif route == "categories:run-curation-cycle":
        categories_run_curation_cycle(flags)
    elif route == "auth:refresh-jwt":
        refresh_jwt(flags)
    elif route == "batch:register-catalog":
        register_catalog_batches(flags)
    elif route == "batch:enrich-references":
        run_post_ingestion_enrichment_batches(flags)
    elif route == "test:category-mappers":
        run_category_mapper_tests(flags)
    elif route in {"test:doi-backfill", "test:identifier-backfill"}:
        run_identifier_backfill_tests(flags)
    elif route == "policy:check-backend-node-scripts":
        check_backend_node_scripts(flags)
    elif route == "policy:check-reference-action-contract":
        check_reference_action_contract(flags)
    else:
        raise ValueError(f"Unsupported papyrus command: {group} {command}")


def corpora_status(flags: list[str]) -> None:
    options = parse_options(flags)
    steering_config = require_steering_config(options.get("config"))
    client, _ = create_authoring_client()
    graph_state = load_corpus_graph_state(client)
    statuses = [
        build_corpus_status(
            corpus,
            graph_state=graph_state,
            endpoint=graphql_endpoint(),
            force=bool(options.get("force")),
        )
        for corpus in selected_corpus_configs(steering_config, options.get("corpus-key"))
    ]
    payload = {
        "ok": all(status["readiness"]["readyForWorker"] for status in statuses),
        "command": "corpora status",
        "endpoint": graphql_endpoint(),
        "expectedBucket": storage_bucket_from_amplify_outputs(),
        "configPath": steering_config["configPath"],
        "corpora": statuses,
    }
    if options.get("json"):
        print(json.dumps(payload, indent=2))
    else:
        print_corpus_status(payload)


def corpora_worker_bootstrap(flags: list[str]) -> None:
    options = parse_options(flags)
    steering_config = require_steering_config(options.get("config"))
    client, _ = create_authoring_client()
    graph_state = load_corpus_graph_state(client)
    statuses = []
    for corpus in selected_corpus_configs(steering_config, options.get("corpus-key")):
        status = build_corpus_status(
            corpus,
            graph_state=graph_state,
            endpoint=graphql_endpoint(),
            force=bool(options.get("force")),
        )
        status["next"] = next_corpus_bootstrap_command(status)
        statuses.append(status)
    payload = {
        "ok": all(status["target"]["ok"] and status["local"]["exists"] for status in statuses),
        "command": "corpora worker-bootstrap",
        "endpoint": graphql_endpoint(),
        "expectedBucket": storage_bucket_from_amplify_outputs(),
        "configPath": steering_config["configPath"],
        "corpora": statuses,
    }
    if options.get("json"):
        print(json.dumps(payload, indent=2))
    else:
        print_corpus_worker_bootstrap(payload)


def corpora_sync(flags: list[str], *, direction: str) -> None:
    options = parse_options(flags)
    resolve_mutation_apply(options, f"ops corpora sync-{direction}")
    if not options.get("corpus-key"):
        raise ValueError(f"corpora sync-{direction.replace('_', '-')} requires --corpus-key <key>.")
    steering_config = require_steering_config(options.get("config"))
    corpus = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    plan = build_corpus_sync_plan(corpus, direction=direction, options=options)
    run_or_print_corpus_sync_plan(plan, options)


def references_make_catalog(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("input"):
        raise ValueError("references make-catalog requires --input <sources.txt|sources.md>.")
    if not options.get("output"):
        raise ValueError("references make-catalog requires --output <catalog.json>.")
    text = Path(options["input"]).read_text(encoding="utf-8")
    url_regex = re.compile(r"(https?://[^\s)]+)(?:\))?")
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for match in url_regex.finditer(line):
            url = match.group(1).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            before = line.split(url, 1)[0].strip(" \t>-*0123456789.:—")
            items.append(
                catalog_item_with_external_item_id({"source_uri": url, "title": before or None})
            )
    catalog = {"schema_version": 1, "items": items}
    Path(options["output"]).write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"references\tmake-catalog\t{len(items)}\t{options['output']}")


def references_prepare_catalog(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("catalog"):
        raise ValueError("references prepare-catalog requires --catalog <catalog.json>.")
    if not options.get("output"):
        raise ValueError("references prepare-catalog requires --output <prepared-catalog.json>.")
    if not options.get("corpus-key"):
        raise ValueError("references prepare-catalog requires --corpus-key <key>.")
    steering_config = require_steering_config(options.get("config"))
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    catalog = load_json_file(options["catalog"])
    prepared = build_prepared_reference_catalog(
        catalog,
        {
            "corpusConfig": corpus_config,
            "corpusKey": options["corpus-key"],
            "publicationName": steering_config["publication"]["name"],
        },
    )
    write_json_file(options["output"], prepared)
    items = catalog_items(prepared)
    rationale_count = sum(1 for item in items if item.get("ingestion_rationale") or item.get("ingestionRationale"))
    print(
        f"references\tprepare-catalog\t{options['corpus-key']}\t{options['output']}\t"
        f"{len(items)} items\t{rationale_count} rationales"
    )


def references_register_catalog(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references create-from-catalog")
    if not options.get("catalog"):
        raise ValueError("references create-from-catalog requires --catalog <catalog.json>.")
    if not options.get("corpus-key"):
        raise ValueError("references create-from-catalog requires --corpus-key <key>.")
    client, _ = create_authoring_client()
    result = plan_reference_catalog_registration(client, {**options, "__apply": apply})
    print_reference_registration_summary(result["plan"], result["changes"], apply=apply)
    if not apply:
        print("references\tcreate-from-catalog\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    apply_record_changes(client, result["changes"])
    update_newsroom_summary_after_reference_registration(client, result["changes"], result["plan"])


def references_register_catalog_split(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references create-from-catalog-split")
    if not options.get("catalog"):
        raise ValueError("references create-from-catalog-split requires --catalog <catalog.json>.")
    steering_config = require_steering_config(options.get("config"))
    research_key = options.get("research-corpus-key") or steering_config["canonicalTopicSet"]["corpusKey"]
    news_key = options.get("news-corpus-key") or "AI-ML-journalism"
    catalog = maybe_enrich_reference_catalog_title_subtitle(load_json_file(options["catalog"]), options)
    items = catalog_items(catalog)
    buckets = {"research": [], "news": []}
    for item in items:
        bucket = infer_reference_corpus_bucket(item)
        buckets["research" if bucket == "research" else "news"].append(item)
    client, _ = create_authoring_client()
    for bucket_name, corpus_key, bucket_items in (
        ("research", research_key, buckets["research"]),
        ("news", news_key, buckets["news"]),
    ):
        if not bucket_items:
            continue
        bucket_options = {**options, "__apply": apply}
        bucket_options["corpus-key"] = corpus_key
        bucket_catalog = {**catalog, "items": bucket_items}
        write_json_file(
            str(Path(tempfile.gettempdir()) / f"papyrus-register-{bucket_name}.json"),
            bucket_catalog,
        )
        result = plan_reference_catalog_registration(
            client,
            {
                **bucket_options,
                "catalog": bucket_catalog,
            },
        )
        print(
            f"references\tcreate-from-catalog-split\tbucket\t{bucket_name}\tcorpus\t{corpus_key}\t"
            f"items\t{result['plan']['itemCount']}\tapply\t{'yes' if apply else 'no'}"
        )
        print_reference_registration_summary(result["plan"], result["changes"], apply=apply)
        if apply:
            apply_record_changes(client, result["changes"])
            update_newsroom_summary_after_reference_registration(client, result["changes"], result["plan"])


def references_source_status(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("corpus-key"):
        raise ValueError("references process-status requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    status = normalize_source_status_filter(options.get("status"))
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    extraction_index = build_extraction_index(corpus_config.get("path"))
    rows = build_reference_source_status_rows(
        references=references,
        attachments=attachments,
        corpus_id=corpus_id,
        curation_status=status,
        extraction_index=extraction_index,
    )
    counts: dict[str, int] = {}
    processing_counts: dict[str, int] = {}
    text_counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
        process_status = row.get("processingStatus") or row["readiness"].get("processingStatus") or "blocked"
        processing_counts[process_status] = processing_counts.get(process_status, 0) + 1
        text_state = row["readiness"].get("textState") or SOURCE_TEXT_STATES["NOT_APPLICABLE"]
        text_counts[text_state] = text_counts.get(text_state, 0) + 1
    limit = normalize_non_negative_integer(options.get("limit"), "--limit")
    if limit is None:
        limit = 50
    selected = rows if limit == 0 else rows[:limit]
    print(f"references\tprocess-status\tcorpus\t{corpus_id}")
    print(f"references\tprocess-status\tstatus\t{status}")
    for process_status in ("created", "processable", "processed", "blocked"):
        print(f"references\tprocess-status\t{process_status}\t{processing_counts.get(process_status, 0)}")
    for state in SOURCE_READINESS_STATES.values():
        print(f"references\tprocess-status\treadiness-{state}\t{counts.get(state, 0)}")
    for state in SOURCE_TEXT_STATES.values():
        print(f"references\tprocess-status\ttext-{state}\t{text_counts.get(state, 0)}")
    print(f"references\tprocess-status\textraction-snapshots\t{len(extraction_index.snapshot_ids)}")
    print(f"references\tprocess-status\trows\t{len(rows)}")
    for row in selected:
        reference = row["reference"]
        print(
            "\t".join(
                [
                    "reference-process",
                    row.get("processingStatus") or row["readiness"].get("processingStatus") or "blocked",
                    row["state"],
                    row["readiness"].get("textState") or SOURCE_TEXT_STATES["NOT_APPLICABLE"],
                    reference.get("curationStatus") or "-",
                    reference.get("id") or "-",
                    reference.get("externalItemId") or "-",
                    row["readiness"].get("storagePath") or "-",
                    row["readiness"].get("textStoragePath") or "-",
                    reference.get("sourceUri") or "-",
                    next_reference_source_command(row),
                    reference.get("title") or "-",
                ]
            )
        )
    if len(rows) > len(selected):
        print(f"references\tprocess-status\tomitted\t{len(rows) - len(selected)}\tpass --limit {len(rows)} to print every row")


def references_create_accession_assignments(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references process-create-accession-assignments")
    if not options.get("corpus-key"):
        raise ValueError("references process-create-accession-assignments requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    status = normalize_source_status_filter(options.get("status") or "pending")
    if status == "all":
        raise ValueError(
            "references process-create-accession-assignments requires --status pending|accepted|rejected|archived, not all."
        )
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    assignments = client.list_records("Assignment")
    rows = build_reference_source_status_rows(
        references=references,
        attachments=attachments,
        corpus_id=corpus_id,
        curation_status=status,
        extraction_index=None,
    )
    rows = [row for row in rows if row["state"] == SOURCE_READINESS_STATES["URL_ONLY"]]
    now = _utc_now()
    actor_label = normalize_string(options.get("actor")) or "Papyrus content CLI"
    records = build_reference_accession_assignment_records(
        rows,
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        assignments=assignments,
        actor_label=actor_label,
        now=now,
    )
    changes = build_record_changes(client, records)
    print_reference_accession_assignment_summary(rows, changes, apply=apply)
    if not apply:
        print("references\tprocess-create-accession-assignments\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    apply_record_changes(client, changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        changes,
        actor_label=actor_label,
        reason=f"references process-create-accession-assignments {corpus_id}",
    )


def references_accession_now(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("reference"):
        raise ValueError("references process-accession-now requires --reference <reference-id>.")
    client, auth = create_authoring_client()
    references = client.list_records("Reference")
    reference = find_reference_for_source_accession(references, options["reference"])
    if not reference:
        raise ValueError(f"Reference {options['reference']} was not found.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config_by_id_or_key(
        steering_config,
        reference["corpusId"],
        options.get("corpus-key"),
    )
    corpus_id = knowledge_corpus_id(corpus_config)
    attachments = client.list_records("ReferenceAttachment")
    assignments = client.list_records("Assignment")
    readiness = reference_source_readiness(reference, attachments, None)
    if readiness["state"] != SOURCE_READINESS_STATES["URL_ONLY"]:
        raise ValueError(
            f"Reference {reference['id']} is {readiness['state']}, not url_only; accession is only needed for URL-only source material."
        )
    rows = [{"reference": reference, "readiness": readiness, "state": readiness["state"]}]
    now = _utc_now()
    actor_label = (
        normalize_string(options.get("assignee-key"))
        or normalize_string(options.get("assignee"))
        or normalize_string(options.get("actor"))
        or "Papyrus content CLI"
    )
    records = build_reference_accession_assignment_records(
        rows,
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        assignments=assignments,
        actor_label=actor_label,
        now=now,
    )
    changes = build_record_changes(client, records)
    if any(change.get("action") != "noop" for change in changes):
        apply_record_changes(client, changes)
        update_newsroom_summary_after_assignment_creates(
            client,
            changes,
            actor_label=actor_label,
            reason=f"references process-accession-now create {reference['id']}",
        )
    assignment_id = reference_accession_assignment_id(reference, corpus_id)
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="claim",
        assignment_id=assignment_id,
        options=options,
        actor_label=actor_label,
    )
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment {assignment_id} was not found after planning.")
    execution = execute_reference_accession_assignment(client, assignment, options)
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="complete",
        assignment_id=assignment_id,
        options=options,
        actor_label=actor_label,
    )
    print(f"reference-process-accession-now\tassignment\t{assignment_id}")
    print(f"reference-process-accession-now\trun\t{execution['runId']}")
    print(f"reference-process-accession-now\tmanifest\t{execution['manifestPath']}")
    print(f"reference-process-accession-now\tstorage-path\t{execution.get('storagePath') or '-'}")


def plan_reference_catalog_registration(client, options: dict[str, Any]) -> dict[str, Any]:
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    catalog_path = options.get("catalog")
    catalog = maybe_enrich_reference_catalog_title_subtitle(
        load_json_file(catalog_path) if catalog_path else options["catalog"],
        options,
        persist=bool(options.get("__apply") and catalog_path),
    )
    if options.get("skip-existing", True) is not False and str(options.get("skip-existing", "true")).lower() != "false":
        existing = client.list_records("Reference")
        corpus_id = knowledge_corpus_id(corpus_config)
        existing_ids = {
            ref["externalItemId"]
            for ref in existing
            if ref.get("corpusId") == corpus_id and ref.get("externalItemId")
        }
        filtered = [
            item
            for item in catalog_items(catalog)
            if (item.get("item_id") or item.get("externalItemId") or item.get("id")) not in existing_ids
        ]
        skipped = len(catalog_items(catalog)) - len(filtered)
        if skipped:
            print(f"references\tcreate-from-catalog\tskip-existing\t{skipped} duplicates")
        catalog = {**catalog, "items": filtered}
    plan_options = {
        "corpusConfig": corpus_config,
        "corpusId": knowledge_corpus_id(corpus_config),
        "classifierId": options.get("classifier") or resolve_classifier_for_corpus(steering_config, corpus_config, None),
        "status": normalize_reference_curation_status(options.get("status"), "pending"),
        "reasonCode": normalize_reference_rejection_reason_code(
            options.get("reason-code") or options.get("reasonCode"),
            required=normalize_reference_curation_status(options.get("status"), "pending") == "rejected",
        ),
        "note": options.get("note"),
        "ingestionRationale": options.get("ingestion-rationale") or options.get("ingestionRationale"),
        "actor": options.get("actor") or "Papyrus content CLI",
    }
    plan = build_reference_catalog_registration_records(catalog, plan_options)
    existing_run = client.get_record("KnowledgeImportRun", plan["importRunId"])
    if existing_run and existing_run.get("importedAt"):
        plan = build_reference_catalog_registration_records(
            catalog,
            {**plan_options, "importedAt": existing_run["importedAt"]},
        )
    assert_reference_catalog_plan_safety(plan)
    changes = build_record_changes(client, plan["records"])
    return {"plan": plan, "changes": changes, "corpusConfig": corpus_config, "options": options}


def print_reference_registration_summary(plan: dict[str, Any], changes: list[dict[str, Any]], *, apply: bool) -> None:
    action_counts = {"create": 0, "update": 0, "noop": 0}
    for change in changes:
        action_counts[change.get("action", "noop")] = action_counts.get(change.get("action", "noop"), 0) + 1
    print(f"references\tcreate-from-catalog\timport-run\t{plan['importRunId']}")
    print(f"references\tcreate-from-catalog\titems\t{plan['itemCount']}")
    print(
        f"references\tcreate-from-catalog\tsummary\tcreate={action_counts['create']}\t"
        f"update={action_counts['update']}\tnoop={action_counts['noop']}"
    )
    print(f"references\tcreate-from-catalog\tapply\t{'yes' if apply else 'no'}")


def sync_reference_vectors_after_registration(result: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    if parse_boolean_option(options.get("vector-sync"), True, "--vector-sync") is False:
        return {"lines": ["references\tvector-sync\tdisabled"]}
    reference_ids = sorted(
        {
            change["expected"].get("lineageId") or change["expected"].get("id")
            for change in result["changes"]
            if change.get("modelName") == "Reference" and change.get("action") in {"create", "update"}
        }
    )
    if not reference_ids:
        return {"lines": ["references\tvector-sync\tskipped\tno GraphQL Reference changes"]}
    lines = []
    for index in range(0, len(reference_ids), 100):
        batch = reference_ids[index : index + 100]
        args = [
            "run",
            "papyrus",
            "knowledge-vector-index",
            "--action",
            "sync",
            "--force",
            "--progress-every",
            "0",
            *sum([["--reference-id", reference_id] for reference_id in batch], []),
        ]
        completed = subprocess.run(["poetry", *args], cwd=PAPYRUS_ROOT, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "vector sync failed"
            lines.append(f"references\tvector-sync\tfailed\t{len(batch)}\t{message}")
            raise RuntimeError(f"Reference registration updated GraphQL state but vector sync failed: {message}")
        lines.append(f"references\tvector-sync\tsynced\t{len(batch)}")
    return {"lines": lines}


def fetch_reference_url_text_after_registration(
    client,
    result: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    if parse_boolean_option(options.get("url-text"), True, "--url-text") is False:
        return {"lines": ["references\tprocess-fetch-url-text\tdisabled"]}
    reference_ids = sorted(
        {
            change["expected"].get("id")
            for change in result["changes"]
            if change.get("modelName") == "Reference" and change.get("action") in {"create", "update"}
        }
    )
    if not reference_ids:
        return {"lines": ["references\tprocess-fetch-url-text\tskipped\tno GraphQL Reference changes"]}
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    semantic_relations = client.list_records("SemanticRelation")
    corpus_config = result.get("corpusConfig") or {}
    corpus_id = result.get("plan", {}).get("corpusId")
    max_count = normalize_non_negative_integer(options.get("url-text-max-count"), "--url-text-max-count")
    force = parse_boolean_option(options.get("url-text-force"), False, "--url-text-force")
    model = normalize_string(options.get("url-text-model")) or DEFAULT_REFERENCE_FILTER_MODEL
    extraction = run_reference_url_text_extraction(
        client=client,
        references=references,
        attachments=attachments,
        semantic_relations=semantic_relations,
        corpus_key_by_id={str(corpus_id or ""): str(corpus_config.get("key") or "")},
        corpus_id=str(corpus_id or "") or None,
        reference_ids=set(reference_ids),
        curation_status="all",
        max_count=max_count,
        force=force,
        apply=True,
        bucket=normalize_string(options.get("bucket")),
        model=model,
    )
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        extraction["changes"],
        actor_label=str(options.get("actor") or "Papyrus content CLI"),
        reason=f"references create-from-catalog process-fetch-url-text {corpus_id or '-'}",
    )
    lines = [
        f"references\tprocess-fetch-url-text\teligible\t{extraction['eligibleCount']}",
        f"references\tprocess-fetch-url-text\tskipped-existing\t{extraction['skippedExistingCount']}",
        f"references\tprocess-fetch-url-text\tplanned\t{extraction['plannedCount']}",
        f"references\tprocess-fetch-url-text\tplanned-attachments\t{extraction.get('plannedAttachmentCount', 0)}",
        f"references\tprocess-fetch-url-text\tplanned-reference-metadata\t{extraction.get('plannedReferenceMetadataCount', 0)}",
        f"references\tprocess-fetch-url-text\tfiltered\t{extraction.get('filteredCount', 0)}",
        f"references\tprocess-fetch-url-text\tfallback-raw\t{extraction.get('fallbackRawCount', 0)}",
        f"references\tprocess-fetch-url-text\tchanges\t{extraction['changeCount']}",
        f"references\tprocess-fetch-url-text\treference-metadata-changes\t{extraction.get('referenceMetadataChangeCount', 0)}",
        f"references\tprocess-fetch-url-text\tattachment-changes\t{extraction.get('attachmentChangeCount', 0)}",
        f"references\tprocess-fetch-url-text\tfailures\t{len(extraction['failures'])}",
        f"references\tprocess-fetch-url-text\tmodel\t{model}",
    ]
    if max_count:
        lines.append(f"references\tprocess-fetch-url-text\tmax-count\t{max_count}")
    for failure in extraction["failures"][:10]:
        lines.append(
            f"reference-url-text\tfailed\t{failure.get('referenceId') or '-'}\t"
            f"{failure.get('sourceUri') or '-'}\t{failure.get('error') or 'unknown error'}"
        )
    for fallback in (extraction.get("filterFallbacks") or [])[:10]:
        lines.append(
            f"reference-url-text\tfilter-fallback\t{fallback.get('referenceId') or '-'}\t"
            f"{fallback.get('sourceUri') or '-'}\t"
            f"{json.dumps(fallback.get('reason') or {}, sort_keys=True)}"
        )
    if len(extraction["failures"]) > 10:
        lines.append(f"references\tprocess-fetch-url-text\tomitted-failures\t{len(extraction['failures']) - 10}")
    return {"lines": lines}


def generate_reference_metadata_after_registration(
    client,
    result: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    if parse_boolean_option(options.get("metadata-from-text"), True, "--metadata-from-text") is False:
        return {"lines": ["references\tprocess-generate-metadata\tdisabled"]}
    reference_ids = sorted(
        {
            change["expected"].get("id")
            for change in result["changes"]
            if change.get("modelName") == "Reference" and change.get("action") in {"create", "update"}
        }
    )
    if not reference_ids:
        return {"lines": ["references\tprocess-generate-metadata\tskipped\tno GraphQL Reference changes"]}
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    corpus_id = result.get("plan", {}).get("corpusId")
    max_count = normalize_non_negative_integer(options.get("metadata-max-count"), "--metadata-max-count")
    generation = run_reference_metadata_generation_from_extracted_text(
        references=references,
        attachments=attachments,
        corpus_id=str(corpus_id or "") or None,
        reference_ids=set(reference_ids),
        curation_status="all",
        max_count=max_count,
        model=normalize_string(options.get("metadata-model")) or DEFAULT_REFERENCE_SUMMARY_MODEL,
        apply=True,
        bucket=normalize_string(options.get("bucket")),
    )
    lines = [
        f"references\tprocess-generate-metadata\tattempted\t{generation['attemptedCount']}",
        f"references\tprocess-generate-metadata\tgenerated\t{generation['generatedCount']}",
        f"references\tprocess-generate-metadata\tskipped-missing-text\t{generation['skippedMissingTextCount']}",
        f"references\tprocess-generate-metadata\tgeneration-failures\t{generation['generationFailureCount']}",
    ]
    if max_count:
        lines.append(f"references\tprocess-generate-metadata\tmax-count\t{max_count}")
    failure_rows = [
        item for item in generation.get("items") or []
        if str(item.get("status") or "") not in {"generated", "skipped_missing_text"}
    ]
    for failure in failure_rows[:10]:
        reference = failure.get("reference") if isinstance(failure.get("reference"), dict) else {}
        lines.append(
            f"reference-metadata\tfailed\t{reference.get('id') or '-'}\t"
            f"{reference.get('externalItemId') or '-'}\t{failure.get('error') or 'generation failed'}"
        )
    if len(failure_rows) > 10:
        lines.append(f"references\tprocess-generate-metadata\tomitted-failures\t{len(failure_rows) - 10}")
    return {"lines": lines}


def maybe_enrich_reference_catalog_title_subtitle(
    catalog: dict[str, Any],
    options: dict[str, Any],
    *,
    persist: bool = False,
) -> dict[str, Any]:
    if parse_boolean_option(options.get("title-subtitle-enrichment"), False, "--title-subtitle-enrichment") is False:
        return catalog
    raise ValueError(
        "Pre-registration title/subtitle enrichment is disabled. "
        "Register references first, fetch extracted text, then run "
        "`references process-generate-metadata`."
    )


def infer_reference_corpus_bucket(item: dict[str, Any]) -> str:
    source_uri = normalize_string(item.get("source_uri") or item.get("sourceUri") or item.get("url")) or ""
    media_type = normalize_string(item.get("media_type") or item.get("mediaType")) or ""
    host = ""
    pathname = ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(source_uri)
        host = parsed.hostname or ""
        pathname = parsed.path.lower()
    except ValueError:
        pass
    uri = source_uri.lower()
    if media_type == "application/pdf" or uri.endswith(".pdf") or pathname.endswith(".pdf"):
        return "research"
    research_hosts = {
        "arxiv.org",
        "aclanthology.org",
        "openreview.net",
        "proceedings.neurips.cc",
        "neurips.cc",
        "dl.acm.org",
        "doi.org",
        "pmc.ncbi.nlm.nih.gov",
        "drops.dagstuhl.de",
    }
    if host in research_hosts or host.endswith(".ijcai.org"):
        return "research"
    if host.endswith("nature.com") and "/articles/" in pathname:
        return "research"
    return "news"


def load_corpus_graph_state(client) -> dict[str, Any]:
    return {
        "corpora": client.list_records("KnowledgeCorpus"),
        "references": client.list_records("Reference"),
        "referenceAttachments": client.list_records("ReferenceAttachment"),
        "importRuns": client.list_records("KnowledgeImportRun"),
    }


def normalize_source_status_filter(value: Any) -> str:
    normalized = str(value or "all").strip().lower()
    if normalized in {"pending", "accepted", "rejected", "archived", "all"}:
        return normalized
    raise ValueError("--status must be pending, accepted, rejected, archived, or all.")


def load_json_file(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def write_json_file(path: str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_reference_process_runtime(command_name: str) -> None:
    runtime_role = str(os.environ.get("PAPYRUS_RUNTIME_ROLE") or "").strip().lower()
    if runtime_role and runtime_role not in {"cli", "worker"}:
        raise ValueError(
            f"{command_name} requires utility worker runtime with reachable GROBID service/container. "
            f"Current PAPYRUS_RUNTIME_ROLE={runtime_role!r} is not supported."
        )
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        raise ValueError(
            f"{command_name} requires utility worker runtime with reachable GROBID service/container. "
            "API/Lambda runtime is not supported for process commands."
        )


def print_usage() -> None:
    print("Usage: poetry run papyrus <group> <command> [options]")
    print("Python-native: content inspect, content schema-check, content list articles,")
    print("  corpora status/worker-bootstrap/sync-*, references create/process/curate/export commands,")
    print("  assignments list, analysis profiles/validate-profiles/reindex-plan/preview-reindex/")
    print("  create-reindex-assignment/run-now/execute-assignment (auto sync-from-cloud when local catalog is stale;")
    print("  --skip-sync-from-cloud/--sync-from-cloud)/entity-graph-preflight/graph-artifacts/publish-graph-snapshot/import-graph-artifact/doctor-entity-graph,")
    print("  newsroom recount-summary/repair-message-status/prune-attachments/backfill-feed-fields/")
    print("  backfill-operational-indexes/import-sections,")
    print("  relations import-types/backfill, ontology preflight/rank/status/explain/profile/associate/dedupe/recompute-authority/doctor,")
    print("  messages export/import-legacy-comments,")
    print("  categories import/export/draft/review/curation-cycle/rebuild-roots commands,")
    print("    note: rebuild-roots + taxonomy discovery run BERTopic clustering;")
    print("    semi-supervised classifier behavior lives in Biblicus topic-classifier train/project,")
    print("  auth refresh-jwt, batch register-catalog/enrich-references,")
    print("  and test category-mappers/doi-backfill/identifier-backfill")
