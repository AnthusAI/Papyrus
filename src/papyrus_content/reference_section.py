"""Set or clear the Section of a Reference without voting on it again (PPY-b5cb8e).

This is the one definition behind ``papyrus references set-section`` and the MCP tool ``reference_set_section``: both call
``set_reference_section`` and print or return the same result. It changes only ``curationSectionId`` (an enabled ``NewsroomSection`` id) and the
two fields that say who changed it and when (``curationSectionUpdatedBy``, ``curationSectionUpdatedAt``). The vote (status, note, actor kind, who and when),
the feedback and the star rating are never written, so the Cyclotron sees no new vote.

A section can be named by its id, by the qualified form ``<publication>#<slug>`` (the id itself, or a publication prefix and the slug), by its
slug (the id's part after ``#``), or by its display name (title or short title). An unrecognised form or an unknown or disabled section is an error
that lists the accepted forms and the sections that are available.
"""
from __future__ import annotations

from typing import Any, Mapping

from .section_ids import match_section, slug_of

ACCEPTED_FORMS = (
    "a section's display name (for example 'Security'), its slug (for example security), "
    "or the qualified form <publication>#<slug> (for example machines-on-machines#security)"
)

SET_SECTION_MUTATION = """
mutation SetReferenceSection($referenceId: ID!, $sectionId: ID, $agentLabel: String) {
  setReferenceSection(referenceId: $referenceId, sectionId: $sectionId, agentLabel: $agentLabel) {
    ok
    referenceId
    sectionId
    previousSectionId
    changed
    status
  }
}
"""


class SectionError(ValueError):
    """A section the caller named cannot be used. The message lists the accepted forms and the sections that are available."""


def _enabled(row: Mapping[str, Any]) -> bool:
    return row.get("enabled") is not False and row.get("enabledStatus") != "disabled"


def available_sections(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted((row for row in rows if _enabled(row)), key=lambda row: (row.get("sortOrder") or 0, str(row.get("id"))))


def _listing(rows: list[Mapping[str, Any]]) -> str:
    available = available_sections(rows)
    if not available:
        return "This site has no enabled sections."
    lines = [f"  {row.get('id')}  ({row.get('title') or row.get('shortTitle') or ''}; slug {slug_of(str(row.get('id')).split('#')[-1])})" for row in available]
    return "Available sections:\n" + "\n".join(lines)


def resolve_section(rows: list[Mapping[str, Any]], value: Any) -> Mapping[str, Any]:
    """The enabled section ``value`` names, or a SectionError that lists the accepted forms and the available sections."""
    text = "" if value is None or value is True else str(value).strip()
    if not text:
        raise SectionError(f"A section is required: give {ACCEPTED_FORMS}, or clear it.\n{_listing(rows)}")
    found = _match(rows, text)
    if found is None:
        raise SectionError(f"There is no section '{text}'. Accepted forms: {ACCEPTED_FORMS}.\n{_listing(rows)}")
    if not _enabled(found):
        raise SectionError(f"Section {found.get('id')} is disabled and cannot be set. Accepted forms: {ACCEPTED_FORMS}.\n{_listing(rows)}")
    return found


def _match(rows: list[Mapping[str, Any]], text: str) -> Mapping[str, Any] | None:
    if "#" in text:
        publication, _, slug = text.partition("#")
        for row in rows:   # the id itself
            if row.get("id") == text:
                return row
        if not publication.strip() or not slug.strip():
            return None
        # A qualified form whose id is stored as the bare slug, or under another prefix, still names the section whose slug matches,
        # but only when the id carries no publication of its own that disagrees.
        wanted = slug_of(slug)
        candidates = []
        for row in rows:
            parts = str(row.get("id") or "").split("#")
            if slug_of(parts[-1]) != wanted:
                continue
            if len(parts) == 1 or slug_of(parts[0]) == slug_of(publication):
                candidates.append(row)
        if len(candidates) > 1:
            raise SectionError(f"Section '{text}' is ambiguous: {', '.join(str(row.get('id')) for row in candidates)}.")
        return candidates[0] if candidates else None
    try:
        return match_section(rows, text)
    except ValueError as error:
        raise SectionError(f"{error} Use the qualified form <publication>#<slug>.") from None


SECTIONS_BY_STATE = "newsroomSectionsByEnabledStatus"


def sections_of(client: Any) -> list[Mapping[str, Any]]:
    """Every section, enabled first then disabled, through the enabled-status index: two partition reads, never a table scan."""
    return [*client.list_by_index(SECTIONS_BY_STATE, "enabled"), *client.list_by_index(SECTIONS_BY_STATE, "disabled")]


def current_reference_row(rows: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The working row of a lineage: the one marked current, else the highest version."""
    marked = [row for row in rows if row.get("versionState") == "current"]
    pool = marked or rows
    return max(pool, key=lambda row: (str(row.get("versionCreatedAt") or ""), int(row.get("versionNumber") or 0)))


def read_reference(client: Any, token: str) -> Mapping[str, Any]:
    """The Reference a lineage id (or record id) names: its working version."""
    from .reference_reads import references_for_tokens

    rows = references_for_tokens(client, [token])
    if not rows:
        raise ValueError(f"Reference not found: {token}")
    lineages = {str(row.get("lineageId") or row.get("id")) for row in rows}
    if len(lineages) > 1:
        raise ValueError(f"{token} names more than one Reference: {', '.join(sorted(lineages))}.")
    return current_reference_row(rows)


def set_reference_section(client: Any, *, reference: Any, section: Any = None, clear: bool = False, dry_run: bool = False,
                          agent_label: str = "") -> dict[str, Any]:
    """Set (``section``) or clear (``clear``) a Reference's section. Reads only when ``dry_run``; otherwise the site's function writes it.

    Returns ``{ok, dryRun, changed, referenceId, lineageId, status, previousSectionId, sectionId, sectionTitle}``.
    """
    token = "" if reference is None or reference is True else str(reference).strip()
    if not token:
        raise ValueError("A Reference is required: give its lineage id (--reference).")
    wants_section = section is not None and section is not True and str(section).strip() != ""
    if clear and wants_section:
        raise ValueError("Give a section or --clear, not both.")
    if not clear and not wants_section:
        raise SectionError(f"A section is required: give {ACCEPTED_FORMS}, or use --clear.")
    row = read_reference(client, token)
    previous = str(row.get("curationSectionId") or "") or None
    status = str(row.get("curationStatus") or "pending")
    chosen = None
    if wants_section:
        rows = sections_of(client)
        chosen = resolve_section(rows, section)
        if status != "accepted":
            raise ValueError(f"A section can be set only on an accepted Reference; {token} is {status}. Accept it first, or use --clear.")
    section_id = str(chosen["id"]) if chosen else None
    result = {
        "ok": True, "dryRun": bool(dry_run), "changed": section_id != previous, "referenceId": str(row["id"]),
        "lineageId": str(row.get("lineageId") or row["id"]), "status": status, "previousSectionId": previous, "sectionId": section_id,
        "sectionTitle": (chosen.get("title") or chosen.get("shortTitle")) if chosen else None,
    }
    if dry_run:
        return result
    answer = client.graphql(SET_SECTION_MUTATION, {"referenceId": result["referenceId"], "sectionId": section_id, "agentLabel": (agent_label or "").strip() or None})
    saved = answer.get("setReferenceSection")
    if not isinstance(saved, Mapping) or not saved.get("ok"):
        raise RuntimeError(f"The section was not saved for {token}.")
    return {**result, "changed": bool(saved.get("changed")), "previousSectionId": saved.get("previousSectionId"), "sectionId": saved.get("sectionId")}


def format_line(result: Mapping[str, Any]) -> str:
    """The one tab-separated line the CLI prints: the same facts as the MCP result."""
    shown = result.get("sectionId") or "(none)"
    before = result.get("previousSectionId") or "(none)"
    state = "dry-run: nothing sent" if result.get("dryRun") else ("changed" if result.get("changed") else "unchanged")
    return f"references\tset-section\t{result.get('referenceId')}\t{before}\t{shown}\t{state}"


# --- the MCP tool: the same operation, described for the MCP server's TOOLS and DESCRIPTIONS tables -------------------------------------------------

TOOL_NAME = "reference_set_section"
_TEXT = {"type": "string", "minLength": 1}
TOOLS = {
    TOOL_NAME: ("staff", {
        "type": "object",
        "properties": {
            "lineageId": {**_TEXT, "description": "The lineage id of the accepted Reference."},
            "section": {**_TEXT, "description": f"The section: {ACCEPTED_FORMS}. Omit with clear."},
            "clear": {"type": "boolean", "description": "Remove the section instead of setting one."},
            "dryRun": {"type": "boolean", "description": "Check and report the change; write nothing."},
        },
        "required": ["lineageId"], "additionalProperties": False}),
}
DESCRIPTIONS = {
    TOOL_NAME: "Change only the section of an accepted Reference (or clear it); the acceptance, its note, feedback and star rating stay as they are.",
}


def call_tool(client: Any, arguments: Mapping[str, Any], *, agent_label: str = "") -> dict[str, Any]:
    """Run the MCP tool: the same ``set_reference_section`` the CLI runs. An unusable request is ``{"ok": False, "error": {...}}``, never a raise."""
    unknown = set(arguments) - set(TOOLS[TOOL_NAME][1]["properties"])
    if unknown or not isinstance(arguments.get("lineageId"), str):
        return {"ok": False, "error": {"code": "invalid_input", "message": "Give lineageId, and section or clear (optionally dryRun)."}}
    try:
        return set_reference_section(client, reference=arguments["lineageId"], section=arguments.get("section"), clear=bool(arguments.get("clear")),
                                     dry_run=bool(arguments.get("dryRun")), agent_label=agent_label)
    except SectionError as error:
        return {"ok": False, "error": {"code": "unknown_section", "message": str(error)}}
    except ValueError as error:
        return {"ok": False, "error": {"code": "invalid_request", "message": str(error)}}
