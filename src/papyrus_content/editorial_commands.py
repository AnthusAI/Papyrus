"""`papyrus editorial`: the site's editorial policies, checked by Humanus from the command line.

    papyrus editorial pack [--section KEY] [--language TAG] [--output FILE]
    papyrus editorial import --profile publications/<pub>/style-profile.yml [--replace]
    papyrus editorial check --draft FILE [--story LINEAGE] [--section KEY] [--language TAG] [--pack FILE] [--output FILE]
    papyrus editorial suggest --draft FILE [--story LINEAGE] (--finding-id ID | --select TEXT) [--note TEXT] [--section KEY] [--language TAG] [--pack FILE]
    papyrus editorial policies list | import-starter NAME | ensure-defaults
    papyrus editorial policies add --file PACK [--dry-run] [--publication KEY] [--actor NAME]
    papyrus editorial policies export --file PACK [--language TAG] [--pack-id ID] [--pack-version V]
    papyrus editorial check-version --item VERSION_ID [--json]
    papyrus editorial check-drafts [--limit N] [--dry-run]

Policies and settings come from the site (EditorialPolicy / EditorialCheckSettings,
read with the authoring role) unless `--pack` names a Humanus policy-pack file.
The newsroom's article editor runs the same checks; this is for agents and scripts.

A draft is checked in its language: `--language`, or the site's primary language (the
editorial settings' `languages.primary`), which is the language every Story is written in
until the multilingual plan's Story language field exists (`editorial_languages`).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import humanus

from . import editorial_policy_pack as policy_pack
from .editorial_checks import (
    PUBLICATION_SCOPE,
    GraphQLEditorialStore,
    Services,
    check_draft,
    check_editorial,
    ensure_default_policies,
    import_starter_pack,
    policy_identity,
    record_from_policy,
    settings_from,
    suggest_rewrite,
)
from .editorial_languages import ANY_LANGUAGE, primary_language, site_language

STORY_HELP = "The story (lineage id or slug) this draft revises, so its own saved versions are not compared as other stories by the cross-story boilerplate check."
LANGUAGE_HELP = "Language of the draft (en, es-419, zh-Hans ...). Default: the site's primary language, the language its Stories are written in."


class PackFileStore:
    """Serves one policy-pack file's policies, with no settings or decisions."""

    def __init__(self, path: Path) -> None:
        pack = humanus.load_policy_pack(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            import yaml

            payload = yaml.safe_load(text)
        self._records = [record_from_policy(policy, scope=PUBLICATION_SCOPE, language=pack.language, source=f"file:{path.name}") for policy in payload["policies"]]
        self._guidance = pack.guidance or ""
        # The file's language is the only language it can check; a language-neutral file checks text in any language the caller names.
        self._languages = None if pack.language == ANY_LANGUAGE else {"primary": pack.language, "enabled": [pack.language]}

    def list_policies(self) -> list[dict[str, Any]]:
        return self._records

    context_mode = 'local'

    def get_editorial_context(self, section: str | None) -> dict[str, Any]:
        from .editorial_context import build_context
        entries = [{'scope': 'publication', 'kind': 'guidance',
                    'text': self._guidance or 'Explicit local policy pack; apply its enabled controls only.',
                    'source': {}}]
        return build_context({'key': 'explicit-policy-file'}, {'sectionId': section}, entries, mode='local',
                             warnings=['Explicit file policy; not current hosted doctrine.'])

    def get_settings(self) -> dict[str, Any] | None:
        return {"settings": {"guidance": self._guidance, **({"languages": self._languages} if self._languages else {})}}

    def list_feedback(self) -> list[dict[str, Any]]:
        return []

    def create_policy(self, record: dict[str, Any]) -> None:
        raise ValueError("A policy-pack file is read-only here.")

    update_policy = create_policy

    def put_settings(self, values: dict[str, Any], *, exists: bool) -> None:
        raise ValueError("A policy-pack file is read-only here.")


def _store(pack: str | None):
    return PackFileStore(Path(pack).resolve()) if pack else GraphQLEditorialStore()


def _emit(payload: Any, output: str | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _read_draft(path: str) -> str:
    draft = Path(path).resolve()
    if not draft.is_file():
        raise ValueError(f"Draft file not found: {draft}")
    return draft.read_text(encoding="utf-8")


def _language(args: argparse.Namespace, settings: dict[str, Any]) -> str:
    return args.language or primary_language(settings)


def editorial_pack(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial pack", description="Print the site's policy pack for a section and language.")
    parser.add_argument("--section", default=None, help="Desk key whose policies replace publication policies with the same key.")
    parser.add_argument("--language", default=None, help="The language of the text the pack checks. Default: the site's primary language.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(flags)
    store = GraphQLEditorialStore()
    from .editorial_model_context import editing_pack
    settings = settings_from(store)
    _emit(editing_pack(store, args.section, settings, site_language(_language(args, settings), settings)), args.output)


def import_style_profile(store, profile: Path, *, replace: bool) -> dict[str, int]:
    """Add a style profile's controls to the store as publication policies."""
    existing = {policy_identity(r): r for r in store.list_policies()}
    pack = humanus.policy_pack_from_style_profile(profile)
    counts = {"created": 0, "replaced": 0, "skipped": 0}
    for policy in pack["policies"]:
        record = record_from_policy(policy, scope=PUBLICATION_SCOPE, language=pack["language"], source=f"style-profile:{pack['packId']}")
        current = existing.get(policy_identity(record))
        if current is None:
            store.create_policy(record)
            counts["created"] += 1
        elif replace:
            store.update_policy({**record, "id": current["id"], "version": int(current.get("version") or 1) + 1})
            counts["replaced"] += 1
        else:
            counts["skipped"] += 1
    return counts


def editorial_import(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="papyrus editorial import",
        description="Add a style profile's controls to the site as editorial policies (scope: publication). To keep the checks in step with the writing guidelines "
                    "instead, save them with `papyrus guidelines save --kind writing`.",
    )
    parser.add_argument("--profile", required=True, help="Style profile YAML/JSON, e.g. publications/anthus/style-profile.yml")
    parser.add_argument("--replace", action="store_true", help="Overwrite policies that already exist with the same key.")
    args = parser.parse_args(flags)
    counts = import_style_profile(GraphQLEditorialStore(), Path(args.profile).resolve(), replace=args.replace)
    print(f"{counts['created']} created, {counts['replaced']} replaced, {counts['skipped']} already present (--replace overwrites)")


def editorial_check(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial check", description="Check a draft against the site's editorial policies.")
    parser.add_argument("--draft", required=True, help="Markus/Markdown body to check (read-only).")
    parser.add_argument("--story", default=None, help=STORY_HELP)
    parser.add_argument("--section", default=None, help="Desk key, for desk policies.")
    parser.add_argument("--language", default=None, help=LANGUAGE_HELP)
    parser.add_argument("--pack", default=None, help="Use this Humanus policy-pack file instead of the site's policies. A policy file has no stories, so the cross-story boilerplate check cannot run; the output's notRun list says so.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(flags)
    services = Services(store=_store(args.pack))
    language = _language(args, settings_from(services.store))
    _emit(check_draft({"body": _read_draft(args.draft), "format": "markus", "section": args.section, "language": language}, services, story=args.story), args.output)


def editorial_suggest(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="papyrus editorial suggest",
        description="Rewrite options for one finding or a passage of a draft. Prints options; never edits the draft.",
    )
    parser.add_argument("--draft", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--finding-id", help="A finding id from `papyrus editorial check` on the same draft.")
    target.add_argument("--select", help="Exact text of the draft to rewrite.")
    parser.add_argument("--note", default=None, help="Editor note, e.g. 'shorter'.")
    parser.add_argument("--story", default=None, help=STORY_HELP)
    parser.add_argument("--section", default=None)
    parser.add_argument("--language", default=None, help=LANGUAGE_HELP)
    parser.add_argument("--pack", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(flags)
    body = _read_draft(args.draft)
    services = Services(store=_store(args.pack))
    language = _language(args, settings_from(services.store))
    arguments: dict[str, Any] = {"body": body, "format": "markus", "section": args.section, "language": language, "note": args.note}
    if args.finding_id:
        result = check_draft({"body": body, "format": "markus", "section": args.section, "language": language}, services, story=args.story)
        finding = next((f for f in result["findings"] if f["id"] == args.finding_id), None)
        if finding is None:
            raise ValueError(f"No finding {args.finding_id} in this draft; run `papyrus editorial check` again.")
        arguments["finding"] = json.dumps(finding)
    else:
        start = body.find(args.select)
        if start < 0:
            raise ValueError("--select text is not in the draft.")
        to_utf16 = lambda index: len(body[:index].encode("utf-16-le")) // 2  # noqa: E731
        arguments["selection"] = json.dumps({"start": to_utf16(start), "end": to_utf16(start + len(args.select))})
    try:
        _emit(suggest_rewrite(arguments, services), args.output)
    except humanus.SuggestUnavailableError as error:
        raise ValueError(str(error)) from error


def editorial_policies_pack(store, args: argparse.Namespace) -> None:
    if args.publication and store.publication_key() != args.publication:
        raise ValueError(f"This site's publication is not {args.publication}; nothing was changed.")
    path = Path(args.file).resolve()
    if args.action == "export":
        language = args.language or primary_language(settings_from(store))
        pack, left_out = policy_pack.export_pack(store, pack_id=args.pack_id, pack_version=args.pack_version, language=language)
        policy_pack.write_pack(path, pack)
        print(f"Exported {len(pack['policies'])} {pack['language']} policies to {path}"
              + (f" ({left_out} left out: a pack has one language and no section scope)" if left_out else ""))
        return
    payload = policy_pack.load_pack_payload(path)
    steps = policy_pack.plan_policies(store, payload, actor=args.actor or policy_pack.DEFAULT_ACTOR)
    for step in steps:
        print(policy_pack.describe_step(step, done=not args.dry_run))
    if not args.dry_run:
        policy_pack.apply_plan(store, steps)
    changed = sum(step["action"] != "unchanged" for step in steps)
    print(f"{'Dry run: ' if args.dry_run else ''}{changed} of {len(steps)} policies {'would change' if args.dry_run else 'changed'}")


def editorial_policies(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial policies", description="List or add the site's editorial policies.")
    subcommands = parser.add_subparsers(dest="action", required=True)
    listing = subcommands.add_parser("list", help="The site's policies: key, scope, severity, enabled, source.")
    listing.add_argument("--json", action="store_true")
    starter = subcommands.add_parser("import-starter", help="Add a Humanus starter pack's policies that the site does not have yet.")
    starter.add_argument("name", help="A starter pack Humanus ships: ai-writing-tells, plain-language, asd-ste100, typography-es, ai-writing-tells-zh-hans ...")
    subcommands.add_parser("ensure-defaults", help="Write the language of older policies, then import the starter packs of every enabled language once (what a deploy does).")
    add = subcommands.add_parser("add", help="Create or version policies (with classifier questions) from a policy-pack-v1 file.")
    add.add_argument("--file", required=True, help="Humanus policy-pack-v1 file (JSON or YAML).")
    add.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing.")
    add.add_argument("--publication", default=None, help="Refuse unless the site's publication key is this.")
    add.add_argument("--actor", default=None, help=f"Who ran this, recorded in each policy's source (default {policy_pack.DEFAULT_ACTOR}).")
    export = subcommands.add_parser("export", help="Write the site's publication policies as a policy-pack-v1 file.")
    export.add_argument("--file", required=True, help="Output file (.json, .yml or .yaml).")
    export.add_argument("--language", default=None, help="The pack's language: its policies written for exactly this language (or * for the neutral ones). "
                                                         "Default: the site's primary language.")
    export.add_argument("--pack-id", default="site-policies")
    export.add_argument("--pack-version", default=None, help="Default: the highest policy version.")
    export.add_argument("--publication", default=None, help="Refuse unless the site's publication key is this.")
    args = parser.parse_args(flags)
    store = GraphQLEditorialStore()
    if args.action in ("add", "export"):
        editorial_policies_pack(store, args)
    elif args.action == "list":
        rows = sorted(store.list_policies(), key=lambda row: (row["scope"], row.get("language") or "", row["policyKey"]))
        if args.json:
            _emit([{key: row.get(key) for key in ("policyKey", "scope", "language", "severity", "enabled", "source", "version")} for row in rows], None)
            return
        for row in rows:
            print(f"{row['scope']}\t{row.get('language')}\t{row['policyKey']}\t{row['severity']}\t{'enabled' if row.get('enabled') else 'disabled'}\t{row.get('source')}")
        print(f"{len(rows)} policies")
    elif args.action == "import-starter":
        counts = import_starter_pack({"name": args.name}, Services(store=store))
        print(f"{args.name}: {counts['created']} created, {counts['skipped']} already present")
    else:
        _emit(ensure_default_policies(store), None)


LOGGER = logging.getLogger(__name__)
CHECK_ITEM_VERSION = "mutation CheckItemVersion($itemId: ID!) { checkItemVersion(itemId: $itemId) }"
LIST_CHECK_RUNS = "query ListEditorialCheckRuns($nextToken: String) { listEditorialCheckRuns(limit: 1000, nextToken: $nextToken) { items { id contentHash } nextToken } }"
CHECKED_ITEM_TYPES = ("article", "page")


def request_item_check(item_id: str, execute=None) -> dict[str, Any]:
    """Ask the site's editorial-checks function to check one saved version and store the result with it."""
    if execute is None:
        from .graphql_http import execute_graphql

        execute = execute_graphql
    from .editorial_checks import _awsjson_document

    return _awsjson_document(execute(CHECK_ITEM_VERSION, {"itemId": item_id})["checkItemVersion"])


GET_CHECK_RUN = "query GetEditorialCheckRun($id: ID!) { getEditorialCheckRun(id: $id) { id itemId lineageId versionNumber section contentHash packVersion violations reviews findings lanes checkedAt } }"


def read_item_check_run(item_id: str, execute=None) -> dict[str, Any] | None:
    """The stored check of one saved version (counts, findings, lane status), or None if it has none yet."""
    if execute is None:
        from .graphql_http import execute_graphql

        execute = execute_graphql
    from .editorial_checks import _awsjson_document

    run = (execute(GET_CHECK_RUN, {"id": item_id}) or {}).get("getEditorialCheckRun")
    if not run:
        return None
    return {**run, "findings": _awsjson_document(run.get("findings")) or [], "lanes": _awsjson_document(run.get("lanes"))}


def check_saved_version_best_effort(item_id: str, execute=None) -> dict[str, Any]:
    """Check a version that was just saved. Never raises: the save stands, and the next update checks again."""
    try:
        return request_item_check(item_id, execute)
    except Exception as error:
        LOGGER.warning("Editorial check of saved version %s failed: %s", item_id, str(error)[:200])
        return {"itemId": item_id, "notChecked": str(error)[:200]}


def check_summary_line(result: dict[str, Any]) -> str:
    from .editorial_checks import lanes_not_run

    if result.get("skipped") and result.get("skipped") != "unchanged":
        return f"editorial\tcheck\t{result.get('itemId')}\tskipped\t{result['skipped']}"
    counts = f"{result.get('violations', 0)} violations\t{result.get('reviews', 0)} for review"
    if result.get("reused"):
        # Said first, so a reused 0 is never taken for a fresh pass: nothing was checked just now.
        origin = f"reused: not checked again, same text and policies as the check of {result.get('checkedAt') or 'an earlier time'}"
        line = f"editorial\tcheck\t{result.get('itemId')}\t{counts}\t{origin}"
    else:
        line = f"editorial\tcheck\t{result.get('itemId')}\t{counts}\tchecked now"
    notes = lanes_not_run(result.get("lanes"))
    return line + "".join(f"\t{note}" for note in notes)


def check_after_save(item_id: str, execute=None) -> None:
    """Every save path checks the new version; a failed check never undoes the save."""
    try:
        print(check_summary_line(request_item_check(item_id, execute)))
    except Exception as error:
        print(f"editorial\tcheck\t{item_id}\tnot checked\t{str(error)[:200]} (run: papyrus editorial check-version --item {item_id})")


def format_findings(findings: list[dict[str, Any]]) -> list[str]:
    """One block per finding: violations first, then those for review, then anything else. Each carries what an editor acts on."""
    order = {"violation": 0, "review": 1}
    lines: list[str] = []
    for finding in sorted(findings, key=lambda f: order.get(f.get("status"), 2)):
        probability = finding.get("probability")
        score = "" if probability is None else f"\tp={probability}"
        lines.append(f"{finding.get('status')}\t{finding.get('severity')}\t{finding.get('policyId')}{score}\t{finding.get('id')}")
        lines.append(f"  {finding.get('message')}")
        excerpt = finding.get("excerpt")
        lines.append(f"  excerpt: {excerpt!r}" if excerpt else "  excerpt: (none: the whole story)")
    return lines


def sync_checklist_of_version(item_id: str) -> None:
    """A finished check is evidence for the Story's copy-edit step: bring its checklist up to date once. Never fails the check."""
    try:
        from .graphql_authoring import create_authoring_client
        from .story_checklist import sync_quietly

        client, _ = create_authoring_client()
        item = client.get_record("Item", item_id)
        if item is not None:
            sync_quietly(client, item.get("lineageId") or item_id)
    except Exception as error:  # noqa: BLE001
        import sys

        print(f"checklist\tnot updated\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)


def editorial_check_version(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial check-version", description="Check one saved version of a story, store the result with it and print every finding.")
    parser.add_argument("--item", required=True, help="Item version id, e.g. <lineage>-v2.")
    parser.add_argument("--json", action="store_true", help="Print the summary and the full findings as JSON.")
    args = parser.parse_args(flags)
    summary = request_item_check(args.item)
    run = read_item_check_run(args.item) or {}
    findings = run.get("findings") or []
    sync_checklist_of_version(args.item)
    if args.json:
        _emit({"summary": summary, "findings": findings}, None)
        return
    print(check_summary_line(summary))
    for line in format_findings(findings):
        print(line)


def unchecked_draft_versions(items: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Unpublished draft versions with no stored check, or whose text changed since their check."""
    checked = {run["id"]: run.get("contentHash") for run in runs}
    return [
        item for item in items
        if item.get("type") in CHECKED_ITEM_TYPES
        and item.get("versionState") in ("draft", "current")
        and item.get("status") != "published"
        and (item["id"] not in checked or checked[item["id"]] != item.get("contentHash"))
    ]


def editorial_check_drafts(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial check-drafts", description="Check every unpublished draft version that has no stored check yet.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(flags)
    from .graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    check_unchecked_drafts(client, limit=args.limit, dry_run=args.dry_run)


def check_unchecked_drafts(client, *, limit: int = 0, dry_run: bool = False) -> None:
    """Check every unpublished draft version with no stored check (or a stale one), through the given client."""
    runs = GraphQLEditorialStore()._list(LIST_CHECK_RUNS, "listEditorialCheckRuns")
    pending = unchecked_draft_versions(client.list_records("Item"), runs)
    if limit:
        pending = pending[:limit]
    print(f"editorial\tcheck-drafts\t{len(pending)} versions to check\t{'dry run' if dry_run else 'checking'}")
    if dry_run:
        for item in pending:
            print(f"editorial\tcheck-drafts\t{item['id']}\t{item.get('section')}\t{item.get('title')}")
        return
    for item in pending:
        check_after_save(item["id"])
