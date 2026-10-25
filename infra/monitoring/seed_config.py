#!/usr/bin/env python3
"""Seed (or replace) a monitor's config item. Config is data in the table.

  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_config.py --table TABLE [--replace]
  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_config.py --table TABLE --monitor-id ttab \
      --source-type ttab-decisions --interval-seconds 86400 --limit 100 --lookback-days 30 \
      --precedential-lookback-days 180
  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_config.py --table TABLE --monitor-id huggingface \
      --source-type huggingface-models --file huggingface-config.json

A huggingface-models monitor is configured with `--file` (a JSON object with the fields in
docs/monitoring-cloud.md: pipelineTags, authors, search, sort, minLikes, minDownloads, lookbackDays,
pageSize, pagesPerQuery, intervalSeconds, limit); the item is validated with the collector's own validator
before it is written, so a config the Lambda would refuse is never stored.

Defaults: the public HN RSS feed, every 900 s, 30 items. A ttab-decisions monitor defaults to the
TTAB Reading Room decision search. Asserts the AWS account.
"""
import argparse
import json
from pathlib import Path
import sys

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from papyrus_content.monitoring_cloud import _validate_config  # noqa: E402

ACCOUNT = "712236451410"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--monitor-id", default="hn")
    parser.add_argument("--source-type", default="hn-rss", choices=("hn-rss", "ttab-decisions", "huggingface-models"))
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--lookback-days", type=int, default=30, help="ttab-decisions only")
    parser.add_argument("--precedential-lookback-days", type=int, default=0,
                        help="ttab-decisions only: also re-check precedential decisions over this many days (0 = off)")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--file", help="huggingface-models: JSON file with the monitor's filters and limits")
    parser.add_argument("--replace", action="store_true", help="overwrite an existing config item")
    args = parser.parse_args()
    item = None
    if args.source_type == "huggingface-models":
        if not args.file:
            parser.error("--source-type huggingface-models needs --file")
        item = {"intervalSeconds": 86400, "limit": 300, **json.loads(Path(args.file).read_text()),
                "pk": f"MONITOR#{args.monitor_id}", "sk": "CONFIG", "sourceType": args.source_type, "enabled": True}
        item["sourceUrl"] = args.source_url or item.get("sourceUrl") or "https://huggingface.co/api/models"
    if boto3.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        print(f"Refusing to write: caller account is not {ACCOUNT}", file=sys.stderr)
        return 2
    if item is None:
        default_url = {"hn-rss": "https://news.ycombinator.com/rss",
                       "ttab-decisions": "https://ttab-reading-room.uspto.gov/ttab-efoia-api/decision/search"}[args.source_type]
        item = {"pk": f"MONITOR#{args.monitor_id}", "sk": "CONFIG", "sourceType": args.source_type,
                "sourceUrl": args.source_url or default_url,
                "intervalSeconds": args.interval_seconds, "limit": args.limit, "enabled": True}
        if args.source_type == "ttab-decisions":
            item["lookbackDays"] = args.lookback_days
            if args.precedential_lookback_days:
                item["precedentialLookbackDays"] = args.precedential_lookback_days
    _validate_config(item)
    table = boto3.resource("dynamodb").Table(args.table)
    kwargs = {} if args.replace else {"ConditionExpression": "attribute_not_exists(pk)"}
    try:
        table.put_item(Item=item, **kwargs)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        print("Config already exists; pass --replace to overwrite", file=sys.stderr)
        return 1
    print(f"Seeded MONITOR#{args.monitor_id} CONFIG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
