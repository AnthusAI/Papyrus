"""`papyrus stories link-concept`, `papyrus references link-concept` and the two `check-links` audits (docs/story-reporting.md, "Tagging with concepts")."""

from __future__ import annotations

import json
import sys

from .concept_tags import audit_reference_links, audit_story_links, tag_with_concepts
from .content_item_lifecycle import SYSTEM_ITEM_TYPES
from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_boolean_option, parse_options, parse_repeated_option, resolve_mutation_apply


def _actor(client, options: dict, group: str, command: str, apply: bool):
    """Who the tag records: the signed-in person (``--author-label`` ignored there), or the required ``--author-label`` on the IAM lane, as link-reference does."""
    from .operator_errors import OperatorError
    from .user_auth_mode import user_auth_requested

    label = normalize_string(options.get("author-label"))
    if not user_auth_requested():
        if not label:
            raise ValueError("--author-label is required on the IAM lane, where there is no sign-in to name the author.")
        return label
    if not apply:
        return None
    if label:
        print(f"{group}\t{command}\twarning\t--author-label is ignored: the tag records the person who signed in.", file=sys.stderr)
    from .cli_user_auth import signed_in_label

    actor = signed_in_label(client.endpoint)
    if not actor:
        raise OperatorError("The tag was not saved: the signed-in session names no one. Run `papyrus whoami` to check it.")
    return actor


def _link_concept(flags: list[str], group: str, target_kind: str, target_flag: str) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, f"{group} link-concept")
    target = normalize_string(options.get(target_flag))
    if not target or target is True:
        raise ValueError(f"--{target_flag} is required.")
    concepts = [value for value in parse_repeated_option(flags, "concept") if value.strip()]
    if not concepts:
        raise ValueError("--concept is required (repeat it for several concepts).")
    for forbidden in ("predicate", "relation", "state", "create"):
        if options.get(forbidden) is not None:
            raise ValueError(f"--{forbidden} is not accepted: a tag is always the one official edge to an existing accepted concept, and this command never creates a concept.")
    client, _ = create_authoring_client()
    actor = _actor(client, options, group, "link-concept", apply)
    from .user_auth_mode import user_auth_requested

    as_json = bool(options.get("json"))

    def show(row: dict) -> None:
        if as_json:
            return
        page = "public page" if row["publicPage"] else "no public page"
        print("\t".join([group, "link-concept", row["target"], str(row["nodeKey"]), row["name"], page, row["outcome"]]))
        if row.get("legacy"):
            print(f"{group}\tlink-concept\twarning\t{row['name']} is already tagged with the legacy related_to; nothing was written (migrate later).", file=sys.stderr)
        if row.get("warning"):
            print(f"{group}\tlink-concept\twarning\t{row['warning']}", file=sys.stderr)

    result = tag_with_concepts(client, target_kind, target, concepts, actor=actor, provenance="human" if user_auth_requested() else "derived",
                               note=normalize_string(options.get("note")), apply=apply, on_row=show)
    done = None
    if target_kind == "story":   # a Reference has no public page yet: nothing to re-render
        from .story_rerender import announce, rerender_after_write

        wrote = any(row["outcome"] == "write" for row in result["concepts"])
        done = rerender_after_write(client, [result["target"]] if wrote else [], enabled=apply and not parse_boolean_option(options.get("no-rerender"), default=False, label="--no-rerender"))
    if as_json:
        print(json.dumps({"ok": True, **result, **({"rerendered": done["rerendered"]} if done else {})}, indent=2))
    if done:
        announce(done, quiet=as_json)


def stories_link_concept(flags: list[str]) -> None:
    """papyrus stories link-concept --story <lineage|slug> --concept <name|#hashtag|nodeKey> [--concept ...] [--note TEXT] [--author-label NAME] [--dry-run] [--json]

    Tags a story (article or post) with existing accepted concepts. A concept is found by exact node key, exact hashtag or exact name or alias (case-insensitive),
    never created, never fuzzy: an unknown name lists the closest accepted concepts, an ambiguous one lists its node keys, a non-accepted one is refused. The edge is
    always `tagged_with` (no predicate, relation, state or create option exists). A tag that exists in any accepted form (tagged_with, the legacy related_to, mentions)
    is reported and nothing is written; a tag a person rejected stays rejected. Each concept line says whether it has a public wiki page, and warns when it has none.
    Signed in, the tag records the person who signed in (provenance human); on the IAM lane --author-label is required (provenance derived)."""
    _link_concept(flags, "stories", "story", "story")


def references_link_concept(flags: list[str]) -> None:
    """papyrus references link-concept --reference <id|lineage> --concept <name|#hashtag|nodeKey> [--concept ...] [--note TEXT] [--author-label NAME] [--dry-run] [--json]

    The same rules as `stories link-concept` for a Reference. `references link --concept` is the editors' older route (it can create a concept and writes the legacy
    related_to); an agent uses this one."""
    _link_concept(flags, "references", "reference", "reference")


def _print_findings(group: str, checked: int, findings: list[dict], as_json: bool, label: str) -> None:
    if as_json:
        print(json.dumps({"ok": True, "checked": checked, "problems": len(findings), "findings": findings}, indent=2))
        return
    for f in findings:
        print("\t".join([group, "check-links", str(f["owner"]), f["problem"], str(f["predicate"]), str(f["state"]), str(f["object"]), f["detail"], str(f["relationId"])]))
    print(f"{group}\tcheck-links\t{len(findings)} problem(s) across {checked} {label}")


def stories_check_links(flags: list[str]) -> None:
    """papyrus stories check-links [--story <lineage|slug>] [--json]

    Read only. Lists, for the published stories (or one story), every story-to-story and story-to-concept relation that is not the official shape: a wrong predicate or
    kind, a state that is not current, a concept that is missing, not accepted or has no public page, a story target that is not published, a legacy related_to tag
    ("legacy: migrate"), and duplicate pairs. Fixing is out of scope. Cost: one read of the published-story summaries, then three index reads per story (25 keys to a request)
    and one batched read of the concepts they name."""
    options = parse_options(flags)
    client, _ = create_authoring_client()
    story = normalize_string(options.get("story"))
    if story and story is not True:
        from .story_links import resolve_story

        found = resolve_story(client, story)
        lineages = [found.get("lineageId") or found["id"]]
    else:
        lineages = sorted({str(row["itemLineageId"]) for row in client.list_published_item_summaries() if row.get("itemLineageId") and row.get("type") not in SYSTEM_ITEM_TYPES})
    _print_findings("stories", len(lineages), audit_story_links(client, lineages), bool(options.get("json")), "stories")


def references_check_links(flags: list[str]) -> None:
    """papyrus references check-links (--reference <id|lineage> | --corpus-id ID) [--json]

    Read only. The same audit for Reference-to-concept relations. With --corpus-id it checks the corpus's accepted References, read through the
    referencesByCurationStatusKey index; the relations come from the subject-state index (three keys per Reference, 25 keys to a request), the concepts from one batched
    get per 25. No table is scanned. About 827 accepted References cost one paginated index read, roughly 100 relation requests and a few concept requests."""
    from .reference_reads import REFERENCE_BY_CURATION_STATUS
    from .story_reporting import current_reference

    options = parse_options(flags)
    client, _ = create_authoring_client()
    reference, corpus = normalize_string(options.get("reference")), normalize_string(options.get("corpus-id"))
    if reference and reference is not True:
        found = current_reference(client, reference)
        if found is None:
            raise ValueError(f"Reference not found: {reference}")
        lineages = [found.get("lineageId") or found["id"]]
    elif corpus and corpus is not True:
        lineages = sorted({str(row.get("lineageId") or row["id"]) for row in client.list_by_index(REFERENCE_BY_CURATION_STATUS, f"{corpus}#accepted")
                           if row.get("versionState", "current") == "current"})
    else:
        raise ValueError("references check-links needs --reference ID or --corpus-id ID.")
    _print_findings("references", len(lineages), audit_reference_links(client, lineages), bool(options.get("json")), "References")
