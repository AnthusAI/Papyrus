#!/usr/bin/env python3
"""One-off: write the `CAND#<hash>` candidate records for discoveries collected before candidates existed.

  AWS_PROFILE=papyrus-production python3 infra/monitoring/index_candidates.py --table TABLE            # counts only
  AWS_PROFILE=papyrus-production python3 infra/monitoring/index_candidates.py --table TABLE --apply    # writes

Web-search monitors skip a URL another monitor already collected by reading its candidate. The collectors and the email receiver
write candidates for every new item from this release on; this covers earlier discoveries (a Scan, so run it once, by an
operator). An existing candidate gains the monitor in `collectedBy` if missing. Asserts the AWS account.
"""
import argparse
from pathlib import Path
import sys

import boto3
from boto3.dynamodb.conditions import Attr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from papyrus_content.monitoring_candidates import candidate_key  # noqa: E402

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
    configs = {}
    for item in table.scan(FilterExpression=Attr("sk").eq("CONFIG"))["Items"]:
        configs[item["pk"].removeprefix("MONITOR#")] = item
    seen = written = 0
    kwargs = {"FilterExpression": Attr("sk").begins_with("DISC#")}
    while True:
        page = table.scan(**kwargs)
        for disc in page["Items"]:
            monitor = disc.get("monitorId") or disc["pk"].removeprefix("MONITOR#")
            try:
                key = candidate_key(disc["canonicalUrl"])
            except (KeyError, ValueError):
                continue
            seen += 1
            source_type = (configs.get(monitor) or {}).get("sourceType", disc.get("sourceType") or "hn-rss")
            holder = {"monitorId": monitor, "sourceType": source_type, "sourceId": disc["sourceId"],
                      "candidateGroup": (configs.get(monitor) or {}).get("candidateGroup") or monitor}
            if not args.apply:
                continue
            cand = table.get_item(Key=key, ConsistentRead=True).get("Item") or {
                **key, "canonicalUrl": disc["canonicalUrl"], "title": disc.get("title", ""), "firstFoundAt": disc.get("observedAt", ""),
                "collectedBy": [], "provenance": []}
            if any(c.get("monitorId") == monitor for c in cand["collectedBy"]):
                continue
            cand["collectedBy"] = [*cand["collectedBy"], holder]
            cand["provenance"] = [*cand["provenance"], {"monitorId": monitor, "runId": disc.get("runId", ""),
                                                        "foundAt": disc.get("observedAt", "")}]
            table.put_item(Item=cand)
            written += 1
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    print(f"{seen} discoveries with a URL; {written} candidates written" + ("" if args.apply else " (dry run: pass --apply)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
