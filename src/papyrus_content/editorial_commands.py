"""`papyrus editorial`: the site's editorial policies, checked by Humanus from the command line.

    papyrus editorial pack [--section KEY] [--output FILE]
    papyrus editorial import --profile publications/<pub>/style-profile.yml [--replace]
    papyrus editorial check --draft FILE [--section KEY] [--pack FILE] [--output FILE]
    papyrus editorial suggest --draft FILE (--finding-id ID | --select TEXT) [--note TEXT] [--section KEY] [--pack FILE]
    papyrus editorial policies list | import-starter NAME | ensure-defaults
    papyrus editorial check-version --item VERSION_ID
    papyrus editorial check-drafts [--limit N] [--dry-run]

Policies and settings come from the site (EditorialPolicy / EditorialCheckSettings,
read with the authoring role) unless `--pack` names a Humanus policy-pack file.
The newsroom's article editor runs the same checks; this is for agents and scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import humanus

from .editorial_checks import (
    PUBLICATION_SCOPE,
    GraphQLEditorialStore,
    Services,
    check_editorial,
    compose_pack,
    ensure_default_policies,
    import_starter_pack,
    policy_record_id,
    record_from_policy,
    settings_from,
    suggest_rewrite,
)


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
        self._records = [record_from_policy(policy, scope=PUBLICATION_SCOPE, source=f"file:{path.name}") for policy in payload["policies"]]
        self._guidance = pack.guidance or ""

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
        return {"settings": {"guidance": self._guidance}}

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


def editorial_pack(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial pack", description="Print the site's policy pack for a desk.")
    parser.add_argument("--section", default=None, help="Desk key whose policies replace publication policies with the same key.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(flags)
    store = GraphQLEditorialStore()
    from .editorial_model_context import editing_pack
    _emit(editing_pack(store, args.section, settings_from(store)), args.output)


def import_style_profile(store, profile: Path, *, replace: bool) -> dict[str, int]:
    """Add a style profile's controls to the store as publication policies."""
    existing = {policy_record_id(r["policyKey"], r["scope"]): r for r in store.list_policies()}
    pack = humanus.policy_pack_from_style_profile(profile)
    counts = {"created": 0, "replaced": 0, "skipped": 0}
    for policy in pack["policies"]:
        record = record_from_policy(policy, scope=PUBLICATION_SCOPE, source=f"style-profile:{pack['packId']}")
        current = existing.get(record["id"])
        if current is None:
            store.create_policy(record)
            counts["created"] += 1
        elif replace:
            store.update_policy({**record, "version": int(current.get("version") or 1) + 1})
            counts["replaced"] += 1
        else:
            counts["skipped"] += 1
    return counts


def editorial_import(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="papyrus editorial import",
        description="Add a style profile's controls to the site as editorial policies (scope: publication).",
    )
    parser.add_argument("--profile", required=True, help="Style profile YAML/JSON, e.g. publications/anthus/style-profile.yml")
    parser.add_argument("--replace", action="store_true", help="Overwrite policies that already exist with the same key.")
    args = parser.parse_args(flags)
    counts = import_style_profile(GraphQLEditorialStore(), Path(args.profile).resolve(), replace=args.replace)
    print(f"{counts['created']} created, {counts['replaced']} replaced, {counts['skipped']} already present (--replace overwrites)")


def editorial_check(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial check", description="Check a draft against the site's editorial policies.")
    parser.add_argument("--draft", required=True, help="Markus/Markdown body to check (read-only).")
    parser.add_argument("--section", default=None, help="Desk key, for desk policies.")
    parser.add_argument("--pack", default=None, help="Use this Humanus policy-pack file instead of the site's policies.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(flags)
    services = Services(store=_store(args.pack))
    _emit(check_editorial({"body": _read_draft(args.draft), "format": "markus", "section": args.section}, services), args.output)


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
    parser.add_argument("--section", default=None)
    parser.add_argument("--pack", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(flags)
    body = _read_draft(args.draft)
    services = Services(store=_store(args.pack))
    arguments: dict[str, Any] = {"body": body, "format": "markus", "section": args.section, "note": args.note}
    if args.finding_id:
        result = check_editorial({"body": body, "format": "markus", "section": args.section}, services)
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


def editorial_policies(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial policies", description="List or add the site's editorial policies.")
    subcommands = parser.add_subparsers(dest="action", required=True)
    listing = subcommands.add_parser("list", help="The site's policies: key, scope, severity, enabled, source.")
    listing.add_argument("--json", action="store_true")
    starter = subcommands.add_parser("import-starter", help="Add a Humanus starter pack's policies that the site does not have yet.")
    starter.add_argument("name", help="ai-writing-tells, plain-language or asd-ste100")
    subcommands.add_parser("ensure-defaults", help="Import the default starter packs once (what a deploy does).")
    args = parser.parse_args(flags)
    store = GraphQLEditorialStore()
    if args.action == "list":
        rows = sorted(store.list_policies(), key=lambda row: (row["scope"], row["policyKey"]))
        if args.json:
            _emit([{key: row.get(key) for key in ("policyKey", "scope", "severity", "enabled", "source", "version")} for row in rows], None)
            return
        for row in rows:
            print(f"{row['scope']}\t{row['policyKey']}\t{row['severity']}\t{'enabled' if row.get('enabled') else 'disabled'}\t{row.get('source')}")
        print(f"{len(rows)} policies")
    elif args.action == "import-starter":
        counts = import_starter_pack({"name": args.name}, Services(store=store))
        print(f"{args.name}: {counts['created']} created, {counts['skipped']} already present")
    else:
        _emit(ensure_default_policies(store), None)


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


def check_summary_line(result: dict[str, Any]) -> str:
    if result.get("skipped"):
        return f"editorial\tcheck\t{result.get('itemId')}\tskipped\t{result['skipped']}"
    return f"editorial\tcheck\t{result.get('itemId')}\t{result.get('violations', 0)} violations\t{result.get('reviews', 0)} for review"


def check_after_save(item_id: str, execute=None) -> None:
    """Every save path checks the new version; a failed check never undoes the save."""
    try:
        print(check_summary_line(request_item_check(item_id, execute)))
    except Exception as error:
        print(f"editorial\tcheck\t{item_id}\tnot checked\t{str(error)[:200]} (run: papyrus editorial check-version --item {item_id})")


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


def editorial_check_version(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial check-version", description="Check one saved version of a story and store the result with it.")
    parser.add_argument("--item", required=True, help="Item version id, e.g. <lineage>-v2.")
    args = parser.parse_args(flags)
    print(check_summary_line(request_item_check(args.item)))


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
