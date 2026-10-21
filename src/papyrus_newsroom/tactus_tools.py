"""Papyrus tools for Tactus procedure agents, shipped inside the package.

A procedure loads them by module name, so it runs the same from an installed site as from a Papyrus checkout:

    Toolset "papyrus" { type = "plugin", modules = {"papyrus_newsroom.tactus_tools"} }

Every public function defined here is a tool. Story writes go through the same functions as the
``papyrus stories`` commands, so an agent can do nothing the CLI could not.
"""

from __future__ import annotations

import io
import json
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


def papyrus_story_versions(story: str) -> list[dict[str, Any]]:
    """List a story's versions, newest first, with their state, author and reason."""

    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import story_versions

    client, _ = create_authoring_client()
    fields = ("id", "versionNumber", "versionState", "status", "stage", "versionCreatedAt", "versionCreatedBy", "changeReason")
    return [{field: version.get(field) for field in fields} for version in story_versions(client, story)]
