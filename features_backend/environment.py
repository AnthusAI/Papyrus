from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
from pathlib import Path

REQUIRES_CYCLOTRON_TAG = "requires-cyclotron"
CYCLOTRON_MODULE = "decision_flywheel"
OPERATOR_TAG = "operator"
WORK_IN_PROGRESS_TAG = "wip"
REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATOR_FIXTURE_ROOT = REPO_ROOT / "features_backend" / "fixtures" / "operator-cli"


def before_all(context):
    context.repo_root = REPO_ROOT
    context.fixture_root = OPERATOR_FIXTURE_ROOT
    context.tmp_dirs = []
    context.last_result = None


def after_all(context):
    for tmp_dir in getattr(context, "tmp_dirs", []):
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Variables that choose a GraphQL lane or a signed-in site. A developer's machine has a real `papyrus login` session in
# ~/.config/papyrus and often a lane in the shell; scenarios must see neither (PPY-5f119a). A scenario that wants a lane sets it.
SIGN_IN_ENVIRONMENT = ("PAPYRUS_GRAPHQL_AUTH", "PAPYRUS_CLI_AUTH_CONFIG", "PAPYRUS_GRAPHQL_ENDPOINT")


def isolate_sign_in(context):
    context.sign_in_saved = {name: os.environ.pop(name, None) for name in (*SIGN_IN_ENVIRONMENT, "PAPYRUS_CLI_STATE_DIR")}
    context.sign_in_state_dir = tempfile.mkdtemp(prefix="papyrus-behave-state-")
    os.environ["PAPYRUS_CLI_STATE_DIR"] = context.sign_in_state_dir


def restore_sign_in(context):
    shutil.rmtree(getattr(context, "sign_in_state_dir", ""), ignore_errors=True)
    for name, value in getattr(context, "sign_in_saved", {}).items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def before_scenario(context, scenario):
    from papyrus_content import cli_user_auth

    isolate_sign_in(context)

    context.real_site_enrolls = cli_user_auth.site_enrolls
    cli_user_auth.site_enrolls = lambda config, **kwargs: False
    if WORK_IN_PROGRESS_TAG in scenario.effective_tags:
        scenario.skip("work in progress: waits for a task that has not landed")
        return
    if REQUIRES_CYCLOTRON_TAG in scenario.effective_tags and importlib.util.find_spec(CYCLOTRON_MODULE) is None:
        scenario.skip("decision_flywheel not installed (poetry install --with cyclotron)")
    if OPERATOR_TAG in scenario.effective_tags:
        context.env = os.environ.copy()
        context.config_path = None
        context.last_command = ""
        context.last_result = None
        context.content_store_reads = []
        context.fixture_root_active = True
        context.graphql_stub_endpoint = None


def after_scenario(context, scenario):
    from unittest import mock

    from papyrus_content import cli_user_auth

    mock.patch.stopall()   # patches a scenario started and did not stop (the router's idea sink double)

    cli_user_auth.site_enrolls = context.real_site_enrolls
    if OPERATOR_TAG in scenario.effective_tags:
        graphql_stub_server = getattr(context, "graphql_stub_server", None)
        if graphql_stub_server is not None:
            graphql_stub_server.shutdown()
            graphql_stub_server.server_close()
            context.graphql_stub_server = None
            context.graphql_stub_endpoint = None
        os.environ.clear()
        os.environ.update(context.env)
    restore_sign_in(context)
