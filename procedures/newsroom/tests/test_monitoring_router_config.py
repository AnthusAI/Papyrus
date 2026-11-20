"""The router config files in Git (infra/monitoring/router-config) and the custom resource that writes them to the monitoring table.

Nothing here calls AWS. features_backend/monitoring/monitoring-router-config-in-git.feature tells the same story in prose.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from papyrus_content import monitoring_router_config as mrc
from papyrus_content.monitoring_router import ROUTER_CONFIG_SK

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "infra" / "monitoring" / "router-config"
TEMPLATE = ROOT / "infra" / "monitoring" / "papyrus-monitoring.yaml"
SSM_PARAMETER = re.compile(r"/amplify/shared/[a-z0-9]+/OPENAI_API_KEY")
# Values the stack passes, made up here (a literal account id must not be written in this repository).
SUBSTITUTIONS = {"AccountId": "1" * 12, "CyclotronInvokerRoleArn": "arn:aws:iam::" + "2" * 12 + ":role/cyclotron-machine-invoker"}
API_IDS = {site: f"api{site.lower()}" for site in ("AnthUs", "MachinesOnMachines", "ThreatIntel", "DataParade", "Pilobolus", "Shipped", "Distinctive")}
PARAMETERS = {"/papyrus/monitoring/cyclotron/endpoint": "https://abc123.execute-api.us-east-1.amazonaws.com", "/papyrus/monitoring/cyclotron/account-id": "cyclotron-account", "/papyrus/monitoring/cyclotron/run-id": "cyclotron-run"}


def fake_lookup(kind, argument):
    if kind == "AppSyncEndpoint":
        return f"https://{argument}.appsync-api.us-east-1.amazonaws.com/graphql"
    return PARAMETERS[argument]   # a missing parameter raises, as SSM does


def references(lookup=fake_lookup, api_ids=None):
    return mrc.References(SUBSTITUTIONS, API_IDS if api_ids is None else api_ids, lookup)


SITE_PUBLICATIONS = ("anth-us", "machines-on-machines", "threat-intelligence", "data-parade", "pilobol-us", "shipped")


class Table:
    """The slice of a DynamoDB table the applier uses; items come back as DynamoDB would return them (numbers as Decimal)."""

    def __init__(self, items=()):
        self.items = {(item["pk"], item["sk"]): json.loads(json.dumps(item), parse_float=Decimal, parse_int=Decimal) for item in items}
        self.puts: list[tuple[str, str]] = []

    def get_item(self, Key, ConsistentRead=False):
        found = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": found} if found else {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item
        self.puts.append((Item["pk"], Item["sk"]))


def test_every_file_is_a_config_the_router_accepts():
    configs = mrc.read_configs(references(), DIRECTORY)
    assert "hn" in configs and len(configs) == len(list(DIRECTORY.glob("*.json")))


def test_no_file_holds_an_account_id_a_host_or_a_cyclotron_id_only_references():
    for path in DIRECTORY.glob("*.json"):
        text = path.read_text()
        assert not re.search(r"\d{12}|appsync-api|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}|execute-api", text), path.name
    configs = mrc.read_configs(references(), DIRECTORY)
    assert configs["hn"]["cyclotron"]["roleArn"] == SUBSTITUTIONS["CyclotronInvokerRoleArn"]
    assert configs["hn"]["cyclotron"]["accountId"] == "cyclotron-account" and configs["hn"]["cyclotron"]["runId"] == "cyclotron-run"
    assert SUBSTITUTIONS["AccountId"] in configs["hn"]["publications"][0]["monitorStories"]["vectorIndexArn"]
    assert all("api" in p["appsyncEndpoint"] for p in configs["hn"]["publications"])


@pytest.mark.parametrize("reference", ["${Unknown}", "${Other:x}", "${AppSyncEndpoint:Nowhere}", "${Ssm:/somewhere/else}"])
def test_a_reference_outside_the_allowed_set_is_refused_before_any_lookup(reference):
    def never(kind, argument):
        raise AssertionError("looked up")
    with pytest.raises(ValueError):
        mrc.expand({"a": [reference]}, references(never))


def test_a_reference_that_does_not_resolve_fails_naming_it():
    with pytest.raises(ValueError, match="did not resolve"):
        mrc.expand("${Ssm:/papyrus/monitoring/cyclotron/missing}", references())


def test_every_reference_in_the_files_is_one_the_template_passes():
    template = TEMPLATE.read_text()
    passed = set(re.findall(r"^        (\w+): !Ref \w+ApiId$", template.split("  RouterConfigApplier:")[1], re.M))
    used = {m for path in DIRECTORY.glob("*.json") for m in re.findall(r"\$\{AppSyncEndpoint:(\w+)\}", path.read_text())}
    assert used and used <= passed
    assert set(API_IDS) == passed


def test_every_site_publication_on_hn_has_its_model_key_parameter():
    publications = {p["publicationId"]: p for p in mrc.read_configs(references(), DIRECTORY)["hn"]["publications"]}
    assert set(publications) == set(SITE_PUBLICATIONS)
    for publication_id, publication in publications.items():
        assert SSM_PARAMETER.fullmatch(publication.get("openaiKeyParameter", "")), publication_id


def test_machines_on_machines_can_be_started_by_the_localize_automation():
    from papyrus_content.automations import MonitoringReader

    hn = mrc.read_configs(references(), DIRECTORY)["hn"]
    table = Table([mrc.item_of("hn", hn)])
    router = MonitoringReader(table).router_config("hn")
    publication = next(p for p in router["publications"] if p["publicationId"] == "machines-on-machines")
    assert publication["openaiKeyParameter"] and publication["appsyncEndpoint"].startswith("https://")


def test_apply_creates_writes_and_then_leaves_alone():
    configs = mrc.read_configs(references(), DIRECTORY)
    table = Table()
    first = mrc.apply(table, configs)
    assert sorted(first["created"]) == sorted(configs) and not first["written"] and not first["unchanged"]
    table.puts.clear()
    second = mrc.apply(table, configs)
    assert sorted(second["unchanged"]) == sorted(configs) and not table.puts


def test_apply_replaces_an_item_whole_so_a_field_taken_out_of_the_file_leaves_the_table():
    configs = mrc.read_configs(references(), DIRECTORY)
    stored = {**mrc.item_of("hn", configs["hn"]), "holdDecisions": True, "somethingTypedByHand": "x"}
    table = Table([stored])
    outcome = mrc.apply(table, {"hn": configs["hn"]})
    assert outcome["written"] == ["hn"]
    assert "somethingTypedByHand" not in table.items[("MONITOR#hn", ROUTER_CONFIG_SK)]


def test_apply_leaves_a_monitor_with_no_file_alone():
    other = {"pk": "MONITOR#elsewhere", "sk": ROUTER_CONFIG_SK, "mode": "dry-run"}
    table = Table([other])
    mrc.apply(table, {"hn": mrc.read_configs(references(), DIRECTORY)["hn"]})
    assert table.items[("MONITOR#elsewhere", ROUTER_CONFIG_SK)] == other


def test_a_file_the_router_would_refuse_is_named_and_nothing_is_written(tmp_path):
    (tmp_path / "hn.json").write_text(json.dumps({"mode": "live", "publications": [
        {"publicationId": "a", "appsyncEndpoint": "https://x.appsync-api.us-east-1.amazonaws.com/graphql",
         "procedureTriggers": [{"procedureKey": "k.procedure"}]}]}))
    with pytest.raises(ValueError, match="hn.json"):
        mrc.read_configs(references(), tmp_path)


@pytest.mark.parametrize("name,body", [("Bad_Name.json", {"mode": "dry-run"}), ("hn.json", {"pk": "MONITOR#hn", "mode": "dry-run"})])
def test_a_file_must_be_named_for_its_monitor_and_hold_no_key(tmp_path, name, body):
    (tmp_path / name).write_text(json.dumps({"publications": [], **body}))
    with pytest.raises(ValueError):
        mrc.read_configs(references(), tmp_path)


def test_an_empty_directory_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no router config files"):
        mrc.read_configs(references(), tmp_path)


def test_the_handler_reports_success_and_failure_to_cloudformation(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(mrc, "_respond", lambda event, status, reason, physical_id: sent.append((status, reason)))
    table = Table()
    import boto3

    class Resource:
        def Table(self, name):
            return table

    monkeypatch.setattr(boto3, "resource", lambda service: Resource())
    monkeypatch.setattr(mrc, "aws_lookup", fake_lookup)
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("ROUTER_CONFIG_DIRECTORY", str(DIRECTORY))
    mrc.handler({"RequestType": "Update", "ResourceProperties": {"Substitutions": SUBSTITUTIONS, "ApiIds": API_IDS}}, None)
    mrc.handler({"RequestType": "Delete"}, None)
    assert [status for status, _ in sent] == ["SUCCESS", "SUCCESS"] and len(table.puts) == len(list(DIRECTORY.glob("*.json")))
    monkeypatch.setenv("ROUTER_CONFIG_DIRECTORY", str(tmp_path))
    mrc.handler({"RequestType": "Create", "ResourceProperties": {"Substitutions": SUBSTITUTIONS, "ApiIds": API_IDS}}, None)
    assert sent[-1][0] == "FAILED" and "router config not applied" in sent[-1][1]


def test_the_template_applies_the_files_with_a_role_that_reaches_only_config_writes():
    template = TEMPLATE.read_text()
    assert "CyclotronInvokerRoleArn: !Ref CyclotronInvokerRoleArn" in template and "AccountId: !Ref AWS::AccountId" in template
    assert "Type: Custom::RouterConfig" in template and "papyrus_content.monitoring_router_config.handler" in template
    role = template.split("  RouterConfigApplierRole:")[1].split("  RouterConfigApplierFunction:")[0]
    actions = re.findall(r"- (dynamodb:\w+)", role)
    assert sorted(actions) == ["dynamodb:GetItem", "dynamodb:PutItem"]
    assert sorted(re.findall(r"Action: ((?:ssm|appsync):\w+)", role)) == ["appsync:GetGraphqlApi", "ssm:GetParameter"]


def test_the_router_zip_carries_the_module_and_the_files():
    import importlib.util

    spec = importlib.util.spec_from_file_location("monitoring_build", ROOT / "infra" / "monitoring" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert "monitoring_router_config" in build.ROUTER_ROOTS and build.ROUTER_CONFIG == DIRECTORY


def test_the_hand_seed_script_is_gone():
    assert not (ROOT / "infra" / "monitoring" / "seed_router_config.py").exists()
