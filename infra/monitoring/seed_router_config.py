#!/usr/bin/env python3
"""Seed, replace or flip the router config item (`CONFIG#router`). Config is data in the table.

  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_router_config.py --table TABLE --file router.json [--replace]
  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_router_config.py --table TABLE --set mode=live
  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_router_config.py --table TABLE --set feedback=true
  AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_router_config.py --table TABLE --set ceilings=decisionsTotal=300,decisionsPerDay=100,items=300

`--set ceilings=...` records the shared Cyclotron's decision ceilings as display data for the newsroom's
Monitoring page (the router never uses them to decide anything); `ceilings=none` clears them.

`--file` is a JSON document of the shape in docs/monitoring-cloud.md (example:
docs/monitoring-router-config.example.json). `--set` changes one top-level field of the stored
item (mode, feedback, maxItemsPerRun, enabled). Every write is validated with the Lambda's own
validator, so a config the router would refuse is never stored. Asserts the AWS account.
"""
import argparse
import json
from pathlib import Path
import sys

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from papyrus_content.monitoring_router import ROUTER_CONFIG_SK, validate_router_config  # noqa: E402

ACCOUNT = "712236451410"


def coerce(key: str, value: str):
    if key in ("feedback", "enabled"):
        if value not in ("true", "false"):
            raise ValueError(f"{key} must be true or false")
        return value == "true"
    if key == "maxItemsPerRun":
        return int(value)
    if key == "mode":
        return value
    if key == "ceilings":
        if value == "none":
            return None
        pairs = [part.partition("=") for part in value.split(",")]
        if not all(name and sep and number.isdigit() for name, sep, number in pairs):
            raise ValueError("ceilings must look like decisionsTotal=300,decisionsPerDay=100,items=300 (or none)")
        return {name: int(number) for name, _, number in pairs}
    raise ValueError(f"--set supports mode, feedback, maxItemsPerRun, enabled and ceilings, not {key}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--monitor-id", default="hn")
    parser.add_argument("--file", help="router config JSON")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--replace", action="store_true", help="overwrite an existing router config with --file")
    args = parser.parse_args()
    if bool(args.file) == bool(args.set):
        parser.error("give exactly one of --file or --set")
    if boto3.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        print(f"Refusing to write: caller account is not {ACCOUNT}", file=sys.stderr)
        return 2
    table = boto3.resource("dynamodb").Table(args.table)
    key = {"pk": f"MONITOR#{args.monitor_id}", "sk": ROUTER_CONFIG_SK}
    if args.file:
        item = {**json.loads(Path(args.file).read_text()), **key}
        validate_router_config(item)
        kwargs = {} if args.replace else {"ConditionExpression": "attribute_not_exists(pk)"}
        try:
            table.put_item(Item=item, **kwargs)
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            print("Router config already exists; pass --replace to overwrite", file=sys.stderr)
            return 1
        print(f"Seeded {key['pk']} {key['sk']} (mode {item['mode']}, feedback {item.get('feedback') is True})")
        return 0
    stored = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not stored:
        print("No router config to change; seed it with --file first", file=sys.stderr)
        return 1
    for pair in args.set:
        name, _, value = pair.partition("=")
        coerced = coerce(name, value)
        if coerced is None:
            stored.pop(name, None)
        else:
            stored[name] = coerced
    validate_router_config(json.loads(json.dumps(stored, default=int)))
    table.put_item(Item=stored)
    print(f"Updated {key['pk']} {key['sk']}: " + ", ".join(args.set))
    return 0


if __name__ == "__main__":
    sys.exit(main())
