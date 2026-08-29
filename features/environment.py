from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "features" / "fixtures" / "operator-cli"


def before_all(context):
    context.repo_root = REPO_ROOT
    context.fixture_root = FIXTURE_ROOT
    context.tmp_dirs: list[Path] = []
    context.last_result = None


def after_all(context):
    for tmp_dir in getattr(context, "tmp_dirs", []):
        shutil.rmtree(tmp_dir, ignore_errors=True)


def before_scenario(context, scenario):
    context.env = os.environ.copy()
    context.config_path = None
    context.last_command = ""
    context.last_result = None
    context.tmp_env_path = None
    context.content_store_reads: list[str] = []
    context.fixture_root_active = True


def after_scenario(context, scenario):
    os.environ.clear()
    os.environ.update(context.env)
