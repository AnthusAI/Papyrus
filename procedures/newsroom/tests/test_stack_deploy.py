"""The release pipeline for shared stacks (PPY-b8cc79): safety checks, the deploy flow against a fake CloudFormation, and the repo's wiring.

Nothing here calls AWS. features/stack-pipeline.feature tells the same story in prose.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "infra" / "pipeline"
spec = importlib.util.spec_from_file_location("stack_deploy", PIPELINE / "stack_deploy.py")
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)

GOOD_KEY = "papyrus-monitoring/router-" + "a" * 64 + ".zip"
TEMPLATE = """
Parameters:
  CodeBucket: {Type: String}
  CodeKey: {Type: String}
  Kept: {Type: String, Default: x}
  Fresh: {Type: String, Default: y}
Resources:
  Queue: {Type: "AWS::SQS::Queue"}
"""


class FakeCloud:
    """A scripted CloudFormation. `script` is the (stack status, change-set execution status) pair each poll sees after execute."""
    region = "us-east-1"

    def __init__(self, stack_status="UPDATE_COMPLETE", params=None, changes=None, create_status="CREATE_COMPLETE", reason="", script=None,
                 change_sets=None, events=None):
        self.stack = None if stack_status is None else {"StackStatus": stack_status, "Parameters": [{"ParameterKey": k, "ParameterValue": v} for k, v in (params or {}).items()]}
        self.changes, self.create_status, self.reason = changes or [], create_status, reason
        self.script, self.executed, self.created, self.deleted, self.uploaded = list(script or []), False, [], [], []
        self.change_sets, self.events, self.clock, self.slept = change_sets or [], events or [], 0.0, 0

    def account(self):
        return "123456789012"

    def describe_stack(self, name):
        if self.executed and self.script:
            status, _ = self.script[0]
            self.stack = {**(self.stack or {"Parameters": []}), "StackStatus": status, "StackStatusReason": "boom" if status.endswith("FAILED") or "ROLLBACK" in status else ""}
        return self.stack

    def describe_change_set(self, stack, name):
        if self.executed and self.script:
            _, execution = self.script[0]
            if len(self.script) > 1:
                self.script.pop(0)
            return {"Status": "CREATE_COMPLETE", "ExecutionStatus": execution, "Changes": self.changes}
        return {"Status": self.create_status, "StatusReason": self.reason, "ExecutionStatus": "AVAILABLE", "Changes": self.changes}

    def get_template(self, name):
        return TEMPLATE

    def list_change_sets(self, name):
        return self.change_sets

    def create_change_set(self, stack, name, kind, template_url, parameters, capabilities, tags, role_arn):
        self.created.append({"name": name, "kind": kind, "parameters": parameters, "url": template_url, "role": role_arn, "tags": tags})

    def delete_change_set(self, stack, name):
        self.deleted.append(name)

    def execute_change_set(self, stack, name):
        self.executed = True

    def stack_events(self, name):
        return self.events

    def upload(self, path, bucket, key):
        self.uploaded.append((bucket, key))

    def hosted_zones(self, dns_name):
        return [{"Id": "/hostedzone/ZABC", "Name": dns_name}]

    def sleep(self, seconds):
        self.clock += seconds
        self.slept += 1

    def now(self):
        return self.clock


def make(tmp_path, cloud, allowed=None, **overrides):
    (tmp_path / "t.yaml").write_text(TEMPLATE)
    config = {"region": "us-east-1", "serviceRoleName": "svc", "templateBucketFrom": {"stack": "s", "parameter": "CodeBucket"}}
    messages = []
    ctx = sd.Context(cloud, config, allowed or [], "sha-1-1", root=tmp_path, out=messages.append, poll=10, start_grace=60, execute_timeout=600, **overrides)
    ctx.messages = messages
    return ctx


CFG = {"name": "s", "template": "t.yaml", "parameters": {"CodeKey": GOOD_KEY}, "keepPrevious": True, "capabilities": [], "tags": {}}
CURRENT = {"CodeBucket": "cdk-hnb659fds-assets-123456789012-us-east-1", "CodeKey": "old", "Kept": "kept"}


def change(logical, action="Modify", replacement="False", **extra):
    return {"Type": "Resource", "ResourceChange": {"Action": action, "LogicalResourceId": logical, "ResourceType": "AWS::SQS::Queue", "Replacement": replacement, **extra}}


# --- parameter and key checks -------------------------------------------------------------------------------------------------------


def test_a_valid_key_passes_and_a_two_line_key_is_refused():
    sd.validate_parameters({"RouterCodeKey": GOOD_KEY, "SiteId": "operators"})
    with pytest.raises(sd.Stop, match="one line"):
        sd.validate_parameters({"RouterCodeKey": GOOD_KEY + "\nUploaded s3://bucket/key"})
    with pytest.raises(sd.Stop, match="one line"):
        sd.validate_parameters({"CodeKey": "x\r"})


@pytest.mark.parametrize("key", ["papyrus-monitoring/" + "a" * 63 + ".zip", "other/" + "a" * 64 + ".zip", GOOD_KEY + " ", " " + GOOD_KEY, GOOD_KEY.upper()])
def test_a_badly_shaped_key_is_refused(key):
    with pytest.raises(sd.Stop):
        sd.validate_parameters({"OperatorCodeKey": key})


# --- stack state --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["UPDATE_ROLLBACK_FAILED", "ROLLBACK_FAILED", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED", "ROLLBACK_COMPLETE", "UPDATE_IN_PROGRESS", "UPDATE_ROLLBACK_IN_PROGRESS"])
def test_a_failed_or_busy_stack_stops_the_run_before_any_change_set(tmp_path, status):
    cloud = FakeCloud(stack_status=status, params=CURRENT)
    with pytest.raises(sd.Stop):
        sd.deploy_stack(make(tmp_path, cloud), CFG)
    assert cloud.created == [] and not cloud.executed and cloud.uploaded == []


def test_review_in_progress_is_a_first_create_and_a_missing_stack_is_too():
    assert sd.classify_stack({"StackStatus": "REVIEW_IN_PROGRESS"}) == ("create", "REVIEW_IN_PROGRESS")
    assert sd.classify_stack(None)[0] == "create"
    assert sd.classify_stack({"StackStatus": "UPDATE_ROLLBACK_COMPLETE"})[0] == "update"


# --- parameters ---------------------------------------------------------------------------------------------------------------------


def test_other_parameters_keep_their_previous_values_and_new_ones_take_the_default():
    template = sd.parse_template(TEMPLATE)["Parameters"]
    plan = sd.parameter_plan(template, {"CodeBucket": "b", "CodeKey": "old", "Kept": "kept"}, {"CodeKey": GOOD_KEY}, keep_previous=True)
    assert {"ParameterKey": "CodeKey", "ParameterValue": GOOD_KEY} in plan
    assert {"ParameterKey": "Kept", "UsePreviousValue": True} in plan
    assert {"ParameterKey": "CodeBucket", "UsePreviousValue": True} in plan
    assert not any(p["ParameterKey"] == "Fresh" for p in plan)  # not in the stack yet: the template default applies


def test_a_required_parameter_with_no_value_is_an_error_not_a_guess():
    template = sd.parse_template(TEMPLATE)["Parameters"]
    with pytest.raises(sd.Stop, match="CodeBucket"):
        sd.parameter_plan(template, {}, {"CodeKey": GOOD_KEY}, keep_previous=True)
    with pytest.raises(sd.Stop, match="not in the template"):
        sd.parameter_plan(template, CURRENT, {"Nope": "1"}, keep_previous=True)


# --- the change set review ----------------------------------------------------------------------------------------------------------


def test_remove_and_replace_are_violations_unless_listed_for_that_stack():
    changes = [change("Gone", "Remove"), change("Swapped", "Modify", "True"), change("Maybe", "Modify", "Conditional"), change("Fine", "Add"), change("Tweaked")]
    violations, _ = sd.review_changes("s", changes, [])
    assert [v.split()[0] for v in violations] == ["Gone", "Swapped", "Maybe"]
    allowed = [{"stack": "s", "logicalId": "Gone", "change": "Remove"}, {"stack": "s", "logicalId": "Swapped", "change": "Replace"}, {"stack": "other", "logicalId": "Maybe", "change": "Replace"}]
    violations, lines = sd.review_changes("s", changes, allowed)
    assert [v.split()[0] for v in violations] == ["Maybe"]  # an entry for another stack does not count
    assert any("allowed by allowed-changes.json" in line for line in lines)


def test_a_replacement_hidden_in_the_details_still_counts():
    hidden = change("Hidden", replacement="False", Details=[{"Target": {"RequiresRecreation": "Always"}}])
    assert sd.review_changes("s", [hidden], [])[0]


def test_the_allowed_list_in_the_repo_is_well_formed():
    entries = json.loads((PIPELINE / "allowed-changes.json").read_text())["allowed"]
    for entry in entries:
        assert set(entry) >= {"stack", "logicalId", "change", "reason"} and entry["change"] in ("Remove", "Replace")


# --- the deploy flow ----------------------------------------------------------------------------------------------------------------


def test_a_clean_change_set_executes_once_and_waits_for_the_stack(tmp_path):
    cloud = FakeCloud(params=CURRENT, changes=[change("Fn")], script=[("UPDATE_COMPLETE", "AVAILABLE"), ("UPDATE_IN_PROGRESS", "EXECUTE_IN_PROGRESS"), ("UPDATE_COMPLETE", "EXECUTE_COMPLETE")])
    assert sd.deploy_stack(make(tmp_path, cloud), CFG) == "deployed"
    assert cloud.executed and len(cloud.created) == 1 and cloud.created[0]["kind"] == "update"
    assert cloud.created[0]["role"] == "arn:aws:iam::123456789012:role/svc"
    assert cloud.created[0]["url"].startswith("https://cdk-hnb659fds-assets-123456789012-us-east-1.s3.us-east-1.amazonaws.com/papyrus-monitoring/templates/s-")
    assert cloud.slept >= 2  # it polled; it did not trust the first answer


def test_a_stale_success_status_is_not_read_as_done(tmp_path):
    """The stack still says UPDATE_COMPLETE from the last deploy for several polls; that must not end the wait."""
    script = [("UPDATE_COMPLETE", "AVAILABLE")] * 3 + [("UPDATE_IN_PROGRESS", "EXECUTE_IN_PROGRESS")] * 2 + [("UPDATE_COMPLETE", "EXECUTE_COMPLETE")]
    cloud = FakeCloud(params=CURRENT, changes=[change("Fn")], script=script)
    sd.deploy_stack(make(tmp_path, cloud), CFG)
    assert cloud.clock >= 50  # it kept polling through the stale answers


def test_an_execution_that_never_starts_fails_instead_of_passing(tmp_path):
    cloud = FakeCloud(params=CURRENT, changes=[change("Fn")], script=[("UPDATE_COMPLETE", "AVAILABLE")])
    with pytest.raises(sd.Failed, match="never started"):
        sd.deploy_stack(make(tmp_path, cloud), CFG)


def test_a_failed_update_fails_the_run_with_the_first_failure_as_the_cause(tmp_path):
    events = [{"EventId": "3", "Timestamp": "2026-11-04T12:00:03", "LogicalResourceId": "Fn", "ResourceStatus": "UPDATE_ROLLBACK_COMPLETE", "ResourceStatusReason": ""},
              {"EventId": "2", "Timestamp": "2026-11-04T12:00:02", "LogicalResourceId": "Role", "ResourceStatus": "UPDATE_FAILED", "ResourceStatusReason": "Access denied to iam:CreateRole"},
              {"EventId": "1", "Timestamp": "2026-11-04T11:00:00", "LogicalResourceId": "Old", "ResourceStatus": "UPDATE_FAILED", "ResourceStatusReason": "an older failure"}]
    # Event 1 predates the run: it is in `known` because FakeCloud returns the same list before and after, so mark it by giving the fake a first call.
    class Cloud(FakeCloud):
        calls = 0

        def stack_events(self, name):
            Cloud.calls += 1
            return events[2:] if Cloud.calls == 1 else events

    cloud = Cloud(params=CURRENT, changes=[change("Fn")], script=[("UPDATE_COMPLETE", "AVAILABLE"), ("UPDATE_ROLLBACK_IN_PROGRESS", "EXECUTE_IN_PROGRESS"), ("UPDATE_ROLLBACK_COMPLETE", "EXECUTE_FAILED")])
    with pytest.raises(sd.Failed) as caught:
        sd.deploy_stack(make(tmp_path, cloud), CFG)
    assert "Role UPDATE_FAILED: Access denied to iam:CreateRole" in str(caught.value) and "older failure" not in str(caught.value)


def test_an_unlisted_removal_deletes_the_change_set_and_never_executes(tmp_path):
    cloud = FakeCloud(params=CURRENT, changes=[change("Precious", "Remove"), change("Fn")])
    ctx = make(tmp_path, cloud)
    with pytest.raises(sd.Stop, match="Precious"):
        sd.deploy_stack(ctx, CFG)
    assert not cloud.executed and cloud.deleted == ["papyrus-release-sha-1-1"]


def test_an_unlisted_replacement_never_executes_and_a_listed_one_does(tmp_path):
    changes = [change("Table", "Modify", "True")]
    with pytest.raises(sd.Stop):
        sd.deploy_stack(make(tmp_path, FakeCloud(params=CURRENT, changes=changes)), CFG)
    cloud = FakeCloud(params=CURRENT, changes=changes, script=[("UPDATE_COMPLETE", "AVAILABLE"), ("UPDATE_IN_PROGRESS", "EXECUTE_IN_PROGRESS"), ("UPDATE_COMPLETE", "EXECUTE_COMPLETE")])
    sd.deploy_stack(make(tmp_path, cloud, allowed=[{"stack": "s", "logicalId": "Table", "change": "Replace", "reason": "test"}]), CFG)
    assert cloud.executed


def test_no_changes_is_a_quiet_success(tmp_path):
    cloud = FakeCloud(params=CURRENT, create_status="FAILED", reason="The submitted information didn't contain changes. Submit different information to create a change set.")
    assert sd.deploy_stack(make(tmp_path, cloud), CFG) == "unchanged"
    assert not cloud.executed and cloud.deleted


def test_a_change_set_that_cannot_be_created_fails_the_run(tmp_path):
    cloud = FakeCloud(params=CURRENT, create_status="FAILED", reason="Parameters: [X] do not exist in the template")
    with pytest.raises(sd.Failed, match="do not exist"):
        sd.deploy_stack(make(tmp_path, cloud), CFG)


def test_a_first_create_uses_a_create_change_set_and_leaves_changes_sets_it_does_not_own(tmp_path):
    foreign = [{"ChangeSetName": "operators-first", "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE"},
               {"ChangeSetName": "papyrus-release-old-1-1", "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE"},
               {"ChangeSetName": "papyrus-release-done-1-1", "Status": "CREATE_COMPLETE", "ExecutionStatus": "EXECUTE_COMPLETE"}]
    cloud = FakeCloud(stack_status="REVIEW_IN_PROGRESS", params=CURRENT, change_sets=foreign, changes=[change("Id", "Add")],
                      script=[("REVIEW_IN_PROGRESS", "AVAILABLE"), ("CREATE_IN_PROGRESS", "EXECUTE_IN_PROGRESS"), ("CREATE_COMPLETE", "EXECUTE_COMPLETE")])
    cfg = {**CFG, "tags": {"papyrus:site": "operators"}}
    sd.deploy_stack(make(tmp_path, cloud), cfg)
    assert cloud.created[0]["kind"] == "create" and cloud.created[0]["tags"] == {"papyrus:site": "operators"}
    assert cloud.deleted == ["papyrus-release-old-1-1"]  # ours, unexecuted; the other two are left alone


# --- scope and the repo's wiring ----------------------------------------------------------------------------------------------------


def test_a_docs_only_release_deploys_nothing_and_a_code_change_deploys_the_monitoring_stack():
    config = json.loads((PIPELINE / "stacks.json").read_text())
    assert sd.changed_stacks(config, ["docs/operator-alerts.md", "AGENTS.md", "project/issues/x.json", "docs/hosting/x.md"]) == []
    assert sd.changed_stacks(config, ["src/papyrus_content/monitoring_router.py"]) == ["papyrus-monitoring"]
    assert sd.changed_stacks(config, ["infra/newsletter/papyrus-newsletter-sending.yaml"]) == ["papyrus-newsletter-sending-operators"]
    assert sd.changed_stacks(config, ["infra/pipeline/allowed-changes.json"]) == ["papyrus-newsletter-sending-operators", "papyrus-monitoring"]


def test_every_path_that_scopes_a_stack_also_triggers_the_dry_run_workflow():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "stack-deploy.yml").read_text())
    globs = [g.removesuffix("**") for g in workflow[True]["pull_request"]["paths"]]
    for stack in json.loads((PIPELINE / "stacks.json").read_text())["stacks"]:
        for path in stack["paths"]:
            assert any(path.startswith(g) or path == g for g in globs), path
        assert (ROOT / stack["template"]).exists()


def test_the_workflow_deploys_only_from_main_with_oidc_and_no_stored_keys():
    text = (ROOT / ".github" / "workflows" / "stack-deploy.yml").read_text()
    workflow = yaml.safe_load(text)
    assert workflow[True]["push"]["branches"] == ["main"]
    assert "aws-access-key-id" not in text.lower() and "secrets." not in text
    assert not re.search(r"\b\d{12}\b", text)
    jobs = workflow["jobs"]
    assert jobs["deploy"]["needs"] == ["scope", "tests"] and jobs["tests"]["uses"] == "./.github/workflows/tests.yml"
    assert jobs["deploy"]["concurrency"] == {"group": "stack-deploy", "cancel-in-progress": False}
    assert "pull_request" in jobs["dry-run"]["if"] and "id-token" in jobs["dry-run"]["permissions"]
    assert "plan-github" in text and "deploy-github" in text
    assert "workflow_call" in yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text())[True]


def test_the_bootstrap_template_trusts_only_this_repos_main_and_its_pull_requests():
    template = sd.parse_template((PIPELINE / "papyrus-stack-pipeline.yaml").read_text())
    resources = template["Resources"]

    def sub(role):
        statement = resources[role]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
        return statement["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"]["Fn::Sub"]

    assert sub("DeployRole") == "repo:${GitHubRepository}:ref:refs/heads/main"
    assert sub("PlanRole") == "repo:${GitHubRepository}:pull_request"
    plan_actions = [a for s in resources["PlanRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"] for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])]
    assert all(a.split(":")[1].startswith(("Describe", "Get", "List")) for a in plan_actions), plan_actions
    everything = json.dumps(template)
    assert '"Action": "*"' not in everything and not re.search(r"\b\d{12}\b", everything)
    deploy = json.dumps(resources["DeployRole"]["Properties"]["Policies"])
    assert "cloudformation:RoleArn" in deploy and "iam:PassedToService" in deploy
    for policy in ("ComputeAndIdentityPolicy", "DataAndMailPolicy"):
        assert len(json.dumps(resources[policy]["Properties"]["PolicyDocument"], separators=(",", ":"))) < 6144  # managed policy size limit


def test_the_docs_no_longer_tell_anyone_to_hand_run_these_stacks():
    agents = (ROOT / "AGENTS.md").read_text()
    assert "- **Shared stacks** (`papyrus-monitoring`, `papyrus-procedure-runner`" not in agents
    assert "infra/pipeline/README.md" in agents
    assert "Nothing is deployed by the pull request. Each write is a change set a person reads first." not in (ROOT / "docs" / "operator-alerts.md").read_text()


# --- the dry run, templates and the AWS wrapper -------------------------------------------------------------------------------------


def test_template_diff_reports_added_removed_and_modified_resources():
    old = {"Parameters": {"A": {}}, "Resources": {"Keep": {"Properties": {"x": 1}}, "Gone": {}, "Edit": {"Properties": {"a": 1, "b": 2}}}}
    new = {"Parameters": {"A": {}, "B": {}}, "Resources": {"Keep": {"Properties": {"x": 1}}, "New": {}, "Edit": {"Properties": {"a": 1, "b": 3}}}}
    diff = sd.diff_templates(old, new)
    assert diff == {"added": ["New"], "removed": ["Gone"], "modified": {"Edit": ["b"]}, "parameters_added": ["B"], "parameters_removed": []}


def test_the_dry_run_is_read_only_and_flags_a_removal_that_would_stop_the_release(tmp_path):
    class Live(FakeCloud):
        def get_template(self, name):
            return TEMPLATE + "  Orphan: {Type: \"AWS::SQS::Queue\"}\n"

    cloud = Live(params=CURRENT)
    ctx = make(tmp_path, cloud)
    sd.plan_stack(ctx, CFG)
    text = "\n".join(ctx.messages)
    assert "remove `Orphan`" in text and "would STOP the release" in text
    assert cloud.created == [] and cloud.uploaded == [] and not cloud.executed and cloud.deleted == []


def test_the_dry_run_of_a_stack_in_a_failed_state_says_the_release_would_stop(tmp_path):
    ctx = make(tmp_path, FakeCloud(stack_status="UPDATE_ROLLBACK_FAILED", params=CURRENT))
    sd.plan_stack(ctx, CFG)
    assert "would STOP" in "\n".join(ctx.messages)


def test_vendored_requirements_come_from_the_lock_file():
    lock = '[[package]]\nname = "PyYAML"\nversion = "6.0.2"\n[[package]]\nname = "youtube-transcript-api"\nversion = "1.0.0"\n'
    assert sd.vendored_requirements(lock, ("yaml", "youtube_transcript_api")) == ["pyyaml==6.0.2", "youtube-transcript-api==1.0.0"]
    with pytest.raises(sd.Stop):
        sd.vendored_requirements(lock, ("requests",))


def test_the_real_lock_file_covers_every_vendored_package():
    spec = importlib.util.spec_from_file_location("build", ROOT / "infra" / "monitoring" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert len(sd.vendored_requirements((ROOT / "poetry.lock").read_text(), build.VENDORED)) == len(build.VENDORED)


def test_the_aws_wrapper_passes_the_service_role_and_tags_only_on_create():
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    cli = sd.AwsCli("us-east-1", run=run)
    cli.create_change_set("s", "c", "update", "https://u", [], [], {"a": "b"}, "arn:role")
    cli.create_change_set("s", "c", "create", "https://u", [], ["CAPABILITY_IAM"], {"a": "b"}, "arn:role")
    assert "--role-arn" in calls[0] and "--tags" not in calls[0] and "--change-set-type" in calls[0] and "UPDATE" in calls[0]
    assert "--tags" in calls[1] and "Key=a,Value=b" in calls[1] and "CREATE" in calls[1] and "CAPABILITY_IAM" in calls[1]
    assert not any("wait" in part for command in calls for part in command)
