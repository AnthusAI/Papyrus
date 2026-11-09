"""Papyrus tools for Tactus procedure agents, shipped inside the package.

A procedure loads them by module name, so it runs the same from an installed site as from a Papyrus checkout:

    Toolset "papyrus" { type = "plugin", modules = {"papyrus_newsroom.tactus_tools"} }

Every public function defined here is a tool. Story writes go through the same functions as the
``papyrus stories`` commands, so an agent can do nothing the CLI could not.
"""

from __future__ import annotations

import io
import json
import time
from typing import Any

from papyrus_newsroom.tactus_runtime import execute_tactus_harnessed as _execute_tactus_harnessed


def execute_tactus(
    tactus: str,
    harness: str = "raw",
    assignment_id: str = "",
    assignment_item_json: str = "",
    corpus_key: str = "",
    max_evidence_items: int = 20,
    research_mode: str = "",
    knowledge_query_scope: dict | None = None,
) -> dict:
    """Execute a Papyrus Tactus snippet through the newsroom runtime.

    Use harness="research" when the caller should provide only the research body.
    The research harness preloads the assignment item, OpenAI web search helper,
    corpus key, and dry-run research-plan finisher.
    """

    return _execute_tactus_harnessed(
        tactus,
        harness=harness,
        assignment_id=assignment_id,
        assignment_item_json=assignment_item_json,
        corpus_key=corpus_key,
        max_evidence_items=max_evidence_items,
        research_mode=research_mode,
        knowledge_query_scope=knowledge_query_scope,
    )


def papyrus_editorial_context(section: str = "", story: str = "") -> dict:
    """Return the publication's current editorial guidance for a section or story: mission, policy,
    section guidance and kill criteria, each with its source. Read it before writing; it overrides memory."""

    from papyrus_newsroom.newsroom import papyrus_editorial_context as _editorial_context

    return _editorial_context(section_id=section, story_lineage_id=story)


def papyrus_fetch_pdf_text(url: str, first_page: int = 1, last_page: int = 0) -> dict:
    """Download a PDF (for example a TTAB or court opinion) and return its text page by page,
    numbered as printed in the file, so findings can be pin-cited. last_page 0 means the end."""

    from papyrus_content.pdf_text import download_pdf, extract_pages

    page_count, pages = extract_pages(download_pdf(url), first_page, last_page)
    return {"url": url, "pageCount": page_count, "pages": pages}


def papyrus_curate_reference(reference_id: str, force: bool = False) -> dict:
    """Curate one Reference before an editor reviews it: capture its full text, store the completeness signals,
    write a summary and, for a research paper, GROBID fields. Safe to run twice (a finished Reference is left alone).
    Returns the outcome and the status of each stage."""

    from papyrus_content.reference_curation import curate_reference_by_id

    return curate_reference_by_id(reference_id, force=force)


def papyrus_create_story(title: str, section: str, author_label: str, stage: str = "reporting", summary: str = "", based_on_references: str = "") -> dict:
    """Create a story (a new item lineage) in a section at the idea, assignment or reporting stage.
    Pass the Reference ids the story is based on, comma separated, in based_on_references: each is linked to the story.
    Returns its lineage id and first version id."""

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import create_story, link_reference_to_story

    client, _ = create_authoring_client()
    item = create_story(client, title=title, section_key=section or None, stage=stage, summary=summary or None, actor=author_label)
    for reference_id in [value.strip() for value in based_on_references.split(",") if value.strip()]:
        link_reference_to_story(client, item["lineageId"], reference_id, role="based_on", actor=author_label)
    return {"lineageId": item["lineageId"], "versionId": item["id"], "stage": item.get("stage")}


def papyrus_save_story_version(story: str, body_markus: str, reason: str, author_label: str, front_matter_yaml: str = "", stage: str = "") -> dict:
    """Save the next draft version of a story: YAML front matter (without --- lines) and a Markus body.
    Empty front matter keeps the latest version's. Never publishes. Returns the new version id, and an
    editorialCheck summary (the new version is checked as it is saved; content already checked is not checked again)."""

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import latest_story_version, save_story_version

    client, _ = create_authoring_client()
    if not front_matter_yaml:
        latest = latest_story_version(client, story)
        metadata = latest.get("metadata")
        front_matter_yaml = (json.loads(metadata) if isinstance(metadata, str) and metadata else metadata or {}).get("frontMatterYaml") or ""
    record = save_story_version(
        client, story, front_matter_yaml=front_matter_yaml or None, body_markus=body_markus, actor=author_label, change_reason=reason, stage=stage or None
    )
    result = {"versionId": record["id"], "versionNumber": record["versionNumber"], "status": record.get("status")}
    # Every saved version is checked, like the editor's saves; a failed check never undoes the save.
    from papyrus_content.editorial_commands import check_saved_version_best_effort

    result["editorialCheck"] = check_saved_version_best_effort(record["id"], client.graphql)
    return result


def papyrus_link_story_reference(story: str, reference: str, role: str, author_label: str, note: str = "", citation_key: str = "") -> dict:
    """Attach a reference to a story as consulted (used in reporting), cited (appears in the article) or based_on (the story is made from it)."""

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import link_reference_to_story

    client, _ = create_authoring_client()
    return link_reference_to_story(client, story, reference, role=role, actor=author_label, note=note or None, citation_key=citation_key or None)


def papyrus_link_stories(story: str, see_also_stories: Any, author_label: str, note: str = "", see_also_references: Any = None) -> dict:
    """Link a story to other stories for its See also block: pass the story (lineage id or slug) and see_also_stories (a list, or comma separated), each a lineage id or slug.
    There is no relation to choose. Every one must be an existing story and none the story itself; a link that exists in either direction is left alone.
    Returns one row per target with its title, type, stage, outcome (write or exists) and a warning when it is not published yet.
    see_also_references (optional, a list or comma separated) are Reference ids to "read this source too"; each must exist and be accepted, or nothing is written."""

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_links import link_reference_set, link_story_set, resolve_link_references, resolve_link_targets, resolve_story

    targets = see_also_stories.split(",") if isinstance(see_also_stories, str) else list(see_also_stories or [])
    reference_ids = see_also_references.split(",") if isinstance(see_also_references, str) else list(see_also_references or [])
    client, _ = create_authoring_client()
    if targets:
        resolved, others = resolve_link_targets(client, story, targets)
    else:
        if not reference_ids:
            raise ValueError("At least one related story or Reference is required.")
        resolved, others = resolve_story(client, story), []
    references = resolve_link_references(client, reference_ids)
    return {"story": resolved.get("lineageId") or resolved["id"], "links": link_story_set(client, resolved, others, actor=author_label, provenance="derived", note=note or None),
            "referenceLinks": link_reference_set(client, resolved, references, actor=author_label, provenance="derived", note=note or None)}


def papyrus_link_concepts(target_kind: str, target: str, concepts: Any, author_label: str, note: str = "") -> dict:
    """Tag a story or a Reference with existing accepted concepts. target_kind is "story" or "reference"; target is the story (lineage id or slug) or the Reference id; concepts is a list
    (or comma separated) of exact node keys, hashtags, names or aliases. A concept is never created and never guessed: an unknown name is an error that lists the closest accepted
    concepts, an ambiguous one lists its node keys. A tag that already exists (also the older related_to, or a mention) is left alone, and a tag a person rejected stays rejected.
    There is no field for a relation or a state. Returns one row per concept with its outcome and whether it has a public wiki page (a warning says when it does not)."""

    from papyrus_content.concept_tags import tag_with_concepts
    from papyrus_content.graphql_authoring import create_authoring_client

    names = concepts.split(",") if isinstance(concepts, str) else list(concepts or [])
    client, _ = create_authoring_client()
    return tag_with_concepts(client, target_kind, target, names, actor=author_label, provenance="derived", note=note or None)


def papyrus_find_or_register_source(url: str, title: str, corpus: str, author_label: str, media_type: str = "text/html", rationale: str = "") -> dict:
    """Return the publication's Reference for a source URL (an opinion PDF, a notice, an article),
    registering it as pending in the corpus when it is new. Use its id with papyrus_link_story_reference."""

    import os

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.reference_intake import canonical_source_url, find_or_create_source_reference

    client, _ = create_authoring_client()
    if not client.get_record("KnowledgeCorpus", corpus):
        raise ValueError(f"Unknown KnowledgeCorpus {corpus}.")
    item = {"source_uri": canonical_source_url(url), "title": title, "media_type": media_type, "ingestion_rationale": rationale or f"Source for a story, registered by {author_label}."}
    publication = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").rstrip("/")
    return find_or_create_source_reference(client, client.list_records("Reference"), publication=publication, corpus_id=corpus, item=item, actor=f"agent:{author_label}")


def papyrus_set_story_slug(story: str, slug: str, author_label: str) -> dict:
    """Give a story's draft its page address (for example in-re-wemby-corporation for the caption
    In re Wemby Corporation): lowercase letters, digits and single hyphens. New stories start with a
    placeholder slug. Refuses a published story: an editor changes a live address."""

    import contextlib
    import io

    from papyrus_content.story_commands import stories_set_slug

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        stories_set_slug(["--story", story, "--slug", slug, "--author-label", author_label])
    lines = [line.split("\t") for line in output.getvalue().splitlines() if line.strip()]
    return {"slug": slug, "lines": ["\t".join(line) for line in lines]}


def papyrus_story_version(version: str) -> dict:
    """Read one story version in full: its YAML front matter and Markus body, with its state and stage.
    Use the version ids from papyrus_story_versions or papyrus_save_story_version."""

    from papyrus_content.graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    record = client.get_record("Item", version)
    if record is None:
        raise ValueError(f"Story version not found: {version}")
    metadata = record.get("metadata")
    metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
    fields = ("id", "lineageId", "versionNumber", "versionState", "status", "stage", "section", "slug")
    return {**{field: record.get(field) for field in fields}, "frontMatterYaml": metadata.get("frontMatterYaml") or "", "bodyMarkus": record.get("bodyMarkus") or ""}


def papyrus_story_versions(story: str) -> list[dict[str, Any]]:
    """List a story's versions, newest first, with their state, author and reason."""

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import story_versions

    client, _ = create_authoring_client()
    fields = ("id", "versionNumber", "versionState", "status", "stage", "versionCreatedAt", "versionCreatedBy", "changeReason")
    return [{field: version.get(field) for field in fields} for version in story_versions(client, story)]


CHECK_WAIT_SECONDS = 10
CHECK_POLL_SECONDS = 1


def _finding(finding: dict[str, Any]) -> dict[str, Any]:
    """One finding for a bot. A finding with no quote is about the whole document (a review rule such as
    general-meaning-first), so it says `scope: "document"`; a paragraph is returned only when the stored finding names one."""
    quote = finding.get("excerpt")
    result = {
        "id": finding.get("id"),
        "rule": finding.get("policyId"),
        "severity": finding.get("severity"),
        "status": finding.get("status"),
        "message": finding.get("message"),
        "quote": quote,
        "scope": "quote" if isinstance(quote, str) and quote.strip() else "document",
        "probability": finding.get("probability"),
    }
    if finding.get("paragraph") not in (None, ""):
        result["paragraph"] = finding["paragraph"]
    return result


def _lanes_finished(lanes: Any) -> bool:
    from papyrus_content.editorial_checks import FINISHED_LANE_STATUSES, _awsjson_document

    return all((lane or {}).get("status") in FINISHED_LANE_STATUSES for lane in (_awsjson_document(lanes) or {}).values() if isinstance(lane, dict))


def _check_result(item: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    findings = [_finding(finding) for finding in run["findings"]]
    from papyrus_content.editorial_checks import lanes_not_run

    violations, reviews = int(run.get("violations") or 0), int(run.get("reviews") or 0)
    lanes = run.get("lanes")
    not_run = lanes_not_run(lanes)
    # A lane that broke (unavailable, failed, partial) makes the result not clean; one switched off or skipped for want of a
    # mission is the publication's choice, so it stays clean but is named in lanesNotRun.
    return {
        "status": "checked",
        "clean": violations == 0 and reviews == 0 and _lanes_finished(lanes),
        "lanesNotRun": not_run,
        "versionId": item["id"],
        "lineageId": run.get("lineageId") or item.get("lineageId"),
        "versionNumber": int(run.get("versionNumber") or item.get("versionNumber") or 0),
        "packVersion": run.get("packVersion"),
        "contentHash": run.get("contentHash"),
        "checkedAt": run.get("checkedAt"),
        "violations": violations,
        "reviews": reviews,
        "findings": findings,
        "lanes": run.get("lanes"),
    }


def papyrus_copy_edit_story_version(story: str, version: str = "", suggest: bool = True) -> dict:
    """Copy-edit one saved version of a story (the newest by default). Applies ONLY the mechanical fixes the site's policies
    declare (a phrase policy with a replacement, such as a stale name, or the uncontracted-forms check where the house voice wants
    contractions) and saves them as one new version by AI; never rewrites anything else, never publishes, never moves the stage.
    Each remaining violation or review finding that quotes text gets rewrite options, stored with the version's check result.
    Returns version (the version id to hand back: the new one, or the one you gave when nothing was mechanical), versionNumber,
    changed, mechanicalFixes, violations, reviews, findings (with suggest options), hold and reason. Return
    {"version": version, "hold": hold, "reason": reason} from the procedure: a hold means an error-severity violation survived and a
    person has to decide, so the engine raises a review request instead of advancing the story."""

    from papyrus_content.copy_edit import copy_edit_version
    from papyrus_content.editorial_checks import GraphQLEditorialStore, Services
    from papyrus_content.graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    services = Services(store=GraphQLEditorialStore(execute=client.graphql, tenant_id=getattr(client, "tenant_id", None)))
    return copy_edit_version(client, services, story=story, version=version or None, suggest=suggest)


def papyrus_check_story_version(story: str = "", version: str = "", version_number: int = 0, wait_seconds: int = CHECK_WAIT_SECONDS) -> dict:
    """Run the editorial checks (the publication's and the section's policies, rules and classifier lanes) on
    one saved version of a story and return the findings. Name the version by its id (from papyrus_save_story_version
    or papyrus_story_versions), or give the story's lineage id with a version_number (0 = the newest version).
    The version is checked against its own section's policy pack and the result is stored with it.
    Returns status "checked", "skipped" (editorial checks are turned off) or "pending" (no stored result within
    wait_seconds); clean is true only when checked with no violations and nothing for review. Each finding has
    id, rule (policy id), severity, status ("violation" or "review"), message, quote, scope and probability.
    scope is "quote" when the finding quotes the text, and "document" when quote is empty: the finding is about the whole
    document, so judge it against the full text instead of searching for the quote."""

    from papyrus_content.editorial_commands import read_item_check_run, request_item_check
    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import story_versions

    client, _ = create_authoring_client()
    if version:
        item = client.get_record("Item", version)
        if item is None:
            raise ValueError(f"Story version not found: {version}")
        if story and item.get("lineageId") != story:
            raise ValueError(f"Version {version} is not a version of story {story}.")
    elif story:
        versions = story_versions(client, story)
        if version_number:
            versions = [row for row in versions if int(row.get("versionNumber") or 0) == version_number]
        if not versions:
            raise ValueError(f"Story {story} has no version {version_number}." if version_number else f"Story not found: {story}")
        item = versions[0]
    else:
        raise ValueError("Give a version id, or a story lineage id (with an optional version_number).")

    summary = request_item_check(item["id"], client.graphql)
    base = {"versionId": item["id"], "lineageId": item.get("lineageId"), "versionNumber": int(item.get("versionNumber") or 0)}
    if summary.get("skipped") and summary["skipped"] != "unchanged":  # "unchanged": already checked, the stored result stands
        return {**base, "status": "skipped", "clean": False, "reason": summary["skipped"], "findings": []}
    deadline = time.monotonic() + max(wait_seconds, 0)
    while True:
        run = read_item_check_run(item["id"], client.graphql)
        if run is not None:
            return _check_result(item, run)
        if time.monotonic() >= deadline:
            return {**base, "status": "pending", "clean": False, "findings": []}
        time.sleep(CHECK_POLL_SECONDS)


def papyrus_editor_review_inputs(story: str, version: str) -> dict:
    """Everything an editor reads to review one story version: the version (front matter and Markus body), its pipe tables
    (the editorial check skips them), the References linked to the story, the brief (or none: then the doctrine is the brief),
    the editorial context with its hash, and the editorial check run on that exact version (Humanus rules and the Jev lane)."""

    from papyrus_content.editor_review import gather_review_inputs
    from papyrus_content.graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    return gather_review_inputs(
        client, story, version,
        run_check=lambda version_id: papyrus_check_story_version(version=version_id),
        read_context=lambda lineage: papyrus_editorial_context(story=lineage),
    )


def papyrus_record_editor_review(story: str, version: str, review: dict, model: str, context_hash: str) -> dict:
    """Record the editor's review as Item.metadata.editorReview on the version it reviewed and return the stage-bot contract
    {version, hold, reason, verdict}: approve lets the engine advance the story, revise or reframe holds it. A review that
    left a criterion unassessed or has an error-level failure cannot approve. Writes metadata only: never a Message, never a
    state or stage change, never publishing."""

    from datetime import datetime, timezone

    from papyrus_content.editor_review import record_review
    from papyrus_content.editorial_commands import read_item_check_run
    from papyrus_content.graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    stored = read_item_check_run(version, client.graphql)
    check = _check_result({"id": version, "lineageId": story}, stored) if stored is not None else None
    return record_review(client, story, version, review, model=model, context_hash=context_hash, check=check,
                         at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
