"""stack_deploy.py for a deployment repository's own account-level stacks: --config/root, inline templates, per-stack enabled/fromEnv/fromStackOutput,
adoption of hand-made resources by CloudFormation IMPORT, and the name-server check. Nothing here calls AWS; the cloud is a fake.

The existing config and flow are covered, unchanged, by test_stack_deploy.py; the last tests here only pin that nothing moved.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "infra" / "pipeline"
spec = importlib.util.spec_from_file_location("stack_deploy_account", PIPELINE / "stack_deploy.py")
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)

ACCOUNT = "7" * 12   # a made-up account id, built so no literal id is written down
ZONE_TEMPLATE = """
Parameters:
  DomainName: {Type: String}
Resources:
  HostedZone:
    Type: "AWS::Route53::HostedZone"
    DeletionPolicy: Retain
    Properties: {Name: !Ref DomainName}
"""
BUDGET_TEMPLATE = """
Parameters:
  BudgetName: {Type: String}
  AlertAddress: {Type: String}
Resources:
  MonthlyBudget:
    Type: "AWS::Budgets::Budget"
    DeletionPolicy: Retain
    Properties: {Budget: {BudgetName: !Ref BudgetName}}
"""
CERT_TEMPLATE = """
Parameters:
  HostedZoneId: {Type: String}
Resources:
  Queue: {Type: "AWS::SQS::Queue"}
"""
NS = ["ns-1.awsdns-01.com", "ns-2.awsdns-02.net", "ns-3.awsdns-03.org", "ns-4.awsdns-04.co.uk"]


def change(logical, action="Modify", replacement="False", rtype="AWS::Route53::HostedZone", **extra):
    return {"Type": "Resource", "ResourceChange": {"Action": action, "LogicalResourceId": logical, "ResourceType": rtype, "Replacement": replacement, **extra}}


class AccountCloud:
    """A scripted account: stacks by name, zones, budgets, and change sets that execute instantly. `log` records the order of every call."""
    region = "us-east-1"

    def __init__(self, stacks=None, zones=None, budgets=(), name_servers=None, changes=None):
        self.stacks = {n: dict(s) for n, s in (stacks or {}).items()}
        self.zones, self.budgets, self.ns = zones if zones is not None else {}, set(budgets), name_servers or {}
        self.changes = changes or {}            # change set type (lowercase) -> the Changes it will show
        self.created, self.deleted, self.uploaded, self.log, self.template_reads = [], [], [], [], []
        self.pending = None
        self.clock = 0.0

    def account(self):
        return ACCOUNT

    def describe_stack(self, name):
        return self.stacks.get(name)

    def get_template(self, name):
        self.template_reads.append(name)
        if name == sd.PIPELINE_STACK or name not in self.stacks:
            raise sd.AwsError(f"Stack with id {name} does not exist")
        return ZONE_TEMPLATE

    def list_change_sets(self, name):
        return getattr(self, "existing_change_sets", [])

    def create_change_set(self, stack, name, kind, template_url, parameters, capabilities, tags, role_arn, template_path=None, resources=None):
        self.created.append({"stack": stack, "name": name, "kind": kind, "url": template_url, "parameters": parameters, "capabilities": capabilities,
                             "tags": tags, "role": role_arn, "template_path": template_path, "resources": resources})
        self.log.append(f"create:{kind}")
        self.pending = (stack, name, kind)

    def describe_change_set(self, stack, name):
        kind = self.pending[2]
        executed = self.log and self.log[-1].startswith("execute")
        return {"Status": "CREATE_COMPLETE", "ExecutionStatus": "EXECUTE_COMPLETE" if executed else "AVAILABLE", "Changes": self.changes.get(kind, [])}

    def change_set_events(self, stack, change_set_id):
        return []

    def delete_change_set(self, stack, name):
        self.deleted.append(name)
        self.log.append("delete")

    def execute_change_set(self, stack, name):
        _, _, kind = self.pending
        self.log.append(f"execute:{kind}")
        status = {"create": "CREATE_COMPLETE", "update": "UPDATE_COMPLETE", "import": "IMPORT_COMPLETE"}[kind]
        self.stacks[stack] = {**self.stacks.get(stack, {}), "StackStatus": status, "Parameters": [{"ParameterKey": p["ParameterKey"], "ParameterValue": p.get("ParameterValue", "")} for p in self.created[-1]["parameters"]]}

    def stack_events(self, name):
        return []

    def upload(self, path, bucket, key):
        self.uploaded.append((bucket, key))

    def hosted_zones(self, dns_name):
        return [{"Id": f"/hostedzone/{zid}", "Name": dns_name} for domain, zid in self.zones.items() if domain + "." == dns_name]

    def zone_name_servers(self, zone_id):
        return self.ns[zone_id]

    def budget(self, name):
        return {"BudgetName": name} if name in self.budgets else None

    def sleep(self, seconds):
        self.clock += seconds

    def now(self):
        return self.clock


def stack_cfg(name, template, **extra):
    return {"name": name, "template": template, "capabilities": [], "tags": {"owner": "x"}, "parameters": {}, **extra}


def make(tmp_path, cloud, stacks, allowed=None, env=None, **config):
    for fname, text in {"zone.yaml": ZONE_TEMPLATE, "budget.yaml": BUDGET_TEMPLATE, "cert.yaml": CERT_TEMPLATE}.items():
        (tmp_path / fname).write_text(text)
    cfg = {"region": "us-east-1", "serviceRoleName": "svc", "stacks": stacks, **config}
    messages = []
    ctx = sd.Context(cloud, cfg, allowed or [], "sha-1-1", root=tmp_path, out=messages.append, poll=10, start_grace=60, execute_timeout=600, env=env or {})
    ctx.messages = messages
    return ctx


ZONE_IMPORT = {"logicalId": "HostedZone", "resourceType": "AWS::Route53::HostedZone", "lookup": {"kind": "hostedZoneByName", "name": "example.test"}, "identifierKey": "HostedZoneId"}
ZONE = stack_cfg("acct-dns", "zone.yaml", parameters={"DomainName": "example.test"}, **{"import": ZONE_IMPORT})
BUDGET = stack_cfg("acct-budget", "budget.yaml", parameters={"BudgetName": "monthly", "AlertAddress": {"fromEnv": "ALERT_TO"}}, capabilities=["CAPABILITY_IAM"],
                   **{"import": {"logicalId": "MonthlyBudget", "resourceType": "AWS::Budgets::Budget", "lookup": {"kind": "budgetByName", "name": "monthly"}, "identifierKey": "Id"}})


# --- config loading: --config, root, papyrus: --------------------------------------------------------------------------------------------


def test_root_is_relative_to_the_config_file_and_absent_means_the_papyrus_repository(tmp_path):
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "stacks.json").write_text(json.dumps({"region": "r", "root": "..", "stacks": []}))
    config, root = sd.load_config(tmp_path / "infra" / "stacks.json")
    assert root == tmp_path.resolve()
    (tmp_path / "infra" / "plain.json").write_text(json.dumps({"region": "r", "stacks": []}))
    assert sd.load_config(tmp_path / "infra" / "plain.json")[1] == sd.ROOT


def test_a_template_resolves_under_the_root_and_papyrus_prefix_resolves_in_the_papyrus_repository(tmp_path):
    ctx = make(tmp_path, AccountCloud(), [])
    assert sd.template_file(ctx, {"template": "stacks/dns.yaml"}) == tmp_path / "stacks" / "dns.yaml"
    assert sd.template_file(ctx, {"template": "papyrus:infra/newsletter/papyrus-newsletter-sending.yaml"}) == sd.ROOT / "infra" / "newsletter" / "papyrus-newsletter-sending.yaml"


def test_a_papyrus_provided_template_deploys_from_a_deployment_repository(tmp_path):
    cloud = AccountCloud()
    ctx = make(tmp_path, cloud, [])
    cfg = stack_cfg("acct-q", "papyrus:procedures/newsroom/tests/test_account_stacks.py")   # any existing file is enough to prove which tree is read
    with pytest.raises(Exception) as caught:   # not a YAML template, but it must have been read from the Papyrus tree and not from tmp_path
        sd.deploy_stack(ctx, cfg)
    assert not isinstance(caught.value, FileNotFoundError)


def write_repo(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.test", *a], check=True, capture_output=True)
    return run


def test_scope_with_config_diffs_relative_to_root_skips_disabled_stacks(tmp_path, monkeypatch):
    run = write_repo(tmp_path, {"README": "x"})
    run("init", "-q", "-b", "main")
    run("add", "."), run("commit", "-qm", "one")
    config = {"region": "r", "root": "..", "stacks": [
        {"name": "dns", "template": "stacks/dns.yaml", "paths": ["stacks/dns.yaml"]},
        {"name": "cert", "template": "stacks/cert.yaml", "paths": ["stacks/cert.yaml"], "enabled": False, "reason": "waits for delegation"},
        {"name": "ses", "template": "stacks/ses.yaml", "paths": ["stacks/ses.yaml"]}]}
    write_repo(tmp_path, {"infra/stacks.json": json.dumps(config), "stacks/dns.yaml": "a", "stacks/cert.yaml": "b"})
    run("add", "."), run("commit", "-qm", "two")
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert sd.main(["scope", "--config", str(tmp_path / "infra" / "stacks.json"), "--base", "HEAD~1", "--head", "HEAD"]) == 0
    assert "stacks=dns\n" in out.read_text() and "deploy=true" in out.read_text()
    # A base git cannot resolve puts every ENABLED stack in scope.
    out.write_text("")
    sd.main(["scope", "--config", str(tmp_path / "infra" / "stacks.json"), "--base", "nope", "--head", "HEAD"])
    assert "stacks=dns,ses\n" in out.read_text()


def test_scope_in_a_subdirectory_checkout_names_paths_relative_to_the_root(tmp_path, monkeypatch):
    """The repository is the parent of the root; changed files are named relative to the root, as the stack paths are."""
    run = write_repo(tmp_path, {"README": "x"})
    run("init", "-q", "-b", "main")
    run("add", "."), run("commit", "-qm", "one")
    sub = tmp_path / "deploy"
    config = {"region": "r", "stacks": [{"name": "dns", "template": "dns.yaml", "paths": ["dns.yaml"]}]}
    write_repo(tmp_path, {"deploy/stacks.json": json.dumps({**config, "root": "."}), "deploy/dns.yaml": "a", "other.txt": "b"})
    run("add", "."), run("commit", "-qm", "two")
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    sd.main(["scope", "--config", str(sub / "stacks.json"), "--base", "HEAD~1", "--head", "HEAD"])
    assert "stacks=dns\n" in out.read_text()


def test_allowed_changes_default_sits_next_to_the_config_and_allowed_overrides_it(tmp_path, monkeypatch, capsys):
    cloud = AccountCloud(zones={})
    monkeypatch.setattr(sd, "AwsCli", lambda region: cloud)
    monkeypatch.setenv("AWS_ACCOUNT_ID", ACCOUNT)
    (tmp_path / "zone.yaml").write_text(ZONE_TEMPLATE)
    (tmp_path / "stacks.json").write_text(json.dumps({"region": "r", "serviceRoleName": "svc", "pipelineCheck": False, "root": ".", "stacks": [ZONE]}))
    with pytest.raises(FileNotFoundError):   # next to the config, and there is none
        sd.main(["plan", "--config", str(tmp_path / "stacks.json")])
    (tmp_path / "elsewhere.json").write_text(json.dumps({"allowed": []}))
    assert sd.main(["plan", "--config", str(tmp_path / "stacks.json"), "--allowed", str(tmp_path / "elsewhere.json")]) == 0
    (tmp_path / "allowed-changes.json").write_text(json.dumps({"allowed": []}))
    assert sd.main(["plan", "--config", str(tmp_path / "stacks.json")]) == 0


# --- disabled stacks ----------------------------------------------------------------------------------------------------------------------


def test_a_disabled_stack_needs_a_reason():
    with pytest.raises(sd.Stop, match="non-empty reason"):
        sd.validate_config({"stacks": [{"name": "a", "enabled": False}]})
    with pytest.raises(sd.Stop, match="non-empty reason"):
        sd.validate_config({"stacks": [{"name": "a", "enabled": False, "reason": "  "}]})
    sd.validate_config({"stacks": [{"name": "a", "enabled": False, "reason": "waits for the registrar"}, {"name": "b"}]})


def test_a_stack_output_reference_must_point_at_an_earlier_stack():
    ref = {"HostedZoneId": {"fromStackOutput": {"stack": "dns", "output": "ZoneId"}}}
    sd.validate_config({"stacks": [{"name": "dns"}, {"name": "cert", "parameters": ref}]})
    with pytest.raises(sd.Stop, match="earlier"):
        sd.validate_config({"stacks": [{"name": "cert", "parameters": ref}, {"name": "dns"}]})


def test_disabled_stacks_are_left_out_of_plan_and_deploy(tmp_path, monkeypatch):
    cloud = AccountCloud(zones={})
    monkeypatch.setattr(sd, "AwsCli", lambda region: cloud)
    monkeypatch.setenv("AWS_ACCOUNT_ID", ACCOUNT)
    off = {**stack_cfg("acct-off", "cert.yaml"), "enabled": False, "reason": "not yet"}
    (tmp_path / "zone.yaml").write_text(ZONE_TEMPLATE)
    (tmp_path / "cert.yaml").write_text(CERT_TEMPLATE)
    (tmp_path / "allowed-changes.json").write_text(json.dumps({"allowed": []}))
    (tmp_path / "stacks.json").write_text(json.dumps({"region": "r", "serviceRoleName": "svc", "pipelineCheck": False, "root": ".", "stacks": [off, stack_cfg("acct-dns", "zone.yaml", parameters={"DomainName": "example.test"})]}))
    cloud.changes = {"create": []}
    assert sd.main(["plan", "--config", str(tmp_path / "stacks.json")]) == 0
    assert sd.main(["deploy", "--config", str(tmp_path / "stacks.json")]) == 0
    assert [c["stack"] for c in cloud.created] == ["acct-dns"]
    assert sd.selected({"stacks": [off, ZONE]}, None) == [ZONE]
    assert sd.selected({"stacks": [off, ZONE]}, ["acct-off"]) == []   # asked for by name, still skipped
    with pytest.raises(sd.Stop, match="unknown stack"):
        sd.selected({"stacks": [off, ZONE]}, ["nope"])


# --- pipelineCheck and changeSetPrefix ----------------------------------------------------------------------------------------------------


def run_main(tmp_path, monkeypatch, cloud, command, stacks, **config):
    monkeypatch.setattr(sd, "AwsCli", lambda region: cloud)
    monkeypatch.setenv("AWS_ACCOUNT_ID", ACCOUNT)
    for fname, text in {"zone.yaml": ZONE_TEMPLATE, "budget.yaml": BUDGET_TEMPLATE, "cert.yaml": CERT_TEMPLATE}.items():
        (tmp_path / fname).write_text(text)
    (tmp_path / "allowed-changes.json").write_text(json.dumps({"allowed": config.pop("allowedList", [])}))
    (tmp_path / "stacks.json").write_text(json.dumps({"region": "r", "serviceRoleName": "svc", "root": ".", "stacks": stacks, **config}))
    return sd.main([command, "--config", str(tmp_path / "stacks.json")])


def test_pipeline_check_false_never_reads_the_pipeline_stack_and_the_default_does(tmp_path, monkeypatch):
    cloud = AccountCloud()
    run_main(tmp_path, monkeypatch, cloud, "plan", [ZONE], pipelineCheck=False)
    assert cloud.template_reads == []
    run_main(tmp_path, monkeypatch, cloud, "plan", [ZONE])
    assert cloud.template_reads == [sd.PIPELINE_STACK]


def test_change_set_prefix_names_the_change_set_and_scopes_stale_cleanup(tmp_path):
    cloud = AccountCloud(stacks={"acct-dns": {"StackStatus": "UPDATE_COMPLETE", "Parameters": []}}, changes={"update": []})
    cloud.existing_change_sets = [{"ChangeSetName": "acct-old", "ExecutionStatus": "AVAILABLE"}, {"ChangeSetName": "papyrus-release-x", "ExecutionStatus": "AVAILABLE"},
                                  {"ChangeSetName": "acct-run", "ExecutionStatus": "EXECUTE_COMPLETE"}]
    ctx = make(tmp_path, cloud, [ZONE], changeSetPrefix="acct-")
    sd.deploy_stack(ctx, ZONE)
    assert cloud.deleted[0] == "acct-old" and "papyrus-release-x" not in cloud.deleted and "acct-run" not in cloud.deleted
    assert cloud.created[0]["name"] == "acct-sha-1-1"


# --- parameters: fromEnv and fromStackOutput ----------------------------------------------------------------------------------------------


def test_from_env_unset_or_empty_stops_a_deploy_before_anything_is_created(tmp_path):
    for env in ({}, {"ALERT_TO": ""}):
        cloud = AccountCloud()
        with pytest.raises(sd.Stop, match="ALERT_TO"):
            sd.deploy_stack(make(tmp_path, cloud, [BUDGET], env=env), BUDGET)
        assert cloud.created == [] and cloud.log == []


def test_from_env_is_passed_as_the_parameter_value(tmp_path):
    cloud = AccountCloud(changes={"create": []})
    sd.deploy_stack(make(tmp_path, cloud, [BUDGET], env={"ALERT_TO": "ops-box"}), BUDGET)
    assert {"ParameterKey": "AlertAddress", "ParameterValue": "ops-box"} in cloud.created[0]["parameters"]


def test_from_env_unset_is_shown_in_plan_without_failing(tmp_path):
    cloud = AccountCloud()
    ctx = make(tmp_path, cloud, [BUDGET], env={})
    sd.plan_stack(ctx, BUDGET)
    text = "\n".join(ctx.messages)
    assert "ALERT_TO" in text and "unset" in text and ctx.failed_checks == []


CERT = stack_cfg("acct-cert", "cert.yaml", parameters={"HostedZoneId": {"fromStackOutput": {"stack": "acct-dns", "output": "ZoneId"}}})


def test_from_stack_output_reads_the_output_of_an_earlier_stack(tmp_path):
    dns = {"StackStatus": "CREATE_COMPLETE", "Parameters": [], "Outputs": [{"OutputKey": "Other", "OutputValue": "no"}, {"OutputKey": "ZoneId", "OutputValue": "Z123"}]}
    cloud = AccountCloud(stacks={"acct-dns": dns}, changes={"create": []})
    sd.deploy_stack(make(tmp_path, cloud, [ZONE, CERT]), CERT)
    assert {"ParameterKey": "HostedZoneId", "ParameterValue": "Z123"} in cloud.created[0]["parameters"]


def test_from_stack_output_missing_stack_or_output_stops_a_deploy(tmp_path):
    with pytest.raises(sd.Stop, match="does not exist"):
        sd.deploy_stack(make(tmp_path, AccountCloud(), [ZONE, CERT]), CERT)
    no_output = AccountCloud(stacks={"acct-dns": {"StackStatus": "CREATE_COMPLETE", "Parameters": [], "Outputs": []}})
    with pytest.raises(sd.Stop, match="no such output"):
        sd.deploy_stack(make(tmp_path, no_output, [ZONE, CERT]), CERT)


def test_plan_says_when_the_stack_a_parameter_reads_does_not_exist_yet(tmp_path):
    ctx = make(tmp_path, AccountCloud(), [ZONE, CERT])
    sd.plan_stack(ctx, CERT)
    assert "acct-dns" in "\n".join(ctx.messages) and "does not exist yet" in "\n".join(ctx.messages)


# --- inline templates ---------------------------------------------------------------------------------------------------------------------


def test_without_a_template_bucket_the_template_goes_inline_and_nothing_touches_s3(tmp_path):
    cloud = AccountCloud(changes={"create": []})
    ctx = make(tmp_path, cloud, [CERT], env={})
    sd.deploy_stack(ctx, stack_cfg("acct-cert", "cert.yaml", parameters={"HostedZoneId": "Z9"}))
    call = cloud.created[0]
    assert cloud.uploaded == [] and call["url"] is None and call["template_path"] == tmp_path / "cert.yaml"
    assert call["role"] == f"arn:aws:iam::{ACCOUNT}:role/svc" and call["kind"] == "create" and call["tags"] == {"owner": "x"}


def test_an_inline_template_of_51200_bytes_or_more_is_refused(tmp_path):
    cloud = AccountCloud()
    ctx = make(tmp_path, cloud, [CERT])
    (tmp_path / "cert.yaml").write_text(CERT_TEMPLATE + "# " + "x" * (sd.INLINE_TEMPLATE_LIMIT - len(CERT_TEMPLATE)) + "\n")
    with pytest.raises(sd.Stop, match="inline template must be under"):
        sd.deploy_stack(ctx, stack_cfg("acct-cert", "cert.yaml", parameters={"HostedZoneId": "Z9"}))
    assert cloud.created == []
    (tmp_path / "cert.yaml").write_text(CERT_TEMPLATE + "# " + "x" * (sd.INLINE_TEMPLATE_LIMIT - len(CERT_TEMPLATE) - 10) + "\n")
    sd.deploy_stack(ctx, stack_cfg("acct-cert", "cert.yaml", parameters={"HostedZoneId": "Z9"}))
    assert len(cloud.created) == 1


def test_builds_need_a_template_bucket(tmp_path):
    with pytest.raises(sd.Stop, match="templateBucketFrom"):
        sd.deploy_stack(make(tmp_path, AccountCloud(), [CERT]), {**stack_cfg("acct-cert", "cert.yaml"), "builds": [{"parameter": "CodeKey", "script": "x.py"}]})


# --- IMPORT -------------------------------------------------------------------------------------------------------------------------------


def import_cloud(**kw):
    return AccountCloud(zones={"example.test": "ZONE1"}, changes={"import": [change("HostedZone", "Import")], "update": [change("HostedZone", "Modify")]}, **kw)


def test_a_hand_made_zone_is_imported_then_updated(tmp_path):
    cloud = import_cloud()
    ctx = make(tmp_path, cloud, [ZONE])
    assert sd.deploy_stack(ctx, ZONE) == "deployed"
    imp, upd = cloud.created
    assert imp["kind"] == "import" and imp["tags"] == {"owner": "x"}   # tags are the stack's own config; see below for what the CLI sends
    assert imp["resources"] == [{"ResourceType": "AWS::Route53::HostedZone", "LogicalResourceId": "HostedZone", "ResourceIdentifier": {"HostedZoneId": "ZONE1"}}]
    assert imp["name"].endswith("-import") and imp["template_path"] == tmp_path / "zone.yaml"
    assert upd["kind"] == "update" and upd["resources"] is None and not upd["name"].endswith("-import")
    assert cloud.log == ["create:import", "execute:import", "create:update", "execute:update"]
    assert cloud.stacks["acct-dns"]["StackStatus"] == "UPDATE_COMPLETE"


def test_a_stack_left_in_review_in_progress_is_still_imported_never_created(tmp_path):
    """A first run whose change set failed to create leaves an empty REVIEW_IN_PROGRESS stack; creating a zone then would make a second zone."""
    cloud = import_cloud()
    cloud.stacks["acct-dns"] = {"StackStatus": "REVIEW_IN_PROGRESS", "Parameters": []}
    ctx = make(tmp_path, cloud, [ZONE])
    sd.deploy_stack(ctx, ZONE)
    assert [c["kind"] for c in cloud.created][0] == "import"
    assert "create" not in [c["kind"] for c in cloud.created]


def test_the_zone_id_is_the_bare_id_without_the_hostedzone_prefix(tmp_path):
    cloud = import_cloud()
    assert sd.find_import(make(tmp_path, cloud, [ZONE]), ZONE_IMPORT) == "ZONE1"


def test_import_complete_is_a_success_and_an_updatable_state():
    assert "IMPORT_COMPLETE" in sd.SUCCESS and "IMPORT_COMPLETE" in sd.UPDATABLE
    assert sd.classify_stack({"StackStatus": "IMPORT_COMPLETE"}) == ("update", "IMPORT_COMPLETE")


def test_an_import_change_set_that_would_do_anything_but_import_is_deleted_and_nothing_runs(tmp_path):
    cloud = import_cloud()
    cloud.changes["import"] = [change("HostedZone", "Import"), change("Extra", "Add", rtype="AWS::SQS::Queue")]
    with pytest.raises(sd.Stop, match="Extra"):
        sd.deploy_stack(make(tmp_path, cloud, [ZONE]), ZONE)
    assert cloud.log == ["create:import", "delete"] and len(cloud.created) == 1


@pytest.mark.parametrize("action", ["Modify", "Remove", "Dynamic"])
def test_every_non_import_action_is_a_violation(action):
    violations, lines = sd.review_changes("s", [change("R", action)], [], importing=True)
    assert violations and "NOT ALLOWED" in lines[0]


def test_an_import_change_may_do_more_only_when_allowed_changes_lists_it(tmp_path):
    cloud = import_cloud()
    cloud.changes["import"] = [change("HostedZone", "Import"), change("Extra", "Add", rtype="AWS::SQS::Queue")]
    allowed = [{"stack": "acct-dns", "logicalId": "Extra", "change": "Add", "reason": "on purpose"}]
    assert sd.deploy_stack(make(tmp_path, cloud, [ZONE], allowed=allowed), ZONE) == "deployed"
    assert cloud.log[:2] == ["create:import", "execute:import"]


def test_the_follow_up_update_keeps_the_remove_and_replace_safety(tmp_path):
    cloud = import_cloud()
    cloud.changes["update"] = [change("HostedZone", "Modify", replacement="True")]
    with pytest.raises(sd.Stop, match="Replaced"):
        sd.deploy_stack(make(tmp_path, cloud, [ZONE]), ZONE)
    # The import ran (it only adopts); the replacement was refused and its change set deleted unexecuted.
    assert cloud.log == ["create:import", "execute:import", "create:update", "delete"]


def test_an_existing_stack_never_looks_up_or_imports(tmp_path):
    cloud = import_cloud(stacks={"acct-dns": {"StackStatus": "UPDATE_COMPLETE", "Parameters": []}})
    cloud.hosted_zones = lambda name: pytest.fail("looked up a zone for a stack that exists")
    sd.deploy_stack(make(tmp_path, cloud, [ZONE]), ZONE)
    assert [c["kind"] for c in cloud.created] == ["update"]


def test_a_missing_resource_means_a_normal_create_with_tags(tmp_path):
    cloud = AccountCloud(changes={"create": [change("HostedZone", "Add")]})
    assert sd.deploy_stack(make(tmp_path, cloud, [ZONE]), ZONE) == "deployed"
    assert [c["kind"] for c in cloud.created] == ["create"] and cloud.created[0]["resources"] is None and cloud.created[0]["tags"] == {"owner": "x"}


def test_two_public_zones_with_the_name_stop_the_deploy(tmp_path):
    cloud = import_cloud()
    cloud.hosted_zones = lambda name: [{"Id": "/hostedzone/A", "Name": name}, {"Id": "/hostedzone/B", "Name": name}]
    with pytest.raises(sd.Stop, match="at most one"):
        sd.deploy_stack(make(tmp_path, cloud, [ZONE]), ZONE)
    assert cloud.created == []


def test_a_hand_made_budget_is_found_by_name_and_imported_with_its_name_as_identifier(tmp_path):
    cloud = AccountCloud(budgets={"monthly"}, changes={"import": [change("MonthlyBudget", "Import", rtype="AWS::Budgets::Budget")], "update": []})
    ctx = make(tmp_path, cloud, [BUDGET], env={"ALERT_TO": "ops-box"})
    sd.deploy_stack(ctx, BUDGET)
    imp = cloud.created[0]
    assert imp["kind"] == "import" and imp["capabilities"] == ["CAPABILITY_IAM"]
    assert imp["resources"] == [{"ResourceType": "AWS::Budgets::Budget", "LogicalResourceId": "MonthlyBudget", "ResourceIdentifier": {"Id": "monthly"}}]


def test_no_such_budget_means_create(tmp_path):
    cloud = AccountCloud(budgets={"another"}, changes={"create": []})
    sd.deploy_stack(make(tmp_path, cloud, [BUDGET], env={"ALERT_TO": "ops-box"}), BUDGET)
    assert cloud.created[0]["kind"] == "create"


def test_plan_says_import_or_create_from_a_read_only_lookup(tmp_path):
    found = import_cloud()
    ctx = make(tmp_path, found, [ZONE])
    sd.plan_stack(ctx, ZONE)
    assert "would IMPORT the existing AWS::Route53::HostedZone (read-only lookup found it)" in "\n".join(ctx.messages)
    assert found.created == [] and found.log == []
    empty = AccountCloud()
    ctx = make(tmp_path, empty, [ZONE])
    sd.plan_stack(ctx, ZONE)
    assert "would CREATE (no existing resource found)" in "\n".join(ctx.messages)


# --- the name-server check ----------------------------------------------------------------------------------------------------------------


CHECK = {"kind": "nameservers", "zone": "example.test", "expectedFile": "expected-nameservers.json"}
ZONE_CHECKED = {**ZONE, "checks": [CHECK]}


def checked_cloud(live, expected=NS, tmp_path=None):
    (tmp_path / "expected-nameservers.json").write_text(json.dumps({"example.test": expected}))
    return AccountCloud(stacks={"acct-dns": {"StackStatus": "UPDATE_COMPLETE", "Parameters": []}}, zones={"example.test": "ZONE1"}, name_servers={"ZONE1": live}, changes={"update": []})


def test_matching_name_servers_pass_a_deploy(tmp_path):
    cloud = checked_cloud(NS, tmp_path=tmp_path)
    ctx = make(tmp_path, cloud, [ZONE_CHECKED])
    sd.deploy_stack(ctx, ZONE_CHECKED)
    assert any("check passed" in m for m in ctx.messages)


def test_case_and_trailing_dots_do_not_matter(tmp_path):
    live = [h.upper() + "." for h in NS]
    cloud = checked_cloud(live, expected=[" " + h for h in reversed(NS)], tmp_path=tmp_path)
    sd.deploy_stack(make(tmp_path, cloud, [ZONE_CHECKED]), ZONE_CHECKED)
    assert sd.normalise_hosts(["Ns-1.Example.COM."]) == {"ns-1.example.com"}


def test_different_name_servers_fail_the_deploy_and_print_both_sets(tmp_path):
    other = NS[:3] + ["ns-9.awsdns-09.com"]
    cloud = checked_cloud(other, tmp_path=tmp_path)
    with pytest.raises(sd.Failed) as caught:
        sd.deploy_stack(make(tmp_path, cloud, [ZONE_CHECKED]), ZONE_CHECKED)
    text = str(caught.value)
    assert "ns-9.awsdns-09.com" in text and NS[3] in text and "live" in text and "expected" in text


def test_a_failed_check_makes_main_exit_1(tmp_path, monkeypatch):
    cloud = checked_cloud(NS[:3] + ["ns-9.awsdns-09.com"], tmp_path=tmp_path)
    assert run_main(tmp_path, monkeypatch, cloud, "deploy", [ZONE_CHECKED], pipelineCheck=False) == 1


def test_plan_shows_pass_and_exits_zero_or_shows_fail_and_exits_one(tmp_path, monkeypatch, capsys):
    good = checked_cloud(NS, tmp_path=tmp_path)
    assert run_main(tmp_path, monkeypatch, good, "plan", [ZONE_CHECKED], pipelineCheck=False) == 0
    assert "Check nameservers example.test: PASS" in capsys.readouterr().out
    bad = checked_cloud(NS[:3] + ["ns-9.awsdns-09.com"], tmp_path=tmp_path)
    assert run_main(tmp_path, monkeypatch, bad, "plan", [ZONE_CHECKED], pipelineCheck=False) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "ns-9.awsdns-09.com" in out


def test_plan_skips_the_check_when_the_zone_does_not_exist_yet(tmp_path):
    (tmp_path / "expected-nameservers.json").write_text(json.dumps({"example.test": NS}))
    ctx = make(tmp_path, AccountCloud(), [ZONE_CHECKED])
    sd.plan_stack(ctx, ZONE_CHECKED)
    assert "skipped" in "\n".join(ctx.messages) and ctx.failed_checks == []


def test_expected_file_is_read_relative_to_the_config_directory_not_the_root(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "expected-nameservers.json").write_text(json.dumps({"example.test": NS}))
    cloud = AccountCloud(zones={"example.test": "ZONE1"}, name_servers={"ZONE1": NS})
    ctx = make(tmp_path, cloud, [ZONE_CHECKED])
    ctx.config_dir = tmp_path / "cfg"
    assert sd.nameserver_check(ctx, CHECK)[0] is True


# --- AwsCli command lines (a fake runner) -------------------------------------------------------------------------------------------------


def cli(stdout="{}", returncode=0, stderr=""):
    calls = []

    def run(args, **kw):
        calls.append(args)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return sd.AwsCli("us-east-1", run=run), calls


def test_the_url_flow_command_is_unchanged():
    aws, calls = cli()
    aws.create_change_set("s", "cs", "create", "https://b.s3/x.yaml", [], ["CAPABILITY_IAM"], {"k": "v"}, "arn")
    args = calls[0]
    assert "--template-url" in args and "--template-body" not in args and "--resources-to-import" not in args
    assert args[args.index("--tags") + 1] == "Key=k,Value=v" and args[args.index("--change-set-type") + 1] == "CREATE"


def test_inline_flow_passes_the_file_as_template_body():
    aws, calls = cli()
    aws.create_change_set("s", "cs", "update", None, [], [], {}, "arn", template_path=Path("/x/t.yaml"))
    args = calls[0]
    assert args[args.index("--template-body") + 1] == "file:///x/t.yaml" and "--template-url" not in args


def test_import_command_has_resources_capabilities_and_no_tags():
    aws, calls = cli()
    resources = [{"ResourceType": "T", "LogicalResourceId": "L", "ResourceIdentifier": {"Id": "i"}}]
    aws.create_change_set("s", "cs", "import", None, [], ["CAPABILITY_IAM"], {"k": "v"}, "arn", template_path=Path("/x/t.yaml"), resources=resources)
    args = calls[0]
    assert args[args.index("--change-set-type") + 1] == "IMPORT" and json.loads(args[args.index("--resources-to-import") + 1]) == resources
    assert "--tags" not in args and "CAPABILITY_IAM" in args


def test_budget_lookup_and_zone_name_servers_use_read_only_calls():
    aws, calls = cli(json.dumps({"Account": ACCOUNT, "Budget": {"BudgetName": "monthly"}}))
    assert aws.budget("monthly") == {"BudgetName": "monthly"}
    describe = calls[-1]
    assert describe[:3] == ["aws", "budgets", "describe-budget"] and describe[describe.index("--budget-name") + 1] == "monthly"
    missing, _ = cli(stdout="", returncode=254, stderr="An error occurred (NotFoundException) when calling the DescribeBudget operation")
    missing.account = lambda: ACCOUNT
    assert missing.budget("monthly") is None
    denied, _ = cli(stdout="", returncode=254, stderr="AccessDeniedException")
    denied.account = lambda: ACCOUNT
    with pytest.raises(sd.AwsError):
        denied.budget("monthly")
    ns, calls = cli(json.dumps({"DelegationSet": {"NameServers": NS}}))
    assert ns.zone_name_servers("ZONE1") == NS and calls[0][:3] == ["aws", "route53", "get-hosted-zone"] and calls[0][calls[0].index("--id") + 1] == "ZONE1"


# --- nothing changes for the existing config ----------------------------------------------------------------------------------------------


def test_the_default_config_and_its_allowed_file_are_the_ones_beside_the_script():
    assert sd.CONFIG_PATH == PIPELINE / "stacks.json" and sd.ALLOWED_PATH == PIPELINE / "allowed-changes.json"
    config, root = sd.load_config(sd.CONFIG_PATH)
    assert root == sd.ROOT and config == json.loads((PIPELINE / "stacks.json").read_text())
    assert (sd.CONFIG_PATH.parent / "allowed-changes.json") == sd.ALLOWED_PATH
    assert not any(key in config for key in ("root", "pipelineCheck", "changeSetPrefix")) and "templateBucketFrom" in config
    assert all(s.get("enabled", True) and "import" not in s and "checks" not in s for s in config["stacks"])


def test_the_default_config_keeps_the_defaults_for_the_new_keys(tmp_path):
    config, _ = sd.load_config(sd.CONFIG_PATH)
    ctx = make(tmp_path, AccountCloud(), config["stacks"], templateBucketFrom=config["templateBucketFrom"])
    assert ctx.prefix == sd.CHANGE_SET_PREFIX == "papyrus-release-" and ctx.inline is False
    assert sd.selected(config, None) == config["stacks"]
    assert sd.changed_stacks(config, ["infra/pipeline/stacks.json"]) == [s["name"] for s in config["stacks"]]
    for stack in config["stacks"]:
        assert sd.template_file(ctx, stack) == tmp_path / stack["template"]   # relative templates still resolve under the context root


def test_an_ordinary_change_set_is_still_reviewed_the_old_way():
    changes = [change("A", "Remove"), change("B", "Modify", replacement="True")]
    violations, lines = sd.review_changes("s", changes, [])
    assert len(violations) == 2 and sd.review_changes("s", [change("I", "Import")], []) == ([], ["| Import | `I` | AWS::Route53::HostedZone | False |"])


# --- serviceRoleName per stack, groups, and `changed` -------------------------------------------------------------------------------------


def test_a_stack_service_role_overrides_the_config_one(tmp_path):
    cloud = AccountCloud(changes={"create": []})
    sd.deploy_stack(make(tmp_path, cloud, [CERT]), stack_cfg("acct-cert", "cert.yaml", parameters={"HostedZoneId": "Z9"}, serviceRoleName="roles-svc"))
    assert cloud.created[0]["role"] == f"arn:aws:iam::{ACCOUNT}:role/roles-svc"
    sd.deploy_stack(make(tmp_path, cloud, [CERT]), stack_cfg("acct-two", "cert.yaml", parameters={"HostedZoneId": "Z9"}))
    assert cloud.created[1]["role"] == f"arn:aws:iam::{ACCOUNT}:role/svc"


def test_group_selection_defaults_to_default_and_explicit_stacks_must_belong(tmp_path):
    a, b = stack_cfg("a", "zone.yaml"), stack_cfg("b", "zone.yaml", group="roles")
    config = {"stacks": [a, b]}
    assert sd.selected(config, None, "default") == [a] and sd.selected(config, None, "roles") == [b]
    assert sd.selected(config, None) == [a, b]
    assert sd.selected(config, ["b"], "roles") == [b]
    with pytest.raises(sd.Stop, match="not in group default"):
        sd.selected(config, ["b"], "default")


def test_plan_and_deploy_take_a_group(tmp_path, monkeypatch):
    cloud = AccountCloud(changes={"create": []})
    stacks = [stack_cfg("acct-a", "cert.yaml", parameters={"HostedZoneId": "Z"}), stack_cfg("acct-b", "cert.yaml", parameters={"HostedZoneId": "Z"}, group="roles")]
    run_main(tmp_path, monkeypatch, cloud, "deploy", stacks, pipelineCheck=False)
    assert [c["stack"] for c in cloud.created] == ["acct-a"]
    monkeypatch.setattr(sd, "AwsCli", lambda region: cloud)
    assert sd.main(["deploy", "--config", str(tmp_path / "stacks.json"), "--group", "roles"]) == 0
    assert [c["stack"] for c in cloud.created] == ["acct-a", "acct-b"]
    assert sd.main(["deploy", "--config", str(tmp_path / "stacks.json"), "--group", "roles", "--stack", "acct-a"]) == 2


def changed_cloud(tmp_path, template=CERT_TEMPLATE, params=None):
    class Cloud(AccountCloud):
        def get_template(self, name):
            return template
    return Cloud(stacks={"acct-cert": {"StackStatus": "UPDATE_COMPLETE", "Parameters": [{"ParameterKey": k, "ParameterValue": v} for k, v in (params or {"HostedZoneId": "Z9"}).items()]}})


def test_changed_compares_template_and_parameters_and_writes_the_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    cfg = stack_cfg("acct-cert", "cert.yaml", parameters={"HostedZoneId": "Z9"})
    assert run_main(tmp_path, monkeypatch, changed_cloud(tmp_path), "changed", [cfg], pipelineCheck=False) == 0
    assert "acct-cert: unchanged" in capsys.readouterr().out and out.read_text() == "changed=false\n"
    out.write_text("")
    assert run_main(tmp_path, monkeypatch, changed_cloud(tmp_path, template=CERT_TEMPLATE + "# x\n"), "changed", [cfg], pipelineCheck=False) == 0
    assert "template differs" in capsys.readouterr().out and out.read_text() == "changed=true\n"
    out.write_text("")
    assert run_main(tmp_path, monkeypatch, changed_cloud(tmp_path, params={"HostedZoneId": "Z1"}), "changed", [cfg], pipelineCheck=False) == 0
    assert "parameter HostedZoneId differs" in capsys.readouterr().out and out.read_text() == "changed=true\n"


def test_changed_ignores_noecho_values_unresolved_env_disabled_stacks_and_other_groups(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("ALERT_TO", raising=False)
    cfg = stack_cfg("acct-cert", "cert.yaml", parameters={"HostedZoneId": "Z9", "Other": {"fromEnv": "ALERT_TO"}})
    noecho = changed_cloud(tmp_path, params={"HostedZoneId": "****", "Other": "x"})
    other = {**stack_cfg("acct-x", "cert.yaml"), "group": "roles"}
    off = {**stack_cfg("acct-y", "cert.yaml"), "enabled": False, "reason": "later"}
    assert run_main(tmp_path, monkeypatch, noecho, "changed", [cfg, other, off], pipelineCheck=False) == 0
    out_text = capsys.readouterr().out
    assert "acct-x" not in out_text and "acct-y" not in out_text and out.read_text() == "changed=false\n"


def test_changed_counts_a_missing_stack_as_changed_and_still_exits_zero(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert run_main(tmp_path, monkeypatch, AccountCloud(), "changed", [stack_cfg("acct-cert", "cert.yaml")], pipelineCheck=False) == 0
    assert "does not exist" in capsys.readouterr().out and out.read_text() == "changed=true\n"
    assert AccountCloud().created == []


def test_default_group_and_role_leave_the_existing_config_alone():
    config, _ = sd.load_config(sd.CONFIG_PATH)
    assert sd.selected(config, None, "default") == config["stacks"] == sd.selected(config, None)
    assert all("group" not in s and "serviceRoleName" not in s for s in config["stacks"])


# ---------------------------------------------------------------------------------------------------------- the shipped account templates


import re  # noqa: E402

import yaml  # noqa: E402

ACCOUNT_DIR = ROOT / "infra" / "account"


def test_account_templates_are_generic_and_carry_no_ids():
    """The account baseline and stacks are for any deployment: no Anthus repository or domain, no account ids, no emails."""
    files = [ACCOUNT_DIR / "baseline.yaml", *sorted((ACCOUNT_DIR / "stacks").glob("*.yaml"))]
    assert len(files) == 5
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b\d{12}\b", text), path
        assert "AnthusAI" not in text and "anth.us" not in text, path
        assert not re.search(r"[\w.]+@[\w-]+\.[a-z]{2,}", text), path


def test_baseline_names_everything_from_the_prefix():
    text = (ACCOUNT_DIR / "baseline.yaml").read_text(encoding="utf-8")
    assert "Prefix:" in text
    assert not re.search(r"RoleName: (?!!Sub)\S", text)  # every role name is built from the prefix
    assert "role/humorus" not in text and "stack/humorus" not in text


def test_adopted_resources_are_retained():
    for name, logical in (("dns", "HostedZone"), ("budget", "MonthlyBudget")):
        text = (ACCOUNT_DIR / "stacks" / f"{name}.yaml").read_text(encoding="utf-8")
        block = text[text.index(f"  {logical}:"):]
        assert "DeletionPolicy: Retain" in block and "UpdateReplacePolicy: Retain" in block


def test_reusable_workflow_is_valid_and_pins_actions():
    text = (ROOT / ".github" / "workflows" / "account-stacks.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    triggers = doc.get("on") or doc.get(True)
    assert "workflow_call" in triggers
    assert set(doc["jobs"]) == {"lint", "plan", "roles-check", "roles", "deploy"}
    assert doc["jobs"]["roles"]["needs"] == "roles-check" and "roles" in doc["jobs"]["deploy"]["needs"]  # roles are applied before the app stacks
    for line in re.findall(r"^\s+- uses: (\S+)", text, flags=re.M):
        assert re.search(r"@[0-9a-f]{40}$", line), line  # every action pinned by commit
    assert doc["jobs"]["roles"]["environment"]


def test_import_template_drops_outputs_only():
    """CloudFormation refuses an IMPORT change set that adds Outputs; the UPDATE after it carries the whole template."""
    text = "Parameters:\n  A: {Type: String}\nResources:\n  Z:\n    Type: X\nOutputs:\n  O:\n    Value: !Ref Z\nMetadata:\n  m: 1\n"
    stripped = sd.import_template_text(text)
    assert "Outputs" not in stripped and "Value: !Ref Z" not in stripped
    assert "Resources:\n  Z:" in stripped and "Metadata:" in stripped
    assert sd.import_template_text("Resources:\n  Z: {Type: X}\n") == "Resources:\n  Z: {Type: X}\n"
    real = (ROOT / "infra" / "account" / "stacks" / "dns.yaml").read_text(encoding="utf-8")
    assert "Outputs" in real and "Outputs" not in sd.import_template_text(real) and "HostedZone:" in sd.import_template_text(real)


def test_baseline_trust_supports_the_repository_subject_prefix():
    """A repository with immutable OIDC subjects has a different prefix; every trust statement must use the parameter when it is set."""
    text = (ACCOUNT_DIR / "baseline.yaml").read_text(encoding="utf-8")
    assert "GithubSubjectPrefix:" in text and "CustomSubject:" in text
    assert text.count("Subject: !If [CustomSubject, !Ref GithubSubjectPrefix") == 3  # deploy, plan, roles-apply
    assert 'repo:${GithubRepository}:' not in text
