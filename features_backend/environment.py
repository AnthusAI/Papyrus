from __future__ import annotations

import importlib.util
import os
import shutil
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


def before_scenario(context, scenario):
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
    if OPERATOR_TAG in scenario.effective_tags:
        graphql_stub_server = getattr(context, "graphql_stub_server", None)
        if graphql_stub_server is not None:
            graphql_stub_server.shutdown()
            graphql_stub_server.server_close()
            context.graphql_stub_server = None
            context.graphql_stub_endpoint = None
        os.environ.clear()
        os.environ.update(context.env)
