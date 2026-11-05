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


def test_a_first_create_keeps_waiting_after_its_change_set_disappears(tmp_path):
    """CloudFormation removed the change set of the operator stack's first create while it ran (the 2026-11-04 release)."""
    class Vanishing(FakeCloud):
        def describe_change_set(self, stack, name):
            if self.executed:
                if len(self.script) > 1:
                    self.script.pop(0)
                raise sd.AwsError(f"An error occurred (ChangeSetNotFound) when calling the DescribeChangeSet operation: ChangeSet [{name}] does not exist")
            return super().describe_change_set(stack, name)

    cloud = Vanishing(stack_status="REVIEW_IN_PROGRESS", params=CURRENT, changes=[change("Id", "Add")],
                      script=[("CREATE_IN_PROGRESS", ""), ("CREATE_IN_PROGRESS", ""), ("CREATE_COMPLETE", "")])
    assert sd.deploy_stack(make(tmp_path, cloud), CFG) == "deployed"
    assert cloud.slept >= 2

    failed = Vanishing(stack_status="REVIEW_IN_PROGRESS", params=CURRENT, changes=[change("Id", "Add")],
                       script=[("CREATE_IN_PROGRESS", ""), ("ROLLBACK_COMPLETE", "")])
    with pytest.raises(sd.Failed):
        sd.deploy_stack(make(tmp_path, failed), CFG)


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


# --- the role bootstrap: one repeatable step, documented, and impossible to miss (PPY-9d1b3e) -----------------------------------------

PIPELINE_TEMPLATE = PIPELINE / "papyrus-stack-pipeline.yaml"


def _policy_documents(template):
    for name, resource in template["Resources"].items():
        props = resource.get("Properties", {})
        if resource["Type"] == "AWS::IAM::ManagedPolicy":
            yield name, props["PolicyDocument"]
        elif resource["Type"] == "AWS::IAM::Role":
            yield f"{name} trust", props["AssumeRolePolicyDocument"]
            for policy in props.get("Policies", []):
                yield f"{name} {policy['PolicyName']}", policy["PolicyDocument"]


def test_no_policy_in_the_role_template_repeats_a_statement_id():
    # A duplicate Sid made IAM refuse the policy and failed a release on 2026-11-05.
    template = sd.parse_template(PIPELINE_TEMPLATE.read_text())
    checked = 0
    for where, document in _policy_documents(template):
        sids = [s["Sid"] for s in document["Statement"] if "Sid" in s]
        assert len(sids) == len(set(sids)), f"duplicate Sid in {where}: {sorted(x for x in sids if sids.count(x) > 1)}"
        checked += 1
    assert checked >= 5


def test_both_roles_may_read_the_pipeline_stack_and_only_read_it():
    template = sd.parse_template(PIPELINE_TEMPLATE.read_text())
    for role in ("PlanRole", "DeployRole"):
        statements = template["Resources"][role]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        read = [s for s in statements if "stack/papyrus-stack-pipeline/" in json.dumps(s["Resource"])]
        assert len(read) == 1 and set(read[0]["Action"]) == {"cloudformation:DescribeStacks", "cloudformation:GetTemplate"}


def test_the_service_role_covers_the_service_of_every_resource_type_the_stacks_create():
    # Service level only: it cannot know every action a resource needs. A new service in a stack template fails here before it fails a release.
    pipeline = sd.parse_template(PIPELINE_TEMPLATE.read_text())
    granted = set()
    for name in ("ComputeAndIdentityPolicy", "DataAndMailPolicy"):
        for statement in pipeline["Resources"][name]["Properties"]["PolicyDocument"]["Statement"]:
            actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            granted |= {a.split(":")[0] for a in actions}
    for stack in json.loads((PIPELINE / "stacks.json").read_text())["stacks"]:
        for logical, resource in sd.parse_template((ROOT / stack["template"]).read_text())["Resources"].items():
            kind = resource["Type"]
            if kind.startswith("Custom::") or kind == "AWS::CloudFormation::CustomResource":
                service = "lambda"
            elif kind.startswith("AWS::"):
                service = kind.split("::")[1].lower()
            else:
                continue
            assert service in granted, f"{stack['name']} {logical} ({kind}): the service role has no {service}:* permission"


def test_a_change_to_the_role_template_puts_both_stacks_in_scope_so_the_release_checks_the_roles():
    config = json.loads((PIPELINE / "stacks.json").read_text())
    assert sd.changed_stacks(config, ["infra/pipeline/papyrus-stack-pipeline.yaml"]) == [s["name"] for s in config["stacks"]]


class PipelineCloud(FakeCloud):
    def __init__(self, deployed, **kwargs):
        super().__init__(**kwargs)
        self.deployed = deployed

    def get_template(self, name):
        if name == sd.PIPELINE_STACK:
            if isinstance(self.deployed, Exception):
                raise self.deployed
            return self.deployed
        return TEMPLATE


REPO_PIPELINE = PIPELINE_TEMPLATE.read_text()
STALE_PIPELINE = REPO_PIPELINE.replace("MaxSessionDuration: 3600", "MaxSessionDuration: 7200", 1)


@pytest.mark.parametrize("deployed, state", [
    (REPO_PIPELINE, "same"),
    (STALE_PIPELINE, "differs"),
    (sd.AwsError("Stack with id papyrus-stack-pipeline does not exist"), "missing"),
    (sd.AwsError("User is not authorized to perform: cloudformation:GetTemplate"), "unreadable"),
])
def test_the_deployed_roles_are_compared_with_the_template_in_the_repo(deployed, state):
    assert sd.pipeline_state(PipelineCloud(deployed), REPO_PIPELINE)[0] == state


def test_an_out_of_date_role_is_said_plainly_once_names_the_command_and_stops_nothing(tmp_path):
    cloud = PipelineCloud(STALE_PIPELINE, params=CURRENT)
    ctx = make(tmp_path, cloud)
    ctx.check_pipeline = True
    sd.plan_stack(ctx, CFG)
    sd.plan_stack(ctx, CFG)
    text = "\n".join(ctx.messages)
    assert text.count("### The pipeline roles are out of date") == 1
    assert "role-stack-deploy" in text and "approves" in text and "::warning::" in text
    assert "Resources added" in text and cloud.created == []  # the dry run went on as usual


def test_unreadable_roles_from_before_the_check_are_a_notice_not_a_failure(tmp_path):
    ctx = make(tmp_path, PipelineCloud(sd.AwsError("not authorized to perform cloudformation:GetTemplate"), params=CURRENT))
    ctx.check_pipeline = True
    assert sd.pipeline_notice(ctx) == "unreadable"
    assert "cannot read the papyrus-stack-pipeline stack" in "\n".join(ctx.messages)


def test_matching_roles_add_no_noise(tmp_path):
    ctx = make(tmp_path, PipelineCloud(REPO_PIPELINE, params=CURRENT))
    ctx.check_pipeline = True
    assert sd.pipeline_notice(ctx) == "same" and ctx.messages == []


def test_a_not_authorized_failure_names_the_approval_workflow():
    hint = sd.bootstrap_hint("User: arn:aws:sts::1:assumed-role/papyrus-stack-deploy-cloudformation is not authorized to perform: cloudwatch:PutCompositeAlarm")
    assert "role-stack-deploy" in hint and "approves it in GitHub" in hint and "never approves" in hint
    assert sd.bootstrap_hint("Resource handler returned message: queue name already exists") == ""


def test_the_first_papyrus_monitoring_of_a_new_account_takes_the_cdk_bootstrap_bucket(tmp_path):
    cloud = FakeCloud(stack_status=None, changes=[change("Id", "Add")],
                      script=[("CREATE_COMPLETE", "AVAILABLE"), ("CREATE_IN_PROGRESS", "EXECUTE_IN_PROGRESS"), ("CREATE_COMPLETE", "EXECUTE_COMPLETE")])
    assert sd.deploy_stack(make(tmp_path, cloud), CFG) == "deployed"
    bucket = "cdk-hnb659fds-assets-123456789012-us-east-1"
    assert cloud.created[0]["kind"] == "create" and {"ParameterKey": "CodeBucket", "ParameterValue": bucket} in cloud.created[0]["parameters"]
    assert cloud.uploaded[0][0] == bucket


SETUP_DOCS = ["README.md", "AGENTS.md", "infra/pipeline/README.md", "docs/site-hosting.md", "docs/operator-alerts.md", "docs/releasing.md", "docs/standard-site.md"]


@pytest.mark.parametrize("path", SETUP_DOCS)
def test_every_place_that_describes_account_setup_points_at_the_approval_workflow_and_the_one_setup(path):
    text = (ROOT / path).read_text()
    assert "role-stack-deploy" in text and "bootstrap.sh" in text, f"{path} must name the workflow and infra/pipeline/bootstrap.sh"
    assert "--approver-only" in text, f"{path} must give the one-time setup command"


@pytest.mark.parametrize("path", ["README.md", "AGENTS.md", "infra/pipeline/README.md"])
def test_the_main_docs_say_what_to_do_after_any_template_change_and_who_does_what(path):
    text = (ROOT / path).read_text().replace("*", "")
    assert "papyrus-stack-pipeline.yaml" in text and "any change" in text.lower() and "approve" in text and "new AWS account" in text
    assert "<12-digit account id>" in text and "create-environment.sh --reviewer" in text


@pytest.mark.parametrize("path", SETUP_DOCS)
def test_no_doc_tells_anyone_to_apply_the_pipeline_roles_by_hand_as_the_normal_path(path):
    text = (ROOT / path).read_text()
    assert "a person runs infra/pipeline/bootstrap.sh --account <12-digit account id>`" not in text
    assert "required-the-role-bootstrap" not in text


def test_agents_are_told_to_link_the_approval_and_never_to_approve_or_work_around():
    text = (ROOT / "AGENTS.md").read_text().replace("*", "")
    assert "Never approve it" in text and "never work around a refusal" in text and "give the reviewer its link" in text
    assert "The pipeline roles are out of date" in text and "unless the user tells you to" in text


ACCOUNT = "2" * 12  # made up, and built rather than written so no account-id shape sits in the file
OTHER = "9" * 12


def _fake_tools(tmp_path, account, providers=f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"):
    """An `aws` and a `gh` that record every call and answer just enough. Nothing leaves the machine."""
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "aws").write_text(f"""#!/bin/sh
echo "aws $*" >> {log}
case "$*" in
  *"sts get-caller-identity"*) echo {account} ;;
  *"list-open-id-connect-providers"*) echo '{providers}' ;;
  *"describe-stacks"*) exit 255 ;;
  *"describe-change-set"*"StatusReason"*) echo None ;;
  *"describe-change-set"*"Status"*) echo CREATE_COMPLETE ;;
esac
exit 0
""")
    (bin_dir / "gh").write_text(f"#!/bin/sh\necho \"gh $*\" >> {log}\n")
    (bin_dir / "git").write_text(f"""#!/bin/sh
echo "git $*" >> {log}
for last; do :; done
path="${{last#*:}}"
case "$*" in
  *" show origin/develop:"*) mode="$FAKE_DEVELOP" ;;
  *" show origin/main:"*) mode="$FAKE_MAIN" ;;
  *) exit 0 ;;
esac
case "$mode" in
  same) cat "$FAKE_ROOT/$path" ;;
  other) echo "Resources: {{}}" ;;
esac
exit 0
""")
    for tool in ("aws", "gh", "git"):
        (bin_dir / tool).chmod(0o755)
    return bin_dir, log


def _bootstrap(tmp_path, actual, *args, develop="same", main="none", **tools):
    bin_dir, log = _fake_tools(tmp_path, actual, **tools)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "FAKE_DEVELOP": develop, "FAKE_MAIN": main, "FAKE_ROOT": str(ROOT)}
    done = subprocess.run(["bash", str(PIPELINE / "bootstrap.sh"), *args], capture_output=True, text=True, env=env, input="no\n")
    return done, (log.read_text() if log.exists() else "")


def test_bootstrap_refuses_the_wrong_account_before_changing_anything(tmp_path):
    done, calls = _bootstrap(tmp_path, OTHER, "--account", ACCOUNT)
    assert done.returncode == 2 and f"belong to account {OTHER}, not {ACCOUNT}" in done.stderr
    assert "create-change-set" not in calls and "variable set" not in calls


def test_bootstrap_needs_an_account_and_never_assumes_one(tmp_path):
    done, calls = _bootstrap(tmp_path, ACCOUNT)
    assert done.returncode == 2 and "--account" in done.stderr and calls == ""


def test_bootstrap_shows_a_change_set_and_applies_nothing_without_a_yes(tmp_path):
    done, calls = _bootstrap(tmp_path, ACCOUNT, "--account", ACCOUNT)
    assert done.returncode == 2 and "not confirmed" in done.stderr
    assert "create-change-set" in calls and "--change-set-type CREATE" in calls and "execute-change-set" not in calls and "variable set" not in calls


def test_bootstrap_plan_only_deletes_its_change_set(tmp_path):
    done, calls = _bootstrap(tmp_path, ACCOUNT, "--account", ACCOUNT, "--plan-only")
    assert done.returncode == 0 and "execute-change-set" not in calls and "delete-change-set" in calls


def test_bootstrap_asks_for_the_provider_flag_when_the_account_has_none(tmp_path):
    done, calls = _bootstrap(tmp_path, ACCOUNT, "--account", ACCOUNT, providers="")
    assert done.returncode == 2 and "--create-oidc-provider" in done.stderr and "create-change-set" not in calls


def test_bootstrap_refuses_to_create_a_second_provider(tmp_path):
    done, calls = _bootstrap(tmp_path, ACCOUNT, "--account", ACCOUNT, "--create-oidc-provider")
    assert done.returncode == 2 and "already has" in done.stderr and "create-change-set" not in calls


def test_the_bootstrap_script_and_docs_hold_no_real_account_id():
    for path in [PIPELINE / name for name in ("bootstrap.sh", "create-environment.sh", "role_stack.py", "README.md", "papyrus-stack-pipeline.yaml", "papyrus-pipeline-approver.yaml")] + [ROOT / ".github" / "workflows" / "role-stack-deploy.yml"]:
        assert not re.search(r"(?<![\d<-])\d{12}(?![\d>])", path.read_text()), path


def test_bootstrap_applies_only_a_template_that_is_merged_to_develop_or_main(tmp_path):
    other = tmp_path / "other.yaml"
    other.write_text("Resources: {}\n")
    done, calls = _bootstrap(tmp_path, ACCOUNT, "--account", ACCOUNT, develop="other")
    assert done.returncode == 2 and "matches neither origin/develop nor origin/main" in done.stderr
    assert "fetch" in calls and "aws " not in calls  # refused before any AWS call
    again = tmp_path / "again"
    again.mkdir()
    done, calls = _bootstrap(again, ACCOUNT, "--account", ACCOUNT, "--plan-only", develop="other", main="same")
    assert "matches origin/main" in done.stdout and "create-change-set" in calls


def test_bootstrap_names_develop_when_the_template_matches_it(tmp_path):
    done, _ = _bootstrap(tmp_path, ACCOUNT, "--account", ACCOUNT, "--plan-only")
    assert done.returncode == 0 and "matches origin/develop" in done.stdout


def test_bootstrap_plan_only_warns_about_an_unmerged_template_instead_of_refusing(tmp_path):
    other = tmp_path / "other.yaml"
    other.write_text("Resources: {}\n")
    done, calls = _bootstrap(tmp_path, ACCOUNT, "--account", ACCOUNT, "--plan-only", develop="other")
    assert done.returncode == 0 and "WARNING" in done.stdout and "create-change-set" in calls and "execute-change-set" not in calls


def test_bootstrap_has_no_flag_to_skip_the_merged_check():
    text = (PIPELINE / "bootstrap.sh").read_text()  # also: both templates are checked, not just one
    assert "--force" not in text and "--skip" not in text and "--unmerged" not in text


# --- the approval-gated role deploy (PPY-9d1b3e) ----------------------------------------------------------------------------------------

import fnmatch  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, str(PIPELINE))
sys.modules["stack_deploy"] = sd  # one module, so role_stack raises the same Stop and Failed
spec_roles = importlib.util.spec_from_file_location("role_stack", PIPELINE / "role_stack.py")
rs = importlib.util.module_from_spec(spec_roles)
spec_roles.loader.exec_module(rs)

APPROVER = PIPELINE / "papyrus-pipeline-approver.yaml"
ROLES_WORKFLOW = ROOT / ".github" / "workflows" / "role-stack-deploy.yml"
APPROVER_NAMES = ["papyrus-pipeline-roles-plan-github", "papyrus-pipeline-roles-apply-github", "papyrus-pipeline-roles-cloudformation"]


def _as_list(value):
    return value if isinstance(value, list) else [value]


def _approver():
    return sd.parse_template(APPROVER.read_text())


def _policy(template, role):
    return template["Resources"][role]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]


def test_no_policy_in_the_approver_template_repeats_a_statement_id():
    template = _approver()
    checked = 0
    for where, document in _policy_documents(template):
        sids = [s["Sid"] for s in document["Statement"] if "Sid" in s]
        assert len(sids) == len(set(sids)), f"duplicate Sid in {where}"
        checked += 1
    assert checked >= 6


def test_the_provider_is_created_by_the_approver_stack_only_when_asked():
    template = _approver()
    assert template["Parameters"]["CreateGitHubOidcProvider"]["Default"] == "false"
    provider = template["Resources"]["GitHubOidcProvider"]
    assert provider["Condition"] == "CreatesProvider" and provider["Properties"]["ClientIdList"] == ["sts.amazonaws.com"]
    assert provider["Properties"]["Url"] == "https://token.actions.githubusercontent.com"
    for role in ("PlanRole", "ApplyRole"):
        federated = template["Resources"][role]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Principal"]["Federated"]
        assert "Fn::If" in federated
    assert "GitHubOidcProvider" not in sd.parse_template(PIPELINE_TEMPLATE.read_text())["Resources"]  # one place creates it


def test_the_apply_role_trusts_exactly_the_approval_environment_with_the_audience_checked():
    template = _approver()
    condition = template["Resources"]["ApplyRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]
    assert set(condition) == {"StringEquals"}  # exact match, never StringLike
    assert condition["StringEquals"]["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert condition["StringEquals"]["token.actions.githubusercontent.com:sub"] == {"Fn::Sub": "repo:${GitHubRepository}:environment:${ApprovalEnvironment}"}
    assert template["Parameters"]["ApprovalEnvironment"]["Default"] == "pipeline-roles" and template["Parameters"]["GitHubRepository"]["Default"] == "AnthusAI/Papyrus"


def test_the_plan_role_trusts_only_pushes_to_develop_and_main_and_cannot_execute():
    template = _approver()
    condition = template["Resources"]["PlanRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"]
    assert [x["Fn::Sub"] for x in condition["token.actions.githubusercontent.com:sub"]] == ["repo:${GitHubRepository}:ref:refs/heads/develop", "repo:${GitHubRepository}:ref:refs/heads/main"]
    actions = {a for s in _policy(template, "PlanRole") for a in _as_list(s["Action"])}
    assert "cloudformation:ExecuteChangeSet" not in actions and "cloudformation:DeleteStack" not in actions
    create = [s for s in _policy(template, "PlanRole") if s["Action"] == "cloudformation:CreateChangeSet"][0]
    assert create["Condition"]["StringEquals"]["cloudformation:RoleArn"] == {"Fn::GetAtt": ["ServiceRole", "Arn"]}


def test_the_apply_role_has_no_iam_rights_and_only_touches_the_pipeline_stack():
    template = _approver()
    for statement in _policy(template, "ApplyRole"):
        assert all(a.startswith("cloudformation:") for a in _as_list(statement["Action"]))
        assert "stack/papyrus-stack-pipeline/" in json.dumps(statement["Resource"])
        assert "papyrus-pipeline-approver" not in json.dumps(statement["Resource"])


def test_the_approval_roles_cannot_touch_their_own_stack_or_roles_and_cannot_create_arbitrary_roles():
    template = _approver()
    pipeline_roles = ["papyrus-stack-plan-github", "papyrus-stack-deploy-github", "papyrus-stack-deploy-cloudformation"]
    for role in ("PlanRole", "ApplyRole", "ServiceRole"):
        for statement in _policy(template, role):
            actions = _as_list(statement["Action"])
            resources = [r["Fn::Sub"] if isinstance(r, dict) and "Fn::Sub" in r else json.dumps(r) for r in _as_list(statement["Resource"])]
            assert "*" not in resources and not any(a in ("*", "iam:*", "cloudformation:*") or a.endswith(":*") for a in actions), (role, statement.get("Sid"))
            for resource in resources:
                if "iam::" not in resource:
                    continue
                name = resource.split("/", 1)[1]
                # Every IAM resource is one of the three pipeline roles by exact name, or the pipeline stack's managed policies by prefix.
                assert name in pipeline_roles or name == "papyrus-stack-pipeline-*", f"{role} {statement.get('Sid')} reaches {resource}"
                assert not any(fnmatch.fnmatch(own, name) for own in APPROVER_NAMES), f"{resource} would match the approval roles"
                if any(a in ("iam:CreateRole", "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy") for a in actions):
                    assert name in pipeline_roles  # create and rewrite only the three named roles
    # Attaching is limited to the pipeline stack's own managed policies, so no role can be given an AWS-managed policy.
    attach = [s for s in _policy(template, "ServiceRole") if "iam:AttachRolePolicy" in _as_list(s["Action"])][0]
    assert "policy/papyrus-stack-pipeline-*" in json.dumps(attach["Condition"])
    # Nothing grants a change to the approver stack (cloudformation on it), nor passes a role other than the service role.
    everything = json.dumps([_policy(template, r) for r in ("PlanRole", "ApplyRole", "ServiceRole")])
    assert "stack/papyrus-pipeline-approver" not in everything
    passes = [s for s in _policy(template, "PlanRole") if "iam:PassRole" in _as_list(s["Action"])]
    assert len(passes) == 1 and passes[0]["Resource"] == {"Fn::GetAtt": ["ServiceRole", "Arn"]}


def test_the_service_role_can_only_be_assumed_by_cloudformation_in_this_account():
    statement = _approver()["Resources"]["ServiceRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert statement["Principal"] == {"Service": "cloudformation.amazonaws.com"} and "aws:SourceAccount" in json.dumps(statement["Condition"])


def test_the_pipeline_template_fits_in_a_change_set_body():
    assert len(PIPELINE_TEMPLATE.read_bytes()) < 50000  # --template-body is limited to 51,200 bytes; no bucket is needed


# --- the workflow --------------------------------------------------------------------------------------------------------------------


def _workflow():
    return yaml.safe_load(ROLES_WORKFLOW.read_text())


def test_the_role_workflow_runs_on_merged_code_only_and_asks_for_approval_only_to_apply():
    flow = _workflow()
    on = flow[True]
    assert on["push"]["branches"] == ["develop", "main"] and "infra/pipeline/papyrus-stack-pipeline.yaml" in on["push"]["paths"] and "workflow_dispatch" in on
    assert "pull_request" not in on and "pull_request_target" not in on  # unmerged code never runs here
    plan, apply = flow["jobs"]["plan"], flow["jobs"]["apply"]
    assert "environment" not in plan and "refs/heads/develop" in plan["if"] and "refs/heads/main" in plan["if"]
    assert apply["environment"] == "pipeline-roles" and apply["needs"] == "plan" and apply["if"] == "needs.plan.outputs.needed == 'true'"
    assert flow["concurrency"]["cancel-in-progress"] is False


def test_the_role_workflow_uses_oidc_with_separate_roles_and_the_exact_change_set():
    text = ROLES_WORKFLOW.read_text()
    flow = _workflow()
    assert "papyrus-pipeline-roles-plan-github" in json.dumps(flow["jobs"]["plan"]) and "papyrus-pipeline-roles-apply-github" in json.dumps(flow["jobs"]["apply"])
    assert flow["jobs"]["plan"]["permissions"]["id-token"] == "write" and flow["jobs"]["apply"]["permissions"]["id-token"] == "write"
    for forbidden in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "secrets."):
        assert forbidden not in text
    assert "--change-set \"$CHANGE_SET\"" in text and "--template-sha" in text and "--stamp" in text
    assert "ref: ${{ github.sha }}" in text  # apply reads the commit that was planned


def test_the_environment_script_sets_the_reviewer_and_limits_branches_without_committing_anything_private(tmp_path):
    log = tmp_path / "gh.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(f"""#!/bin/sh
echo "gh $*" >> {log}
cat > /dev/null 2>&1 < /dev/null
case "$*" in
  *"users/"*) echo 4242 ;;
esac
exit 0
""")
    (bin_dir / "gh").chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    script = str(PIPELINE / "create-environment.sh")
    refused = subprocess.run(["bash", script], capture_output=True, text=True, env=env)
    assert refused.returncode == 2 and "--reviewer" in refused.stderr and not log.exists()
    done = subprocess.run(["bash", script, "--reviewer", "some-login"], capture_output=True, text=True, env=env)
    calls = log.read_text()
    assert done.returncode == 0, done.stderr
    assert "users/some-login" in calls and "--method PUT repos/AnthusAI/Papyrus/environments/pipeline-roles" in calls
    assert calls.count("--method POST repos/AnthusAI/Papyrus/environments/pipeline-roles/deployment-branch-policies") == 2
    assert "some-login" not in (PIPELINE / "create-environment.sh").read_text()


# --- the plan and the apply -----------------------------------------------------------------------------------------------------------


class RolesFake(FakeCloud):
    def __init__(self, deployed=None, cs_template=None, later=None, **kwargs):
        super().__init__(**kwargs)
        self.deployed, self.cs_template, self.stack_deleted, self.role_change_sets = deployed, cs_template, False, []
        self.later, self.event_calls = later, 0

    def stack_events(self, name):
        self.event_calls += 1
        return [] if self.event_calls == 1 else (self.later or [])

    def get_template(self, name):
        return self.deployed if self.deployed is not None else TEMPLATE

    def create_roles_change_set(self, name, kind, template_path, parameters, role_arn):
        self.role_change_sets.append({"name": name, "kind": kind, "role": role_arn, "parameters": parameters})

    def change_set_template(self, name):
        return self.cs_template if self.cs_template is not None else REPO_PIPELINE

    def delete_stack(self):
        self.stack_deleted = True


def _plan(tmp_path, cloud):
    ctx = make(tmp_path, cloud)
    outputs = {}
    code = rs.plan(ctx, PIPELINE_TEMPLATE, "7-1", lambda k, v: outputs.__setitem__(k, v))
    return code, outputs, "\n".join(ctx.messages)


def test_a_plan_for_a_new_account_prints_every_change_and_the_iam_view_and_asks_for_approval(tmp_path):
    cloud = RolesFake(stack_status=None, changes=[change("PlanRole", "Add"), change("DeployRole", "Add")])
    code, outputs, text = _plan(tmp_path, cloud)
    assert code == 0 and outputs["needed"] == "true" and outputs["change_set"].startswith("roles-") and outputs["stamp"] == "none"
    assert cloud.role_change_sets[0]["kind"] == "create" and cloud.role_change_sets[0]["role"].endswith(":role/papyrus-pipeline-roles-cloudformation")
    assert "waiting for approval" in text and "`PlanRole`" in text and "IAM statements that change" in text
    assert "+ PlanRole / read-only-dry-run" in text and "cloudformation:GetTemplate" in text and "Nothing has been applied" in text
    assert not cloud.executed


def test_a_plan_with_nothing_to_change_ends_quietly_without_asking_anyone(tmp_path):
    cloud = RolesFake(params={"GitHubRepository": "AnthusAI/Papyrus"}, create_status="FAILED", reason="The submitted information didn't contain changes. Submit different information.")
    code, outputs, text = _plan(tmp_path, cloud)
    assert code == 0 and outputs == {"needed": "false"} and "No approval is needed" in text and "waiting for approval" not in text
    assert len(cloud.deleted) == 1  # its empty change set is removed


def test_a_plan_stops_on_a_failed_change_set_and_on_a_stack_in_a_bad_state(tmp_path):
    with pytest.raises(sd.Failed, match="could not be created"):
        _plan(tmp_path, RolesFake(params={"GitHubRepository": "x"}, create_status="FAILED", reason="Template format error"))
    with pytest.raises(sd.Stop, match="UPDATE_ROLLBACK_FAILED"):
        _plan(tmp_path, RolesFake(stack_status="UPDATE_ROLLBACK_FAILED"))


def test_a_plan_removes_its_own_earlier_unexecuted_change_sets_only(tmp_path):
    old = [{"ChangeSetName": "roles-aaaa-1-1", "ExecutionStatus": "AVAILABLE"}, {"ChangeSetName": "roles-bbbb-1-1", "ExecutionStatus": "EXECUTE_COMPLETE"},
           {"ChangeSetName": "someone-elses", "ExecutionStatus": "AVAILABLE"}]
    cloud = RolesFake(params={"GitHubRepository": "x"}, change_sets=old, changes=[change("PlanRole")])
    _plan(tmp_path, cloud)
    assert cloud.deleted == ["roles-aaaa-1-1"]


def test_the_iam_view_shows_added_and_removed_statements_with_actions_and_resources():
    old = sd.parse_template(REPO_PIPELINE)
    new = sd.parse_template(REPO_PIPELINE.replace("cloudformation:DeleteChangeSet", "cloudformation:DeleteStack", 1))
    view = rs.iam_view(old, new)
    assert view.startswith("```diff") and "- DeployRole / change-sets-on-the-shared-stacks" in view and "+ DeployRole / change-sets-on-the-shared-stacks" in view
    assert "cloudformation:DeleteStack" in view and "stack/papyrus-monitoring" in view
    assert rs.iam_view(old, old) == "No IAM statement changes."


APPLY_RUN = [("UPDATE_COMPLETE", "AVAILABLE"), ("UPDATE_IN_PROGRESS", "EXECUTE_IN_PROGRESS"), ("UPDATE_COMPLETE", "EXECUTE_COMPLETE")]


def _apply(tmp_path, cloud, sha=None, stamp="none"):
    ctx = make(tmp_path, cloud)
    sha = sha or rs.template_sha(REPO_PIPELINE)
    code = rs.apply(ctx, PIPELINE_TEMPLATE, "roles-x-1-1", sha, stamp)
    return code, "\n".join(ctx.messages)


def test_apply_executes_the_exact_change_set_once_then_verifies_the_deployed_template(tmp_path):
    cloud = RolesFake(params={"GitHubRepository": "x"}, deployed=REPO_PIPELINE, script=list(APPLY_RUN), changes=[change("PlanRole")])
    code, text = _apply(tmp_path, cloud)
    assert code == 0 and cloud.executed and "Applied and verified" in text and cloud.slept >= 2


@pytest.mark.parametrize("what", ["template", "stack", "not-ready", "wrong-template"])
def test_apply_refuses_and_executes_nothing_when_anything_moved_since_the_plan(tmp_path, what):
    kwargs = {"params": {"GitHubRepository": "x"}, "deployed": REPO_PIPELINE, "script": list(APPLY_RUN)}
    call = {}
    if what == "template":
        call["sha"] = "0" * 16
    elif what == "stack":
        call["stamp"] = "2026-11-05 12:00:00"
    elif what == "not-ready":
        kwargs["create_status"] = "FAILED"
    else:
        kwargs["cs_template"] = "Resources: {}\n"
    cloud = RolesFake(**kwargs)
    with pytest.raises(sd.Stop, match="nothing was executed"):
        _apply(tmp_path, cloud, **call)
    assert not cloud.executed


def test_a_failed_apply_names_the_first_failed_resource_and_reports_the_clean_state(tmp_path):
    events = [{"EventId": "2", "Timestamp": "2026-11-05T12:00:02", "LogicalResourceId": "DeployRole", "ResourceStatus": "UPDATE_FAILED", "ResourceStatusReason": "not authorized to perform iam:PutRolePolicy"}]
    cloud = RolesFake(params={"GitHubRepository": "x"}, deployed=REPO_PIPELINE, later=events,
                      script=[("UPDATE_COMPLETE", "AVAILABLE"), ("UPDATE_ROLLBACK_IN_PROGRESS", "EXECUTE_IN_PROGRESS"), ("UPDATE_ROLLBACK_COMPLETE", "EXECUTE_FAILED")])
    code, text = _apply(tmp_path, cloud)
    assert code == 1 and "DeployRole UPDATE_FAILED: not authorized to perform iam:PutRolePolicy" in text
    assert "rolled the update back" in text and not cloud.stack_deleted


def test_a_first_create_that_rolls_back_is_deleted_so_the_next_run_starts_clean(tmp_path):
    cloud = RolesFake(stack_status=None, deployed=REPO_PIPELINE,
                      script=[("CREATE_COMPLETE", "AVAILABLE"), ("CREATE_IN_PROGRESS", "EXECUTE_IN_PROGRESS"), ("ROLLBACK_COMPLETE", "EXECUTE_FAILED")])
    code, text = _apply(tmp_path, cloud)
    assert code == 1 and cloud.stack_deleted and "deleted so the next run starts clean" in text


def test_a_stack_that_finishes_but_differs_from_the_repository_fails_the_verify(tmp_path):
    cloud = RolesFake(params={"GitHubRepository": "x"}, deployed=STALE_PIPELINE, script=list(APPLY_RUN))
    with pytest.raises(sd.Failed, match="differ"):
        _apply(tmp_path, cloud)
