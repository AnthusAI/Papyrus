#!/usr/bin/env python3
"""Plan and apply the papyrus-stack-pipeline stack (the pipeline's own roles) from GitHub, with an automatic check instead of an approval click.

  plan                                create a change set from the template on this commit, print it (with an IAM view) as a job summary,
                                      and write `needed=`, `change_set=`, `template_sha=` and `stamp=` to $GITHUB_OUTPUT. The plan stops, and
                                      deletes its change set, when the change breaks a hard rule or touches an IAM statement, or removes or
                                      replaces a resource, that allowed-role-changes.json and allowed-changes.json do not list.
  check --base-ref REF                no AWS: the same checks between the template at REF and the one in this checkout, for a pull request.
  apply --change-set N --template-sha S --stamp T
                                      refuse if the stack or the template moved since the plan, execute that exact change set, poll it,
                                      verify the deployed template equals the repository.

Used by .github/workflows/role-stack-deploy.yml and role-change-check.yml. Tested by procedures/newsroom/tests/test_stack_deploy.py.
Exit codes: 0 done or nothing to do, 1 failed, 2 a safety check refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stack_deploy as sd  # noqa: E402

STACK = sd.PIPELINE_STACK
CHANGE_PREFIX = "roles-"
ALLOWED_ROLE_CHANGES_PATH = Path(__file__).resolve().parent / "allowed-role-changes.json"
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


# ------------------------------------------------------------------------------------------------------- the automatic check
#
# This replaces the approval click that used to sit on the `apply` job. Two layers, both run before anything is applied:
#   1. Hard rules: a template that breaks one is refused, and no list can allow it. They keep the pipeline roles from growing into an administrator.
#   2. Allowed role changes: every IAM statement that would be added or removed must be listed in allowed-role-changes.json by its fingerprint, with a
#      reason, the same pattern allowed-changes.json uses for a Remove or a Replace. The refusal prints the fingerprints, and the pull request check
#      (role-change-check.yml) prints them before the merge, so the list is written in the same pull request that changes the template.
# A change that edits this file or the lists is not stopped by either layer. The outer wall for that is the approver stack, which a person applies
# and which limits `papyrus-pipeline-roles-cloudformation` to IAM rights on the three pipeline roles and their policies by name.

BROAD_ADMIN_POLICY_NAMES = ("AdministratorAccess", "PowerUserAccess", "IAMFullAccess")
FORBIDDEN_WILDCARD_ACTIONS = ("*", "*:*", "iam:*", "sts:*", "organizations:*", "account:*")
IAM_ESCALATION_ACTIONS = {
    "iam:createrole", "iam:putrolepolicy", "iam:attachrolepolicy", "iam:updateassumerolepolicy", "iam:passrole", "iam:createpolicyversion",
    "iam:setdefaultpolicyversion", "iam:createaccesskey", "iam:createuser", "iam:attachuserpolicy", "iam:putuserpolicy", "iam:createloginprofile",
    "iam:updateloginprofile", "iam:addusertogroup", "iam:attachgrouppolicy", "iam:putgrouppolicy", "iam:putrolepermissionsboundary",
    "iam:deleterolepermissionsboundary",
}
UNSCOPED_IAM_RESOURCE = re.compile(r"^(\*|arn:.*:iam::.*:(role|policy|user|group)/\*|arn:.*:iam::\*:.*|arn:.*:iam::[^/]*:\*)$")
GITHUB_OIDC_SUB_KEY = "token.actions.githubusercontent.com:sub"
GITHUB_OIDC_AUD_KEY = "token.actions.githubusercontent.com:aud"


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def _text(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _resource_strings(resource) -> list[str]:
    """Each resource as a string; an intrinsic is shown as its Fn::Sub text, so a `*` written inside one is still seen."""
    found = []
    for item in _as_list(resource):
        if isinstance(item, dict):
            found.append(item["Fn::Sub"] if isinstance(item.get("Fn::Sub"), str) else _text(item))
        else:
            found.append(str(item))
    return found


def _principal_values(principal) -> list:
    return [principal] if not isinstance(principal, dict) else [value for item in principal.values() for value in _as_list(item)]


def hard_rule_violations(template: dict) -> list[str]:
    problems = []
    for logical, resource in template.get("Resources", {}).items():
        kind, props = resource.get("Type", ""), resource.get("Properties", {})
        if kind not in ("AWS::IAM::Role", "AWS::IAM::ManagedPolicy"):
            continue
        for arn in props.get("ManagedPolicyArns", []):
            if any(name in _text(arn) for name in BROAD_ADMIN_POLICY_NAMES):
                problems.append(f"{logical} attaches a broad AWS-managed policy ({_text(arn)}); the pipeline roles never get an administrator-sized policy")
        documents = [(f"{logical} / {policy.get('PolicyName')}", policy.get("PolicyDocument", {})) for policy in props.get("Policies", [])]
        if kind == "AWS::IAM::ManagedPolicy":
            documents.append((logical, props.get("PolicyDocument", {})))
        for where, document in documents:
            for statement in _as_list(document.get("Statement", [])):
                if statement.get("Effect") != "Allow":
                    continue
                actions = [str(action) for action in _as_list(statement.get("Action", []))]
                label = f"{where} sid {statement.get('Sid', '-')}"
                for action in actions:
                    if action.lower() in FORBIDDEN_WILDCARD_ACTIONS:
                        problems.append(f"{label} allows {action}; a wildcard over a whole service that can change identities is never allowed")
                escalating = [action for action in actions if action.lower() in IAM_ESCALATION_ACTIONS]
                unscoped = [text for text in _resource_strings(statement.get("Resource", [])) if UNSCOPED_IAM_RESOURCE.match(text)]
                if escalating and unscoped:
                    problems.append(f"{label} allows {', '.join(sorted(escalating))} on {', '.join(unscoped)}; identity changes must name resources by a papyrus prefix")
        if kind == "AWS::IAM::Role":
            for statement in _as_list(props.get("AssumeRolePolicyDocument", {}).get("Statement", [])):
                principal, condition = statement.get("Principal", {}), statement.get("Condition", {})
                where = f"{logical} (who may assume it)"
                if "*" in _principal_values(principal):
                    problems.append(f"{where} trusts everyone (a `*` principal)")
                if "token.actions.githubusercontent.com" in _text(principal):
                    exact = condition.get("StringEquals", {})
                    loose = [operator for operator, keys in condition.items() if operator != "StringEquals" and GITHUB_OIDC_SUB_KEY in keys]
                    subject = exact.get(GITHUB_OIDC_SUB_KEY)
                    if GITHUB_OIDC_AUD_KEY not in exact or subject is None:
                        problems.append(f"{where} trusts GitHub without an exact audience and subject condition")
                    elif loose or "*" in _text(subject):
                        problems.append(f"{where} trusts a GitHub subject by pattern; the subject must be matched exactly")
    return problems


def role_statement_fingerprint(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()[:12]


def role_change_lines(old: dict, new: dict) -> list[tuple[str, str]]:
    """(`+` or `-`, line) for each IAM statement that is added or removed, in the order the IAM view prints them."""
    before, after = iam_lines(old), iam_lines(new)
    return [("-", line) for line in sorted(before - after)] + [("+", line) for line in sorted(after - before)]


def unlisted_role_changes(old: dict, new: dict, allowed: list[dict]) -> list[str]:
    listed = {entry["fingerprint"] for entry in allowed}
    return [f"{sign} {role_statement_fingerprint(line)}  {line}" for sign, line in role_change_lines(old, new) if role_statement_fingerprint(line) not in listed]


def role_change_refusal(old: dict, new: dict, allowed_role_changes: list[dict], violations: list[str]) -> str | None:
    """None when the change may go ahead, else the whole reason in plain words. `old` is empty on a first create, where only the hard rules apply."""
    reasons = [f"- breaks a hard rule: {problem}" for problem in hard_rule_violations(new)]
    reasons += [f"- {violation}, and allowed-changes.json does not list it for {STACK}" for violation in violations]
    if old:
        reasons += [f"- IAM statement not in allowed-role-changes.json: {line}" for line in unlisted_role_changes(old, new, allowed_role_changes)]
    if not reasons:
        return None
    return ("the change to the pipeline roles is refused by the automatic check, so nothing was applied:\n" + "\n".join(reasons) +
            "\nTo go ahead on purpose, list each IAM statement above by its fingerprint in infra/pipeline/allowed-role-changes.json "
            "({\"fingerprint\", \"reason\"}) in the same pull request. A hard rule cannot be listed; it has to be fixed in the template.")


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


def plan(ctx: sd.Context, template_path: Path, tag: str, outputs, allowed_role_changes: list[dict] | None = None) -> int:
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

    violations, lines = sd.review_changes(STACK, described.get("Changes", []), ctx.allowed)
    live = sd.parse_template(cloud.get_template(STACK)) if stack is not None else {}
    listed = sd.load_json(ALLOWED_ROLE_CHANGES_PATH)["allowed"] if allowed_role_changes is None else allowed_role_changes
    refusal = role_change_refusal(live, new, listed, violations)
    if refusal:
        cloud.delete_change_set(STACK, name)
        raise sd.Stop(refusal)
    table = "| Action | Logical id | Type | Replacement |\n| --- | --- | --- | --- |\n" + "\n".join(lines)
    ctx.write_summary(
        f"## Pipeline roles: the change passed the automatic check and is being applied\n"
        f"Stack `{STACK}` ({status}, a {kind} change set). Template fingerprint `{sha}`, change set `{name}`.\n\n"
        f"### Every change\n{table}\n\n### IAM statements that change (roles, policies, actions, resources)\n{iam_view(live, new)}\n\n"
        f"The check refused nothing: no hard rule is broken, every IAM statement above is listed in allowed-role-changes.json, and every removal or replacement is "
        f"listed in allowed-changes.json. The next job, `apply`, executes exactly this change set.")
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


# ------------------------------------------------------------------------------------------------------------ pull request check


def check(base_template_text: str, template_path: Path, allowed_role_changes: list[dict], out=print) -> int:
    """The plan's checks between two templates, with no AWS: for a pull request. Prints the fingerprints a change needs when it is refused."""
    old, new = sd.parse_template(base_template_text), sd.parse_template(template_path.read_text(encoding="utf-8"))
    refusal = role_change_refusal(old, new, allowed_role_changes, [])
    if refusal:
        out(refusal)
        return 2
    out(iam_view(old, new))
    out("The automatic check passed: no hard rule is broken and every changed IAM statement is listed in allowed-role-changes.json.")
    return 0


def template_at(ref: str) -> str:
    return subprocess.run(["git", "show", f"{ref}:infra/pipeline/papyrus-stack-pipeline.yaml"], capture_output=True, text=True, check=True).stdout


# ------------------------------------------------------------------------------------------------------------ command line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    pull_request = sub.add_parser("check")
    pull_request.add_argument("--base-ref", required=True)
    run = sub.add_parser("apply")
    run.add_argument("--change-set", required=True)
    run.add_argument("--template-sha", required=True)
    run.add_argument("--stamp", required=True)
    args = parser.parse_args(argv)

    if args.command == "check":
        return check(template_at(args.base_ref), sd.PIPELINE_TEMPLATE, sd.load_json(ALLOWED_ROLE_CHANGES_PATH)["allowed"])

    cloud = RolesCli(sd.load_json(sd.CONFIG_PATH)["region"])
    expected = os.environ.get("AWS_ACCOUNT_ID", "")
    if not expected or cloud.account() != expected:
        print("refusing: the caller account is not the AWS_ACCOUNT_ID variable", file=sys.stderr)
        return 2
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    tag = f"{os.environ.get('GITHUB_RUN_ID', '0')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    ctx = sd.Context(cloud, {}, sd.load_json(sd.ALLOWED_PATH)["allowed"], tag, summary=Path(summary) if summary else None)
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
