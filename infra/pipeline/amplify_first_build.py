#!/usr/bin/env python3
"""Start the first build of a Papyrus site's Amplify app by itself, and only when the two person-only steps are done.

A brand-new site backend is too big for one CloudFormation operation, so the first build runs twice (docs/site-hosting.md, "Start a new
Papyrus site: the two-deploy first backend"): pass 1 with the branch variable PAPYRUS_BOOTSTRAP_STAGE=1, then pass 2 without it.

  check   Read-only. Is the app ready: does the app-shell stack exist with its CmsAppId, does the Amplify app have a repository connected
          (person step 1), and do the Google client parameters exist in SSM (person step 2)? Prints one plain status line and writes
          ready=true|false and reason=... to $GITHUB_OUTPUT. Anything missing is ready=false, never an error exit. Lists parameter NAMES
          only: it never reads a parameter value.
  run     Needs write rights on the Amplify app. Idempotent and resumable: it reads the branch's jobs and variables and does the next step.
          Writes done=true|false and phase=... to $GITHUB_OUTPUT. Exit 1 when a first-build job failed (a person reads the job log), or on
          timeout; exit 0 when done, and when the app is not ready (with a notice).

The Amplify app id and variable values are never printed or written to $GITHUB_OUTPUT. AWS goes only through AmplifyCli, which tests replace.

A failed first create can leave the Amplify backend root stack amplify-<appId>-<branch>-branch-<hash> in ROLLBACK_COMPLETE. CloudFormation
cannot update such a stack, so a person (or the pipeline) must delete it before the build is retried with --retry-failed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BOOTSTRAP_VARIABLE = "PAPYRUS_BOOTSTRAP_STAGE"
PASS_1_MESSAGE = "first-build pass 1"
PASS_2_MESSAGE = "first-build pass 2"
GOOGLE_SUFFIXES = ("/GOOGLE_CLIENT_ID", "/GOOGLE_CLIENT_SECRET")
ACTIVE = {"PENDING", "PROVISIONING", "RUNNING", "BUILDING", "DEPLOYING", "CANCELLING"}
SUCCESS = {"SUCCEED", "SUCCEEDED"}   # the Amplify API says SUCCEED
POLL_SECONDS = 20
DEFAULT_TIMEOUT_MINUTES = 50


class AwsError(RuntimeError):
    pass


class AmplifyCli:
    """The only code that talks to AWS. Tests replace it with a fake that has the same methods."""

    def __init__(self, region: str, run=subprocess.run):
        self.region, self._run = region, run

    def _aws(self, *args: str):
        done = self._run(["aws", *args, "--region", self.region, "--output", "json"], capture_output=True, text=True)
        if done.returncode != 0:
            raise AwsError((done.stderr or done.stdout).strip())
        return json.loads(done.stdout) if done.stdout.strip() else {}

    def stack_outputs(self, stack: str) -> dict | None:
        """The stack's outputs as {key: value}, or None when the stack does not exist."""
        try:
            stacks = self._aws("cloudformation", "describe-stacks", "--stack-name", stack)["Stacks"]
        except AwsError as error:
            if "does not exist" in str(error):
                return None
            raise
        return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}

    def get_app(self, app_id: str) -> dict:
        return self._aws("amplify", "get-app", "--app-id", app_id)["app"]

    def parameter_names(self, prefix: str) -> list[str]:
        """Names only (describe-parameters never returns values)."""
        found = self._aws("ssm", "describe-parameters", "--parameter-filters", f"Key=Name,Option=BeginsWith,Values={prefix}")
        return [p["Name"] for p in found.get("Parameters", [])]

    def get_branch(self, app_id: str, branch: str) -> dict:
        return self._aws("amplify", "get-branch", "--app-id", app_id, "--branch-name", branch)["branch"]

    def update_branch_variables(self, app_id: str, branch: str, variables: dict) -> None:
        """Replaces the whole variable map; the caller passes the merged map."""
        try:
            self._aws("amplify", "update-branch", "--app-id", app_id, "--branch-name", branch, "--environment-variables", json.dumps(variables))
        except AwsError:
            raise AwsError("update-branch failed (the message is withheld because it can quote branch variables)") from None

    def list_jobs(self, app_id: str, branch: str) -> list[dict]:
        """Newest first."""
        return self._aws("amplify", "list-jobs", "--app-id", app_id, "--branch-name", branch).get("jobSummaries", [])

    def get_job(self, app_id: str, branch: str, job_id: str) -> dict:
        return self._aws("amplify", "get-job", "--app-id", app_id, "--branch-name", branch, "--job-id", job_id)["job"]["summary"]

    def start_job(self, app_id: str, branch: str, commit_id: str, message: str) -> str:
        return self._aws("amplify", "start-job", "--app-id", app_id, "--branch-name", branch, "--job-type", "RELEASE",
                         "--commit-id", commit_id, "--commit-message", message)["jobSummary"]["jobId"]


class Reporter:
    """Prints and writes $GITHUB_OUTPUT; masks the app id and any 12-digit number in everything it prints."""

    def __init__(self, output_path: str | None = None, out=sys.stdout):
        self.output_path, self.out, self.hidden = output_path, out, set()

    def mask(self, text: str) -> str:
        for secret in self.hidden:
            text = text.replace(secret, "<app>")
        return re.sub(r"\b\d{12}\b", "<account>", text)

    def say(self, text: str) -> None:
        print(self.mask(text), file=self.out, flush=True)

    def output(self, **values: str) -> None:
        if self.output_path:
            with open(self.output_path, "a", encoding="utf-8") as handle:
                for key, value in values.items():
                    handle.write(f"{key}={self.mask(' '.join(str(value).split()))}\n")


def readiness(cli, stack: str, report: Reporter) -> tuple[bool, str, str]:
    """(ready, reason, app id). The app id is returned for the caller's use and registered for masking; it is never printed."""
    try:
        outputs = cli.stack_outputs(stack)
        if outputs is None:
            return False, f"the stack {stack} does not exist yet (the app shell has not deployed)", ""
        app_id = outputs.get("CmsAppId", "")
        if not app_id:
            return False, f"the stack {stack} has no CmsAppId output yet", ""
        report.hidden.add(app_id)
        if not (cli.get_app(app_id).get("repository") or "").strip():
            return False, "the Amplify app has no repository connected yet (person step: connect the GitHub repository in the Amplify console)", app_id
        names = cli.parameter_names(f"/amplify/{app_id}/")
        missing = [s.lstrip("/") for s in GOOGLE_SUFFIXES if not any(n.endswith(s) for n in names)]
        if missing:
            return False, f"the Google sign-in parameters are missing in SSM: {', '.join(missing)} (person step: papyrus site google-secrets set)", app_id
    except AwsError as error:
        return False, f"could not read the app's state: {error}", ""
    return True, "the repository is connected and the Google client parameters exist", app_id


def check(cli, args, report: Reporter) -> int:
    ready, reason, _ = readiness(cli, args.stack_name, report)
    report.say(f"first build: {'ready to start' if ready else 'not ready'} - {reason}")
    report.output(ready="true" if ready else "false", reason=reason)
    return 0


class Stop(Exception):
    def __init__(self, phase: str, message: str):
        super().__init__(message)
        self.phase = phase


def first_build_jobs(jobs: list[dict]) -> list[dict]:
    return [j for j in jobs if j.get("commitMessage") in (PASS_1_MESSAGE, PASS_2_MESSAGE)]


class FirstBuild:
    def __init__(self, cli, app_id: str, branch: str, commit_id: str, deadline: float, report: Reporter, sleeper, clock, retry_failed: bool):
        self.cli, self.app_id, self.branch, self.commit_id = cli, app_id, branch, commit_id
        self.deadline, self.report, self.sleep, self.now, self.retry_failed = deadline, report, sleeper, clock, retry_failed

    def wait(self, job_id: str, label: str) -> str:
        self.report.output(phase=label)
        while True:
            status = self.cli.get_job(self.app_id, self.branch, job_id)["status"]
            if status not in ACTIVE:
                self.report.say(f"first build: {label} finished with status {status}")
                return status
            if self.now() >= self.deadline:
                raise Stop("timeout", f"first build: {label} was still {status} when the time limit ran out. Run it again to resume waiting; "
                                      "the job itself keeps running in Amplify.")
            self.report.say(f"first build: {label} is {status}")
            self.sleep(POLL_SECONDS)

    def variables(self) -> dict:
        return dict(self.cli.get_branch(self.app_id, self.branch).get("environmentVariables") or {})

    def set_bootstrap_variable(self, present: bool) -> None:
        current = self.variables()
        if present and current.get(BOOTSTRAP_VARIABLE) == "1":
            return
        if not present and BOOTSTRAP_VARIABLE not in current:
            return
        merged = {**current, BOOTSTRAP_VARIABLE: "1"} if present else {k: v for k, v in current.items() if k != BOOTSTRAP_VARIABLE}
        self.cli.update_branch_variables(self.app_id, self.branch, merged)
        self.report.say(f"first build: {BOOTSTRAP_VARIABLE} {'set' if present else 'removed'} on the branch (other variables kept)")

    def failed(self, label: str) -> Stop:
        return Stop("failed", f"first build: {label} did not succeed. A person reads the Amplify job log, fixes the cause and runs this again with "
                              "--retry-failed. If the backend's first create failed, the Amplify backend root stack "
                              "amplify-<appId>-<branch>-branch-<hash> may be in ROLLBACK_COMPLETE; it must be deleted by a person or the pipeline first.")

    def pass_one(self) -> None:
        self.set_bootstrap_variable(True)
        job = self.cli.start_job(self.app_id, self.branch, self.commit_id, PASS_1_MESSAGE)
        if self.wait(job, "pass 1") not in SUCCESS:
            raise self.failed("pass 1")

    def pass_two(self) -> None:
        self.set_bootstrap_variable(False)
        job = self.cli.start_job(self.app_id, self.branch, self.commit_id, PASS_2_MESSAGE)
        if self.wait(job, "pass 2") not in SUCCESS:
            raise self.failed("pass 2")

    def drive(self) -> None:
        for _ in range(6):   # each round does one step; the bound means this can never loop
            ours = first_build_jobs(self.cli.list_jobs(self.app_id, self.branch))
            p1 = [j for j in ours if j["commitMessage"] == PASS_1_MESSAGE]
            p2 = [j for j in ours if j["commitMessage"] == PASS_2_MESSAGE]
            if any(j["status"] in SUCCESS for j in p2):
                return
            active = [j for j in ours if j["status"] in ACTIVE]
            if active:
                label = "pass 1" if active[0]["commitMessage"] == PASS_1_MESSAGE else "pass 2"
                self.report.say(f"first build: {label} is already running; waiting for it")
                if self.wait(active[0]["jobId"], label) not in SUCCESS:
                    raise self.failed(label)
                continue
            if ours and not self.retry_failed:
                newest = ours[0]
                if newest["status"] not in SUCCESS:
                    raise self.failed("pass 1" if newest["commitMessage"] == PASS_1_MESSAGE else "pass 2")
            if any(j["status"] in SUCCESS for j in p1):
                self.pass_two()
                return
            self.pass_one()
        raise Stop("failed", "first build: gave up after repeated rounds; a person looks at the Amplify jobs")


def run(cli, args, report: Reporter, sleeper=time.sleep, clock=time.monotonic) -> int:
    ready, reason, app_id = readiness(cli, args.stack_name, report)
    if not ready:
        report.say(f"first build: nothing started, not ready - {reason}")
        report.output(done="false", phase="not-ready")
        return 0
    deadline = clock() + args.timeout_minutes * 60
    try:
        FirstBuild(cli, app_id, args.branch, args.commit_id, deadline, report, sleeper, clock, args.retry_failed).drive()
    except Stop as stop:
        report.say(str(stop))
        report.output(done="false", phase=stop.phase)
        return 1
    except AwsError as error:
        report.say(f"first build: AWS refused a call: {error}")
        report.output(done="false", phase="failed")
        return 1
    report.say("first build: done (pass 2 succeeded)")
    report.output(done="true", phase="done")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("check", "run"):
        s = sub.add_parser(name)
        s.add_argument("--stack-name", required=True, help="the app-shell stack; its output CmsAppId is the Amplify app")
        s.add_argument("--branch", default="main")
        s.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")
        if name == "run":
            s.add_argument("--commit-id", required=True)
            s.add_argument("--timeout-minutes", type=float, default=DEFAULT_TIMEOUT_MINUTES)
            s.add_argument("--retry-failed", action="store_true", help="start again although a first-build job failed (after a person fixed the cause)")
    return p


def main(argv=None, cli=None, sleeper=time.sleep, clock=time.monotonic) -> int:
    args = parser().parse_args(argv)
    report = Reporter(os.environ.get("GITHUB_OUTPUT"))
    cli = cli or AmplifyCli(args.region)
    return check(cli, args, report) if args.command == "check" else run(cli, args, report, sleeper, clock)


if __name__ == "__main__":
    sys.exit(main())
