"""``papyrus agents``: ``validate`` checks a folder of agent definition files with no network, no sign-in and no model (slice D1, PPY-68abaa);
``apply`` applies the definitions to a site as its deploy does (slice D2, PPY-df3e74, ``release.py``); ``schedules`` makes the site's schedule group
agree with the applied definitions (slice C1, PPY-2a53cd, ``schedules.py``).

``set-rung`` sets an agent's rung in the site's policy document (slice H3, PPY-e6f31e, ``agent_policy/set_rung.py``). ``set-budget`` sets the site's AI budget
and releases the paid wakes that waited for it (slice G2, PPY-9376f8, ``spend_stop.py``). ``pause``, ``resume``, ``pauses`` and ``wake`` are rows of the one
operation table (group ``agents``; ``agent_poke_in.py``), run by the table's adapter so the newsroom and the command line share their names and answers.
Later slices add the other ``papyrus agents`` commands (redirect, undo, runbook, explain) to this group.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TextIO

from papyrus_content.actor_identity import actor_kind
from papyrus_content.agent_rungs import RUNGS
from papyrus_content.images.cli import ERROR_EXIT_CODE
from papyrus_content.images.handlers import error_envelope

from .. import agent_listeners as listeners
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


LISTENERS_USAGE = ("Usage: papyrus agents listeners [--dir DIR] [--core DIR] [--root DIR] [--dry-run | --check]\n"
                   "  Write the site's listener index: one small document, derived from the agent definitions in Git, that says which agents listen for which\n"
                   "  change (slice B2, PPY-8a374e). The Item change feed reads it to put a wake on the queue for each agent that listens, so it never lists the\n"
                   "  Automation table or any other. It is run by the deploy right after `papyrus agents schedules`; the same definitions write nothing, a changed set\n"
                   "  writes the next version. It holds no rung, pause or budget (those are the agent policy). --dir, --core and --root are as for `papyrus agents apply`.\n"
                   "  --dry-run reads and says what would change; --check also exits 2 when the index differs. Run it as the operator (PAPYRUS_GRAPHQL_AUTH=iam).")


SCHEDULES_USAGE = ("Usage: papyrus agents schedules --site SITE [--dry-run | --check]\n"
                   "  Make the site's EventBridge Scheduler group (papyrus-<site>-agent-schedules) agree with the agents' registered definitions, as the deploy does\n"
                   "  right after `papyrus agents apply`. Each agent that names a schedule, is not retired and is switched on gets one entry named agent-<id>: the\n"
                   "  definition's cron expression in its time zone, with the site's wake queue as its only target. An entry that no agent names is deleted. A timer\n"
                   "  only raises a wake; the run that follows re-checks the policy and the pause. Entries whose names do not start agent- are never touched.\n"
                   "  --site is the site's brand id (the name the wake queue is built from). The agent must name its router publication\n"
                   "  (papyrus automations update <id> --monitor M --publication P). --dry-run reads and says what would change; --check also exits 2 when anything\n"
                   "  differs. Run it as the operator (PAPYRUS_GRAPHQL_AUTH=iam); running it again with nothing changed writes nothing.")


SET_RUNG_USAGE = ("Usage: papyrus --site SITE agents set-rung --id AGENT --rung RUNG --reason TEXT [--scope DIMENSION=VALUE ...] [--apply]\n"
                  "  [--on-instruction-of PERSON --quote WORDS --agent NAME]  (an agent, on the instruction of the person whose admin session it runs in, up to rung prepare; recorded as theirs, entered by the agent)\n"
                  "  Set how far one agent may go on this site: write its rung into the agent policy document as a new version that records who, when and why.\n"
                  "  Admin only, and only a person: sign in with `papyrus login` as an admin. A dry run unless --apply: it prints the agent's policy entry before and after and\n"
                  "  the version it would be, and writes nothing. --apply saves it; the old version stays in the history. Raising and lowering are the same command.\n"
                  f"  RUNG is one of: {', '.join(RUNGS)}. AGENT is the id of an agent definition (`papyrus agents validate --dir DIR` lists them). It is refused when the rung is above\n"
                  "  the highest rung the definition's operations need, when it is publish_auto while a hard floor forbids it, and when the reason is missing.\n"
                  "  --scope narrows the change to the override for one scope (list, channel, kind, storyType or section), for example --scope channel=linkedin; repeat it to name more than one.\n"
                  "  --dir and --core name the definition folders as `papyrus agents apply` does (default ./papyrus-site-agents when it exists, then the core definitions).\n"
                  "  The policy body is written to tenants/<tenant>/site/agents/ in the site's media bucket, which the signed-in role must be allowed to write.")


SET_BUDGET_USAGE = ("Usage: papyrus --site SITE agents set-budget --amount USD --period day|week|month --reason TEXT [--apply]\n"
                    "  Set the site's AI budget: what paid agent work may spend in each cycle (a day, a week from Monday, or a month, in UTC). At the budget a paid wake\n"
                    "  does not run: its run record waits for the next cycle and one flag a cycle tells the admins; free checks, reading, editing and serving continue.\n"
                    "  Admin only, and only a person: sign in with `papyrus login` as an admin; an agent may never change the budget. A dry run unless --apply: it prints\n"
                    "  the budget before and after, the version it would be and the wakes that wait now, and writes nothing. --apply saves it as a new version of the\n"
                    "  agent policy (who, when and why; signed in, the site's agent-policy function saves it, and refuses a token that is not a person's) and then puts every waiting wake back on the site's queue, oldest first; each re-checks the new budget when it\n"
                    "  arrives, so a budget still too small leaves it waiting. Releasing the wakes needs the operator's AWS credentials for the site's wake queue.\n"
                    "Usage: papyrus --site SITE agents set-budget --agent RESPONSIBILITY --per-run USD --reason TEXT [--apply]\n"
                    "  Set one agent's budget for a single run (RESPONSIBILITY is the agent's key in the agent policy, as the spend ledger names it). A run over it is never\n"
                    "  stopped: it raises one flag with the figures, as a run far above the agent's own cost history does. Admin who is a person only; a dry run unless --apply.")


def route_tree() -> dict:
    from papyrus_content.images import cli as images_cli

    return {"validate": {}, "apply": {}, "schedules": {}, "listeners": {}, "set-rung": {}, "set-budget": {}, **images_cli.route_tree(GROUP)}


def usage_for(words: list[str]) -> str | None:
    from papyrus_content.images import cli as images_cli

    return {"validate": VALIDATE_USAGE, "apply": APPLY_USAGE, "schedules": SCHEDULES_USAGE, "listeners": LISTENERS_USAGE, "set-rung": SET_RUNG_USAGE,
            "set-budget": SET_BUDGET_USAGE}.get(" ".join(words)) or images_cli.usage_for(words, GROUP)


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


def schedules_command(argv: list[str], stdout: TextIO | None = None, client_factory=None, aws_factory=None, reader_factory=None, site_store_factory=None) -> int:
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

        client = (client_factory or _client)()
        rows = client.list_tenant_rows("Automation", AUTOMATION_FIELDS)
        lists = _lists_for_site(client, site_store_factory)
        sqs, scheduler = (aws_factory or _aws_clients)()
        result = schedules.reconcile_site(sqs, scheduler, rows, site, reader=(reader_factory or monitoring_reader_from_environment)(),
                                          endpoint=os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT") or None, apply=not (dry_run or check), lists=lists)
    except (schedules.ScheduleError, schedules.CronError, ValueError) as error:
        return refuse(str(error))
    action = "check" if check else "dry-run" if dry_run else "apply"
    changed = result["created"] or result["updated"] or result["deleted"]
    if check and changed:
        return refuse("The schedule group differs from the definitions: "
                      + "; ".join(f"{name} {word}" for word, names in (("is missing", result["created"]), ("differs", result["updated"]), ("is not named by any definition", result["deleted"])) for name in names)
                      + ". The deploy reconciles them (papyrus agents schedules).", "constraint_conflict")
    warnings = [] if result["groupDeployed"] else [f"The schedule group {result['group']} is not deployed yet, and no agent needs one."]
    return finish({"ok": True, "op": "agents_schedules", "result": {"action": action, **result}, "warnings": warnings}, 0)


def listeners_command(argv: list[str], stdout: TextIO | None = None, client_factory=None, site_store_factory=None) -> int:
    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(LISTENERS_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    def refuse(message: str, code: str = "invalid_input", **details) -> int:
        return finish(error_envelope("agents_listeners", code, message, details=details), ERROR_EXIT_CODE)

    values: dict[str, str] = {}
    dry_run = check = False
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--dry-run":
            dry_run = True
        elif word == "--check":
            check = True
        elif word in ("--dir", "--core", "--root") and rest:
            values[word] = rest.pop(0)
        else:
            return refuse(f"{word} is not a flag of agents listeners, or has no value.", path=word)
    if dry_run and check:
        return refuse("agents listeners takes --check or --dry-run, not both: both read only, --check also fails on a difference.")
    root = Path(values.get("--root", "."))
    site_folder = Path(values["--dir"]) if "--dir" in values else root / release.SITE_FOLDER
    if "--dir" in values and not site_folder.is_dir():
        return refuse(f"The folder of definitions {site_folder} is not there.", path="--dir")
    core = Path(values["--core"]) if "--core" in values else definition.CORE_DIRECTORY
    try:
        definitions = release.load(site_folder if site_folder.is_dir() else None, core)
        client = (client_factory or _client)()
        tenant_id = getattr(client, "tenant_id", None)
        if not tenant_id:
            return refuse("The site's tenant is not known, so its listener index cannot be written: sign in to the site (papyrus login), or run as the operator with the site's tenant set.", path="--site")
        result = listeners.publish((site_store_factory or _site_store_for)(client), tenant_id, definitions, actor=release.ACTOR, apply=not (dry_run or check))
    except release.ReleaseError as error:
        return refuse(str(error))
    except ValueError as error:
        return refuse(str(error))
    if check and result["action"] != "unchanged":
        return refuse(f"The listener index differs from the definitions in Git ({result['action']}). The deploy writes it (papyrus agents listeners).", "constraint_conflict")
    return finish({"ok": True, "op": "agents_listeners", "result": {"action": "check" if check else "dry-run" if dry_run else "apply", "index": result}, "warnings": []}, 0)


def _site_store_for(client):
    """The site store over the site's own catalogue and media bucket: the bucket the site publishes, where the runner reads ``tenants/<tenant>/site/<kind>/``."""
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
    return SiteStore(s3, bucket, SiteCatalogueTable(client))


def _policy_function_sender(client):
    def send(request: dict) -> dict:
        answer = client.graphql("mutation AgentPolicyChange($input: AWSJSON) { agentPolicyChange(input: $input) }", {"input": json.dumps(request)})["agentPolicyChange"]
        return json.loads(answer) if isinstance(answer, str) else answer

    return send


def _policy_store_for_site(client):
    from papyrus_content.agent_policy import AgentPolicyStore
    from papyrus_content.agent_policy.remote import RemoteAgentPolicyStore
    from papyrus_content.user_auth_mode import user_auth_requested

    site_store = _site_store_for(client)
    if user_auth_requested():
        return RemoteAgentPolicyStore(site_store, _policy_function_sender(client))
    return AgentPolicyStore(site_store)


def _lists_for_site(client, site_store_for=None) -> dict:
    """The periodic lists of the site (``list_cadence.schedule.wanted``): each is a schedule entry the group must hold. A site that has never saved list settings has none."""
    from papyrus_content.list_cadence import schedule as list_schedule
    from papyrus_content.list_cadence.store import ListSettingsStore

    tenant_id = getattr(client, "tenant_id", None)
    if not tenant_id:
        raise ValueError("The site's tenant is not known, so its lists cannot be read and their schedule entries would be deleted: sign in to the site (papyrus login).")
    return list_schedule.wanted(ListSettingsStore((site_store_for or _site_store_for)(client)).read(tenant_id).document)


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
        elif word in ("--id", "--rung", "--reason", "--dir", "--core", "--on-instruction-of", "--quote", "--agent") and rest:
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
        kind = actor_kind()
        caller = (caller_factory or identify)(client, Caller(kind=kind))
        if caller.kind == "agent":
            from papyrus_content.agent_policy.delegation import delegated_caller

            caller, delegated = delegated_caller(caller, person=values.get("--on-instruction-of", ""), quote=values.get("--quote", ""), agent=values.get("--agent", ""),
                                                 rung=values.get("--rung", ""))
            values["--reason"] = f"{values['--reason'].strip()} {delegated}"
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


def set_budget_command(argv: list[str], stdout: TextIO | None = None, client_factory=None, policy_factory=None, caller_factory=None,
                       sender_factory=None) -> int:
    out = stdout or sys.stdout
    if argv in (["--help"], ["-h"]):
        out.write(SET_BUDGET_USAGE + "\n")
        return 0

    def finish(envelope: dict, code: int) -> int:
        out.write(json.dumps(envelope, indent=2) + "\n")
        return code

    def refuse(message: str, code: str = "invalid_input", **details) -> int:
        return finish(error_envelope("agents_set_budget", code, message, details=details), ERROR_EXIT_CODE)

    values: dict[str, str] = {}
    apply = False
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--apply":
            apply = True
        elif word in ("--amount", "--period", "--reason", "--agent", "--per-run") and rest:
            values[word] = rest.pop(0)
        else:
            return refuse(f"{word} is not a flag of agents set-budget, or has no value.", path=word)
    if "--agent" in values or "--per-run" in values:
        return set_run_budget(values, apply, finish, refuse, client_factory=client_factory, policy_factory=policy_factory, caller_factory=caller_factory)
    for flag in ("--amount", "--period", "--reason"):
        if not values.get(flag, "").strip():
            return refuse(f"Give {flag}.", path=flag)
    try:
        amount = float(values["--amount"])
    except ValueError:
        return refuse("--amount is a number of US dollars, such as 25.", path="--amount")
    budget = {"amountUsd": int(amount) if amount.is_integer() else amount, "period": values["--period"]}
    from papyrus_content import spend_stop
    from papyrus_content.agent_policy import PolicyError
    from papyrus_content.images.handlers import Caller
    from papyrus_content.images.profile_handlers import identify

    try:
        client = (client_factory or _client)()
        caller = (caller_factory or identify)(client, Caller(kind=actor_kind()))
        tenant_id = getattr(client, "tenant_id", None)
        if not tenant_id:
            return refuse("The site's tenant is not known: pass --site, or sign in to the site, so the budget of one site is changed.", path="--site")
        policy = (policy_factory or _policy_store_for_site)(client)

        def edit(document: dict) -> None:
            document["site"]["budget"] = budget

        state, document = policy.prepare(tenant_id, caller, values["--reason"], edit)
        before = state.document.get("site", {}).get("budget")
        changed = document != state.document
        waiting = spend_stop.waiting_runs(client, tenant_id)
        result = {"action": "apply" if apply else "dry-run", "budget": {"before": before, "after": budget}, "changed": changed, "applied": False,
                  "policyVersion": {"before": state.version, "after": state.version + 1 if changed else state.version},
                  "waiting": [row.get("wakeKey") for row in waiting]}
        if not apply:
            return finish({"ok": True, "op": "agents_set_budget", "result": result, "warnings": [] if changed else ["The budget is already as asked; nothing would be written."]}, 0)
        saved = policy.set_value(tenant_id, caller, "budget", budget, reason=values["--reason"]) if changed else state
        result.update(applied=changed, policyVersion={"before": state.version, "after": saved.version})
    except PolicyError as error:
        return refuse(error.message, error.code)
    except ValueError as error:
        return refuse(str(error))
    try:
        result["release"] = spend_stop.release(client, (sender_factory or _wake_sender)(), tenant_id)
    except Exception as error:   # the budget is saved; the waiting wakes still run when the cycle turns, and running this again releases them
        return finish(error_envelope("agents_set_budget", "release_failed",
                                     f"The budget was saved (policy version {result['policyVersion']['after']}), but the waiting wakes could not be put back on the queue "
                                     f"({type(error).__name__}: {error}). They run when the cycle turns; run this command again with the operator's AWS credentials to release them now.",
                                     details={"result": result}), ERROR_EXIT_CODE)
    return finish({"ok": True, "op": "agents_set_budget", "result": result, "warnings": [] if changed else ["The budget is already as asked; nothing was written."]}, 0)


def set_run_budget(values: dict[str, str], apply: bool, finish, refuse, *, client_factory=None, policy_factory=None, caller_factory=None) -> int:
    """``agents set-budget --agent R --per-run USD``: the owner's budget for one run of one agent. It only flags (unusual_cost.py), so nothing waits on it and
    nothing is released."""
    for flag in ("--agent", "--per-run", "--reason"):
        if not values.get(flag, "").strip():
            return refuse(f"Give {flag}.", path=flag)
    if "--amount" in values or "--period" in values:
        return refuse("--per-run sets one agent's budget for a run; --amount and --period set the site's budget. Give one or the other.", path="--per-run")
    try:
        per_run = float(values["--per-run"])
    except ValueError:
        return refuse("--per-run is a number of US dollars, such as 0.25.", path="--per-run")
    responsibility = values["--agent"].strip()
    from papyrus_content.agent_policy import PolicyError
    from papyrus_content.images.handlers import Caller
    from papyrus_content.images.profile_handlers import identify

    try:
        client = (client_factory or _client)()
        caller = (caller_factory or identify)(client, Caller(kind=actor_kind()))
        tenant_id = getattr(client, "tenant_id", None)
        if not tenant_id:
            return refuse("The site's tenant is not known: pass --site, or sign in to the site, so the budget of one site is changed.", path="--site")
        policy = (policy_factory or _policy_store_for_site)(client)

        def edit(document: dict) -> None:
            document["agents"].setdefault(responsibility, {"rung": "off"})["budgetUsdPerRun"] = per_run

        state, document = policy.prepare(tenant_id, caller, values["--reason"], edit)
        changed = document != state.document
        result = {"action": "apply" if apply else "dry-run", "agent": responsibility, "changed": changed, "applied": False,
                  "budgetUsdPerRun": {"before": (state.document["agents"].get(responsibility) or {}).get("budgetUsdPerRun"), "after": per_run},
                  "policyVersion": {"before": state.version, "after": state.version + 1 if changed else state.version}}
        if apply and changed:
            saved = policy.set_value(tenant_id, caller, "budgetUsdPerRun", per_run, reason=values["--reason"], responsibility=responsibility)
            result.update(applied=True, policyVersion={"before": state.version, "after": saved.version})
    except PolicyError as error:
        return refuse(error.message, error.code)
    except ValueError as error:
        return refuse(str(error))
    warnings = [] if changed else ["The agent's budget per run is already as asked; nothing " + ("was" if apply else "would be") + " written."]
    return finish({"ok": True, "op": "agents_set_budget", "result": result, "warnings": warnings}, 0)


def _wake_sender():
    from papyrus_content.agent_wakes import wake_sender

    return wake_sender()


def command(argv: list[str], stdout: TextIO | None = None) -> int:
    from papyrus_content.images import cli as images_cli

    if argv[:1] and argv[0] in images_cli.route_tree(GROUP):
        return images_cli.command(argv, group=GROUP, stdout=stdout)
    if argv[:1] == ["set-budget"]:
        return set_budget_command(argv[1:], stdout)
    if argv[:1] == ["set-rung"]:
        return set_rung_command(argv[1:], stdout)
    if argv[:1] == ["validate"]:
        return validate_command(argv[1:], stdout)
    if argv[:1] == ["apply"]:
        return apply_command(argv[1:], stdout)
    if argv[:1] == ["schedules"]:
        return schedules_command(argv[1:], stdout)
    if argv[:1] == ["listeners"]:
        return listeners_command(argv[1:], stdout)
    out = stdout or sys.stdout
    out.write(json.dumps(error_envelope("agents", "unknown_operation", f"{' '.join(argv) or '(nothing)'} is not an agents command; try: validate, apply, schedules, listeners, set-rung, set-budget, pause, resume, pauses, wake.", details={"command": " ".join(argv)}), indent=2) + "\n")
    return ERROR_EXIT_CODE
