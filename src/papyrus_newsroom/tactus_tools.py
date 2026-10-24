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
import urllib.request
from typing import Any

from papyrus_newsroom.tactus_runtime import execute_tactus_harnessed as _execute_tactus_harnessed

PDF_FETCH_TIMEOUT_SECONDS = 60
PDF_FETCH_USER_AGENT = "Papyrus procedure (+https://github.com/AnthusAI/Papyrus)"


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

    from pypdf import PdfReader

    request = urllib.request.Request(url, headers={"User-Agent": PDF_FETCH_USER_AGENT})
    with urllib.request.urlopen(request, timeout=PDF_FETCH_TIMEOUT_SECONDS) as response:
        reader = PdfReader(io.BytesIO(response.read()))
    page_count = len(reader.pages)
    end = page_count if last_page <= 0 else min(last_page, page_count)
    pages = [{"page": number, "text": reader.pages[number - 1].extract_text() or ""} for number in range(max(first_page, 1), end + 1)]
    return {"url": url, "pageCount": page_count, "pages": pages}


def papyrus_create_story(title: str, section: str, author_label: str, stage: str = "reporting", summary: str = "") -> dict:
    """Create a story (a new item lineage) in a section at the idea, assignment or reporting stage.
    Returns its lineage id and first version id."""

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import create_story

    client, _ = create_authoring_client()
    item = create_story(client, title=title, section_key=section or None, stage=stage, summary=summary or None, actor=author_label)
    return {"lineageId": item["lineageId"], "versionId": item["id"], "stage": item.get("stage")}


def papyrus_save_story_version(story: str, body_markus: str, reason: str, author_label: str, front_matter_yaml: str = "", stage: str = "") -> dict:
    """Save the next draft version of a story: YAML front matter (without --- lines) and a Markus body.
    Empty front matter keeps the latest version's. Never publishes. Returns the new version id."""

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
    return {"versionId": record["id"], "versionNumber": record["versionNumber"], "status": record.get("status")}


def papyrus_link_story_reference(story: str, reference: str, role: str, author_label: str, note: str = "", citation_key: str = "") -> dict:
    """Attach a reference to a story as consulted (used in reporting) or cited (appears in the article)."""

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import link_reference_to_story

    client, _ = create_authoring_client()
    return link_reference_to_story(client, story, reference, role=role, actor=author_label, note=note or None, citation_key=citation_key or None)


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


def _check_result(item: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    findings = [_finding(finding) for finding in run["findings"]]
    violations, reviews = int(run.get("violations") or 0), int(run.get("reviews") or 0)
    return {
        "status": "checked",
        "clean": violations == 0 and reviews == 0,
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
    if summary.get("skipped"):
        return {**base, "status": "skipped", "clean": False, "reason": summary["skipped"], "findings": []}
    deadline = time.monotonic() + max(wait_seconds, 0)
    while True:
        run = read_item_check_run(item["id"], client.graphql)
        if run is not None:
            return _check_result(item, run)
        if time.monotonic() >= deadline:
            return {**base, "status": "pending", "clean": False, "findings": []}
        time.sleep(CHECK_POLL_SECONDS)
