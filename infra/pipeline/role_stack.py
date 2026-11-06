#!/usr/bin/env python3
"""Plan and apply the papyrus-stack-pipeline stack (the pipeline's own roles) from GitHub, after a person approves (PPY-9d1b3e).

  plan                                create a change set from the template on this commit, print it (with an IAM view) as a job summary,
                                      and write `needed=`, `change_set=`, `template_sha=` and `stamp=` to $GITHUB_OUTPUT. No approval needed.
  apply --change-set N --template-sha S --stamp T
                                      run in the approval-gated environment: refuse if the stack or the template moved since the plan,
                                      execute that exact change set, poll it, verify the deployed template equals the repository.

Used by .github/workflows/role-stack-deploy.yml. Tested by procedures/newsroom/tests/test_stack_deploy.py.
Exit codes: 0 done or nothing to do, 1 failed, 2 a safety check refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stack_deploy as sd  # noqa: E402

STACK = sd.PIPELINE_STACK
CHANGE_PREFIX = "roles-"
SERVICE_ROLE = "papyrus-pipeline-roles-cloudformation"


class RolesCli(sd.AwsCli):
    def create_roles_change_set(self, name: str, kind: str, template_path: Path, parameters: list[dict], role_arn: str) -> None:
        self._aws("cloudformation", "create-change-set", "--stack-name", STACK, "--change-set-name", name, "--change-set-type", kind.upper(),
                  "--template-body", f"file://{template_path}", "--parameters", json.dumps(parameters), "--role-arn", role_arn,
                  "--capabilities", "CAPABILITY_NAMED_IAM")

    def change_set_template(self, name: str) -> str:
        body = self._aws("cloudformation", "get-template", "--stack-name", STACK, "--change-set-name", name, "--template-stage", "Original")["TemplateBody"]
        return body if isinstance(body, str) else json.dumps(body)

    def delete_stack(self) -> None:
        self._aws("cloudformation", "delete-stack", "--stack-name", STACK, parse=False)


# ------------------------------------------------------------------------------------------------------------- the IAM view


def iam_lines(template: dict) -> set[str]:
    """One line per IAM statement in the template: who it is on, its effect, actions, resources and conditions. Intrinsics are shown as written."""
    def compact(value) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    def as_list(value):
        return value if isinstance(value, list) else [value]

    lines = set()
    for logical, resource in template.get("Resources", {}).items():
        kind, props = resource.get("Type", ""), resource.get("Properties", {})
        documents = []
        if kind == "AWS::IAM::ManagedPolicy":
            documents.append((logical, props.get("PolicyDocument", {})))
        elif kind == "AWS::IAM::Role":
            documents.append((f"{logical} (who may assume it)", props.get("AssumeRolePolicyDocument", {})))
            documents += [(f"{logical} / {p.get('PolicyName')}", p.get("PolicyDocument", {})) for p in props.get("Policies", [])]
            lines |= {f"{logical} attaches {compact(arn)}" for arn in props.get("ManagedPolicyArns", [])}
        for where, document in documents:
            for statement in as_list(document.get("Statement", [])):
                parts = [where, f"sid {statement.get('Sid', '-')}", statement.get("Effect", "?")]
                for key in ("Principal", "Action", "Resource", "Condition"):
                    if key in statement:
                        value = statement[key]
                        parts.append(f"{key.lower()} " + (", ".join(sorted(map(compact, as_list(value)))) if key in ("Action", "Resource") else compact(value)))
                lines.add(" | ".join(parts))
    return lines


def iam_view(old: dict, new: dict) -> str:
    before, after = iam_lines(old), iam_lines(new)
    added, removed = sorted(after - before), sorted(before - after)
    if not added and not removed:
        return "No IAM statement changes."
    return "```diff\n" + "\n".join([f"- {line}" for line in removed] + [f"+ {line}" for line in added]) + "\n```"


# ------------------------------------------------------------------------------------------------------------------ plan


def stamp_of(stack: dict | None) -> str:
    return "none" if stack is None else str(stack.get("LastUpdatedTime") or stack.get("CreationTime") or "none")


def template_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def delete_stale(cloud, ctx_out) -> None:
    for item in cloud.list_change_sets(STACK):
        if item["ChangeSetName"].startswith(CHANGE_PREFIX) and item.get("ExecutionStatus") == "AVAILABLE":
            cloud.delete_change_set(STACK, item["ChangeSetName"])
            ctx_out(f"deleted the earlier unexecuted change set {item['ChangeSetName']}")


def plan(ctx: sd.Context, template_path: Path, tag: str, outputs) -> int:
    cloud = ctx.cloud
    stack = cloud.describe_stack(STACK)
    kind, status = sd.classify_stack(stack)  # Stop on a failed or busy stack
    text = template_path.read_text(encoding="utf-8")
    new = sd.parse_template(text)
    sha = template_sha(text)
    if stack is not None:
        delete_stale(cloud, ctx.out)
    current = sd.param_map(stack)
    parameters = sd.parameter_plan(new.get("Parameters", {}), current, {}, True)
    name = f"{CHANGE_PREFIX}{sha[:8]}-{tag}"[:128]
    cloud.create_roles_change_set(name, kind, template_path, parameters, f"arn:aws:iam::{cloud.account()}:role/{SERVICE_ROLE}")
    described = sd.wait_for_change_set(ctx, STACK, name)
    if described["Status"] == "FAILED":
        reason = described.get("StatusReason", "")
        cloud.delete_change_set(STACK, name)
        if "didn't contain changes" in reason or "No updates are to be performed" in reason:
            ctx.out("Nothing to do: the deployed pipeline roles already match the template. No approval is needed.")
            outputs("needed", "false")
            return 0
        raise sd.Failed(f"the change set could not be created: {reason}")

    if not described.get("Changes"):
        # CloudFormation makes a change set whenever the template text differs, even when only a comment or a blank line moved. That change set is
        # CREATE_COMPLETE with no changes, not the "didn't contain changes" failure, so it used to reach a reviewer as an empty table (run 42066386724).
        # Nothing would be applied, so nobody is asked, and the unexecuted change set is removed.
        cloud.delete_change_set(STACK, name)
        ctx.write_summary("## Pipeline roles: nothing to do\n"
                          f"The template on this commit (fingerprint `{sha}`) differs from the deployed text, but CloudFormation found no resource or permission change "
                          "(a comment or formatting edit). No approval is needed and nothing was applied.")
        outputs("needed", "false")
        return 0

    _, lines = sd.review_changes(STACK, described.get("Changes", []), [])
    table = "| Action | Logical id | Type | Replacement |\n| --- | --- | --- | --- |\n" + "\n".join(lines)
    live = sd.parse_template(cloud.get_template(STACK)) if stack is not None else {}
    ctx.write_summary(
        f"## Pipeline roles: a change is waiting for approval\n"
        f"Stack `{STACK}` ({status}, a {kind} change set). Template fingerprint `{sha}`, change set `{name}`.\n\n"
        f"### Every change\n{table}\n\n### IAM statements that change (roles, policies, actions, resources)\n{iam_view(live, new)}\n\n"
        f"Nothing has been applied. The next job, `apply`, waits for a reviewer to approve the `pipeline-roles` deployment in GitHub, and then "
        f"executes exactly this change set. Reject the deployment to leave the roles as they are.")
    outputs("needed", "true")
    outputs("change_set", name)
    outputs("template_sha", sha)
    outputs("stamp", stamp_of(stack))
    return 0


# ----------------------------------------------------------------------------------------------------------------- apply


def apply(ctx: sd.Context, template_path: Path, change_set: str, expect_sha: str, expect_stamp: str) -> int:
    cloud = ctx.cloud
    text = template_path.read_text(encoding="utf-8")
    if template_sha(text) != expect_sha:
        raise sd.Stop("the template on this commit is not the one that was planned; nothing was executed. Merge again and approve the new plan.")
    stack = cloud.describe_stack(STACK)
    kind, status = sd.classify_stack(stack)
    if stamp_of(stack) != expect_stamp:
        raise sd.Stop(f"the {STACK} stack changed after the plan (it was {expect_stamp}, it is {stamp_of(stack)}); nothing was executed. Run the workflow again.")
    described = cloud.describe_change_set(STACK, change_set)
    if described.get("Status") != "CREATE_COMPLETE" or described.get("ExecutionStatus") != "AVAILABLE":
        raise sd.Stop(f"change set {change_set} is {described.get('Status')}/{described.get('ExecutionStatus')}, not ready to execute; nothing was executed.")
    if sd.parse_template(cloud.change_set_template(change_set)) != sd.parse_template(text):
        raise sd.Stop(f"change set {change_set} was not made from the template on this commit; nothing was executed.")

    try:
        known = {e["EventId"] for e in cloud.stack_events(STACK)}
    except sd.AwsError:
        known = set()
    ctx.write_summary(f"## Applying `{change_set}` to `{STACK}` ({status}, a {kind})")
    cloud.execute_change_set(STACK, change_set)
    try:
        sd.wait_for_execution(ctx, STACK, change_set, known)
    except sd.Failed as failure:
        ctx.write_summary(f"### Apply FAILED\nFirst failed resource, then the state left behind:\n```\n{failure}\n```")
        after = cloud.describe_stack(STACK)
        end = (after or {}).get("StackStatus", "GONE")
        if kind == "create" and end == "ROLLBACK_COMPLETE":
            cloud.delete_stack()
            ctx.write_summary("The first create rolled back, so nothing was created; the empty stack was deleted so the next run starts clean.")
        else:
            ctx.write_summary(f"The stack is now `{end}`." + (" CloudFormation rolled the update back; the roles are as they were." if end == "UPDATE_ROLLBACK_COMPLETE" else " A person must look at it."))
        return 1
    state, detail = sd.pipeline_state(cloud, text)
    if state != "same":
        raise sd.Failed(f"the stack finished but {detail}")
    ctx.write_summary("Applied and verified: the deployed pipeline roles equal infra/pipeline/papyrus-stack-pipeline.yaml.")
    return 0


# ------------------------------------------------------------------------------------------------------------ command line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    run = sub.add_parser("apply")
    run.add_argument("--change-set", required=True)
    run.add_argument("--template-sha", required=True)
    run.add_argument("--stamp", required=True)
    args = parser.parse_args(argv)

    cloud = RolesCli(sd.load_json(sd.CONFIG_PATH)["region"])
    expected = os.environ.get("AWS_ACCOUNT_ID", "")
    if not expected or cloud.account() != expected:
        print("refusing: the caller account is not the AWS_ACCOUNT_ID variable", file=sys.stderr)
        return 2
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    tag = f"{os.environ.get('GITHUB_RUN_ID', '0')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    ctx = sd.Context(cloud, {}, [], tag, summary=Path(summary) if summary else None)
    try:
        if args.command == "plan":
            return plan(ctx, sd.PIPELINE_TEMPLATE, tag, sd.github_output)
        return apply(ctx, sd.PIPELINE_TEMPLATE, args.change_set, args.template_sha, args.stamp)
    except sd.Stop as stop:
        print(f"::error::STOPPED, nothing executed: {stop}")
        ctx.write_summary(f"### STOPPED, nothing executed\n{stop}")
        return 2
    except (sd.Failed, sd.AwsError) as failure:
        extra = ""
        if sd.re.search(r"not authorized|AccessDenied", str(failure), sd.re.IGNORECASE):
            extra = ("\nA role the workflow runs as lacks a permission. The small approver stack (infra/pipeline/papyrus-pipeline-approver.yaml) "
                     "is changed only by a person, with infra/pipeline/bootstrap.sh --approver-only.")
        print(f"::error::FAILED: {failure}{extra}")
        ctx.write_summary(f"### FAILED\n```\n{failure}\n```{extra}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
