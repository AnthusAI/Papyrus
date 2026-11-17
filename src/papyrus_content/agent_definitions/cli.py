"""``papyrus agents``: ``validate`` checks a folder of agent definition files with no network, no sign-in and no model (slice D1, PPY-68abaa);
``apply`` applies the definitions to a site as its deploy does (slice D2, PPY-df3e74, ``release.py``); ``schedules`` makes the site's schedule group
agree with the applied definitions (slice C1, PPY-2a53cd, ``schedules.py``).

``set-rung`` sets an agent's rung in the site's policy document (slice H3, PPY-e6f31e, ``agent_policy/set_rung.py``). Later slices add the other
``papyrus agents`` commands (pause, resume, wake, runbook, explain) to this group.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TextIO

from papyrus_content.agent_rungs import RUNGS
from papyrus_content.images.cli import ERROR_EXIT_CODE
from papyrus_content.images.handlers import error_envelope

from . import definition, release, schedules

GROUP = "agents"
VALIDATE_USAGE = ("Usage: papyrus agents validate --dir DIR [--core DIR]\n"
                  "  Check the agent definition files in DIR (one <id>.yaml each) with no network and no model. A site's files may extend the engine's core\n"
                  "  definitions (or those in --core) with instructions and must-never rules; nothing else may change and no rule may be removed.\n"
                  "  Exits 0 when every definition is valid and 2 when any is refused, naming each problem by definition and line.")


APPLY_USAGE = ("Usage: papyrus agents apply [--dir DIR] [--core DIR] [--root DIR] [--site-registry FILE] [--dry-run | --check]\n"
               "  Apply the agent definitions to the site as its deploy does, after the procedures are registered. It first checks every definition as\n"
               "  `papyrus agents validate` does and that each names a registered procedure, and stops with a plain error before any write when one does not.\n"
               "  Each definition becomes the registered copy on an automation named for it (created disabled when the site has none; the same digest writes\n"
               "  nothing, a changed one writes the next version); a definition gone from Git is retired, disabled and given no schedule, its history kept.\n"
               "  It never writes the agent policy document and never adopts an automation: a new agent arrives at the rung off.\n"
               f"  --dir is the site's folder of definitions (default ./{release.SITE_FOLDER} under --root, when it exists; the core definitions alone otherwise);\n"
               "  --root is the site's checkout (default the current folder), where papyrus-site-procedures.json is read. --dry-run reads the site and says what\n"
               "  would change; --check also exits 2 when anything differs from Git. Run it as the operator (PAPYRUS_GRAPHQL_AUTH=iam).")


SCHEDULES_USAGE = ("Usage: papyrus agents schedules --site SITE [--dry-run | --check]\n"
                   "  Make the site's EventBridge Scheduler group (papyrus-<site>-agent-schedules) agree with the agents' registered definitions, as the deploy does\n"
                   "  right after `papyrus agents apply`. Each agent that names a schedule, is not retired and is switched on gets one entry named agent-<id>: the\n"
                   "  definition's cron expression in its time zone, with the site's wake queue as its only target. An entry that no agent names is deleted. A timer\n"
                   "  only raises a wake; the run that follows re-checks the policy and the pause. Entries whose names do not start agent- are never touched.\n"
                   "  --site is the site's brand id (the name the wake queue is built from). The agent must name its router publication\n"
                   "  (papyrus automations update <id> --monitor M --publication P). --dry-run reads and says what would change; --check also exits 2 when anything\n"
                   "  differs. Run it as the operator (PAPYRUS_GRAPHQL_AUTH=iam); running it again with nothing changed writes nothing.")


SET_RUNG_USAGE = ("Usage: papyrus --site SITE agents set-rung --id AGENT --rung RUNG --reason TEXT [--scope DIMENSION=VALUE ...] [--apply]\n"
                  "  Set how far one agent may go on this site: write its rung into the agent policy document as a new version that records who, when and why.\n"
                  "  Admin only, and only a person: sign in with `papyrus login` as an admin. A dry run unless --apply: it prints the agent's policy entry before and after and\n"
                  "  the version it would be, and writes nothing. --apply saves it; the old version stays in the history. Raising and lowering are the same command.\n"
                  f"  RUNG is one of: {', '.join(RUNGS)}. AGENT is the id of an agent definition (`papyrus agents validate --dir DIR` lists them). It is refused when the rung is above\n"
                  "  the highest rung the definition's operations need, when it is publish_auto while a hard floor forbids it, and when the reason is missing.\n"
                  "  --scope narrows the change to the override for one scope (list, channel, kind, storyType or section), for example --scope channel=linkedin; repeat it to name more than one.\n"
                  "  --dir and --core name the definition folders as `papyrus agents apply` does (default ./papyrus-site-agents when it exists, then the core definitions).\n"
                  "  The policy body is written to tenants/<tenant>/site/agents/ in the site's media bucket, which the signed-in role must be allowed to write.")


def route_tree() -> dict:
    return {"validate": {}, "apply": {}, "schedules": {}, "set-rung": {}}


def usage_for(words: list[str]) -> str | None:
    return {"validate": VALIDATE_USAGE, "apply": APPLY_USAGE, "schedules": SCHEDULES_USAGE, "set-rung": SET_RUNG_USAGE}.get(" ".join(words))


def validate_command(argv: list[str], stdout: TextIO | None = None) -> int:
    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(VALIDATE_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    directory, core, rest = None, None, list(argv)
    while rest:
        word = rest.pop(0)
        if word in ("--dir", "--core") and rest:
            value = rest.pop(0)
            if word == "--dir":
                directory = value
            else:
                core = value
        else:
            return finish(error_envelope("agents_validate", "invalid_input", f"{word} is not a flag of agents validate, or has no value.", details={"path": word}), ERROR_EXIT_CODE)
    if directory is None:
        return finish(error_envelope("agents_validate", "invalid_input", "Give --dir with the definition files.", details={"path": "--dir"}), ERROR_EXIT_CODE)
    loaded = definition.load_sets(Path(directory), Path(core) if core else definition.CORE_DIRECTORY)
    if loaded.problems:
        return finish(error_envelope("agents_validate", "invalid_input", f"The definitions in {directory} are refused; fix them first.",
                                     details={"problems": [problem.as_dict() for problem in loaded.problems]}), ERROR_EXIT_CODE)
    result = {"definitions": [{"id": item.id, "responsibility": item.responsibility, "source": item.source, "extended": item.extended,
                               "operations": item.data["operations"], "mustNever": item.must_never} for item in loaded.definitions]}
    return finish({"ok": True, "op": "agents_validate", "result": result, "warnings": []}, 0)


def _client():
    from papyrus_content.graphql_authoring import create_authoring_client

    return create_authoring_client()[0]


def apply_command(argv: list[str], stdout: TextIO | None = None, client_factory=None) -> int:
    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(APPLY_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    def refuse(message: str, code: str = "invalid_input", **details) -> int:
        return finish(error_envelope("agents_apply", code, message, details=details), ERROR_EXIT_CODE)

    values: dict[str, str] = {}
    dry_run = check = False
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--dry-run":
            dry_run = True
        elif word == "--check":
            check = True
        elif word in ("--dir", "--core", "--root", "--site-registry") and rest:
            values[word] = rest.pop(0)
        else:
            return refuse(f"{word} is not a flag of agents apply, or has no value.", path=word)
    if dry_run and check:
        return refuse("agents apply takes --check or --dry-run, not both: both read only, --check also fails on a difference.")
    root = Path(values.get("--root", "."))
    site_folder = Path(values["--dir"]) if "--dir" in values else root / release.SITE_FOLDER
    if "--dir" in values and not site_folder.is_dir():
        return refuse(f"The folder of definitions {site_folder} is not there.", path="--dir")
    registry = Path(values["--site-registry"]) if "--site-registry" in values else root / "papyrus-site-procedures.json"
    if "--site-registry" not in values and not registry.is_file():
        registry = None
    core = Path(values["--core"]) if "--core" in values else definition.CORE_DIRECTORY
    try:
        definitions = release.load(site_folder if site_folder.is_dir() else None, core)
        procedures = release.known_procedures(registry)
        client = (client_factory or _client)()
        if check:
            results, action = release.check_drift(client, definitions, procedures), "check"
        else:
            results, action = release.apply_release(client, definitions, procedures, apply=not dry_run), "dry-run" if dry_run else "apply"
    except release.ReleaseDriftError as error:
        return refuse(str(error), "constraint_conflict")
    except release.ReleaseError as error:
        return refuse(str(error))
    return finish({"ok": True, "op": "agents_apply", "result": {"action": action, "definitions": results}, "warnings": []}, 0)


def _aws_clients():
    import boto3   # the operator's environment and the build's both provide it

    return boto3.client("sqs"), boto3.client("scheduler")


def schedules_command(argv: list[str], stdout: TextIO | None = None, client_factory=None, aws_factory=None, reader_factory=None) -> int:
    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(SCHEDULES_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    def refuse(message: str, code: str = "invalid_input", **details) -> int:
        return finish(error_envelope("agents_schedules", code, message, details=details), ERROR_EXIT_CODE)

    site, dry_run, check, rest = None, False, False, list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--dry-run":
            dry_run = True
        elif word == "--check":
            check = True
        elif word == "--site" and rest:
            site = rest.pop(0)
        else:
            return refuse(f"{word} is not a flag of agents schedules, or has no value.", path=word)
    if dry_run and check:
        return refuse("agents schedules takes --check or --dry-run, not both: both read only, --check also fails on a difference.")
    if not site:
        return refuse("Give --site with the site's brand id.", path="--site")
    try:
        from papyrus_content.automations import monitoring_reader_from_environment
        from papyrus_content.graphql_authoring import AUTOMATION_FIELDS

        rows = (client_factory or _client)().list_tenant_rows("Automation", AUTOMATION_FIELDS)
        sqs, scheduler = (aws_factory or _aws_clients)()
        result = schedules.reconcile_site(sqs, scheduler, rows, site, reader=(reader_factory or monitoring_reader_from_environment)(),
                                          endpoint=os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT") or None, apply=not (dry_run or check))
    except (schedules.ScheduleError, schedules.CronError) as error:
        return refuse(str(error))
    action = "check" if check else "dry-run" if dry_run else "apply"
    changed = result["created"] or result["updated"] or result["deleted"]
    if check and changed:
        return refuse("The schedule group differs from the definitions: "
                      + "; ".join(f"{name} {word}" for word, names in (("is missing", result["created"]), ("differs", result["updated"]), ("is not named by any definition", result["deleted"])) for name in names)
                      + ". The deploy reconciles them (papyrus agents schedules).", "constraint_conflict")
    warnings = [] if result["groupDeployed"] else [f"The schedule group {result['group']} is not deployed yet, and no agent needs one."]
    return finish({"ok": True, "op": "agents_schedules", "result": {"action": action, **result}, "warnings": warnings}, 0)


def _policy_store_for_site(client):
    """The policy store over the site's own catalogue and media bucket: the bucket the site publishes, where the runner reads ``tenants/<tenant>/site/agents/``."""
    from papyrus_content.agent_policy import AgentPolicyStore
    from papyrus_content.agent_policy.catalogue import SiteCatalogueTable
    from papyrus_content.env import storage_bucket_from_amplify_outputs
    from papyrus_content.site_store import SiteStore
    from papyrus_content.story_images import user_lane_s3_client
    from papyrus_content.user_auth_mode import user_auth_requested

    bucket = storage_bucket_from_amplify_outputs()
    if not bucket:
        raise ValueError("The site's media bucket is not known: sign in to the site (papyrus login) so its published bucket is read, or run where its amplify_outputs.json is.")
    if user_auth_requested():
        s3 = user_lane_s3_client()
    else:
        import boto3

        s3 = boto3.client("s3")
    return AgentPolicyStore(SiteStore(s3, bucket, SiteCatalogueTable(client)))


def set_rung_command(argv: list[str], stdout: TextIO | None = None, client_factory=None, policy_factory=None, caller_factory=None) -> int:
    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(SET_RUNG_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    def refuse(message: str, code: str = "invalid_input", **details) -> int:
        return finish(error_envelope("agents_set_rung", code, message, details=details), ERROR_EXIT_CODE)

    values: dict[str, str] = {}
    scope: dict[str, str] = {}
    apply = False
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--apply":
            apply = True
        elif word == "--scope" and rest:
            dimension, _, value = rest.pop(0).partition("=")
            if not value:
                return refuse("--scope takes DIMENSION=VALUE, for example --scope channel=linkedin.", path="--scope")
            scope[dimension] = value
        elif word in ("--id", "--rung", "--reason", "--dir", "--core") and rest:
            values[word] = rest.pop(0)
        else:
            return refuse(f"{word} is not a flag of agents set-rung, or has no value.", path=word)
    for flag in ("--id", "--rung", "--reason"):
        if not values.get(flag, "").strip():
            return refuse(f"Give {flag}.", path=flag)
    from papyrus_content.agent_policy import PolicyError, set_rung
    from papyrus_content.images.handlers import Caller
    from papyrus_content.images.profile_handlers import identify

    try:
        site_folder = Path(values["--dir"]) if "--dir" in values else Path(release.SITE_FOLDER)
        if "--dir" in values and not site_folder.is_dir():
            return refuse(f"The folder of definitions {site_folder} is not there.", path="--dir")
        core = Path(values["--core"]) if "--core" in values else definition.CORE_DIRECTORY
        definitions = release.load(site_folder if site_folder.is_dir() else None, core)
        client = (client_factory or _client)()
        kind = "agent" if os.environ.get("PAPYRUS_ACTOR_KIND", "").strip().lower() == "agent" else "person"
        caller = (caller_factory or identify)(client, Caller(kind=kind))
        tenant_id = getattr(client, "tenant_id", None)
        if not tenant_id:
            return refuse("The site's tenant is not known: pass --site, or sign in to the site, so the policy of one site is changed.", path="--site")
        policy = (policy_factory or _policy_store_for_site)(client)
        act = set_rung.apply if apply else set_rung.plan
        change = act(policy, tenant_id, caller, definitions, values["--id"], values["--rung"], reason=values["--reason"], scope=scope or None)
    except release.ReleaseError as error:
        return refuse(str(error))
    except PolicyError as error:
        return refuse(error.message, error.code)
    except ValueError as error:
        return refuse(str(error))
    warnings = [] if change.changed else [f"{change.responsibility} is already as asked; nothing was written."]
    return finish({"ok": True, "op": "agents_set_rung", "result": {"action": "apply" if apply else "dry-run", **change.as_dict()}, "warnings": warnings}, 0)


def command(argv: list[str], stdout: TextIO | None = None) -> int:
    if argv[:1] == ["set-rung"]:
        return set_rung_command(argv[1:], stdout)
    if argv[:1] == ["validate"]:
        return validate_command(argv[1:], stdout)
    if argv[:1] == ["apply"]:
        return apply_command(argv[1:], stdout)
    if argv[:1] == ["schedules"]:
        return schedules_command(argv[1:], stdout)
    out = stdout or sys.stdout
    out.write(json.dumps(error_envelope("agents", "unknown_operation", f"{' '.join(argv) or '(nothing)'} is not an agents command; try: validate, apply, schedules, set-rung.", details={"command": " ".join(argv)}), indent=2) + "\n")
    return ERROR_EXIT_CODE
