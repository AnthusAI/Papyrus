#!/usr/bin/env python3
"""One-off: write the `URL#<hash>` / `MON#<monitorId>` records for discoveries collected before web-search monitors existed.

  AWS_PROFILE=papyrus-production python3 infra/monitoring/index_urls.py --table TABLE            # counts only; writes nothing
  AWS_PROFILE=papyrus-production python3 infra/monitoring/index_urls.py --table TABLE --apply    # writes the records

Web-search monitors skip a URL another monitor already collected by reading these records. The collectors write them for every
new item from this release on; this script covers earlier ones (a Scan of the table, so run it once, by an operator). Records
already present are left alone. Asserts the AWS account.
"""
import argparse
from pathlib import Path
import sys

import boto3
from boto3.dynamodb.conditions import Attr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from papyrus_content.monitoring_web import url_hash  # noqa: E402

ACCOUNT = "712236451410"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if boto3.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        print(f"Refusing: caller account is not {ACCOUNT}", file=sys.stderr)
        return 2
    table = boto3.resource("dynamodb").Table(args.table)
    source_types = {}
    for item in table.scan(FilterExpression=Attr("sk").eq("CONFIG"))["Items"]:
        source_types[item["pk"].removeprefix("MONITOR#")] = item.get("sourceType", "hn-rss")
    seen = written = 0
    kwargs = {"FilterExpression": Attr("sk").begins_with("DISC#")}
    while True:
        page = table.scan(**kwargs)
        for disc in page["Items"]:
            monitor = disc.get("monitorId") or disc["pk"].removeprefix("MONITOR#")
            try:
                key = {"pk": f"URL#{url_hash(disc['canonicalUrl'])}", "sk": f"MON#{monitor}"}
            except (KeyError, ValueError):
                continue
            seen += 1
            if args.apply:
                try:
                    table.put_item(Item={**key, "monitorId": monitor, "sourceType": source_types.get(monitor, "hn-rss"),
                                         "sourceId": disc["sourceId"], "canonicalUrl": disc["canonicalUrl"],
                                         "firstObservedAt": disc.get("observedAt", "")},
                                   ConditionExpression="attribute_not_exists(pk)")
                    written += 1
                except table.meta.client.exceptions.ConditionalCheckFailedException:
                    pass
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    print(f"{seen} discoveries with a URL; {written} records written" + ("" if args.apply else " (dry run: pass --apply)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
