"""Make every stored ``section`` a real newsroom section id, or nothing.

A Story's section is a topic. Older data holds other things: the placeholder ``unsectioned``, type-shaped words such as
``articles`` (the type, written where the URL base used to be read), and section titles written before the ids were used
(``AWS`` for the section ``aws``). This module plans, and on request applies, the change for one site.

    python -m papyrus_content.section_migration plan --site anthus --scan-dir scans --static web [--plan-out plan.json]
    python -m papyrus_content.section_migration apply --plan plan.json --confirm-site anthus --yes   # writes; see below

**``plan`` never writes.** It reads the site's ``Item``, ``PublishedItem`` and ``NewsroomSection`` rows, from read-only
scans saved as ``<site>.<Model>.json`` (``--scan-dir``) or through the authoring client (``--live``), classifies every
distinct ``(type, section)`` pair and prints the table. A pair is

* ``keep``: empty, already a section id, or the folder of an Item that is not a Story (``page``, ``wiki_page``: the wiki sync finds its Items by that section);
* ``map``: a section's title, short title or the local part of its id: it becomes the section's id;
* ``clear``: only the type's name or the placeholder (``articles``, ``unsectioned``, ``wiki`` for a wiki page): it becomes empty,
  so the section stops saying what the type already says;
* ``decision``: anything else. The plan lists it and changes nothing; an editor decides.

A change is **safe** only when the Item's page, listing and feed settings are the same under the site's ``projection.json``
(``--static``) before and after: a value the configuration still needs is ``blocked`` and is never applied. Run ``plan`` with the
configuration the site will have after the change, and run the change only when that configuration is the one deployed.

**``apply`` writes**, one ``update`` per row through the authoring client, only the rows of a plan with no blocked change, only
with ``--confirm-site`` naming the plan's site and ``--yes``. History is left alone: superseded versions keep the value they had.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .content_item_lifecycle import is_story_item_type
from .record_helpers import slugify
from .section_ids import UNSECTIONED, is_type_shaped, match_section

HISTORY = "superseded"
EXAMPLES = 3


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def classify(value: str | None, item_type: str, sections: list[Mapping[str, Any]]) -> dict[str, Any]:
    """What to do with one stored section value of an Item of ``item_type``: ``{action, to, reason}``."""
    if value is None:
        return {"action": "keep", "to": None, "reason": "no section"}
    if value.lower() == UNSECTIONED:
        return {"action": "clear", "to": None, "reason": "the old placeholder for no section"}
    if not is_story_item_type(item_type):
        return {"action": "keep", "to": value, "reason": f"an Item of type {item_type!r} is not a Story: its section is the folder its feature keys on (pages, the wiki sync, a newsletter archive)"}
    if any(section.get("id") == value for section in sections):
        return {"action": "keep", "to": value, "reason": "already a section id"}
    try:
        found = match_section(sections, value)
    except ValueError as error:
        return {"action": "decision", "to": None, "reason": str(error)}
    if found is not None:
        target = str(found["id"])
        if "#" in target:
            return {"action": "decision", "to": target, "reason": f"matches section {target!r}, whose id carries a tenant prefix; decide which spelling a story stores"}
        how = "by title" if _clean(found.get("title")) and slugify(str(found["title"])) == slugify(value) else "by its id"
        return {"action": "map", "to": target, "reason": f"matches section {target!r} {how}"}
    if is_type_shaped(value, item_type):
        return {"action": "clear", "to": None, "reason": f"{value!r} only names the type {item_type!r} (or is the old placeholder)"}
    return {"action": "decision", "to": None, "reason": f"{value!r} is not a section id, a section's title or a type name"}


def _status_with(existing: str | None, section: str | None, status: str | None) -> str:
    suffix = existing.rsplit("#", 1)[1] if existing and "#" in existing else (status or "")
    return f"{slugify(section or '')}#{suffix}"


def url_facts(row: Mapping[str, Any], section: str | None, settings, policy) -> list | None:
    """Where an Item's page lives and how it is listed under ``settings``, with ``section`` as its section; ``None`` when the site projects no page for it."""
    from .projection.standard.entries import entry_for_summary
    from .projection.source import summary_from_row

    try:
        summary = summary_from_row({**row, "section": section})
    except ValueError:
        return None
    entry = entry_for_summary(summary, settings, policy)
    if entry is None:
        return ["no page"]
    return [entry.key, entry.section.name if entry.section else None, entry.listed, entry.feed_eligible, entry.in_sitemap]


def plan_for(
    *,
    site: str,
    items: Iterable[Mapping[str, Any]],
    published: Iterable[Mapping[str, Any]],
    sections: list[Mapping[str, Any]],
    settings=None,
) -> dict[str, Any]:
    """The migration plan of one site. ``settings`` (``StandardSettings`` of the projection.json the site will run) enables the URL check."""
    from .projection.standard.urls import UrlPolicy

    policy = UrlPolicy(settings) if settings is not None else None
    items, published = list(items), list(published)
    table: dict[tuple, dict[str, Any]] = {}
    changes: list[dict[str, Any]] = []
    left_as_history = collections.Counter()

    def consider(model: str, row: Mapping[str, Any]) -> None:
        item_type = str(row.get("type") or "")
        if item_type == "doctrine":
            return
        value = _clean(row.get("section"))
        verdict = classify(value, item_type, sections)
        state = row.get("versionState") or row.get("status") or ""
        kind = (model, item_type, value, verdict["action"], verdict["to"], verdict["reason"])
        entry = table.setdefault(kind, {"model": model, "type": item_type, "section": value, **verdict, "rows": collections.Counter(), "examples": []})
        entry["rows"][f"{row.get('status') or ''}/{state}" if model == "Item" else "published"] += 1
        if len(entry["examples"]) < EXAMPLES:
            entry["examples"].append(str(row.get("slug")))
        if verdict["action"] not in ("map", "clear"):
            return
        if model == "Item" and state == HISTORY:
            left_as_history[(item_type, value)] += 1
            return
        before = url_facts(row, value, settings, policy) if policy else None
        after = url_facts(row, verdict["to"], settings, policy) if policy else None
        change = {
            "model": model, "id": row["id"], "type": item_type, "slug": row.get("slug"), "state": state, "from": value, "to": verdict["to"],
            "action": verdict["action"], "sectionStatusFrom": row.get("sectionStatus"),
            "sectionStatusTo": _status_with(row.get("sectionStatus"), verdict["to"], row.get("status")),
        }
        if policy:
            # a page that did not exist (a section the site did not declare) and now does is not a page that moved
            change.update({"urlBefore": before, "urlAfter": after, "gainsPage": before == ["no page"] and after != before, "safe": before == after or before == ["no page"]})
        else:
            change["safe"] = None
        changes.append(change)

    for row in items:
        consider("Item", row)
    for row in published:
        consider("PublishedItem", row)
    values = []
    for entry in sorted(table.values(), key=lambda entry: (entry["model"], entry["type"], str(entry["section"]))):
        values.append({**entry, "rows": dict(sorted(entry["rows"].items()))})
    blocked = [change for change in changes if change["safe"] is False]
    return {
        "site": site,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sections": [{"id": section["id"], "title": section.get("title"), "enabled": section.get("enabled")} for section in sections],
        "checkedAgainstConfiguration": settings is not None,
        "values": values,
        "changes": changes,
        "published": [{"id": change["id"], "from": change["from"], "to": change["to"]} for change in changes if change["model"] == "PublishedItem"],
        "blocked": len(blocked),
        "decisions": [entry for entry in values if entry["action"] == "decision"],
        "leftAsHistory": [{"type": kind, "section": section, "versions": count} for (kind, section), count in sorted(left_as_history.items(), key=str)],
        "ok": not blocked,
    }


def render(plan: Mapping[str, Any]) -> str:
    lines = [
        f"section migration plan for {plan['site']} (dry run: nothing is written)",
        f"sections: {', '.join(section['id'] for section in plan['sections']) or 'none'}",
        "URL check: " + ("against the given projection.json" if plan["checkedAgainstConfiguration"] else "NOT RUN (pass --static)"),
        "",
        f"{'model':<14}{'type':<18}{'stored section':<24}{'action':<10}{'becomes':<22}rows",
    ]
    for entry in plan["values"]:
        lines.append(
            f"{entry['model']:<14}{entry['type']:<18}{str(entry['section']):<24}{entry['action']:<10}{str(entry['to'] if entry['action'] in ('map', 'clear', 'keep') else '-'):<22}"
            f"{sum(entry['rows'].values())} ({', '.join(f'{k} {v}' for k, v in entry['rows'].items())})"
        )
        if entry["action"] in ("map", "clear", "decision"):
            lines.append(f"{'':<14}{entry['reason']}; e.g. {', '.join(entry['examples'])}")
    counts = collections.Counter((change["model"], change["action"]) for change in plan["changes"])
    lines += ["", "rows that would change: " + (", ".join(f"{model} {action} {count}" for (model, action), count in sorted(counts.items())) or "none")]
    if plan["leftAsHistory"]:
        lines.append("superseded versions left as history: " + ", ".join(f"{entry['type']}/{entry['section']} {entry['versions']}" for entry in plan["leftAsHistory"]))
    if plan["decisions"]:
        pairs = collections.Counter()
        for entry in plan["decisions"]:
            if entry["model"] == "Item":
                pairs[(entry["type"], entry["section"])] += sum(entry["rows"].values())
        lines.append("needs a decision (nothing changes): " + "; ".join(f"{kind}/{section} x{count}" for (kind, section), count in sorted(pairs.items(), key=str)))
    gains = [change for change in plan["changes"] if change.get("gainsPage")]
    if gains:
        lines.append(f"{len(gains)} changed rows get a page they do not have today (the section they name is not declared): " + ", ".join(sorted({change['slug'] for change in gains})[:5]))
    blocked = [change for change in plan["changes"] if change["safe"] is False]
    if blocked:
        lines.append(f"BLOCKED: {len(blocked)} changes would move a page or change how it is listed under this configuration; the configuration still needs the old value:")
        for change in blocked[:10]:
            lines.append(f"  {change['model']} {change['id']}: {change['from']!r} -> {change['to']!r}: {change['urlBefore']} -> {change['urlAfter']}")
    lines.append("RESULT: " + ("safe to apply once this configuration is deployed" if plan["ok"] else "do not apply"))
    return "\n".join(lines)


def load_scan(directory: Path, site: str) -> tuple[list[dict], list[dict], list[dict]]:
    def read(model: str) -> list[dict]:
        return json.loads((directory / f"{site}.{model}.json").read_text(encoding="utf-8"))

    return read("Item"), read("PublishedItem"), read("NewsroomSection")


def apply_plan(plan: Mapping[str, Any], client) -> int:
    """Write the plan's changes through ``client`` (an authoring client); returns the number of rows updated."""
    if plan.get("blocked") or not plan.get("ok"):
        raise SystemExit("the plan has blocked changes; nothing is applied")
    if not plan.get("checkedAgainstConfiguration"):
        raise SystemExit("the plan was not checked against a projection.json (plan with --static); nothing is applied")
    written = 0
    for change in plan["changes"]:
        client.update_record(change["model"], {"id": change["id"], "section": change["to"], "sectionStatus": change["sectionStatusTo"]})
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="section_migration", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="classify the stored sections and print the plan (never writes)")
    plan.add_argument("--site", required=True)
    plan.add_argument("--scan-dir", type=Path, help="directory with <site>.Item.json, <site>.PublishedItem.json and <site>.NewsroomSection.json from read-only scans")
    plan.add_argument("--live", action="store_true", help="read the rows through the authoring client of the current directory's site instead (reads only)")
    plan.add_argument("--static", type=Path, help="the web directory whose projection.json the site will run: checks that no page moves")
    plan.add_argument("--plan-out", type=Path, help="save the plan as JSON")
    apply = commands.add_parser("apply", help="write a saved plan (changes data)")
    apply.add_argument("--plan", required=True, type=Path)
    apply.add_argument("--confirm-site", required=True)
    apply.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan":
        if bool(args.scan_dir) == bool(args.live):
            parser.error("pass exactly one of --scan-dir and --live")
        if args.live:
            from .graphql_authoring import create_authoring_client

            client, _claims = create_authoring_client()
            items, published, sections = (client.list_records(model) for model in ("Item", "PublishedItem", "NewsroomSection"))
        else:
            items, published, sections = load_scan(args.scan_dir, args.site)
        settings = None
        if args.static:
            from .projection.standard.config import standard_settings_from_mapping

            settings = standard_settings_from_mapping(json.loads((args.static / "projection.json").read_text(encoding="utf-8")))
        result = plan_for(site=args.site, items=items, published=published, sections=sections, settings=settings)
        if args.plan_out:
            args.plan_out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(render(result))
        return 0 if result["ok"] else 1
    saved = json.loads(args.plan.read_text(encoding="utf-8"))
    if saved["site"] != args.confirm_site:
        raise SystemExit(f"the plan is for {saved['site']!r}, not {args.confirm_site!r}")
    if not args.yes:
        print(f"dry run: would update {len(saved['changes'])} rows of {saved['site']}; pass --yes to write")
        return 0
    from .graphql_authoring import create_authoring_client

    client, _claims = create_authoring_client()
    print(f"updated {apply_plan(saved, client)} rows of {saved['site']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
