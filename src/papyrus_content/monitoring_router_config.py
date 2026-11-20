"""The router's configuration as files in Git, applied to the monitoring table by the stack deploy.

A monitor's router config (the `CONFIG#router` item of `MONITOR#<id>`) is one JSON file, `infra/monitoring/router-config/<monitorId>.json`: the item
without its key. The files ship inside the router zip. The `papyrus-monitoring` stack runs this module's handler as a CloudFormation custom resource
(`RouterConfigApplier`), so every release that changes a file (or the code that reads it) writes the files to the table, with the stack's own role, and
nobody writes the table by hand. A file the router would refuse (`validate_router_config`) fails the build tests, and fails the deploy before it writes anything.

A file never holds an AWS account id, an endpoint host or a Cyclotron id (this repository is public). Where one belongs it holds a reference, which the applier
resolves at deploy time and which fails the deploy when it does not resolve:

* `${AccountId}`, `${CyclotronInvokerRoleArn}`: values the stack passes (`Substitutions`).
* `${AppSyncEndpoint:<Site>}`: the GraphQL endpoint of the AppSync API whose id the stack passes as `ApiIds.<Site>` (the stack's `<Site>ApiId` parameter).
* `${Ssm:<name>}`: the value of an SSM parameter under `/papyrus/monitoring/` (the Cyclotron's API endpoint, account id and run id are `/papyrus/monitoring/cyclotron/endpoint`, `.../account-id` and `.../run-id`).

A reference to anything else is refused before any lookup. The apply is idempotent: an item that already equals its file is left alone, so a release that changes nothing writes nothing. A file replaces its
item whole, which is what makes Git the one place to change it: a field removed from the file is removed from the table. A monitor with no file is
not touched, and deleting the stack or a file deletes nothing. The handler is also what `docs/automations.md` and `docs/monitoring-cloud.md` mean by "apply".
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any

from .monitoring_router import ROUTER_CONFIG_SK, validate_router_config

CONFIG_DIRECTORY = "router-config"
MONITOR_ID_PATTERN = r"[a-z0-9][a-z0-9-]{0,62}"


def config_directory() -> Path:
    """The directory of files: `router-config` beside this package's parent in the Lambda zip, `infra/monitoring/router-config` in a checkout."""
    configured = os.environ.get("ROUTER_CONFIG_DIRECTORY")
    if configured:
        return Path(configured)
    package_root = Path(__file__).resolve().parent
    for candidate in (package_root.parent / CONFIG_DIRECTORY, package_root.parents[1] / "infra" / "monitoring" / CONFIG_DIRECTORY):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"no {CONFIG_DIRECTORY} directory beside the package or in infra/monitoring")


REFERENCE = re.compile(r"\$\{(\w+)(?::([^}]+))?\}")
SSM_PREFIX = "/papyrus/monitoring/"


class References:
    """Resolves the `${...}` references of a file. `stack_values` and `api_ids` come from the stack; `lookup(kind, argument)` reads AWS (tests pass a fake)."""

    def __init__(self, stack_values: dict[str, str], api_ids: dict[str, str], lookup=None):
        self.stack_values, self.api_ids, self.lookup = stack_values, api_ids, lookup or aws_lookup

    def resolve(self, kind: str, argument: str | None) -> str:
        if argument is None:
            if kind not in self.stack_values:
                raise ValueError(f"${{{kind}}} is not a value the stack passes (it passes {', '.join(sorted(self.stack_values))})")
            return self.stack_values[kind]
        if kind == "AppSyncEndpoint":
            if argument not in self.api_ids:
                raise ValueError(f"${{AppSyncEndpoint:{argument}}} names no API the stack passes (it passes {', '.join(sorted(self.api_ids))})")
            return self.lookup(kind, self.api_ids[argument])
        if kind == "Ssm":
            if not argument.startswith(SSM_PREFIX):
                raise ValueError(f"${{Ssm:{argument}}} must name a parameter under {SSM_PREFIX}")
            return self.lookup(kind, argument)
        raise ValueError(f"${{{kind}:{argument}}} is not a reference kind (AppSyncEndpoint, Ssm)")


def aws_lookup(kind: str, argument: str) -> str:
    import boto3

    if kind == "AppSyncEndpoint":
        return boto3.client("appsync").get_graphql_api(apiId=argument)["graphqlApi"]["uris"]["GRAPHQL"]
    return boto3.client("ssm").get_parameter(Name=argument)["Parameter"]["Value"]


def expand(value: Any, references: References) -> Any:
    """The document with every reference in its strings replaced by what it resolves to. A lookup that fails fails the whole expansion."""
    if isinstance(value, str):
        def replace(match):
            try:
                return references.resolve(match.group(1), match.group(2))
            except ValueError:
                raise
            except Exception as error:
                raise ValueError(f"{match.group(0)} did not resolve: {type(error).__name__}: {error}") from error
        return REFERENCE.sub(replace, value)
    if isinstance(value, list):
        return [expand(entry, references) for entry in value]
    if isinstance(value, dict):
        return {key: expand(entry, references) for key, entry in value.items()}
    return value


def read_configs(references: References, directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Every file as `{monitorId: document}` with its references resolved, each checked with the router's own validator. Raises `ValueError` naming the file that fails."""

    directory = directory or config_directory()
    configs: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        monitor_id = path.stem
        if not re.fullmatch(MONITOR_ID_PATTERN, monitor_id):
            raise ValueError(f"{path.name}: the file name must be the monitor id (lowercase letters, digits and hyphens)")
        try:
            document = expand(json.loads(path.read_text(), parse_float=Decimal), references)
            if not isinstance(document, dict) or "pk" in document or "sk" in document:
                raise ValueError("the file holds the config item without its pk and sk")
            validate_router_config(json.loads(json.dumps(document, default=_plain)))
        except ValueError as error:
            raise ValueError(f"{path.name}: {error}") from error
        configs[monitor_id] = document
    if not configs:
        raise ValueError(f"{directory} holds no router config files")
    return configs


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    raise TypeError(f"{type(value).__name__} is not JSON data")


def item_of(monitor_id: str, document: dict[str, Any]) -> dict[str, Any]:
    return {**document, "pk": f"MONITOR#{monitor_id}", "sk": ROUTER_CONFIG_SK}


def apply(table, configs: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Writes each config whose stored item differs from it. Returns the monitor ids written, left alone, and created."""
    outcome: dict[str, list[str]] = {"written": [], "unchanged": [], "created": []}
    for monitor_id, document in configs.items():
        item = item_of(monitor_id, document)
        stored = table.get_item(Key={"pk": item["pk"], "sk": item["sk"]}, ConsistentRead=True).get("Item")
        if stored == item:
            outcome["unchanged"].append(monitor_id)
            continue
        table.put_item(Item=item)
        outcome["written" if stored else "created"].append(monitor_id)
    return outcome


def _respond(event: dict[str, Any], status: str, reason: str, physical_id: str) -> None:
    body = json.dumps({"Status": status, "Reason": reason[:1000], "PhysicalResourceId": physical_id, "StackId": event["StackId"],
                       "RequestId": event["RequestId"], "LogicalResourceId": event["LogicalResourceId"], "Data": {}}).encode()
    request = urllib.request.Request(event["ResponseURL"], data=body, method="PUT", headers={"content-type": ""})
    urllib.request.urlopen(request, timeout=30).read()   # noqa: S310 - a presigned CloudFormation URL


def handler(event: dict[str, Any], context: Any) -> None:
    """The CloudFormation custom resource. Create and Update validate every file, then apply; Delete does nothing (items stay)."""
    import boto3

    physical_id = event.get("PhysicalResourceId") or "router-config"
    try:
        if event["RequestType"] != "Delete":
            properties = event.get("ResourceProperties", {})
            references = References({name: str(value) for name, value in (properties.get("Substitutions") or {}).items()},
                                    {name: str(value) for name, value in (properties.get("ApiIds") or {}).items()})
            outcome = apply(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]), read_configs(references))
            print(json.dumps({"router": "config_applied", **outcome}))
        _respond(event, "SUCCESS", "applied", physical_id)
    except Exception as error:   # the stack update fails and rolls back; the message is in the stack events and the log
        print(json.dumps({"router": "config_apply_failed", "error": str(error)[:500]}))
        _respond(event, "FAILED", f"router config not applied: {error}", physical_id)
