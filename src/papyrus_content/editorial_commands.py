"""`papyrus editorial`: the site's editorial policies, checked by Limatus from the command line.

    papyrus editorial pack [--section KEY] [--output FILE]
    papyrus editorial import --profile publications/<pub>/style-profile.yml [--replace]
    papyrus editorial check --draft FILE [--section KEY] [--pack FILE] [--output FILE]
    papyrus editorial suggest --draft FILE (--finding-id ID | --select TEXT) [--note TEXT] [--section KEY] [--pack FILE]

Policies and settings come from the site (EditorialPolicy / EditorialCheckSettings,
read with the authoring role) unless `--pack` names a Limatus policy-pack file.
The newsroom's article editor runs the same checks; this is for agents and scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import limatus

from .editorial_checks import (
    PUBLICATION_SCOPE,
    GraphQLEditorialStore,
    Services,
    check_editorial,
    compose_pack,
    policy_record_id,
    record_from_policy,
    settings_from,
    suggest_rewrite,
)


class PackFileStore:
    """Serves one policy-pack file's policies, with no settings or decisions."""

    def __init__(self, path: Path) -> None:
        pack = limatus.load_policy_pack(path)
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
    pack = limatus.policy_pack_from_style_profile(profile)
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
    parser.add_argument("--pack", default=None, help="Use this Limatus policy-pack file instead of the site's policies.")
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
    except limatus.SuggestUnavailableError as error:
        raise ValueError(str(error)) from error
