"""``papyrus knowledge run undo|restore``: take back everything one knowledge run wrote, as one step (PPY-5b5a5d).

``undo --run-id ID`` plans which Items run ``ID`` created (``machine_writes.py``), unpublishes the live ones and moves them all to the
``retired`` stage. It is a dry run unless ``--apply`` is passed: unlike most mutation commands of this CLI, it writes nothing by default.
Nothing is deleted. ``restore --run-id ID`` puts the Items back in the stage they had (a page that was live comes back as a draft).

``--live-out FILE`` (with ``--apply``) writes the ids of the Item rows whose pages were live, the list ``papyrus ops content project
--unpublished-items FILE`` needs to remove those pages from the site: a bulk projection never deletes the pages of an unpublished Item.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..graphql_authoring import create_authoring_client
from ..knowledge_snapshot.commands import announce_backend, select_backend
from ..machine_writes import UNDO_ACTOR, apply_restore, apply_undo, plan_restore, plan_undo
from ..options import normalize_string, parse_options


def _setup(flags: list[str], verb: str):
    options = parse_options(flags)
    run_id = normalize_string(options.get("run-id"))
    if not run_id:
        raise ValueError(f"papyrus knowledge run {verb} requires --run-id <run id> (the id printed by the run, or `knowledge-<publication>-<execution name>` for the cloud run).")
    select_backend(options)
    client, claims = create_authoring_client()
    announce_backend()
    return options, run_id, client, normalize_string((claims or {}).get("sub")) or UNDO_ACTOR


def knowledge_run_undo(flags: list[str]) -> None:
    from ..knowledge_wiki.sync import live_sources  # noqa: PLC0415 - the wiki sync owns how a live page is found

    options, run_id, client, by = _setup(flags, "undo")
    apply = options.get("apply") is True
    rows = client.list_records("Item")
    lineages = {str(row.get("lineageId") or row["id"]) for row in rows}
    plan = plan_undo(rows, run_id, lambda lineage: live_sources(client, [lineage]).get(lineage))
    done = apply_undo(client, plan, by=by) if apply and plan.items else {}
    live_out = normalize_string(options.get("live-out"))
    if apply and live_out:
        target = Path(live_out)
        earlier = set(json.loads(target.read_text(encoding="utf-8"))) if target.exists() else set()
        target.write_text(json.dumps(sorted(earlier | {item.live_item_id for item in plan.live})) + "\n", encoding="utf-8")
    summary = plan.summary()
    if options.get("json"):
        print(json.dumps({"mode": "apply" if apply else "dry-run", **summary, "done": done, "lineagesRead": len(lineages)}, indent=2, sort_keys=True))
        return
    print(f"knowledge\trun-undo\tmode\t{'apply' if apply else 'dry-run'}\t{run_id}")
    for item in plan.items:
        later = f"\trewritten by {item.rewritten_by}" if item.rewritten_by else ""
        print(f"knowledge\trun-undo\tretire\t{item.type}\t{item.section}/{item.slug}\t{'live: unpublish' if item.live else item.status}{later}")
    for name, count in summary["byTypeAndSection"].items():
        print(f"knowledge\trun-undo\tplan\t{name}\t{count}")
    print(f"knowledge\trun-undo\tplan\tto retire\t{summary['toRetire']}\tlive\t{summary['live']}\talready retired\t{summary['alreadyRetired']}")
    if not plan.items:
        print("knowledge\trun-undo\tnothing\tno Item records this run as its creator")
    elif not apply:
        print("knowledge\trun-undo\tapply\tskipped\tpass --apply to write; `papyrus knowledge run restore` reverses it", file=sys.stdout)
    else:
        print(f"knowledge\trun-undo\tdone\tretired {done['retired']}\tunpublished {done['unpublished']}")
        if plan.live and not live_out:
            print("knowledge\trun-undo\tnote\tpass --live-out FILE, then `papyrus ops content project --unpublished-items FILE`, to remove the pages from the site")


def knowledge_run_restore(flags: list[str]) -> None:
    options, run_id, client, by = _setup(flags, "restore")
    apply = options.get("apply") is True
    plan = plan_restore(client.list_records("Item"), run_id)
    restored = apply_restore(client, plan, by=by) if apply and plan.items else 0
    if options.get("json"):
        print(json.dumps({"mode": "apply" if apply else "dry-run", "runId": run_id, "toRestore": len(plan.items), "wereLive": plan.was_live, "restored": restored}, indent=2, sort_keys=True))
        return
    print(f"knowledge\trun-restore\tmode\t{'apply' if apply else 'dry-run'}\t{run_id}")
    print(f"knowledge\trun-restore\tplan\tto restore\t{len(plan.items)}\twere live\t{plan.was_live}")
    if not plan.items:
        print("knowledge\trun-restore\tnothing\tno retired Item records an undo of this run")
    elif not apply:
        print("knowledge\trun-restore\tapply\tskipped\tpass --apply to write")
    else:
        print(f"knowledge\trun-restore\tdone\trestored {restored}\tpages that were live return as drafts; publish them to put them back")
