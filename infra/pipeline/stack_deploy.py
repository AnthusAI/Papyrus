#!/usr/bin/env python3
"""Deploy shared CloudFormation stacks from the release pipeline (PPY-b8cc79).

Subcommands (all read `infra/pipeline/stacks.json`):

  scope --base SHA --head SHA     which stacks have inputs in the diff (writes `stacks=` and `deploy=` to $GITHUB_OUTPUT)
  requirements                    pip requirements for the vendored packages at the poetry.lock versions (a reproducible zip)
  plan [--stack NAME ...]         READ-ONLY dry run: what a release would change, as a job summary (pull requests)
  deploy [--stack NAME ...]       build, upload, create a change set, read it, execute it, watch it (push to main)
  pipeline-check                  does the deployed papyrus-stack-pipeline match infra/pipeline/papyrus-stack-pipeline.yaml (exit 1 if not)

Safety, in this file and nowhere else:
  * parameter values and code keys are single-line and well formed before any call;
  * a stack in a failed or in-progress state stops the run;
  * a change set that would Remove or Replace anything not on `allowed-changes.json` is deleted unexecuted and the run stops;
  * progress is polled (never `aws cloudformation wait`), and a failed update fails the run with the first failure's cause;
  * nothing is retried. The workflow's concurrency group allows one run at a time.

A deployment repository (another organisation, a client account) uses the same file with its own config: `--config PATH`, optional
`--allowed PATH`. The config may set `root` (where templates and paths resolve; a template `papyrus:<path>` resolves in this repository),
`pipelineCheck`, `changeSetPrefix`; omit `templateBucketFrom` to pass templates inline; and per stack `enabled`/`reason`, parameters from the
environment (`fromEnv`) or another stack's output (`fromStackOutput`), `import` (adopt a hand-made resource by CloudFormation IMPORT, then
update, never replace) and `checks` (name servers of a zone against an expected file). Nothing here changes for a config without them.

Exit codes: 0 done or nothing to do, 1 an update failed, 2 a safety check refused.
Needs the AWS CLI. `plan` and `scope` need PyYAML only for templates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).resolve().parent / "stacks.json"
ALLOWED_PATH = Path(__file__).resolve().parent / "allowed-changes.json"
PIPELINE_STACK = "papyrus-stack-pipeline"
PIPELINE_TEMPLATE = Path(__file__).resolve().parent / "papyrus-stack-pipeline.yaml"
ROLES_WORKFLOW = "role-stack-deploy"
ROLES_WORKFLOW_URL = "https://github.com/AnthusAI/Papyrus/actions/workflows/role-stack-deploy.yml"

CHANGE_SET_PREFIX = "papyrus-release-"
CODE_KEY = re.compile(r"^papyrus-monitoring/(router-|operator-|email-)?[0-9a-f]{64}\.zip$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{2,62}$")

# Stack states: where a change may start, and where it must not.
UPDATABLE = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "IMPORT_COMPLETE", "IMPORT_ROLLBACK_COMPLETE"}
FIRST_CREATE = {"REVIEW_IN_PROGRESS"}
SUCCESS = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
INLINE_TEMPLATE_LIMIT = 51200  # bytes: the most `--template-body` accepts
NOT_STARTED = {"AVAILABLE", "UNAVAILABLE", "OBSOLETE"}


class Stop(Exception):
    """A safety check refused to go on. Nothing was executed."""


class Failed(Exception):
    """An update ran and failed, or could not be confirmed."""


class AwsError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------- pure checks


def validate_parameters(values: dict[str, str]) -> None:
    """Every value is one line of printable text; every code key has the exact shape build.py prints.

    A two-line key (a trailing newline from a pasted build log) broke a deploy on 2026-11-04.
    """
    for name, value in values.items():
        if not isinstance(value, str):
            raise Stop(f"parameter {name} is not a string")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise Stop(f"parameter {name} holds a newline or control character; every value must be one line")
        if value != value.strip():
            raise Stop(f"parameter {name} has leading or trailing whitespace")
        if name.endswith("CodeKey") and not CODE_KEY.match(value):
            raise Stop(f"parameter {name} is not a papyrus-monitoring/<kind>-<sha256>.zip key")


def classify_stack(stack: dict | None) -> tuple[str, str]:
    """('create' | 'update', status), or raise Stop for a failed, busy or unknown state."""
    if stack is None:
        return "create", "DOES_NOT_EXIST"
    status = stack["StackStatus"]
    if status in FIRST_CREATE:
        return "create", status
    if status in UPDATABLE:
        return "update", status
    if status.endswith("_IN_PROGRESS"):
        raise Stop(f"stack is {status}: another change is running; not starting a second")
    raise Stop(f"stack is {status} ({stack.get('StackStatusReason') or 'no reason given'}); a person must repair it before any deploy")


def parameter_plan(template_parameters: dict, current: dict[str, str] | None, overrides: dict[str, str], keep_previous: bool) -> list[dict]:
    """Parameters for CreateChangeSet. Overrides win; with `keep_previous`, a parameter the stack already has stays at its value;
    anything else takes the template default. A required parameter with no value is an error, not a guess."""
    result = []
    for name, spec in template_parameters.items():
        if name in overrides:
            result.append({"ParameterKey": name, "ParameterValue": overrides[name]})
        elif keep_previous and current is not None and name in current:
            result.append({"ParameterKey": name, "UsePreviousValue": True})
        elif "Default" in spec:
            continue
        else:
            raise Stop(f"parameter {name} has no default, no previous value and no configured value")
    unknown = sorted(set(overrides) - set(template_parameters))
    if unknown:
        raise Stop(f"configured parameters not in the template: {', '.join(unknown)}")
    return result


def is_replacement(change: dict) -> bool:
    if change.get("Replacement") in ("True", "Conditional"):
        return True
    if change.get("Action") == "Dynamic":
        return True
    return any(detail.get("Target", {}).get("RequiresRecreation") == "Always" for detail in change.get("Details", []))


def review_changes(stack: str, changes: list[dict], allowed: list[dict], importing: bool = False) -> tuple[list[str], list[str]]:
    """(violations, report lines). A violation is a Remove or a Replace not listed for this stack and logical id.
    For an IMPORT change set, anything whose Action is not Import is a violation (unless allowed-changes.json lists that Action)."""
    permitted = {(entry["stack"], entry["logicalId"], entry["change"]) for entry in allowed}
    violations, lines = [], []
    for item in changes:
        if item.get("Type") != "Resource":
            continue
        change = item["ResourceChange"]
        logical, action = change["LogicalResourceId"], change["Action"]
        if importing:
            flag = ""
            if action != "Import":
                if (stack, logical, action) in permitted:
                    flag = f" ({action} allowed by allowed-changes.json)"
                else:
                    violations.append(f"{logical} ({change.get('ResourceType', '?')}) would be {action} by an IMPORT change set, which may only import")
                    flag = " (NOT ALLOWED)"
            lines.append(f"| {action} | `{logical}` | {change.get('ResourceType', '')} | {change.get('Replacement', '')}{flag} |")
            continue
        kinds = (["Remove"] if action == "Remove" else []) + (["Replace"] if is_replacement(change) else [])
        flag = ""
        for kind in kinds:
            if (stack, logical, kind) in permitted:
                flag = f" ({kind} allowed by allowed-changes.json)"
            else:
                violations.append(f"{logical} ({change.get('ResourceType', '?')}) would be {'Removed' if kind == 'Remove' else 'Replaced'}")
                flag = " (NOT ALLOWED)"
        lines.append(f"| {action} | `{logical}` | {change.get('ResourceType', '')} | {change.get('Replacement', '')}{flag} |")
    return violations, lines


def failure_cause(events: list[dict], known: set[str], stack: dict | None) -> str:
    """The earliest failed resource event not in `known` (the events before this execution) is the cause; later ones are usually the rollback."""
    failed = sorted((e for e in events if e["EventId"] not in known and e["ResourceStatus"].endswith("_FAILED") and e.get("ResourceStatusReason")),
                    key=lambda e: str(e["Timestamp"]))
    lines = [f"{e['LogicalResourceId']} {e['ResourceStatus']}: {e['ResourceStatusReason']}" for e in failed]
    if stack and stack.get("StackStatusReason"):
        lines.append(f"stack: {stack['StackStatusReason']}")
    return "\n".join(lines) or "no failure event found"


def validation_failures(events: list[dict]) -> list[str]:
    """Lines for the failed early validations in a change set's events (`describe-events --change-set-name`): which resource, which check, why.
    The change set's own status reason says only that a validation failed."""
    lines = []
    for event in events:
        failed = str(event.get("ValidationStatus", "")).upper() == "FAILED" or (event.get("ValidationName") and str(event.get("ValidationStatus", "")).upper() not in ("", "PASSED", "SUCCEEDED"))
        if not failed:
            continue
        where = event.get("LogicalResourceId") or event.get("ValidationPath") or "(no resource named)"
        lines.append(f"{where} ({event.get('ResourceType', 'unknown type')}): {event.get('ValidationName', 'validation')} failed: {event.get('ValidationStatusReason') or 'no reason given'}")
    return lines


EXISTENCE_HINT = ("A resource this template creates with a fixed name already exists outside the stack (usually a Retain resource left behind by a create that rolled back). "
                  "Look at it: if it is empty and nobody uses it, a person deletes it (this pipeline never deletes data), then re-run the release; if it holds data, import it into the stack instead.")


def changed_stacks(config: dict, files: list[str]) -> list[str]:
    names = []
    for stack in config["stacks"]:
        if not stack.get("enabled", True):
            continue
        if any(file == path or (path.endswith("/") and file.startswith(path)) for file in files for path in stack["paths"]):
            names.append(stack["name"])
    return names


def vendored_requirements(lock_text: str, vendored: tuple[str, ...]) -> list[str]:
    import tomllib

    dist_names = {"yaml": "pyyaml", "youtube_transcript_api": "youtube-transcript-api", "charset_normalizer": "charset-normalizer"}
    versions = {re.sub(r"[-_.]+", "-", p["name"]).lower(): p["version"] for p in tomllib.loads(lock_text)["package"]}
    lines = []
    for module in vendored:
        name = dist_names.get(module, module)
        if name not in versions:
            raise Stop(f"{name} is not in poetry.lock")
        lines.append(f"{name}=={versions[name]}")
    return lines


def _yaml_loader():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def tag(loader, suffix, node):
        name = suffix if suffix in ("Ref", "Condition") else f"Fn::{suffix}"
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
            if suffix == "GetAtt":
                value = value.split(".", 1)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        else:
            value = loader.construct_mapping(node, deep=True)
        return {name: value}

    Loader.add_multi_constructor("!", tag)
    return Loader


def parse_template(text: str) -> dict:
    import yaml

    return yaml.load(text, Loader=_yaml_loader())  # noqa: S506 - a SafeLoader subclass


def diff_templates(live: dict, new: dict) -> dict:
    """Resource and parameter differences between the live template and the one in the commit (read-only; replacement needs a real change set)."""
    old_r, new_r = live.get("Resources", {}), new.get("Resources", {})
    modified = {}
    for key in sorted(set(old_r) & set(new_r)):
        if json.dumps(old_r[key], sort_keys=True, default=str) != json.dumps(new_r[key], sort_keys=True, default=str):
            a, b = old_r[key].get("Properties", {}), new_r[key].get("Properties", {})
            modified[key] = sorted(k for k in set(a) | set(b) if json.dumps(a.get(k), sort_keys=True, default=str) != json.dumps(b.get(k), sort_keys=True, default=str)) or ["(non-property)"]
    old_p, new_p = live.get("Parameters", {}), new.get("Parameters", {})
    return {"added": sorted(set(new_r) - set(old_r)), "removed": sorted(set(old_r) - set(new_r)), "modified": modified,
            "parameters_added": sorted(set(new_p) - set(old_p)), "parameters_removed": sorted(set(old_p) - set(new_p))}


# ------------------------------------------------------------------------------------------------------------------ AWS access


def bootstrap_hint(message: str) -> str:
    """A permission refusal on the service role or deploy role is fixed by changing the pipeline roles, which only the approval-gated workflow does."""
    if re.search(r"not authorized|AccessDenied|is not allowed to perform|UnauthorizedOperation", message, re.IGNORECASE):
        return (f"This looks like a permission the pipeline roles do not have. Roles are changed only by the {ROLES_WORKFLOW} workflow, after a person "
                f"approves it in GitHub: {ROLES_WORKFLOW_URL}. Open its latest run on develop or main and approve the pending 'pipeline-roles' "
                f"deployment (an agent links it and never approves). If it ran and was approved, re-run this workflow. If there is no run, the "
                f"template change has not been merged.")
    return ""


def pipeline_state(cloud, template_text: str) -> tuple[str, str]:
    """('same' | 'differs' | 'missing' | 'unreadable', detail). Compares the template in this checkout with the one deployed as papyrus-stack-pipeline."""
    try:
        deployed = cloud.get_template(PIPELINE_STACK)
    except AwsError as error:
        text = str(error)
        if "does not exist" in text:
            return "missing", "the papyrus-stack-pipeline stack does not exist in this account"
        if re.search(r"not authorized|AccessDenied", text, re.IGNORECASE):
            return "unreadable", "the role in use cannot read the papyrus-stack-pipeline stack (the role predates that permission)"
        raise
    if parse_template(deployed) == parse_template(template_text):
        return "same", "the deployed roles match infra/pipeline/papyrus-stack-pipeline.yaml"
    return "differs", "the deployed roles differ from infra/pipeline/papyrus-stack-pipeline.yaml in this checkout"


def pipeline_notice(ctx: "Context") -> str:
    """Say plainly, in the job summary, when the roles in the account are not the roles in the repository. Never fails the run for it."""
    if not ctx.check_pipeline or ctx.pipeline_said:
        return ctx.pipeline_said or "same"
    state, detail = pipeline_state(ctx.cloud, PIPELINE_TEMPLATE.read_text(encoding="utf-8"))
    ctx.pipeline_said = state
    if state != "same":
        ctx.write_summary(f"### The pipeline roles are out of date\n{detail[0].upper() + detail[1:]}. A permission added to the template since the last approved apply is not in the account, "
                          f"so a deploy can be refused for it. The {ROLES_WORKFLOW} workflow updates them after a person approves in GitHub: "
                          f"{ROLES_WORKFLOW_URL} (see infra/pipeline/README.md). Nothing is stopped for this.")
        ctx.out(f"::warning::The pipeline roles are out of date ({detail}). Approve the {ROLES_WORKFLOW} run: {ROLES_WORKFLOW_URL}")
    return state


class AwsCli:
    """The only code that talks to AWS. Tests replace it with a fake that has the same methods."""

    def __init__(self, region: str, run=subprocess.run, sleeper=time.sleep, clock=time.monotonic):
        self.region, self._run, self.sleep, self.now = region, run, sleeper, clock

    def _aws(self, *args: str, parse: bool = True):
        done = self._run(["aws", *args, "--region", self.region, "--output", "json"], capture_output=True, text=True)
        if done.returncode != 0:
            raise AwsError((done.stderr or done.stdout).strip())
        return json.loads(done.stdout) if parse and done.stdout.strip() else done.stdout

    def account(self) -> str:
        return self._aws("sts", "get-caller-identity")["Account"]

    def describe_stack(self, name: str) -> dict | None:
        try:
            return self._aws("cloudformation", "describe-stacks", "--stack-name", name)["Stacks"][0]
        except AwsError as error:
            if "does not exist" in str(error):
                return None
            raise

    def get_template(self, name: str) -> str:
        body = self._aws("cloudformation", "get-template", "--stack-name", name, "--template-stage", "Original")["TemplateBody"]
        return body if isinstance(body, str) else json.dumps(body)

    def list_change_sets(self, name: str) -> list[dict]:
        return self._aws("cloudformation", "list-change-sets", "--stack-name", name)["Summaries"]

    def create_change_set(self, stack: str, name: str, kind: str, template_url: str | None, parameters: list[dict], capabilities: list[str], tags: dict, role_arn: str,
                          template_path: Path | None = None, resources: list[dict] | None = None) -> None:
        """`template_url` for a template uploaded to S3; `template_path` (and no URL) passes the file as `--template-body`. `resources` is for kind 'import'."""
        source = ["--template-body", f"file://{template_path}"] if template_path is not None else ["--template-url", template_url]
        args = ["cloudformation", "create-change-set", "--stack-name", stack, "--change-set-name", name, "--change-set-type", kind.upper(),
                *source, "--parameters", json.dumps(parameters), "--role-arn", role_arn]
        if resources:
            args += ["--resources-to-import", json.dumps(resources)]
        if capabilities:
            args += ["--capabilities", *capabilities]
        if kind == "create" and tags:
            args += ["--tags", *(f"Key={k},Value={v}" for k, v in tags.items())]
        self._aws(*args)

    def describe_change_set(self, stack: str, name: str) -> dict:
        return self._aws("cloudformation", "describe-change-set", "--stack-name", stack, "--change-set-name", name)

    def change_set_events(self, stack: str, change_set_id: str) -> list[dict]:
        """The events of a change set, which is where a failed early validation says which resource it failed on. Must be read before the change set is deleted."""
        return self._aws("cloudformation", "describe-events", "--stack-name", stack, "--change-set-name", change_set_id)["OperationEvents"]

    def delete_change_set(self, stack: str, name: str) -> None:
        self._aws("cloudformation", "delete-change-set", "--stack-name", stack, "--change-set-name", name, parse=False)

    def execute_change_set(self, stack: str, name: str) -> None:
        self._aws("cloudformation", "execute-change-set", "--stack-name", stack, "--change-set-name", name, parse=False)

    def stack_events(self, name: str) -> list[dict]:
        return self._aws("cloudformation", "describe-stack-events", "--stack-name", name)["StackEvents"]

    def upload(self, path: Path, bucket: str, key: str) -> None:
        self._aws("s3", "cp", str(path), f"s3://{bucket}/{key}", "--only-show-errors", parse=False)

    def hosted_zones(self, dns_name: str) -> list[dict]:
        zones = self._aws("route53", "list-hosted-zones-by-name", "--dns-name", dns_name, "--max-items", "5")["HostedZones"]
        return [z for z in zones if z["Name"] == dns_name and not z.get("Config", {}).get("PrivateZone")]

    def zone_name_servers(self, zone_id: str) -> list[str]:
        return self._aws("route53", "get-hosted-zone", "--id", zone_id)["DelegationSet"]["NameServers"]

    def budget(self, name: str) -> dict | None:
        """The budget called `name` in this account, or None when there is none (read-only)."""
        try:
            return self._aws("budgets", "describe-budget", "--account-id", self.account(), "--budget-name", name)["Budget"]
        except AwsError as error:
            if "NotFound" in str(error):
                return None
            raise


# ------------------------------------------------------------------------------------------------------------------ the deploy


class Context:
    def __init__(self, cloud, config: dict, allowed: list[dict], run_tag: str, root: Path = ROOT, runner=subprocess.run, out=print,
                 summary: Path | None = None, check_pipeline: bool = False, change_set_timeout: float = 600, execute_timeout: float = 3000, poll: float = 10, start_grace: float = 180,
                 config_dir: Path | None = None, env=None):
        self.cloud, self.config, self.allowed, self.run_tag, self.root, self.runner, self.out = cloud, config, allowed, run_tag, root, runner, out
        self.config_dir = config_dir if config_dir is not None else root
        self.env = os.environ if env is None else env
        self.failed_checks: list[str] = []
        self.summary, self.check_pipeline, self.pipeline_said = summary, check_pipeline, None
        self.change_set_timeout, self.execute_timeout, self.poll, self.start_grace = change_set_timeout, execute_timeout, poll, start_grace

    @property
    def prefix(self) -> str:
        return self.config.get("changeSetPrefix", CHANGE_SET_PREFIX)

    @property
    def inline(self) -> bool:
        """No `templateBucketFrom`: templates are passed with --template-body and nothing goes to S3."""
        return "templateBucketFrom" not in self.config

    def write_summary(self, text: str) -> None:
        self.out(text)
        if self.summary:
            with open(self.summary, "a", encoding="utf-8") as handle:
                handle.write(text + "\n")


def param_map(stack: dict | None) -> dict[str, str] | None:
    return None if stack is None else {p["ParameterKey"]: p.get("ParameterValue", "") for p in stack.get("Parameters", [])}


def template_bucket(ctx: Context) -> str:
    source = ctx.config["templateBucketFrom"]
    stack = ctx.cloud.describe_stack(source["stack"])
    value = (param_map(stack) or {}).get(source["parameter"], "")
    if stack is None:
        # A new account has no papyrus-monitoring yet. The CDK bootstrap bucket has a fixed name, so the first stack can still be created.
        value = f"cdk-hnb659fds-assets-{ctx.cloud.account()}-{ctx.cloud.region}"
    if not BUCKET.match(value):
        raise Stop(f"cannot read a bucket name from {source['stack']} parameter {source['parameter']}")
    return value


def lookup_parameters(ctx: Context, cfg: dict) -> dict[str, str]:
    values = {}
    for name, spec in cfg.get("lookups", {}).items():
        zones = ctx.cloud.hosted_zones(spec["hostedZone"].rstrip(".") + ".")
        if len(zones) != 1:
            raise Stop(f"expected exactly one public hosted zone for {spec['hostedZone']}, found {len(zones)}")
        values[name] = zones[0]["Id"].removeprefix("/hostedzone/")
    return values


def build_keys(ctx: Context, cfg: dict, bucket: str) -> dict[str, str]:
    """Run build.py for each configured zip (it asserts the account and uploads by content hash) and read back the printed key."""
    keys = {}
    for build in cfg.get("builds", []):
        done = ctx.runner([sys.executable, str(ctx.root / build["script"]), *build.get("args", []), "--upload", bucket], capture_output=True, text=True, cwd=ctx.root)
        if done.returncode != 0:
            raise Failed(f"build for {build['parameter']} failed: {(done.stderr or done.stdout).strip()[-1500:]}")
        found = [line.split(None, 1)[1] for line in done.stdout.splitlines() if line.startswith("CodeKey ")]
        if len(found) != 1:
            raise Failed(f"build for {build['parameter']} printed {len(found)} CodeKey lines")
        keys[build["parameter"]] = found[0]
    return keys


def delete_own_stale_change_sets(ctx: Context, stack: str) -> None:
    for item in ctx.cloud.list_change_sets(stack):
        name = item["ChangeSetName"]
        if name.startswith(ctx.prefix):
            if item.get("ExecutionStatus") in NOT_STARTED:
                ctx.cloud.delete_change_set(stack, name)
                ctx.out(f"deleted our own unexecuted change set {name}")
        else:
            ctx.out(f"leaving change set {name} alone: it is not ours ({item.get('Status')}, {item.get('ExecutionStatus')})")


def wait_for_change_set(ctx: Context, stack: str, name: str) -> dict:
    deadline = ctx.cloud.now() + ctx.change_set_timeout
    while True:
        described = ctx.cloud.describe_change_set(stack, name)
        if described["Status"] in ("CREATE_COMPLETE", "FAILED"):
            return described
        if ctx.cloud.now() > deadline:
            raise Failed(f"change set {name} was still {described['Status']} after {ctx.change_set_timeout:.0f}s")
        ctx.cloud.sleep(ctx.poll)


def wait_for_execution(ctx: Context, stack: str, name: str, known: set[str]) -> None:
    """Poll until the stack leaves progress. Success needs a success status AND evidence that this execution ran, so a state left over
    from an earlier deploy can never read as done (the CLI waiter returned at once on 2026-11-04)."""
    begin = ctx.cloud.now()
    deadline = begin + ctx.execute_timeout
    seen_progress = False
    while True:
        current = ctx.cloud.describe_stack(stack)
        try:
            change = ctx.cloud.describe_change_set(stack, name)
        except AwsError as error:
            # CloudFormation removes the change set of a first create once it runs; it existed before the execute, so its absence is proof this execution ran.
            if "ChangeSetNotFound" not in str(error):
                raise
            change, seen_progress = {}, True
        status, execution = (current or {}).get("StackStatus", "GONE"), change.get("ExecutionStatus", "")
        if status.endswith("_IN_PROGRESS") and status != "REVIEW_IN_PROGRESS" or execution == "EXECUTE_IN_PROGRESS":
            seen_progress = True
        finished = execution in ("EXECUTE_COMPLETE", "EXECUTE_FAILED")
        if status.endswith("_IN_PROGRESS") is False and status != "GONE" and (seen_progress or finished):
            if status in SUCCESS and execution != "EXECUTE_FAILED":
                return
            raise Failed(f"stack {stack} ended {status}\n{failure_cause(ctx.cloud.stack_events(stack), known, current)}")
        now = ctx.cloud.now()
        if not seen_progress and now - begin > ctx.start_grace:
            raise Failed(f"stack {stack} never started the change set ({status}, {execution}) after {ctx.start_grace:.0f}s; not retrying")
        if now > deadline:
            raise Failed(f"stack {stack} still {status} after {ctx.execute_timeout:.0f}s; not retrying, a person must look")
        ctx.cloud.sleep(ctx.poll)


def template_file(ctx: Context, cfg: dict) -> Path:
    """`template` resolves under the config's root; `papyrus:<path>` resolves in this (the Papyrus) repository."""
    value = cfg["template"]
    return ROOT / value.removeprefix("papyrus:") if value.startswith("papyrus:") else ctx.root / value


def resolve_parameters(ctx: Context, cfg: dict, strict: bool) -> tuple[dict[str, str], list[str]]:
    """Configured parameter values: a string, {"fromEnv": NAME} or {"fromStackOutput": {"stack", "output"}}.
    strict (deploy): an unset or empty variable, a missing stack or output is a Stop. Not strict (plan): it becomes a note and the parameter is left out."""
    values, notes = {}, []
    for name, spec in cfg.get("parameters", {}).items():
        if isinstance(spec, dict) and "fromEnv" in spec:
            var = spec["fromEnv"]
            value = ctx.env.get(var, "")
            if not value:
                if strict:
                    raise Stop(f"parameter {name} comes from the environment variable {var}, which is unset or empty")
                notes.append(f"parameter `{name}`: environment variable `{var}` is unset")
                continue
            values[name] = value
        elif isinstance(spec, dict) and "fromStackOutput" in spec:
            source = spec["fromStackOutput"]
            stack = ctx.cloud.describe_stack(source["stack"])
            if stack is None:
                if strict:
                    raise Stop(f"parameter {name} comes from stack {source['stack']}, which does not exist")
                notes.append(f"parameter `{name}`: stack `{source['stack']}` does not exist yet, so output `{source['output']}` is not known")
                continue
            found = [o["OutputValue"] for o in stack.get("Outputs", []) if o.get("OutputKey") == source["output"]]
            if not found:
                if strict:
                    raise Stop(f"parameter {name} comes from output {source['output']} of stack {source['stack']}, which has no such output")
                notes.append(f"parameter `{name}`: stack `{source['stack']}` has no output `{source['output']}`")
                continue
            values[name] = found[0]
        elif isinstance(spec, str):
            values[name] = spec
        else:
            raise Stop(f"parameter {name} must be a string, {{\"fromEnv\": NAME}} or {{\"fromStackOutput\": {{...}}}}")
    return values, notes


def find_import(ctx: Context, imp: dict) -> str | None:
    """Read-only lookup of the hand-made resource to adopt: its CloudFormation identifier, or None when there is none."""
    lookup = imp["lookup"]
    kind = lookup["kind"]
    if kind == "hostedZoneByName":
        zones = ctx.cloud.hosted_zones(lookup["name"].rstrip(".") + ".")
        if len(zones) > 1:
            raise Stop(f"expected at most one public hosted zone for {lookup['name']}, found {len(zones)}")
        return zones[0]["Id"].removeprefix("/hostedzone/") if zones else None
    if kind == "budgetByName":
        return lookup["name"] if ctx.cloud.budget(lookup["name"]) else None
    raise Stop(f"unknown import lookup kind {kind}")


def import_resources(imp: dict, identifier: str) -> list[dict]:
    return [{"ResourceType": imp["resourceType"], "LogicalResourceId": imp["logicalId"], "ResourceIdentifier": {imp["identifierKey"]: identifier}}]


def normalise_hosts(hosts) -> set[str]:
    return {str(h).strip().lower().rstrip(".") for h in hosts}


def nameserver_check(ctx: Context, check: dict) -> tuple[bool | None, str]:
    """(True | False | None for the zone not existing, message). Compares the zone's delegation set with expectedFile[zone]."""
    zone = check["zone"]
    zones = ctx.cloud.hosted_zones(zone.rstrip(".") + ".")
    if not zones:
        return None, f"zone {zone} does not exist"
    if len(zones) > 1:
        return False, f"expected exactly one public hosted zone for {zone}, found {len(zones)}"
    live = normalise_hosts(ctx.cloud.zone_name_servers(zones[0]["Id"].removeprefix("/hostedzone/")))
    expected = normalise_hosts(load_json(ctx.config_dir / check["expectedFile"]).get(zone, []))
    if live == expected:
        return True, f"name servers of {zone} match"
    return False, f"name servers of {zone} differ: live {sorted(live)}, expected {sorted(expected)}"


def run_checks(ctx: Context, cfg: dict) -> None:
    """After a deploy: a failed check fails the run."""
    for check in cfg.get("checks", []):
        if check["kind"] != "nameservers":
            raise Stop(f"unknown check kind {check['kind']}")
        ok, message = nameserver_check(ctx, check)
        if ok is not True:
            ctx.write_summary(f"### {cfg['name']}: check FAILED\n{message}")
            raise Failed(f"check nameservers failed for {cfg['name']}: {message}")
        ctx.write_summary(f"{cfg['name']}: check passed: {message}")


def import_template_text(text: str) -> str:
    """CloudFormation refuses an IMPORT change set that adds Outputs ("you cannot modify or add [Outputs]"). The import template is the
    template without its top-level Outputs section; the follow-up UPDATE change set carries the whole template (found on 2026-11-11 by
    previewing the Humorus zone import)."""
    return re.sub(r"(?ms)^Outputs:.*?(?=^[A-Za-z]|\Z)", "", text).rstrip() + "\n"


def run_change_set(ctx: Context, cfg: dict, stack: dict | None, kind: str, text: str, overrides: dict[str, str], bucket: str | None, suffix: str = "",
                   resources: list[dict] | None = None) -> str:
    """One change set, from creating it to watching its execution. kind: 'create' | 'update' | 'import'."""
    cloud, name = ctx.cloud, cfg["name"]
    template_path = template_file(ctx, cfg)
    if kind == "import" and import_template_text(text) != text.rstrip() + "\n":
        scratch = Path(tempfile.mkdtemp(prefix="stack-deploy-import-"))
        template_path = scratch / template_path.name
        template_path.write_text(import_template_text(text), encoding="utf-8")
    plan = parameter_plan(parse_template(text).get("Parameters", {}), param_map(stack), overrides, cfg.get("keepPrevious", False))
    validate_parameters({p["ParameterKey"]: p["ParameterValue"] for p in plan if "ParameterValue" in p})

    change_set = (f"{ctx.prefix}{ctx.run_tag}"[:128 - len(suffix)]) + suffix
    role = f"arn:aws:iam::{cloud.account()}:role/{cfg.get('serviceRoleName', ctx.config['serviceRoleName'])}"
    if ctx.inline:
        cloud.create_change_set(name, change_set, kind, None, plan, cfg.get("capabilities", []), cfg.get("tags", {}), role, template_path=template_path,
                                **({"resources": resources} if resources else {}))
    else:
        key = f"papyrus-monitoring/templates/{name}-{hashlib.sha256(text.encode()).hexdigest()[:16]}.yaml"
        cloud.upload(template_path, bucket, key)
        cloud.create_change_set(name, change_set, kind, f"https://{bucket}.s3.{cloud.region}.amazonaws.com/{key}", plan, cfg.get("capabilities", []), cfg.get("tags", {}), role,
                                **({"resources": resources} if resources else {}))
    described = wait_for_change_set(ctx, name, change_set)
    if described["Status"] == "FAILED":
        reason = described.get("StatusReason", "")
        nothing = "didn't contain changes" in reason or "No updates are to be performed" in reason
        detail = []
        if not nothing:
            # Early validation says only "validation failed" in the reason; the events say which resource. Read them before the change set goes.
            try:
                detail = validation_failures(cloud.change_set_events(name, described.get("ChangeSetId") or change_set))
            except (AwsError, KeyError) as error:
                detail = [f"(the change set's validation events could not be read: {error})"]
        cloud.delete_change_set(name, change_set)
        if nothing:
            ctx.write_summary(f"### {name}\nNothing to deploy: the template and parameters match the live stack.")
            return "unchanged"
        hints = [EXISTENCE_HINT] if "ResourceExistenceCheck" in reason + " ".join(detail) else []
        message = "\n".join([f"change set failed to create: {reason}", *detail, *hints])
        raise Failed(message)   # main() puts the message in the job summary and the annotation

    violations, lines = review_changes(name, described.get("Changes", []), ctx.allowed, importing=kind == "import")
    table = "| Action | Logical id | Type | Replacement |\n| --- | --- | --- | --- |\n" + "\n".join(lines)
    if violations:
        cloud.delete_change_set(name, change_set)
        ctx.write_summary(f"### {name}: STOPPED, nothing executed\n{table}\n\n" + "\n".join(f"- {v}" for v in violations) +
                          "\n\nTo go ahead on purpose, add the entry to `infra/pipeline/allowed-changes.json` in a reviewed pull request, release, and remove it afterwards.")
        raise Stop("; ".join(violations))

    ctx.write_summary(f"### {name}: {'importing' if kind == 'import' else 'executing'}\n{table}")
    try:
        known = {e["EventId"] for e in cloud.stack_events(name)}
    except AwsError:
        known = set()
    cloud.execute_change_set(name, change_set)
    wait_for_execution(ctx, name, change_set, known)
    ctx.write_summary(f"{name}: {'imported' if kind == 'import' else 'done'}.")
    return "deployed"


def deploy_stack(ctx: Context, cfg: dict) -> str:
    result = deploy_changes(ctx, cfg)
    run_checks(ctx, cfg)
    return result


def deploy_changes(ctx: Context, cfg: dict) -> str:
    cloud, name = ctx.cloud, cfg["name"]
    pipeline_notice(ctx)
    stack = cloud.describe_stack(name)
    kind, status = classify_stack(stack)
    ctx.out(f"{name}: {status}, will {kind}")
    if stack is not None:
        delete_own_stale_change_sets(ctx, name)
    bucket = None if ctx.inline else template_bucket(ctx)

    overrides, _ = resolve_parameters(ctx, cfg, strict=True)
    overrides.update(lookup_parameters(ctx, cfg))
    if cfg.get("builds"):
        if bucket is None:
            raise Stop(f"{name} has builds, which need templateBucketFrom in the config")
        overrides.update(build_keys(ctx, cfg, bucket))
    if not ctx.inline:
        source = ctx.config["templateBucketFrom"]
        if stack is None and cfg["name"] == source["stack"]:
            overrides[source["parameter"]] = bucket  # the first create takes the bucket from the bootstrap name; later runs keep the live value
    validate_parameters(overrides)

    text = template_file(ctx, cfg).read_text(encoding="utf-8")
    if ctx.inline and len(text.encode("utf-8")) >= INLINE_TEMPLATE_LIMIT:
        raise Stop(f"template of {name} is {len(text.encode('utf-8'))} bytes; an inline template must be under {INLINE_TEMPLATE_LIMIT}")

    imp = cfg.get("import")
    # A stack left in REVIEW_IN_PROGRESS by an earlier change set that failed to create is still a stack that does not exist yet: import, never create.
    identifier = find_import(ctx, imp) if imp and (stack is None or status in FIRST_CREATE) else None
    if identifier is not None:
        ctx.out(f"{name}: the existing {imp['resourceType']} {identifier} will be imported, not replaced")
        run_change_set(ctx, cfg, None, "import", text, overrides, bucket, suffix="-import", resources=import_resources(imp, identifier))
        # The import adopts the resource as it is; the normal update now applies the template's properties, with the usual Remove/Replace safety.
        stack = cloud.describe_stack(name)
        kind, status = classify_stack(stack)
        ctx.out(f"{name}: {status}, will {kind}")
        return run_change_set(ctx, cfg, stack, kind, text, overrides, bucket)
    return run_change_set(ctx, cfg, stack, kind, text, overrides, bucket)


# ------------------------------------------------------------------------------------------------------------------- dry run


def plan_stack(ctx: Context, cfg: dict) -> None:
    """Read-only. Never builds, uploads or creates anything; says what it cannot know."""
    cloud, name = ctx.cloud, cfg["name"]
    pipeline_notice(ctx)
    stack = cloud.describe_stack(name)
    lines = [f"### {name}"]
    try:
        kind, status = classify_stack(stack)
        lines.append(f"Stack state: {status} (a release would {kind})")
    except Stop as stop:
        lines.append(f"**A release would STOP here:** {stop}")
        kind = "blocked"
    text = template_file(ctx, cfg).read_text(encoding="utf-8")
    new = parse_template(text)
    resolved, notes = resolve_parameters(ctx, cfg, strict=False)
    permitted = {(e["stack"], e["logicalId"], e["change"]) for e in ctx.allowed}
    if kind == "blocked":
        pass
    elif stack is not None and kind != "create":
        diff = diff_templates(parse_template(cloud.get_template(name)), new)
        lines.append(f"Resources added: {len(diff['added'])}, removed: {len(diff['removed'])}, modified: {len(diff['modified'])}")
        for logical in diff["added"]:
            lines.append(f"- add `{logical}`")
        for logical in diff["removed"]:
            allowed = (name, logical, "Remove") in permitted
            lines.append(f"- remove `{logical}`" + (" (allowed by allowed-changes.json)" if allowed else " **(would STOP the release: not on allowed-changes.json)**"))
        for logical, props in diff["modified"].items():
            lines.append(f"- modify `{logical}`: {', '.join(props)}")
        lines += [f"- new parameter `{p}`" for p in diff["parameters_added"]] + [f"- parameter `{p}` removed from the template" for p in diff["parameters_removed"]]
        if cfg.get("builds"):
            lines.append("Code: the zips are built on the release, not here; a changed zip modifies its function. Which changes replace a resource is only known from the release's change set, which stops on any Replace not on the list.")
        current = param_map(stack) or {}
        literals = {**resolved, **lookup_parameters(ctx, cfg)}
        lines += [f"- parameter `{k}` would change" for k, v in literals.items() if current.get(k) != v]
    else:
        count = len(new.get("Resources", {}))
        lines.append(f"A release would create this stack with {count} resources.")
        imp = cfg.get("import")
        if imp and stack is None:
            found = find_import(ctx, imp)
            lines.append(f"A release would IMPORT the existing {imp['resourceType']} (read-only lookup found it), then update it from the template." if found is not None
                         else "A release would CREATE (no existing resource found).")
    lines += [f"- {note}" for note in notes]
    for check in cfg.get("checks", []):
        if check["kind"] != "nameservers":
            raise Stop(f"unknown check kind {check['kind']}")
        ok, message = nameserver_check(ctx, check)
        if ok is None:
            lines.append(f"Check nameservers {check['zone']}: skipped ({message})")
        else:
            lines.append(f"Check nameservers {check['zone']}: {'PASS' if ok else '**FAIL**'}: {message}")
            if not ok:
                ctx.failed_checks.append(f"{cfg['name']}: {message}")
    ctx.write_summary("\n".join(lines))


# -------------------------------------------------------------------------------------------------------------------- command line


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def selected(config: dict, names: list[str] | None, group: str | None = None) -> list[dict]:
    """Enabled stacks, in config order. `group` (None = every group) limits them to one `group` (a stack's default is "default");
    a stack named explicitly must belong to that group."""
    chosen = [s for s in config["stacks"] if not names or s["name"] in names]
    if names and len(chosen) != len(set(names)):
        raise Stop(f"unknown stack in {names}")
    if group is not None:
        outside = [s["name"] for s in chosen if s.get("group", "default") != group]
        if names and outside:
            raise Stop(f"stack {', '.join(outside)} is not in group {group}")
        chosen = [s for s in chosen if s.get("group", "default") == group]
    return [s for s in chosen if s.get("enabled", True)]


def changed_stack(ctx: Context, cfg: dict) -> tuple[bool, str]:
    """Read-only: does the live stack differ from Git and the config? A missing stack counts as changed. NoEcho values (shown as ****)
    cannot be compared and are ignored; a parameter that cannot be resolved here (an unset fromEnv) counts as unchanged."""
    name = cfg["name"]
    stack = ctx.cloud.describe_stack(name)
    if stack is None:
        return True, "stack does not exist"
    reasons = []
    live = ctx.cloud.get_template(name).replace("\r\n", "\n")
    if live != template_file(ctx, cfg).read_text(encoding="utf-8").replace("\r\n", "\n"):
        reasons.append("template differs")
    current = param_map(stack) or {}
    resolved, _ = resolve_parameters(ctx, cfg, strict=False)
    for key, value in resolved.items():
        if current.get(key, "") != "****" and current.get(key) != value:
            reasons.append(f"parameter {key} differs")
    return bool(reasons), ", ".join(reasons) or "same as Git and the config"


def validate_config(config: dict) -> None:
    """Config rules that only the optional keys have; a config without them passes untouched."""
    seen = set()
    for stack in config["stacks"]:
        if not stack.get("enabled", True) and not str(stack.get("reason", "")).strip():
            raise Stop(f"stack {stack['name']} is disabled and needs a non-empty reason")
        for pname, spec in stack.get("parameters", {}).items():
            if isinstance(spec, dict) and "fromStackOutput" in spec and spec["fromStackOutput"]["stack"] not in seen:
                raise Stop(f"parameter {pname} of {stack['name']} reads the output of {spec['fromStackOutput']['stack']}, which must come earlier in the config")
        seen.add(stack["name"])


def load_config(path: Path) -> tuple[dict, Path]:
    """(config, root). `root` is relative to the config file's directory; absent means the Papyrus repository."""
    config = load_json(path)
    validate_config(config)
    root = (path.parent / config["root"]).resolve() if config.get("root") else ROOT
    return config, root


def github_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=CONFIG_PATH, help="stacks config (default infra/pipeline/stacks.json)")
    common.add_argument("--allowed", type=Path, default=None, help="allowed-changes.json (default: next to the config file)")
    scope = sub.add_parser("scope", parents=[common])
    scope.add_argument("--base", required=True)
    scope.add_argument("--head", required=True)
    sub.add_parser("requirements", parents=[common])
    sub.add_parser("pipeline-check", parents=[common])
    for command in ("plan", "deploy"):
        p = sub.add_parser(command, parents=[common])
        p.add_argument("--stack", action="append")
        p.add_argument("--group", default="default")
    sub.add_parser("changed", parents=[common]).add_argument("--group", default="default")
    args = parser.parse_args(argv)
    config_path = args.config.resolve()
    try:
        config, root = load_config(config_path)
    except Stop as stop:
        print(f"::error::STOPPED, nothing executed: {stop}")
        return 2
    enabled = [s for s in config["stacks"] if s.get("enabled", True)]

    if args.command == "scope":
        done = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "--relative", args.base, args.head], capture_output=True, text=True)
        # A base git cannot resolve (first run, force push) means every stack is in scope; the live comparison then decides.
        names = [s["name"] for s in enabled] if done.returncode != 0 else changed_stacks(config, done.stdout.split())
        github_output("stacks", ",".join(names))
        github_output("deploy", "true" if names else "false")
        print(f"stacks in scope: {names or 'none'}")
        return 0
    if args.command == "requirements":
        sys.path.insert(0, str(ROOT / "infra" / "monitoring"))
        import build  # noqa: PLC0415

        print("\n".join(vendored_requirements((ROOT / "poetry.lock").read_text(encoding="utf-8"), build.VENDORED)))
        return 0

    cloud = AwsCli(config["region"])
    expected = os.environ.get("AWS_ACCOUNT_ID", "")
    if not expected or cloud.account() != expected:
        print("refusing: the caller account is not the AWS_ACCOUNT_ID variable", file=sys.stderr)
        return 2
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    tag = f"{os.environ.get('GITHUB_SHA', 'local')[:12]}-{os.environ.get('GITHUB_RUN_ID', '0')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    allowed_path = args.allowed or (config_path.parent / "allowed-changes.json")
    ctx = Context(cloud, config, load_json(allowed_path)["allowed"], tag, root=root, summary=Path(summary) if summary else None,
                  check_pipeline=config.get("pipelineCheck", True), config_dir=config_path.parent)
    if args.command == "pipeline-check":
        state, detail = pipeline_state(cloud, PIPELINE_TEMPLATE.read_text(encoding="utf-8"))
        print(f"{state}: {detail}")
        return 0 if state == "same" else 1
    try:
        if args.command == "changed":
            flags = []
            for cfg in selected(config, None, args.group):
                differs, why = changed_stack(ctx, cfg)
                flags.append(differs)
                print(f"{cfg['name']}: {'changed' if differs else 'unchanged'} ({why})")
            github_output("changed", "true" if any(flags) else "false")
            return 0
        for cfg in selected(config, args.stack, args.group):
            (plan_stack if args.command == "plan" else deploy_stack)(ctx, cfg)
        if ctx.failed_checks:
            print("::error::CHECK FAILED: " + "; ".join(ctx.failed_checks))
            return 1
    except Stop as stop:
        print(f"::error::STOPPED, nothing executed: {stop}")
        return 2
    except (Failed, AwsError) as failure:
        print(f"::error::DEPLOY FAILED: {failure}")
        hint = bootstrap_hint(str(failure))
        ctx.write_summary(f"### DEPLOY FAILED\n```\n{failure}\n```" + (f"\n**{hint}**" if hint else ""))
        if hint:
            print(f"::error::{hint}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
