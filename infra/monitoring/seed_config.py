#!/usr/bin/env python3
"""Seed (or replace) a monitor's config item. Config is data in the table.

  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_config.py --table TABLE [--replace]
  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_config.py --table TABLE --monitor-id ttab \
      --source-type ttab-decisions --interval-seconds 86400 --limit 100 --lookback-days 30 \
      --precedential-lookback-days 180

Defaults: the public HN RSS feed, every 900 s, 30 items. A ttab-decisions monitor defaults to the
TTAB Reading Room decision search. Asserts the AWS account.
"""
import argparse
import sys

import boto3

ACCOUNT = "712236451410"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--monitor-id", default="hn")
    parser.add_argument("--source-type", default="hn-rss", choices=("hn-rss", "ttab-decisions"))
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--lookback-days", type=int, default=30, help="ttab-decisions only")
    parser.add_argument("--precedential-lookback-days", type=int, default=0,
                        help="ttab-decisions only: also re-check precedential decisions over this many days (0 = off)")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--replace", action="store_true", help="overwrite an existing config item")
    args = parser.parse_args()
    if boto3.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        print(f"Refusing to write: caller account is not {ACCOUNT}", file=sys.stderr)
        return 2
    default_url = {"hn-rss": "https://news.ycombinator.com/rss",
                   "ttab-decisions": "https://ttab-reading-room.uspto.gov/ttab-efoia-api/decision/search"}[args.source_type]
    item = {"pk": f"MONITOR#{args.monitor_id}", "sk": "CONFIG", "sourceType": args.source_type,
            "sourceUrl": args.source_url or default_url,
            "intervalSeconds": args.interval_seconds, "limit": args.limit, "enabled": True}
    if args.source_type == "ttab-decisions":
        item["lookbackDays"] = args.lookback_days
        if args.precedential_lookback_days:
            item["precedentialLookbackDays"] = args.precedential_lookback_days
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
