from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

REQUIRES_CYCLOTRON_TAG = "requires-cyclotron"
CYCLOTRON_MODULE = "decision_flywheel"
OPERATOR_TAG = "operator"
WORK_IN_PROGRESS_TAG = "wip"
SANDBOX_TAG = "sandbox"
ISOLATION_PENDING_TAG = "isolation-pending"
CHECKLIST_GATE_TAG = "checklist-gate"
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


def _fake_client_modules():
    """The shared in-memory fake, under every name the step files import it by (`fake_client`, `procedures.newsroom.tests.fake_client`)."""
    return [module for name, module in list(sys.modules.items()) if name.endswith("fake_client") and hasattr(module, "head_stage_key_violations")]


def _check_head_stage_keys(scenario) -> None:
    """After every backend scenario: each story lineage written through the shared fake has at most one head row, and it carries its stage
    (features_backend/story-head-stage-index.feature). A writer that sets a stage or a version state without the head stage key fails here."""
    problems = []
    for module in _fake_client_modules():
        for client in module.INSTANCES:
            problems += module.head_stage_key_violations(client)
        module.INSTANCES.clear()
    if problems and scenario.status != "failed":
        raise AssertionError("head stage key invariant broken in '" + scenario.name + "':\n  " + "\n  ".join(problems))


def before_scenario(context, scenario):
    for module in _fake_client_modules():
        module.INSTANCES.clear()
    from papyrus_content import cli_user_auth

    context.real_site_enrolls = cli_user_auth.site_enrolls
    cli_user_auth.site_enrolls = lambda config, **kwargs: False
    from papyrus_content import multi_search_research

    multi_search_research.fetch_source = lambda url: None     # no scenario reaches the network; one that reads pages passes its own reader
    if CHECKLIST_GATE_TAG not in scenario.effective_tags:
        # Publishing refuses while a required checklist step is open (docs/story-procedure.md). Scenarios about something else publish Stories freely;
        # only the features tagged @checklist-gate exercise the rule, with the real checklist.
        from unittest import mock

        mock.patch("papyrus_content.story_checklist.require_checklist_closed", lambda client, item: None).start()
    if WORK_IN_PROGRESS_TAG in scenario.effective_tags:
        scenario.skip("work in progress: waits for a task that has not landed")
        return
    if SANDBOX_TAG in scenario.effective_tags:
        scenario.skip("needs an ampx sandbox with Google test users: run by hand (spikes/tenant-claims-1/README.md)")
        return
    if ISOLATION_PENDING_TAG in scenario.effective_tags:
        scenario.skip("pending: needs the shared stack with two seeded tenants (features_backend/tenant-isolation-adversarial.feature)")
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

    try:
        _check_head_stage_keys(scenario)
    finally:
        _after_scenario_cleanup(context, scenario, mock)


def _after_scenario_cleanup(context, scenario, mock):

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
