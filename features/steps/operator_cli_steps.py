from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml
from behave import given, then, when

from papyrus.operator.commands.references import accepted_flags_for


def _run_papyrus(context, command: str, *, clean_env: bool = False) -> None:
    context.last_command = command
    env = {} if clean_env else os.environ.copy()
    env.pop("PAPYRUS_GRAPHQL_JWT", None)
    env["PYTHONPATH"] = f"{context.repo_root / 'src'}:{context.repo_root}"
    if context.config_path:
        env["PAPYRUS_OPERATOR_CONFIG"] = str(context.config_path)
    if getattr(context, "fixture_root_active", False):
        env["PAPYRUS_OPERATOR_FIXTURE_ROOT"] = str(context.fixture_root)
    if getattr(context, "tmp_env_path", None) and context.tmp_env_path.exists():
        env["PAPYRUS_GRAPHQL_JWT"] = _read_env_value(context.tmp_env_path, "PAPYRUS_GRAPHQL_JWT")
    if getattr(context, "expired_jwt", False):
        env["PAPYRUS_GRAPHQL_JWT"] = _mint_test_jwt(expired=True)
    elif getattr(context, "missing_jwt", False):
        env.pop("PAPYRUS_GRAPHQL_JWT", None)
    if getattr(context, "auth_secret", None):
        env["PAPYRUS_SANDBOX_JWT_SECRET"] = context.auth_secret

    argv = shlex.split(command)
    if argv and argv[0] == "papyrus":
        argv = argv[1:]

    completed = subprocess.run(
        [sys.executable, "-m", "papyrus.cli", *argv],
        cwd=context.repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    context.last_result = completed


def _mint_test_jwt(*, expired: bool) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    now = int(time.time())
    exp = now - 60 if expired else now + 3600
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": exp, "sub": "operator-cli-test"}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.signature"


def _read_env_value(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


@given("the operator CLI fixture root is available")
def step_fixture_root(context):
    assert context.fixture_root.exists()


@given('operator CLI config selects backend "{backend}"')
def step_config_backend(context, backend):
    context.pending_backend = backend
    _write_config(context)


@given('operator CLI config sets default corpus key "{corpus_key}"')
def step_config_corpus(context, corpus_key):
    context.pending_corpus = corpus_key
    _write_config(context)


@given('the cloud references fixture is loaded')
def step_cloud_references_fixture(context):
    context.fixture_root_active = True


@given("the cloud assignments fixture is loaded")
def step_cloud_assignments_fixture(context):
    context.fixture_root_active = True


@given('the local pod fixture "anthus-blog" is configured')
def step_local_pod_fixture(context):
    context.fixture_root_active = True
    context.pending_backend = "local"
    _write_config(context)


@given("cloud auth fixtures can mint a JWT")
def step_cloud_auth_fixture(context):
    context.auth_secret = "operator-cli-test-secret"


@given("`PAPYRUS_GRAPHQL_JWT` is expired")
def step_expired_jwt(context):
    context.expired_jwt = True


@given("`PAPYRUS_GRAPHQL_JWT` is missing")
def step_missing_jwt(context):
    context.missing_jwt = True


@when("I run `{command}`")
def step_run_command(context, command):
    if "<tmp-env>" in command:
        tmp_dir = Path(tempfile.mkdtemp(prefix="operator-cli-env-"))
        context.tmp_dirs.append(tmp_dir)
        context.tmp_env_path = tmp_dir / ".env"
        command = command.replace("<tmp-env>", str(context.tmp_env_path))
    _run_papyrus(context, command)


@when("I run `{command}` from a clean environment without PYTHONPATH")
def step_run_clean_command(context, command):
    _run_papyrus(context, command, clean_env=True)


@when("I compare accepted flags for `{command}`")
def step_compare_flags(context, command):
    context.flag_command = command


@then("the exit code should be {code:d}")
def step_exit_code(context, code):
    assert context.last_result is not None
    assert context.last_result.returncode == code, context.last_result.stderr


@then("stderr should be empty")
def step_stderr_empty(context):
    assert (context.last_result.stderr or "").strip() == ""


@then('stderr should contain "{text}"')
def step_stderr_contains(context, text):
    assert text in (context.last_result.stderr or "")


@then('stdout should mention `list` and `show`')
def step_stdout_mentions_list_and_show(context):
    output = context.last_result.stdout or ""
    assert "list" in output
    assert "show" in output


@then('stderr should mention `local` and `cloud`')
def step_stderr_mentions_backends(context):
    stderr = context.last_result.stderr or ""
    assert "local" in stderr
    assert "cloud" in stderr


@then('stderr should mention `papyrus auth refresh`')
def step_stderr_mentions_auth_refresh(context):
    assert "papyrus auth refresh" in (context.last_result.stderr or "")


@then('stderr should not mention `papyrus auth refresh`')
def step_stderr_no_auth_refresh(context):
    assert "papyrus auth refresh" not in (context.last_result.stderr or "")


@then('stderr should not contain "{text}"')
def step_stderr_not_contains(context, text):
    assert text not in (context.last_result.stderr or "")


@then('stderr should not contain a Python traceback')
def step_no_traceback(context):
    assert "Traceback" not in (context.last_result.stderr or "")


@then('stdout should mention `references`, `assignments`, `auth`, and `knowledge`')
def step_stdout_mentions_groups(context):
    output = context.last_result.stdout or ""
    for item in ("references", "assignments", "auth", "knowledge"):
        assert item in output


@then('stdout should mention `{item}`')
def step_stdout_mentions(context, item):
    assert item in (context.last_result.stdout or "")


@then("stdout should list the available `{group}` subcommands")
def step_stdout_lists_subcommands(context, group):
    output = context.last_result.stdout or ""
    assert group in output
    assert "usage:" in output.lower() or "Usage:" in output


@then("stdout should explain that backend selection comes from project config or `--backend`")
def step_stdout_backend_help(context):
    output = context.last_result.stdout or ""
    assert "--backend" in output
    assert "config" in output.lower()


@then('stdout should report backend "{backend}"')
def step_stdout_reports_backend(context, backend):
    assert f"backend={backend}" in (context.last_result.stdout or "")


@then('stdout should report corpus key "{corpus_key}"')
def step_stdout_reports_corpus(context, corpus_key):
    assert f"corpusKey={corpus_key}" in (context.last_result.stdout or "")


@then("stdout should not require `--corpus-key` on the command line")
def step_no_corpus_flag_required(context):
    assert "--corpus-key" not in context.last_command


@then("stdout should be tabular operator output")
def step_tabular_output(context):
    lines = [line for line in (context.last_result.stdout or "").splitlines() if line.strip()]
    assert len(lines) >= 2
    assert "\t" in lines[-1] or "\t" in lines[0]


@then("stdout header should include columns:")
def step_header_columns(context):
    header_line = _table_header(context)
    for row in context.table:
        assert row["column"] in header_line


@then('stdout row kind should be "{kind}"')
def step_row_kind(context, kind):
    for line in _table_body_lines(context):
        assert line.split("\t", 1)[0] == kind


@then('stdout should contain reference id "{reference_id}"')
def step_contains_reference(context, reference_id):
    assert reference_id in (context.last_result.stdout or "")


@then('stdout should contain assignment id "{assignment_id}"')
def step_contains_assignment(context, assignment_id):
    assert assignment_id in (context.last_result.stdout or "")


@then('stdout should contain story id "{story_id}"')
def step_contains_story(context, story_id):
    assert story_id in (context.last_result.stdout or "")


@then('every listed reference should have status "{status}"')
def step_every_reference_status(context, status):
    for line in _table_body_lines(context):
        parts = line.split("\t")
        assert parts[1] == status


@then("stdout should read pod artifacts from the Kanbus project")
def step_reads_pod_artifacts(context):
    assert "pod-reference" in (context.last_result.stdout or "")


@then("stdout should not read a revived local Markdown content store")
def step_no_markdown_store(context):
    output = context.last_result.stdout or ""
    assert "content/articles" not in output


@then("stdout should be a single reference detail block")
def step_reference_detail_block(context):
    output = context.last_result.stdout or ""
    assert output.startswith("reference\n")
    assert "kind:" in output
    assert "id:" in output


@then('stdout should report kind "{kind}"')
def step_report_kind(context, kind):
    assert f"kind: {kind}" in (context.last_result.stdout or "")


@then('stdout should report id "{identifier}"')
def step_report_id(context, identifier):
    assert f"id: {identifier}" in (context.last_result.stdout or "")


@then("stdout should not label any row as a pod story")
def step_no_pod_story(context):
    for line in _table_body_lines(context):
        assert not line.startswith("pod-story")


@then("stdout should not label any row as a newsroom-assignment")
def step_no_newsroom_assignment(context):
    for line in _table_body_lines(context):
        assert not line.startswith("newsroom-assignment")


@then("stdout help context should direct board work to `kbs`")
def step_kbs_hint(context):
    assert "kbs" in (context.last_result.stdout or "")


@then("stdout should explain that cloud rows are GraphQL Assignment records")
def step_help_cloud_assignments(context):
    assert "GraphQL Assignment" in (context.last_result.stdout or "")


@then("stdout should explain that local rows are Kanbus pod stories")
def step_help_local_stories(context):
    assert "pod stor" in (context.last_result.stdout or "").lower()


@then("stdout should state that `kbs` owns board columns and transitions")
def step_help_kbs_owns_board(context):
    output = context.last_result.stdout or ""
    assert "kbs" in output
    assert "transitions" in output.lower() or "columns" in output.lower()


@then("stdout should confirm the JWT was written")
def step_jwt_written(context):
    output = context.last_result.stdout or ""
    assert "PAPYRUS_GRAPHQL_JWT" in output


@then('the file "{path}" should contain `PAPYRUS_GRAPHQL_JWT`')
def step_env_contains_jwt(context, path):
    resolved = Path(path.replace("<tmp-env>", str(context.tmp_env_path)))
    assert "PAPYRUS_GRAPHQL_JWT=" in resolved.read_text(encoding="utf-8")


@then("local and cloud should accept the same flags:")
def step_same_flags(context):
    command = context.flag_command
    flags = {row["flag"] for row in context.table}
    assert accepted_flags_for(command) == flags


def _write_config(context) -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="operator-cli-config-"))
    context.tmp_dirs.append(tmp_dir)
    config = {
        "backend": getattr(context, "pending_backend", "cloud"),
        "defaultCorpusKey": getattr(context, "pending_corpus", "threat-intelligence"),
        "publicationKey": getattr(context, "pending_corpus", "threat-intelligence"),
        "local": {"podPath": str(context.fixture_root / "local-pod" / "anthus-blog")},
        "cloud": {"graphqlEndpoint": "https://example.appsync-api.example.com/graphql"},
    }
    context.config_path = tmp_dir / "operator-cli.config.yaml"
    context.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _table_header(context) -> str:
    for line in (context.last_result.stdout or "").splitlines():
        if line.startswith("kind\t"):
            return line
    raise AssertionError("missing tabular header")


def _table_body_lines(context) -> list[str]:
    lines = []
    for line in (context.last_result.stdout or "").splitlines():
        if line.startswith("kind\t") or line.startswith("backend=") or line.startswith("corpusKey="):
            continue
        if line.startswith("hint="):
            continue
        if "\t" in line:
            lines.append(line)
    return lines
