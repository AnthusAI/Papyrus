"""
The single process boundary between Papyrus and Biblicus.

Every Papyrus call into Biblicus runs the ``biblicus`` console script installed beside the
interpreter that is running Papyrus. The process boundary keeps heavy Biblicus dependencies (BERTopic,
spaCy, DSPy) out of the Lambda runtime, while :class:`BiblicusRunner` owns executable resolution, the
working directory, the subprocess environment, JSON parsing and typed errors, so no other module
spawns Biblicus itself.

Corpora live under the Biblicus working directory named by the ``BIBLICUS_WORKDIR`` environment
variable, or by an explicit ``--biblicus-workdir`` option. There is no default location.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from biblicus.api import (
        ContextPackBuildBlocksRequest,
        ContextPackBuildBlocksResponse,
        SummarizeMapReduceRequest,
        UrlTextRequest,
        UrlTextResponse,
        WebMetadataRequest,
        WebMetadataResponse,
    )
    from biblicus.web_transform import ArticleInput, TransformResult

BIBLICUS_WORKDIR_ENVIRONMENT_VARIABLE = "BIBLICUS_WORKDIR"
BIBLICUS_GROBID_URL_ENVIRONMENT_VARIABLE = "BIBLICUS_GROBID_URL"
BIBLICUS_CONSOLE_SCRIPT_NAME = "biblicus"
PRIMING_WORKER_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "PATH",
        "PYTHONPATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SYSTEMROOT",
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        BIBLICUS_WORKDIR_ENVIRONMENT_VARIABLE,
    }
)

ResponseModelType = TypeVar("ResponseModelType", bound=BaseModel)


class BiblicusRunnerError(RuntimeError):
    """Base class for every failure raised by :class:`BiblicusRunner`."""

    def failure_reason(self) -> dict[str, Any]:
        """
        Describe the failure as a structured reason with a stable ``code`` and a ``message``.

        :return: Reason object suitable for operator-facing error records.
        :rtype: dict[str, Any]
        """
        return {"code": "biblicus_runner_failed", "message": str(self)}


class BiblicusWorkdirError(BiblicusRunnerError):
    """
    Raised when the Biblicus working directory is not configured or does not exist.

    :ivar workdir: The configured path, or None when nothing was configured.
    :vartype workdir: pathlib.Path or None
    """

    def __init__(self, message: str, *, workdir: Path | None = None) -> None:
        super().__init__(message)
        self.workdir = workdir


class BiblicusExecutableError(BiblicusRunnerError):
    """
    Raised when the ``biblicus`` console script is missing from the Papyrus environment.

    :ivar executable: The path that was expected to hold the console script.
    :vartype executable: pathlib.Path
    """

    def __init__(self, message: str, *, executable: Path) -> None:
        super().__init__(message)
        self.executable = executable


class BiblicusCommandError(BiblicusRunnerError):
    """
    Raised when a Biblicus command exits with a nonzero status.

    :ivar command: The full command line that was run.
    :vartype command: tuple[str, ...]
    :ivar exit_code: The process exit status.
    :vartype exit_code: int
    :ivar stdout: Captured standard output, stripped.
    :vartype stdout: str
    :ivar stderr: Captured standard error, stripped.
    :vartype stderr: str
    :ivar error_stream: The one stream the command prints its structured failure to, or None when
        the command prints none.
    :vartype error_stream: str or None
    """

    def __init__(
        self,
        *,
        command: Sequence[str],
        exit_code: int,
        stdout: str,
        stderr: str,
        error_stream: Literal["stdout", "stderr"] | None = None,
    ) -> None:
        self.command = tuple(command)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.error_stream = error_stream
        detail = stderr or stdout or "no output"
        super().__init__(f"Biblicus command {' '.join(self.command)} exited {exit_code}: {detail}")

    def structured_error(self) -> dict[str, Any] | None:
        """
        Return the structured ``error`` object Biblicus printed, if any.

        Each typed command declares the one stream its failure JSON is written to; only that
        stream is parsed, as a whole, with ``json.loads``. A command that declares no stream, or a
        stream that is not a JSON object holding an ``error`` object, yields None.

        :return: The ``error`` object, or None.
        :rtype: dict[str, Any] or None
        """
        if self.error_stream is None:
            return None
        try:
            payload = json.loads(self.stdout if self.error_stream == "stdout" else self.stderr)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            return payload["error"]
        return None

    def failure_reason(self) -> dict[str, Any]:
        """
        Describe the failure, preferring the structured error Biblicus printed.

        :return: The structured error, or a ``biblicus_cli_failed`` reason built from the captured output.
        :rtype: dict[str, Any]
        """
        error = self.structured_error()
        if error is not None:
            return dict(error)
        return {"code": "biblicus_cli_failed", "message": self.failure_message()}

    def failure_message(self) -> str:
        """
        Return the most useful single-line explanation of the failure.

        :return: The structured error message or code when present, otherwise the captured output.
        :rtype: str
        """
        error = self.structured_error()
        if error is not None:
            return str(error.get("message") or error.get("code") or "Biblicus command failed.")
        return self.stderr or self.stdout or f"Biblicus command exited {self.exit_code}."


class BiblicusCommandTimeoutError(BiblicusRunnerError):
    """
    Raised when a Biblicus command exceeds its timeout.

    :ivar command: The full command line that was run.
    :vartype command: tuple[str, ...]
    :ivar timeout_seconds: The timeout that elapsed.
    :vartype timeout_seconds: float
    """

    def __init__(self, *, command: Sequence[str], timeout_seconds: float) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Biblicus command {' '.join(self.command)} timed out after {timeout_seconds:g} seconds.")

    def failure_reason(self) -> dict[str, Any]:
        """
        Describe the timeout as a ``biblicus_timeout`` reason; a hung child is an infrastructure failure, not a bad source.

        :return: Reason object with the elapsed timeout under ``details``.
        :rtype: dict[str, Any]
        """
        return {
            "code": "biblicus_timeout",
            "message": str(self),
            "details": {"timeout_seconds": self.timeout_seconds},
        }


class BiblicusOutputError(BiblicusRunnerError):
    """
    Raised when a Biblicus command succeeded but its output is not the expected JSON.

    :ivar command: The full command line that was run.
    :vartype command: tuple[str, ...]
    :ivar stdout: Captured standard output, stripped.
    :vartype stdout: str
    """

    def __init__(self, *, command: Sequence[str], stdout: str, detail: str) -> None:
        self.command = tuple(command)
        self.stdout = stdout
        super().__init__(f"Biblicus command {' '.join(self.command)} returned invalid output: {detail}")

    def failure_reason(self) -> dict[str, Any]:
        """
        Describe the failure as an ``invalid_biblicus_output`` reason that carries the raw output.

        :return: Reason object with the captured standard output under ``details``.
        :rtype: dict[str, Any]
        """
        return {"code": "invalid_biblicus_output", "message": str(self), "details": {"stdout": self.stdout}}


@dataclass(frozen=True)
class BiblicusCommandOutput:
    """
    Output of a Biblicus command that exited with status zero.

    :ivar command: The full command line that was run.
    :vartype command: tuple[str, ...]
    :ivar stdout: Captured standard output, stripped.
    :vartype stdout: str
    :ivar stderr: Captured standard error, stripped.
    :vartype stderr: str
    """

    command: tuple[str, ...]
    stdout: str
    stderr: str


def resolve_biblicus_workdir(explicit_workdir: str | Path | None = None, *, environment: Mapping[str, str] | None = None) -> Path:
    """
    Resolve the Biblicus working directory that holds ``corpora/``.

    :param explicit_workdir: Path from an explicit option such as ``--biblicus-workdir``; wins over the environment.
    :type explicit_workdir: str or pathlib.Path or None
    :param environment: Environment to read ``BIBLICUS_WORKDIR`` from; defaults to ``os.environ``.
    :type environment: Mapping[str, str] or None
    :return: The resolved existing directory.
    :rtype: pathlib.Path
    :raises BiblicusWorkdirError: If no path is configured or the path is not a directory.
    """
    source = os.environ if environment is None else environment
    configured = str(explicit_workdir or "").strip() or str(source.get(BIBLICUS_WORKDIR_ENVIRONMENT_VARIABLE, "")).strip()
    if not configured:
        raise BiblicusWorkdirError(
            f"{BIBLICUS_WORKDIR_ENVIRONMENT_VARIABLE} is required: set it to the directory that holds the "
            "Biblicus corpora, or pass --biblicus-workdir.",
        )
    workdir = Path(configured).expanduser().resolve()
    if not workdir.is_dir():
        raise BiblicusWorkdirError(
            f"Biblicus working directory does not exist: {workdir}. Set {BIBLICUS_WORKDIR_ENVIRONMENT_VARIABLE} "
            "to the directory that holds the Biblicus corpora.",
            workdir=workdir,
        )
    return workdir


def resolve_biblicus_executable() -> Path:
    """
    Resolve the ``biblicus`` console script installed beside the running interpreter.

    :return: Path to the console script.
    :rtype: pathlib.Path
    :raises BiblicusExecutableError: If the console script is not installed.
    """
    executable = Path(sys.executable).parent / BIBLICUS_CONSOLE_SCRIPT_NAME
    if not executable.is_file():
        raise BiblicusExecutableError(
            f"The biblicus console script was not found at {executable}. Install Papyrus with its "
            "newsroom extra so Biblicus is installed in the same environment.",
            executable=executable,
        )
    return executable


def build_biblicus_environment(
    *,
    base_environment: Mapping[str, str] | None = None,
    grobid_url: str | None = None,
) -> dict[str, str]:
    """
    Build the environment a Biblicus subprocess runs with.

    Inside a priming worker the inherited environment is reduced to a fixed allowlist and the worker's
    scoped provider settings are layered on top.

    :param base_environment: Environment to start from; defaults to ``os.environ``.
    :type base_environment: Mapping[str, str] or None
    :param grobid_url: GROBID service URL that overrides ``BIBLICUS_GROBID_URL``.
    :type grobid_url: str or None
    :return: The subprocess environment.
    :rtype: dict[str, str]
    """
    from .priming_provider_budget import worker_environment

    environment = dict(os.environ if base_environment is None else base_environment)
    scoped = worker_environment()
    if scoped is not None:
        environment = {name: value for name, value in environment.items() if name in PRIMING_WORKER_ENVIRONMENT_ALLOWLIST}
        environment.update(scoped)
    resolved_grobid = str(grobid_url or environment.get(BIBLICUS_GROBID_URL_ENVIRONMENT_VARIABLE) or "").strip()
    if resolved_grobid:
        environment[BIBLICUS_GROBID_URL_ENVIRONMENT_VARIABLE] = resolved_grobid
    return environment


class BiblicusRunner:
    """
    Runs ``biblicus`` commands in a subprocess and returns parsed, typed results.

    :ivar workdir: Directory the subprocess runs in and that holds ``corpora/``.
    :vartype workdir: pathlib.Path
    :ivar environment: Environment passed to every subprocess.
    :vartype environment: dict[str, str]
    :ivar executable: The ``biblicus`` console script.
    :vartype executable: pathlib.Path
    """

    def __init__(self, *, workdir: Path, environment: Mapping[str, str], executable: Path) -> None:
        self.workdir = workdir
        self.environment = dict(environment)
        self.executable = executable

    @classmethod
    def from_environment(
        cls,
        *,
        workdir: str | Path | None = None,
        grobid_url: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> "BiblicusRunner":
        """
        Build a runner from the process environment.

        :param workdir: Explicit working directory; defaults to ``BIBLICUS_WORKDIR``.
        :type workdir: str or pathlib.Path or None
        :param grobid_url: GROBID service URL for commands that parse scholarly PDFs.
        :type grobid_url: str or None
        :param environment: Environment to start from; defaults to ``os.environ``.
        :type environment: Mapping[str, str] or None
        :return: A configured runner.
        :rtype: BiblicusRunner
        :raises BiblicusWorkdirError: If the working directory is missing.
        :raises BiblicusExecutableError: If the console script is not installed.
        """
        return cls(
            workdir=resolve_biblicus_workdir(workdir, environment=environment),
            environment=build_biblicus_environment(base_environment=environment, grobid_url=grobid_url),
            executable=resolve_biblicus_executable(),
        )

    def command(self, arguments: Sequence[str]) -> list[str]:
        """
        Return the full command line for Biblicus arguments.

        :param arguments: Arguments after the ``biblicus`` executable.
        :type arguments: Sequence[str]
        :return: Executable followed by the arguments.
        :rtype: list[str]
        """
        return [str(self.executable), *[str(argument) for argument in arguments]]

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin_text: str | None = None,
        timeout_seconds: float | None = None,
        error_stream: Literal["stdout", "stderr"] | None = None,
    ) -> BiblicusCommandOutput:
        """
        Run a Biblicus command and require exit status zero.

        :param arguments: Arguments after the ``biblicus`` executable.
        :type arguments: Sequence[str]
        :param stdin_text: Text written to standard input.
        :type stdin_text: str or None
        :param timeout_seconds: Seconds before the command is abandoned.
        :type timeout_seconds: float or None
        :param error_stream: The one stream the command prints its structured failure to.
        :type error_stream: str or None
        :return: Captured output.
        :rtype: BiblicusCommandOutput
        :raises BiblicusCommandError: If the command exits with a nonzero status.
        :raises BiblicusCommandTimeoutError: If the command exceeds the timeout.
        """
        command = self.command(arguments)
        try:
            completed = subprocess.run(
                command,
                cwd=self.workdir,
                env=self.environment,
                input=stdin_text,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise BiblicusCommandTimeoutError(command=command, timeout_seconds=float(timeout_seconds or 0)) from error
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            raise BiblicusCommandError(
                command=command,
                exit_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                error_stream=error_stream,
            )
        return BiblicusCommandOutput(command=tuple(command), stdout=stdout, stderr=stderr)

    def run_json(
        self,
        arguments: Sequence[str],
        *,
        stdin_text: str | None = None,
        timeout_seconds: float | None = None,
        error_stream: Literal["stdout", "stderr"] | None = None,
    ) -> Any:
        """
        Run a Biblicus command and parse its standard output as JSON.

        :param arguments: Arguments after the ``biblicus`` executable.
        :type arguments: Sequence[str]
        :param stdin_text: Text written to standard input.
        :type stdin_text: str or None
        :param timeout_seconds: Seconds before the command is abandoned.
        :type timeout_seconds: float or None
        :param error_stream: The one stream the command prints its structured failure to.
        :type error_stream: str or None
        :return: The decoded JSON value.
        :rtype: Any
        :raises BiblicusOutputError: If standard output is not valid JSON.
        """
        output = self.run(arguments, stdin_text=stdin_text, timeout_seconds=timeout_seconds, error_stream=error_stream)
        try:
            return json.loads(output.stdout)
        except json.JSONDecodeError as error:
            raise BiblicusOutputError(command=output.command, stdout=output.stdout, detail=str(error)) from error

    def run_typed(
        self,
        arguments: Sequence[str],
        response_model: type[ResponseModelType],
        *,
        stdin_text: str | None = None,
        timeout_seconds: float | None = None,
        error_stream: Literal["stdout", "stderr"] | None = None,
    ) -> ResponseModelType:
        """
        Run a Biblicus command and validate its standard output against a response model.

        :param arguments: Arguments after the ``biblicus`` executable.
        :type arguments: Sequence[str]
        :param response_model: Pydantic model the output must satisfy.
        :type response_model: type[pydantic.BaseModel]
        :param stdin_text: Text written to standard input.
        :type stdin_text: str or None
        :param timeout_seconds: Seconds before the command is abandoned.
        :type timeout_seconds: float or None
        :param error_stream: The one stream the command prints its structured failure to.
        :type error_stream: str or None
        :return: The validated response.
        :rtype: pydantic.BaseModel
        :raises BiblicusOutputError: If the output is not JSON or does not satisfy the model.
        """
        output = self.run(arguments, stdin_text=stdin_text, timeout_seconds=timeout_seconds, error_stream=error_stream)
        try:
            return response_model.model_validate_json(output.stdout)
        except ValidationError as error:
            raise BiblicusOutputError(command=output.command, stdout=output.stdout, detail=str(error)) from error

    def extract_url_text(self, request: "UrlTextRequest", *, timeout_seconds: float | None = None) -> "UrlTextResponse":
        """
        Run ``extract url-text``.

        :param request: Validated request.
        :type request: biblicus.api.UrlTextRequest
        :param timeout_seconds: Seconds before the command is killed and abandoned.
        :type timeout_seconds: float or None
        :return: The extraction response.
        :rtype: biblicus.api.UrlTextResponse
        :raises BiblicusCommandError: If extraction fails. Failures print the response to standard output;
            input failures print to standard error and are not parsed (see ``BiblicusCommandError``).
        :raises BiblicusCommandTimeoutError: If the command exceeds the timeout.
        """
        from biblicus.api import UrlTextResponse

        return self.run_typed(
            ["extract", "url-text", "--input-json", "-", "--format", "json"],
            UrlTextResponse,
            stdin_text=request.model_dump_json(),
            timeout_seconds=timeout_seconds,
            error_stream="stdout",
        )

    def extract_web_metadata(self, request: "WebMetadataRequest") -> "WebMetadataResponse":
        """
        Run ``extract web-metadata``.

        :param request: Validated request.
        :type request: biblicus.api.WebMetadataRequest
        :return: The metadata response.
        :rtype: biblicus.api.WebMetadataResponse
        :raises BiblicusCommandError: If extraction fails.
        """
        from biblicus.api import WebMetadataResponse

        return self.run_typed(
            ["extract", "web-metadata", "--input-json", "-"],
            WebMetadataResponse,
            stdin_text=request.model_dump_json(),
            error_stream="stderr",
        )

    def extract_article_text(self, request: "ArticleInput", *, timeout_seconds: float | None = None) -> "TransformResult":
        """
        Run ``extract article-text``.

        :param request: Validated article input.
        :type request: biblicus.web_transform.ArticleInput
        :param timeout_seconds: Seconds before the command is abandoned.
        :type timeout_seconds: float or None
        :return: The transform result.
        :rtype: biblicus.web_transform.TransformResult
        :raises BiblicusCommandError: If the transform reports failure.
        :raises BiblicusCommandTimeoutError: If the command exceeds the timeout.
        """
        from biblicus.web_transform import TransformResult

        return self.run_typed(
            ["extract", "article-text", "--input-json", "-", "--format", "json"],
            TransformResult,
            stdin_text=request.model_dump_json(),
            timeout_seconds=timeout_seconds,
            error_stream="stdout",
        )

    def summarize_map_reduce(self, request: "SummarizeMapReduceRequest") -> "TransformResult":
        """
        Run ``summarize map-reduce``.

        :param request: Validated request; ``task`` and ``model`` become flags and the rest is standard input.
        :type request: biblicus.api.SummarizeMapReduceRequest
        :return: The transform result.
        :rtype: biblicus.web_transform.TransformResult
        :raises BiblicusCommandError: If the transform reports failure.
        """
        from biblicus.web_transform import TransformResult

        source_payload = request.model_dump_json(exclude={"task", "model"})
        return self.run_typed(
            [
                "summarize",
                "map-reduce",
                "--task",
                request.task,
                "--model",
                request.model,
                "--input-json",
                "-",
                "--format",
                "json",
            ],
            TransformResult,
            stdin_text=source_payload,
            error_stream="stdout",
        )

    def build_context_pack_from_blocks(self, request: "ContextPackBuildBlocksRequest") -> "ContextPackBuildBlocksResponse":
        """
        Run ``context-pack build-blocks``.

        :param request: Validated block build request.
        :type request: biblicus.api.ContextPackBuildBlocksRequest
        :return: The built context pack.
        :rtype: biblicus.api.ContextPackBuildBlocksResponse
        """
        from biblicus.api import ContextPackBuildBlocksResponse

        return self.run_typed(
            ["context-pack", "build-blocks"],
            ContextPackBuildBlocksResponse,
            stdin_text=request.model_dump_json(),
        )
