import json
from pathlib import Path
import sys

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_monitoring_router_config as t  # noqa: E402
from papyrus_content import monitoring_router_config as mrc  # noqa: E402
from papyrus_content.automations import MonitoringReader  # noqa: E402


@given("the router config files in Git")
def step_files(context):
    context.configs = mrc.read_configs(t.references(), t.DIRECTORY)
    context.table_ = t.Table()


@then("every file passes the router's own validator")
def step_valid(context):
    assert context.configs and len(context.configs) == len(list(t.DIRECTORY.glob("*.json")))


@then("no file holds an AWS account id, an endpoint host or a Cyclotron id, only references")
def step_no_ids(context):
    import re
    assert not any(re.search(r"\d{12}|appsync-api|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}|execute-api", path.read_text()) for path in t.DIRECTORY.glob("*.json"))


@then("every file is named for its monitor")
def step_named(context):
    assert all(path.stem in context.configs for path in t.DIRECTORY.glob("*.json"))


@then("each of the six site publications on the hn router names its model key parameter")
def step_keys(context):
    publications = {p["publicationId"]: p for p in context.configs["hn"]["publications"]}
    assert set(publications) == set(t.SITE_PUBLICATIONS)
    assert all(t.SSM_PARAMETER.fullmatch(p.get("openaiKeyParameter", "")) for p in publications.values())


@when("they are applied to an empty monitoring table")
def step_apply_empty(context):
    context.outcome = mrc.apply(context.table_, context.configs)


@when("they are applied")
def step_apply(context):
    context.outcome = mrc.apply(context.table_, context.configs)


@when("they are applied again")
def step_apply_again(context):
    context.table_.puts.clear()
    context.second = mrc.apply(context.table_, context.configs)


@then("the second apply writes nothing")
def step_idempotent(context):
    assert not context.table_.puts and not context.second["written"] and not context.second["created"]


@then("the automations code finds the Machines on Machines publication with a model key parameter and an endpoint")
def step_automations(context):
    router = MonitoringReader(context.table_).router_config("hn")
    publication = next(p for p in router["publications"] if p["publicationId"] == "machines-on-machines")
    assert publication["openaiKeyParameter"] and publication["appsyncEndpoint"].startswith("https://")


@given("the table holds an hn router config with a field typed by hand")
def step_hand(context):
    context.table_ = t.Table([{**mrc.item_of("hn", context.configs["hn"]), "typedByHand": "x"}])


@then("the hn item equals its file and the hand-typed field is gone")
def step_replaced(context):
    stored = context.table_.items[("MONITOR#hn", "CONFIG#router")]
    assert stored == mrc.item_of("hn", context.configs["hn"]) and "typedByHand" not in stored


@given("the table holds a router config for a monitor that has no file")
def step_other(context):
    context.other = {"pk": "MONITOR#elsewhere", "sk": "CONFIG#router", "mode": "dry-run"}
    context.table_ = t.Table([context.other])


@then("that item is unchanged")
def step_other_unchanged(context):
    assert context.table_.items[("MONITOR#elsewhere", "CONFIG#router")] == context.other


@given("a router config file with a procedure trigger and no model key parameter")
def step_bad_file(context):
    import tempfile

    context.directory = Path(tempfile.mkdtemp())
    (context.directory / "hn.json").write_text(json.dumps({"mode": "live", "publications": [
        {"publicationId": "a", "appsyncEndpoint": "https://x.appsync-api.us-east-1.amazonaws.com/graphql",
         "procedureTriggers": [{"procedureKey": "k.procedure"}]}]}))
    context.table_ = t.Table()


def run_handler(context, directory):
    import boto3, os
    context.sent = []
    original = (mrc._respond, boto3.resource, mrc.aws_lookup)
    mrc._respond = lambda event, status, reason, physical_id: context.sent.append((status, reason))
    boto3.resource = lambda service: type("R", (), {"Table": lambda self, name: context.table_})()
    mrc.aws_lookup = context.lookup
    os.environ["TABLE_NAME"] = "t"
    os.environ["ROUTER_CONFIG_DIRECTORY"] = str(directory)
    try:
        mrc.handler({"RequestType": "Update", "ResourceProperties": {"Substitutions": t.SUBSTITUTIONS, "ApiIds": t.API_IDS}}, None)
    finally:
        mrc._respond, boto3.resource, mrc.aws_lookup = original
        os.environ.pop("ROUTER_CONFIG_DIRECTORY")


@when("the stack deploy applies it")
def step_deploy(context):
    context.lookup = t.fake_lookup
    run_handler(context, context.directory)


@given("the Cyclotron run id parameter does not exist")
def step_missing_parameter(context):
    def lookup(kind, argument):
        if argument.endswith("/run-id"):
            raise KeyError("ParameterNotFound")
        return t.fake_lookup(kind, argument)
    context.lookup = lookup


@when("the stack deploy applies them")
def step_deploy_them(context):
    run_handler(context, t.DIRECTORY)


@then("the custom resource reports failure naming the reference")
def step_failed_reference(context):
    assert context.sent[-1][0] == "FAILED" and "cyclotron/run-id" in context.sent[-1][1]


@then("the custom resource reports failure naming the file")
def step_failed(context):
    assert context.sent[-1][0] == "FAILED" and "hn.json" in context.sent[-1][1]


@then("no router config item is written")
def step_nothing(context):
    assert not context.table_.puts


@given("the monitoring stack template")
def step_template(context):
    context.template = t.TEMPLATE.read_text()


@then("the config applier has its own role that can only get and put items")
def step_role(context):
    role = context.template.split("  RouterConfigApplierRole:")[1].split("  RouterConfigApplierFunction:")[0]
    import re
    assert sorted(re.findall(r"- (dynamodb:\w+)", role)) == ["dynamodb:GetItem", "dynamodb:PutItem"]


@then("the hand seed script no longer exists")
def step_gone(context):
    assert not (t.ROOT / "infra" / "monitoring" / "seed_router_config.py").exists()
