#!/usr/bin/env python3
"""Seed the seven web-search monitors (`web-<publication>`) and their router configs. Config is data in the table.

  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_web_monitors.py --table TABLE            # plan only; reads, writes nothing
  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_web_monitors.py --table TABLE --apply    # writes the 14 items
  ... --queries-file web-queries.json --approved-by "NAME"   # the reviewed proposal from `papyrus monitors web-queries --all --out`
  ... --enable                          # with --queries-file: enable the monitors that have queries

Each monitor's `CONFIG` is a web-search monitor (hourly, topic news; disabled unless --enable). Its queries are `QUERY#` records
written from --queries-file (a query is searched only once it has --approved-by). Each `CONFIG#router` lists only that publication and sets `holdDecisions: true`: enrichment runs, no decide request
is posted until `seed_router_config.py --monitor-id web-<id> --set holdDecisions=false`. The six shared-Cyclotron publications
copy the `hn` router's cyclotron block and publication entry as stored; Distinctive Mark has `decisions: "hold"` and no
cyclotron block. Existing items are left alone unless --replace. Every item is validated with the Lambda's own validators.
Asserts the AWS account.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from papyrus_content.monitoring_cloud import _validate_config  # noqa: E402
from papyrus_content.monitoring_router import validate_router_config  # noqa: E402
from papyrus_content.monitoring_web import query_record  # noqa: E402
from papyrus_content.monitoring_web_publications import WEB_PUBLICATIONS, monitor_config, monitor_id, router_config  # noqa: E402

ACCOUNT = "712236451410"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--queries-file", help="JSON from `papyrus monitors web-queries --out`: {publicationId: {queries: [...]}}")
    parser.add_argument("--approved-by", help="who approved the queries in --queries-file (unapproved queries are stored but not searched)")
    parser.add_argument("--enable", action="store_true", help="enable monitors that have queries (needs --queries-file)")
    parser.add_argument("--apply", action="store_true", help="write the items; without it nothing is written")
    parser.add_argument("--replace", action="store_true", help="overwrite existing items")
    args = parser.parse_args()
    if args.enable and not args.queries_file:
        parser.error("--enable needs --queries-file")
    if boto3.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        print(f"Refusing: caller account is not {ACCOUNT}", file=sys.stderr)
        return 2
    table = boto3.resource("dynamodb").Table(args.table)
    hn_router = table.get_item(Key={"pk": "MONITOR#hn", "sk": "CONFIG#router"}, ConsistentRead=True)["Item"]
    proposals = json.loads(Path(args.queries_file).read_text()) if args.queries_file else {}
    items = []
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for publication in WEB_PUBLICATIONS:
        queries = (proposals.get(publication) or {}).get("queries") or []
        monitor = monitor_config(publication, enabled=bool(args.enable and queries))
        records = [query_record(monitor_id(publication), q["text"], q["rationale"], origin="drafted", created_by="gpt-6-luna",
                                now_iso=now, approved_by=args.approved_by) for q in queries]
        router = router_config(publication, hn_router)
        _validate_config(json.loads(json.dumps(monitor)))
        validate_router_config(json.loads(json.dumps(router, default=int)))
        items += [monitor, router, *records]
    for item in items:
        kind = "router" if item["sk"] == "CONFIG#router" else "query" if item["sk"].startswith("QUERY#") else "monitor"
        detail = (f"decisions {item['decisions']}, holdDecisions {item['holdDecisions']}, "
                  f"{len(item['publications'])} publications, cyclotron {'yes' if item.get('cyclotron') else 'none'}" if kind == "router"
                  else f"{item['text']!r} (approved by {item.get('approvedBy')})" if kind == "query"
                  else f"enabled {item['enabled']}")
        print(f"{'WRITE' if args.apply else 'plan '} {item['pk']} {item['sk']}: {detail}")
        if args.apply:
            kwargs = {} if args.replace else {"ConditionExpression": "attribute_not_exists(pk)"}
            try:
                table.put_item(Item=item, **kwargs)
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                print("  already exists; pass --replace to overwrite", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
