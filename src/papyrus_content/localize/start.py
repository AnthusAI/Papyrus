"""Starting a translation from the command line, with no automation (``papyrus stories localize`` without ``--automation``).

A person or an agent asks for one run: the translation request is written, then the site's registered ``story_localize`` procedure runs through
the procedure runner's own code (``procedure_runner.run_procedure_request``): the procedure's published version is loaded from the site, a
ProcedureRun is recorded (status, usage, cost, output), and the procedure executes in a child process with every tool real, exactly as the
cloud runner does it. The only difference from a run the runner Lambda starts is where the process lives: this one, signed as the operator.
The engine records the outcome on the LocalizationRequest as ever. No Automation, monitor or router publication is needed.
"""
from __future__ import annotations

import os
from typing import Any

from ..procedure_runner import ProcedureNotRunnable, execute_in_child, run_procedure_request

SUFFIX = "story-localize"
RUN_SECONDS = 3600   # the child's deadline: a long article takes minutes, and nothing here is bounded by a Lambda


def default_procedure_key(site_host: str | None) -> str:
    """The key the procedure is registered under on a site: ``<site host>.story-localize`` (docs/story-translation-procedure.md)."""
    if not site_host:
        raise ValueError("Name the site (`papyrus --site SITE ...`) or the procedure (--procedure KEY): the procedure's key is SITE.story-localize.")
    return f"{site_host}.{SUFFIX}"


def child_environment(client, *, openai_api_key: str) -> dict[str, str]:
    """This process's environment for the child, pointed at this client's site. The child signs as the operator, as the runner's does."""
    environment = dict(os.environ)
    environment.update(PAPYRUS_GRAPHQL_ENDPOINT=client.endpoint, PAPYRUS_GRAPHQL_AUTH="iam", OPENAI_API_KEY=openai_api_key, PYTHONUNBUFFERED="1")
    if getattr(client, "tenant_id", None):
        environment["PAPYRUS_TENANT_ID"] = client.tenant_id
    return environment


def openai_key(parameter: str | None, *, get_parameter=None) -> str:
    """The model key the run's tool uses: OPENAI_API_KEY in this process, or the SSM parameter named by --openai-key-parameter."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    if not parameter:
        raise ValueError("The translation calls a model. Set OPENAI_API_KEY in this process, or name the site's key with "
                         "--openai-key-parameter SSM_PARAMETER (read with your AWS credentials, never printed).")
    if get_parameter is None:
        import boto3
        get_parameter = lambda name: boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]  # noqa: E731
    return get_parameter(parameter)


def run_from_cli(client, *, story: str, language: str, ceiling_usd: float | None, procedure_key: str, key: str, execute=execute_in_child) -> dict[str, Any]:
    """Run the registered procedure once, here, and return the runner's record (runId, runStatus, costUsd, output)."""
    from ..user_auth_mode import iam_requested

    if not iam_requested():
        raise ValueError("A run started here executes the procedure in a child process that signs as the operator: use `papyrus --auth iam` "
                         "(AWS credentials for the site), or start it through an automation with --automation.")
    request = {"appsyncEndpoint": client.endpoint, "procedureKey": procedure_key, "actorLabel": "papyrus stories localize",
               "input": {"story": story, "language": language, "ceiling_usd": ceiling_usd or 0, "procedure_key": procedure_key},
               "trigger": {"kind": "cli", "title": f"{procedure_key}: {story} into {language}", "summary": "Started with papyrus stories localize"}}
    try:
        return run_procedure_request(request, client=client, execute=execute, seconds_available=RUN_SECONDS + 60,
                                     environment=child_environment(client, openai_api_key=key))
    except ProcedureNotRunnable as error:
        raise ValueError(f"{error}. Register the procedure on this site first: papyrus procedures register --file procedures/newsroom/story_localize.tac "
                         f"--key {procedure_key} (docs/story-translation-procedure.md).") from error
