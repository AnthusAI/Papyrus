#!/usr/bin/env python3
"""Seed (or replace) the HN monitor config item. Config is data in the table.

  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_config.py --table TABLE [--replace]

Defaults: the public HN RSS feed, every 900 s, 30 items. Asserts the AWS account.
"""
import argparse
import sys

import boto3

ACCOUNT = "712236451410"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--monitor-id", default="hn")
    parser.add_argument("--source-url", default="https://news.ycombinator.com/rss")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--replace", action="store_true", help="overwrite an existing config item")
    args = parser.parse_args()
    if boto3.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        print(f"Refusing to write: caller account is not {ACCOUNT}", file=sys.stderr)
        return 2
    item = {"pk": f"MONITOR#{args.monitor_id}", "sk": "CONFIG", "sourceUrl": args.source_url,
            "intervalSeconds": args.interval_seconds, "limit": args.limit, "enabled": True}
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
