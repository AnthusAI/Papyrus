"""The first build starts by itself: amplify_first_build.py against a fake Amplify, the two workflows, and the watch role in the baseline.

Nothing here calls AWS. features/account-pipeline.feature tells the same story in prose.
"""
from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("amplify_first_build", ROOT / "infra" / "pipeline" / "amplify_first_build.py")
afb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(afb)

APP = "d1abcdefghijk"
STACK = "demo-cms"
SECRET_VALUE = "super-secret-variable-value"
NAMES = [f"/amplify/{APP}/main-branch-0123456789/GOOGLE_CLIENT_ID", f"/amplify/{APP}/main-branch-0123456789/GOOGLE_CLIENT_SECRET"]


class FakeAmplify:
    """Same methods as AmplifyCli. `job_plan` maps a pass message to the status the job ends with."""

    def __init__(self, outputs=None, repository="https://github.com/o/r", names=None, variables=None, jobs=None, plan=None):
        self.outputs = {"CmsAppId": APP} if outputs is None else outputs
        self.repository, self.names = repository, list(NAMES if names is None else names)
        self.variables = dict({"KEEP": SECRET_VALUE, "OTHER": "x"} if variables is None else variables)
        self.jobs = list(jobs or [])           # newest first
        self.plan = plan or {}
        self.calls, self.polls, self.counter = [], {}, 0

    def stack_outputs(self, stack):
        self.calls.append("describe-stacks")
        return self.outputs

    def get_app(self, app_id):
        self.calls.append("get-app")
        return {"repository": self.repository}

    def parameter_names(self, prefix):
        self.calls.append(f"describe-parameters {prefix}")
        return [n for n in self.names if n.startswith(prefix)]

    def get_branch(self, app_id, branch):
        self.calls.append("get-branch")
        return {"environmentVariables": dict(self.variables)}

    def update_branch_variables(self, app_id, branch, variables):
        self.calls.append("update-branch " + ("with" if afb.BOOTSTRAP_VARIABLE in variables else "without"))
        self.variables = dict(variables)

    def list_jobs(self, app_id, branch):
        self.calls.append("list-jobs")
        return list(self.jobs)

    def start_job(self, app_id, branch, commit_id, message):
        self.counter += 1
        job_id = str(self.counter)
        self.calls.append(f"start {message}")
        self.started_with = (commit_id, message)
        self.jobs.insert(0, {"jobId": job_id, "commitMessage": message, "status": "PENDING"})
        self.polls[job_id] = 0
        return job_id

    def get_job(self, app_id, branch, job_id):
        job = next(j for j in self.jobs if j["jobId"] == job_id)
        self.polls[job_id] = self.polls.get(job_id, 0) + 1
        if self.polls[job_id] == 1:
            job["status"] = "RUNNING"
        else:
            job["status"] = self.plan.get(job["commitMessage"], "SUCCEED")
        self.calls.append("get-job")
        return {"jobId": job_id, "status": job["status"]}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def execute(fake, command="run", extra=(), tmp_path=None, monkeypatch=None):
    out = tmp_path / "github-output"
    out.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    clock = Clock()
    buffer = io.StringIO()
    real = afb.Reporter

    class Capturing(real):
        def __init__(self, path=None, out=None):
            super().__init__(path, buffer)

    monkeypatch.setattr(afb, "Reporter", Capturing)
    argv = [command, "--stack-name", STACK, *(["--commit-id", "abc123"] if command == "run" else []), *extra]
    code = afb.main(argv, cli=fake, sleeper=clock.sleep, clock=clock)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines())
    return code, buffer.getvalue(), outputs, clock


def mutations(fake):
    return [c for c in fake.calls if c.startswith(("update-branch", "start"))]


# ---- check -------------------------------------------------------------------------------------------------------------------------------

def test_check_ready_when_all_three_conditions_hold(tmp_path, monkeypatch):
    code, text, out, _ = execute(FakeAmplify(), "check", tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["ready"] == "true" and "reason" in out and "app-id" not in out
    assert APP not in text and APP not in "".join(out.values())


class StackMissing(FakeAmplify):
    def stack_outputs(self, stack):
        return None


@pytest.mark.parametrize("fake,reason", [
    (StackMissing(), "does not exist"),
    (FakeAmplify(outputs={"Other": "x"}), "no CmsAppId"),
    (FakeAmplify(repository=""), "no repository connected"),
    (FakeAmplify(repository=None), "no repository connected"),
    (FakeAmplify(names=[]), "GOOGLE_CLIENT_ID"),
    (FakeAmplify(names=[NAMES[0]]), "GOOGLE_CLIENT_SECRET"),
    (FakeAmplify(names=[f"/amplify/dother0000000/x/{n.rsplit('/', 1)[1]}" for n in NAMES]), "GOOGLE_CLIENT_ID"),
])
def test_check_not_ready_gives_the_reason_and_no_error_exit(fake, reason, tmp_path, monkeypatch):
    code, text, out, _ = execute(fake, "check", tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["ready"] == "false" and reason in out["reason"]
    assert APP not in text and APP not in "".join(out.values())


def test_check_is_read_only_and_never_reads_a_parameter_value(tmp_path, monkeypatch):
    fake = FakeAmplify()
    execute(fake, "check", tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert fake.calls == ["describe-stacks", "get-app", f"describe-parameters /amplify/{APP}/"]
    source = (ROOT / "infra" / "pipeline" / "amplify_first_build.py").read_text()
    assert "get-parameter" not in source.replace("never get-parameter", "")
    assert "with-decryption" not in source


def test_aws_errors_in_check_become_not_ready(tmp_path, monkeypatch):
    class Broken(FakeAmplify):
        def get_app(self, app_id):
            raise afb.AwsError(f"AccessDenied on arn:aws:amplify:us-east-1:123456789012:apps/{APP}")
    code, text, out, _ = execute(Broken(), "check", tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["ready"] == "false"
    assert APP not in text and "123456789012" not in text and "123456789012" not in out["reason"]


# ---- run ---------------------------------------------------------------------------------------------------------------------------------

P1, P2 = afb.PASS_1_MESSAGE, afb.PASS_2_MESSAGE


def job(message, status, job_id="9"):
    return {"jobId": job_id, "commitMessage": message, "status": status}


def test_first_run_order_of_calls(tmp_path, monkeypatch):
    fake = FakeAmplify()
    code, text, out, clock = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["done"] == "true" and out["phase"] == "done"
    assert mutations(fake) == ["update-branch with", "start first-build pass 1", "update-branch without", "start first-build pass 2"]
    assert fake.started_with == ("abc123", P2)
    assert afb.BOOTSTRAP_VARIABLE not in fake.variables
    assert clock.t == 2 * afb.POLL_SECONDS          # each pass polled once while RUNNING, sleeping between polls


def test_update_branch_merges_and_preserves_other_variables(tmp_path, monkeypatch):
    fake = FakeAmplify(variables={"KEEP": SECRET_VALUE, "OTHER": "x,y=z"})
    seen = []
    original = fake.update_branch_variables
    fake.update_branch_variables = lambda a, b, v: (seen.append(dict(v)), original(a, b, v))
    execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert seen[0] == {"KEEP": SECRET_VALUE, "OTHER": "x,y=z", afb.BOOTSTRAP_VARIABLE: "1"}
    assert seen[1] == {"KEEP": SECRET_VALUE, "OTHER": "x,y=z"}


def test_never_prints_the_app_id_or_variable_values(tmp_path, monkeypatch):
    fake = FakeAmplify()
    code, text, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    everything = text + "".join(out.values())
    assert APP not in everything and SECRET_VALUE not in everything and "abc123" not in everything


def test_resume_after_pass_1_succeeded_starts_pass_2_only(tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[job(P1, "SUCCEED")], variables={"KEEP": "k", afb.BOOTSTRAP_VARIABLE: "1"})
    code, _, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["done"] == "true"
    assert mutations(fake) == ["update-branch without", "start first-build pass 2"]
    assert fake.variables == {"KEEP": "k"}


def test_resume_with_the_variable_already_absent_does_not_update_the_branch(tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[job(P1, "SUCCEED")])
    execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert mutations(fake) == ["start first-build pass 2"]


def test_pass_2_succeeded_means_done_and_nothing_else_happens(tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[job(P2, "SUCCEED", "2"), job(P1, "SUCCEED", "1")])
    code, _, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["done"] == "true" and mutations(fake) == []


def test_a_running_job_is_waited_for_then_the_flow_continues(tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[job(P1, "RUNNING", "7")])
    fake.polls["7"] = 1
    code, _, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["done"] == "true"
    assert mutations(fake) == ["start first-build pass 2"]          # no new pass 1, no variable set


def test_a_running_pass_2_is_waited_for_and_finishes_the_run(tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[job(P2, "RUNNING", "7"), job(P1, "SUCCEED", "6")])
    fake.polls["7"] = 1
    code, _, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["done"] == "true" and mutations(fake) == []


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_a_failed_pass_1_stops_with_exit_1_and_never_loops(status, tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[job(P1, status)])
    code, text, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 1 and out["done"] == "false" and out["phase"] == "failed"
    assert mutations(fake) == [] and "ROLLBACK_COMPLETE" in text and "job log" in text


def test_a_pass_1_that_fails_during_this_run_stops_before_pass_2(tmp_path, monkeypatch):
    fake = FakeAmplify(plan={P1: "FAILED"})
    code, text, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 1 and out["done"] == "false"
    assert mutations(fake) == ["update-branch with", "start first-build pass 1"]


def test_a_failed_pass_2_stops_and_does_not_restart(tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[job(P2, "FAILED", "2"), job(P1, "SUCCEED", "1")])
    code, _, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 1 and mutations(fake) == []


def test_retry_failed_restarts_the_right_pass(tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[job(P2, "FAILED", "2"), job(P1, "SUCCEED", "1")])
    code, _, out, _ = execute(fake, extra=["--retry-failed"], tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["done"] == "true" and mutations(fake) == ["start first-build pass 2"]
    fake = FakeAmplify(jobs=[job(P1, "FAILED", "1")])
    code, _, out, _ = execute(fake, extra=["--retry-failed"], tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and mutations(fake)[:2] == ["update-branch with", "start first-build pass 1"]


def test_other_jobs_are_ignored(tmp_path, monkeypatch):
    fake = FakeAmplify(jobs=[{"jobId": "5", "commitMessage": "feat: something", "status": "FAILED"}])
    code, _, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["done"] == "true"


@pytest.mark.parametrize("fake", [StackMissing(), FakeAmplify(repository=""), FakeAmplify(names=[])])
def test_run_when_not_ready_starts_nothing_and_exits_0(fake, tmp_path, monkeypatch):
    code, text, out, _ = execute(fake, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 0 and out["done"] == "false" and out["phase"] == "not-ready" and "not ready" in text
    assert mutations(fake) == []


def test_timeout_stops_with_exit_1_and_says_to_run_again(tmp_path, monkeypatch):
    class Stuck(FakeAmplify):
        def get_job(self, app_id, branch, job_id):
            return {"jobId": job_id, "status": "RUNNING"}
    code, text, out, clock = execute(Stuck(), extra=["--timeout-minutes", "1"], tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert code == 1 and out["phase"] == "timeout" and "Run it again" in text and clock.t >= 60


def test_aws_command_lines_without_a_network(monkeypatch):
    """AmplifyCli builds the documented commands; update-branch carries JSON and a failure does not echo its message."""
    seen = []

    class Done:
        def __init__(self, out="{}", code=0, err=""):
            self.stdout, self.returncode, self.stderr = out, code, err

    def runner(cmd, **kw):
        seen.append(cmd)
        if "update-branch" in cmd:
            return Done(code=1, err=f"bad value {SECRET_VALUE}")
        return Done('{"jobSummary": {"jobId": "3"}}')

    cli = afb.AmplifyCli("us-east-1", run=runner)
    assert cli.start_job(APP, "main", "abc", "first-build pass 1") == "3"
    cmd = seen[0]
    assert cmd[:3] == ["aws", "amplify", "start-job"] and "RELEASE" in cmd and "--commit-id" in cmd and "first-build pass 1" in cmd
    with pytest.raises(afb.AwsError) as raised:
        cli.update_branch_variables(APP, "main", {"A": SECRET_VALUE})
    assert SECRET_VALUE not in str(raised.value)
    assert '{"A": "%s"}' % SECRET_VALUE in seen[1]


# ---- workflows ---------------------------------------------------------------------------------------------------------------------------

WORKFLOWS = ROOT / ".github" / "workflows"
BUILD, WATCH = WORKFLOWS / "first-build.yml", WORKFLOWS / "first-build-watch.yml"


def load(path):
    return yaml.safe_load(path.read_text())


def triggers(doc):
    return doc.get("on", doc.get(True))


@pytest.mark.parametrize("path", [BUILD, WATCH])
def test_workflows_are_reusable_pin_every_action_and_hold_no_secrets(path):
    doc = load(path)
    assert set(triggers(doc)) == {"workflow_call"}
    for job_ in doc["jobs"].values():
        for step in job_["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
    text = path.read_text()
    assert "secrets." not in text and "secrets:" not in text and "AWS_SECRET_ACCESS_KEY" not in text
    assert not re.search(r"\b\d{12}\b", text)
    assert doc["jobs"][next(iter(doc["jobs"]))]["permissions"] == {"contents": "read", "id-token": "write", "actions": "write"}


def test_build_workflow_runs_on_main_only_with_the_deploy_role_and_disables_the_watcher():
    doc = load(BUILD)
    assert set(doc["jobs"]) == {"run"}
    run_job = doc["jobs"]["run"]
    cond = run_job["if"]
    assert "refs/heads/main" in cond and "push" in cond and "workflow_dispatch" in cond and "pull_request" not in cond
    assert run_job["concurrency"]["cancel-in-progress"] is False
    inputs = triggers(doc)["workflow_call"]["inputs"]
    assert {"prefix", "aws-account-id", "papyrus-ref", "stack-name", "region", "branch", "watcher-workflow"} <= set(inputs)
    assert inputs["watcher-workflow"]["default"] == "first-build-watch.yml" and inputs["branch"]["default"] == "main"
    text = BUILD.read_text()
    assert "${{ inputs.prefix }}-github-deploy" in text and "amplify_first_build.py run" in text and "--commit-id \"$GITHUB_SHA\"" in text
    disable = next(s for s in run_job["steps"] if "gh workflow disable" in s.get("run", ""))
    assert disable["if"] == "steps.build.outputs.done == 'true'" and disable["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert any(s.get("id") == "build" for s in run_job["steps"])


def test_watch_workflow_checks_dispatches_then_disables_itself_only_when_ready():
    doc = load(WATCH)
    assert set(doc["jobs"]) == {"watch"}
    inputs = triggers(doc)["workflow_call"]["inputs"]
    assert {"prefix", "aws-account-id", "papyrus-ref", "stack-name", "region", "dispatch-workflow", "watcher-workflow-file"} <= set(inputs)
    assert inputs["dispatch-workflow"]["default"] == "first-build.yml" and inputs["watcher-workflow-file"]["required"]
    steps = doc["jobs"]["watch"]["steps"]
    text = WATCH.read_text()
    assert "${{ inputs.prefix }}-github-watch" in text and "github-deploy" not in text
    assert "amplify_first_build.py check" in text and "amplify_first_build.py run" not in text
    final = steps[-1]
    assert final["if"] == "steps.check.outputs.ready == 'true'"
    assert final["run"].index('gh workflow run "$DISPATCH" --ref main') < final["run"].index('gh workflow disable "$WATCHER"')
    assert not any("if" in s for s in steps[:-1])           # when not ready the job only prints the reason


# ---- the baseline ------------------------------------------------------------------------------------------------------------------------

BASELINE = ROOT / "infra" / "account" / "baseline.yaml"


def baseline():
    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
                                 else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node))
    return yaml.load(BASELINE.read_text(), Loader)


def statements(role):
    return [s for p in role["Properties"]["Policies"] for s in p["PolicyDocument"]["Statement"]]


def test_baseline_has_the_watch_role_trusted_for_the_default_branch_only():
    doc = baseline()
    assert doc["Parameters"]["DefaultBranch"]["Default"] == "develop"
    role = doc["Resources"]["GithubWatchRole"]
    assert role["Properties"]["RoleName"] == "${Prefix}-github-watch" and role["Properties"]["MaxSessionDuration"] == 3600
    trust = role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert len(trust) == 1
    sub = trust[0]["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"]
    assert sub[0] == "${Subject}:ref:refs/heads/${DefaultBranch}"
    assert "ProductionBranch" not in str(trust)
    assert "GithubSubjectPrefix" in str(sub) and "CustomSubject" in str(sub)       # the same custom-subject mechanism as the other roles


def test_watch_role_is_read_only_names_only():
    role = baseline()["Resources"]["GithubWatchRole"]
    actions = sorted(a for s in statements(role) for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"]))
    assert actions == ["amplify:GetApp", "cloudformation:DescribeStacks", "ssm:DescribeParameters"]
    assert all(s["Effect"] == "Allow" for s in statements(role))
    by_action = {s["Action"]: s["Resource"] for s in statements(role)}
    assert "stack/${Prefix}-*/*" in by_action["cloudformation:DescribeStacks"] and "apps/${AmplifyAppId}" in by_action["amplify:GetApp"]


def test_no_role_in_the_baseline_may_read_a_parameter_value_except_the_known_ones():
    doc = baseline()
    assert "ssm:GetParameter" not in str(doc["Resources"]["GithubWatchRole"])
    assert "ssm:GetParameter" not in str(doc["Resources"]["GithubPlanRole"])


def test_deploy_role_gets_the_first_build_statements_scoped_to_the_app_and_branch():
    role = baseline()["Resources"]["GithubDeployRole"]
    stmts = statements(role)
    first = next(s for s in stmts if s["Sid"] == "ReadAndUpdateTheProductionBranch")
    assert sorted(first["Action"]) == ["amplify:GetApp", "amplify:GetBranch", "amplify:ListJobs", "amplify:UpdateBranch"]
    assert all("apps/${AmplifyAppId}" in r for r in first["Resource"]) and any("branches/${ProductionBranch}/jobs/*" in r for r in first["Resource"])
    assert not any(r.endswith("branches/*") for r in first["Resource"])
    names = next(s for s in stmts if s["Action"] == "ssm:DescribeParameters")
    assert names["Resource"] == "*"
    start = next(s for s in stmts if s["Sid"] == "StartAndReadProductionJobs")
    assert start["Action"] == ["amplify:StartJob", "amplify:GetJob"]


def test_the_roles_service_role_covers_the_watch_role_by_pattern():
    text = BASELINE.read_text()
    assert 'role/${Prefix}-github-*"' in text
