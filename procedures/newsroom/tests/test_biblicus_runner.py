from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from papyrus_content import biblicus_runner
from papyrus_content.biblicus_runner import (
    BiblicusCommandError,
    BiblicusCommandTimeoutError,
    BiblicusExecutableError,
    BiblicusInvalidRequestError,
    BiblicusOperationFailedError,
    BiblicusOutputError,
    BiblicusRunner,
    BiblicusRunnerError,
    BiblicusWorkdirError,
    build_biblicus_environment,
    resolve_biblicus_executable,
    resolve_biblicus_workdir,
)

FAKE_BIBLICUS_SCRIPT = """#!{python}
import json, os, sys, time

arguments = sys.argv[1:]
mode = os.environ.get("FAKE_BIBLICUS_MODE", "echo")
stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
if mode == "echo":
    print(json.dumps({{"arguments": arguments, "cwd": os.getcwd(), "stdin": stdin_text, "grobid": os.environ.get("BIBLICUS_GROBID_URL")}}))
elif mode == "invalid-request":
    print(json.dumps({{"status": "failed", "error": {{"code": "invalid_input_json", "message": "bad input", "details": {{}}}}}}))
    sys.exit(2)
elif mode == "operation-failed":
    details = {{"source_kind": "web", "strategy": "direct", "content_type": None, "prompt_version": "v1", "attempts": [], "http_status": 404}}
    print(json.dumps({{"status": "failed", "error": {{"code": "provider_failed", "message": "provider said no", "details": details}}}}))
    sys.exit(1)
elif mode == "envelope-unexpected-exit":
    print(json.dumps({{"status": "failed", "error": {{"code": "provider_failed", "message": "provider said no"}}}}))
    sys.exit(3)
elif mode == "usage-error":
    sys.stderr.write("usage: biblicus extract url-text [-h]\\nbiblicus: error: unrecognized arguments: --bogus")
    sys.exit(2)
elif mode == "fail-plain":
    sys.stderr.write("Traceback: boom")
    sys.exit(1)
elif mode == "fail-silent":
    sys.exit(3)
elif mode == "not-json":
    print("not json at all")
elif mode == "sleep":
    time.sleep(30)
elif mode == "typed":
    print(os.environ["FAKE_BIBLICUS_PAYLOAD"])
"""


@pytest.fixture
def fake_biblicus(tmp_path: Path) -> Path:
    script = tmp_path / "bin" / "biblicus"
    script.parent.mkdir()
    script.write_text(FAKE_BIBLICUS_SCRIPT.format(python=sys.executable), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    directory = tmp_path / "workdir"
    directory.mkdir()
    return directory


def make_runner(fake_biblicus: Path, workdir: Path, **environment: str) -> BiblicusRunner:
    return BiblicusRunner(workdir=workdir, environment={"PATH": "/usr/bin:/bin", **environment}, executable=fake_biblicus)


def test_run_returns_stripped_output_and_uses_workdir_and_environment(fake_biblicus: Path, workdir: Path) -> None:
    runner = make_runner(fake_biblicus, workdir, BIBLICUS_GROBID_URL="http://grobid.example")
    output = runner.run(["reindex", "--corpus", "corpora/notes"], stdin_text="payload")
    parsed = json.loads(output.stdout)
    assert parsed["arguments"] == ["reindex", "--corpus", "corpora/notes"]
    assert Path(parsed["cwd"]).resolve() == workdir.resolve()
    assert parsed["stdin"] == "payload"
    assert parsed["grobid"] == "http://grobid.example"
    assert output.command == (str(fake_biblicus), "reindex", "--corpus", "corpora/notes")
    assert runner.command(["query"]) == [str(fake_biblicus), "query"]


def test_run_json_parses_standard_output(fake_biblicus: Path, workdir: Path) -> None:
    parsed = make_runner(fake_biblicus, workdir).run_json(["steering", "artifacts"])
    assert parsed["arguments"] == ["steering", "artifacts"]


def test_nonzero_exit_raises_command_error_with_command_exit_code_and_stderr(fake_biblicus: Path, workdir: Path) -> None:
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="fail-plain")
    with pytest.raises(BiblicusCommandError) as caught:
        runner.run(["reindex"])
    error = caught.value
    assert error.command == (str(fake_biblicus), "reindex")
    assert error.exit_code == 1
    assert error.stderr == "Traceback: boom"
    assert error.failure_message() == "Traceback: boom"
    assert error.failure_reason() == {"code": "biblicus_cli_failed", "message": "Traceback: boom"}
    assert "exited 1" in str(error)


def test_typed_failure_envelope_with_exit_two_is_an_invalid_request_error(fake_biblicus: Path, workdir: Path) -> None:
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="invalid-request")
    with pytest.raises(BiblicusInvalidRequestError) as caught:
        runner.run(["extract", "web-metadata"])
    error = caught.value
    assert isinstance(error, BiblicusCommandError)
    assert (error.exit_code, error.code, error.message, error.details) == (2, "invalid_input_json", "bad input", {})
    assert error.failure.status == "failed"
    assert error.failure_message() == "bad input"
    assert error.failure_reason() == {"code": "invalid_input_json", "message": "bad input", "details": {}}
    assert "invalid_input_json: bad input" in str(error)


def test_typed_failure_envelope_with_exit_one_is_an_operation_failed_error_that_keeps_details(fake_biblicus: Path, workdir: Path) -> None:
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="operation-failed")
    with pytest.raises(BiblicusOperationFailedError) as caught:
        runner.run(["summarize", "map-reduce"])
    error = caught.value
    assert (error.exit_code, error.code, error.message) == (1, "provider_failed", "provider said no")
    assert error.details["http_status"] == 404
    assert error.details["strategy"] == "direct"
    assert error.failure_reason() == {"code": "provider_failed", "message": "provider said no", "details": error.details}


def test_envelope_with_an_unexpected_exit_status_is_a_plain_command_error(fake_biblicus: Path, workdir: Path) -> None:
    with pytest.raises(BiblicusCommandError) as caught:
        make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="envelope-unexpected-exit").run(["reindex"])
    assert type(caught.value) is BiblicusCommandError
    assert caught.value.exit_code == 3


def test_typed_commands_raise_the_envelope_errors_through_run_typed_and_run_json(fake_biblicus: Path, workdir: Path) -> None:
    from biblicus.web_transform import TransformResult

    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="invalid-request")
    with pytest.raises(BiblicusInvalidRequestError):
        runner.run_json(["query"])
    with pytest.raises(BiblicusInvalidRequestError):
        runner.run_typed(["extract", "article-text"], TransformResult)


def test_typed_command_failing_without_an_envelope_raises_output_error_with_stderr(fake_biblicus: Path, workdir: Path) -> None:
    from biblicus.web_transform import TransformResult

    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="usage-error")
    with pytest.raises(BiblicusOutputError) as caught:
        runner.run_typed(["extract", "url-text", "--bogus"], TransformResult)
    error = caught.value
    assert error.exit_code == 2
    assert error.stdout == ""
    assert "unrecognized arguments: --bogus" in error.stderr
    assert "unrecognized arguments: --bogus" in str(error)
    assert error.failure_reason()["details"] == {"stdout": "", "stderr": error.stderr, "exit_code": 2}
    with pytest.raises(BiblicusOutputError):
        runner.run_json(["query"])


def test_untyped_command_failing_without_an_envelope_keeps_both_streams_on_a_plain_command_error(fake_biblicus: Path, workdir: Path) -> None:
    with pytest.raises(BiblicusCommandError) as caught:
        make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="usage-error").run(["extract", "build"])
    assert type(caught.value) is BiblicusCommandError
    assert caught.value.exit_code == 2
    assert "unrecognized arguments" in caught.value.failure_message()


@pytest.mark.parametrize(
    "stdout",
    ['{"status": "failed"}', "prefix {not json", '["list"]', '{"error": "text"}', '{"status": "failed", "error": {"code": "c"}}',
     '{"status": "ok", "error": {"code": "c", "message": "m"}}', '{"status": "failed", "error": {"code": "c", "message": "m"}} trailing'],
)
def test_stdout_that_is_not_exactly_one_failure_envelope_is_not_parsed(stdout: str) -> None:
    error = biblicus_runner.command_failure_error(command=["biblicus"], exit_code=1, stdout=stdout, stderr="")
    assert type(error) is BiblicusCommandError


def test_failure_message_without_any_output_names_the_exit_code(fake_biblicus: Path, workdir: Path) -> None:
    with pytest.raises(BiblicusCommandError) as caught:
        make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="fail-silent").run(["reindex"])
    assert caught.value.failure_message() == "Biblicus command exited 3."
    assert "no output" in str(caught.value)


def test_invalid_json_raises_output_error_with_the_raw_output(fake_biblicus: Path, workdir: Path) -> None:
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="not-json")
    with pytest.raises(BiblicusOutputError) as caught:
        runner.run_json(["query"])
    assert caught.value.stdout == "not json at all"
    assert caught.value.command == (str(fake_biblicus), "query")
    reason = caught.value.failure_reason()
    assert reason["code"] == "invalid_biblicus_output"
    assert reason["details"] == {"stdout": "not json at all", "stderr": "", "exit_code": 0}


def test_run_typed_rejects_output_that_does_not_satisfy_the_model(fake_biblicus: Path, workdir: Path) -> None:
    from biblicus.web_transform import TransformResult

    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="typed", FAKE_BIBLICUS_PAYLOAD='{"status": "bogus"}')
    with pytest.raises(BiblicusOutputError):
        runner.run_typed(["extract", "article-text"], TransformResult)


def test_timeout_raises_a_typed_timeout_error(fake_biblicus: Path, workdir: Path) -> None:
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="sleep")
    with pytest.raises(BiblicusCommandTimeoutError) as caught:
        runner.run(["reindex"], timeout_seconds=0.2)
    assert caught.value.timeout_seconds == 0.2
    assert caught.value.command == (str(fake_biblicus), "reindex")
    assert isinstance(caught.value, BiblicusRunnerError)
    assert caught.value.failure_reason()["code"] == "biblicus_timeout"


def test_missing_workdir_configuration_is_a_clear_error() -> None:
    with pytest.raises(BiblicusWorkdirError, match="BIBLICUS_WORKDIR is required"):
        resolve_biblicus_workdir(environment={})
    with pytest.raises(BiblicusWorkdirError, match="BIBLICUS_WORKDIR is required"):
        resolve_biblicus_workdir("  ", environment={"BIBLICUS_WORKDIR": "   "})


def test_workdir_that_is_not_a_directory_is_a_clear_error(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    with pytest.raises(BiblicusWorkdirError, match="does not exist") as caught:
        resolve_biblicus_workdir(environment={"BIBLICUS_WORKDIR": str(missing)})
    assert caught.value.workdir == missing.resolve()


def test_explicit_workdir_wins_over_the_environment(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    configured = tmp_path / "configured"
    configured.mkdir()
    assert resolve_biblicus_workdir(explicit, environment={"BIBLICUS_WORKDIR": str(configured)}) == explicit.resolve()
    assert resolve_biblicus_workdir(environment={"BIBLICUS_WORKDIR": str(configured)}) == configured.resolve()


def test_workdir_defaults_to_the_process_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BIBLICUS_WORKDIR", str(tmp_path))
    assert resolve_biblicus_workdir() == tmp_path.resolve()
    monkeypatch.delenv("BIBLICUS_WORKDIR")
    with pytest.raises(BiblicusWorkdirError):
        resolve_biblicus_workdir()


def test_executable_is_the_console_script_beside_the_running_interpreter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    interpreter_directory = tmp_path / "venv" / "bin"
    interpreter_directory.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(interpreter_directory / "python"))
    with pytest.raises(BiblicusExecutableError, match="newsroom extra") as caught:
        resolve_biblicus_executable()
    assert caught.value.executable == interpreter_directory / "biblicus"
    (interpreter_directory / "biblicus").write_text("#!/bin/sh\n", encoding="utf-8")
    assert resolve_biblicus_executable() == interpreter_directory / "biblicus"


def test_from_environment_resolves_workdir_executable_and_grobid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    interpreter_directory = tmp_path / "venv" / "bin"
    interpreter_directory.mkdir(parents=True)
    (interpreter_directory / "biblicus").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(interpreter_directory / "python"))
    workdir = tmp_path / "work"
    workdir.mkdir()
    runner = BiblicusRunner.from_environment(
        workdir=workdir,
        grobid_url=" http://grobid.example ",
        environment={"PATH": "/bin", "OTHER": "kept"},
    )
    assert runner.workdir == workdir.resolve()
    assert runner.executable == interpreter_directory / "biblicus"
    assert runner.environment == {"PATH": "/bin", "OTHER": "kept", "BIBLICUS_GROBID_URL": "http://grobid.example"}


def test_from_environment_requires_the_workdir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIBLICUS_WORKDIR", raising=False)
    with pytest.raises(BiblicusWorkdirError):
        BiblicusRunner.from_environment()


def test_environment_keeps_the_configured_grobid_url_and_inherits_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIBLICUS_GROBID_URL", "http://configured.example")
    assert build_biblicus_environment()["BIBLICUS_GROBID_URL"] == "http://configured.example"
    assert build_biblicus_environment(grobid_url="http://override.example")["BIBLICUS_GROBID_URL"] == "http://override.example"
    monkeypatch.delenv("BIBLICUS_GROBID_URL")
    assert "BIBLICUS_GROBID_URL" not in build_biblicus_environment()


def test_priming_worker_environment_is_reduced_to_the_allowlist_plus_scoped_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from papyrus_content import priming_provider_budget

    monkeypatch.setattr(priming_provider_budget, "worker_environment", lambda: {"OPENAI_API_KEY": "scoped-token"})
    environment = build_biblicus_environment(
        base_environment={"PATH": "/bin", "BIBLICUS_WORKDIR": "/work", "OPENAI_API_KEY": "real-key", "AWS_SECRET_ACCESS_KEY": "secret"}
    )
    assert environment == {"PATH": "/bin", "BIBLICUS_WORKDIR": "/work", "OPENAI_API_KEY": "scoped-token"}


def test_typed_url_text_and_web_metadata_commands(fake_biblicus: Path, workdir: Path) -> None:
    from biblicus.api import UrlTextRequest, WebMetadataRequest

    url_payload = {
        "status": "ok",
        "source_kind": "web",
        "strategy": "direct",
        "text": "Body",
        "markdown": "Body",
        "title": "Title",
        "content_type": "text/html",
        "prompt_version": "v1",
        "attempts": [],
        "error": None,
    }
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="typed", FAKE_BIBLICUS_PAYLOAD=json.dumps(url_payload))
    response = runner.extract_url_text(UrlTextRequest(source_uri="https://example.org/a"))
    assert response.title == "Title"
    metadata_payload = {
        "status": "ok",
        "schemaVersion": "1",
        "sourceUri": "https://example.org/a",
        "title": "Title",
        "subtitle": None,
        "authors": [],
        "authorsStructured": [],
        "publicationDate": None,
        "publicationDateRaw": None,
        "updatedAt": None,
        "structured": {},
        "method": "html",
        "layers": [],
        "rawMetadata": {},
        "warnings": [],
        "referenceCandidates": [],
        "citationCount": 0,
    }
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="typed", FAKE_BIBLICUS_PAYLOAD=json.dumps(metadata_payload))
    assert runner.extract_web_metadata(WebMetadataRequest(source_uri="https://example.org/a")).citationCount == 0


def test_typed_transform_commands_pass_flags_and_standard_input(fake_biblicus: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from biblicus.api import SummarizeMapReduceRequest
    from biblicus.web_transform import MODEL, ArticleInput

    recorded: list[dict] = []
    original_run = BiblicusRunner.run

    def recording_run(self, arguments, **keywords):
        recorded.append({"arguments": list(arguments), **keywords})
        return original_run(self, arguments, **keywords)

    monkeypatch.setattr(BiblicusRunner, "run", recording_run)
    payload = json.dumps({"status": "ok", "task": "article", "text": "kept"})
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="typed", FAKE_BIBLICUS_PAYLOAD=payload)
    article = runner.extract_article_text(ArticleInput(extracted_text="Body", model=MODEL), timeout_seconds=12)
    assert article.text == "kept"
    assert recorded[-1]["arguments"] == ["extract", "article-text", "--input-json", "-", "--format", "json"]
    assert recorded[-1]["timeout_seconds"] == 12
    assert json.loads(recorded[-1]["stdin_text"])["model"] == MODEL

    summary = runner.summarize_map_reduce(SummarizeMapReduceRequest(extracted_text="Body", task="title", model="model-x"))
    assert summary.status == "ok"
    assert recorded[-1]["arguments"] == [
        "summarize", "map-reduce", "--task", "title", "--model", "model-x", "--input-json", "-", "--format", "json",
    ]
    assert set(json.loads(recorded[-1]["stdin_text"])) == {
        "extracted_text", "source_uri", "reference_title", "original_title", "original_subtitle",
        "source_publication_date", "source_is_archived", "generated_title",
    }


def test_context_pack_build_uses_standard_input_and_returns_the_typed_pack(fake_biblicus: Path, workdir: Path) -> None:
    from biblicus.api import ContextPackBuildBlocksRequest

    pack = {"text": "assembled", "total_tokens": 1, "total_characters": 9}
    runner = make_runner(fake_biblicus, workdir, FAKE_BIBLICUS_MODE="typed", FAKE_BIBLICUS_PAYLOAD=json.dumps(pack))
    request = ContextPackBuildBlocksRequest(blocks=[{"block_id": "a", "section": "doctrine", "text": "assembled"}], max_tokens=10)
    assert runner.build_context_pack_from_blocks(request).text == "assembled"


def test_module_exports_one_runner_class() -> None:
    assert biblicus_runner.BiblicusRunner is BiblicusRunner
