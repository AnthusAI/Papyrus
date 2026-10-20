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
from typing import TYPE_CHECKING, Any, Mapping, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from biblicus.command_failure import CommandFailure
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
INVALID_REQUEST_EXIT_STATUS = 2
OPERATION_FAILED_EXIT_STATUS = 1
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

    A typed command fails with a ``CommandFailure`` envelope on standard output, and the runner raises
    :class:`BiblicusInvalidRequestError` or :class:`BiblicusOperationFailedError` for it. This class
    itself is raised for commands that print no envelope, such as the commands written for people,
    whose failure text is on standard error.

    :ivar command: The full command line that was run.
    :vartype command: tuple[str, ...]
    :ivar exit_code: The process exit status.
    :vartype exit_code: int
    :ivar stdout: Captured standard output, stripped.
    :vartype stdout: str
    :ivar stderr: Captured standard error, stripped.
    :vartype stderr: str
    """

    def __init__(self, *, command: Sequence[str], exit_code: int, stdout: str, stderr: str) -> None:
        self.command = tuple(command)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        detail = stderr or stdout or "no output"
        super().__init__(f"Biblicus command {' '.join(self.command)} exited {exit_code}: {detail}")

    def failure_reason(self) -> dict[str, Any]:
        """
        Describe the failure from the captured output.

        :return: A ``biblicus_cli_failed`` reason built from the captured output.
        :rtype: dict[str, Any]
        """
        return {"code": "biblicus_cli_failed", "message": self.failure_message()}

    def failure_message(self) -> str:
        """
        Return the most useful single-line explanation of the failure.

        :return: The captured standard error or standard output, or the exit status when both are empty.
        :rtype: str
        """
        return self.stderr or self.stdout or f"Biblicus command exited {self.exit_code}."


class BiblicusFailureEnvelopeError(BiblicusCommandError):
    """
    Raised when a typed Biblicus command printed a ``CommandFailure`` envelope on standard output.

    :ivar failure: The parsed envelope.
    :vartype failure: biblicus.command_failure.CommandFailure
    """

    def __init__(self, *, command: Sequence[str], exit_code: int, stdout: str, stderr: str, failure: "CommandFailure") -> None:
        super().__init__(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)
        self.failure = failure
        self.args = (f"Biblicus command {' '.join(self.command)} exited {exit_code}: {failure.error.code}: {failure.error.message}",)

    @property
    def code(self) -> str:
        """
        Return the stable machine-readable failure code.

        :return: The envelope ``error.code``.
        :rtype: str
        """
        return self.failure.error.code

    @property
    def message(self) -> str:
        """
        Return the human-readable failure message.

        :return: The envelope ``error.message``.
        :rtype: str
        """
        return self.failure.error.message

    @property
    def details(self) -> dict[str, Any]:
        """
        Return the structured diagnostics, empty when the command named none.

        :return: The envelope ``error.details``.
        :rtype: dict[str, Any]
        """
        return dict(self.failure.error.details)

    def failure_reason(self) -> dict[str, Any]:
        """
        Describe the failure with the envelope's code, message and details.

        :return: Reason object with ``code``, ``message`` and ``details``.
        :rtype: dict[str, Any]
        """
        return {"code": self.code, "message": self.message, "details": self.details}

    def failure_message(self) -> str:
        """
        Return the envelope message.

        :return: The envelope ``error.message``.
        :rtype: str
        """
        return self.message


class BiblicusInvalidRequestError(BiblicusFailureEnvelopeError):
    """Raised when a typed Biblicus command rejected the request (exit status 2)."""


class BiblicusOperationFailedError(BiblicusFailureEnvelopeError):
    """Raised when a typed Biblicus command accepted the request but the operation failed (exit status 1)."""


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
    Raised when a Biblicus command produced output that is not the expected JSON.

    This covers a successful command whose standard output is not valid, a typed command that failed
    without printing a failure envelope on standard output (for example an argument syntax error that
    ``argparse`` reported on standard error), and a failure envelope with an unexpected exit status.

    :ivar command: The full command line that was run.
    :vartype command: tuple[str, ...]
    :ivar stdout: Captured standard output, stripped.
    :vartype stdout: str
    :ivar stderr: Captured standard error, stripped.
    :vartype stderr: str
    :ivar exit_code: The process exit status.
    :vartype exit_code: int
    """

    def __init__(self, *, command: Sequence[str], stdout: str, detail: str, stderr: str = "", exit_code: int = 0) -> None:
        self.command = tuple(command)
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        super().__init__(f"Biblicus command {' '.join(self.command)} returned invalid output: {detail}")

    def failure_reason(self) -> dict[str, Any]:
        """
        Describe the failure as an ``invalid_biblicus_output`` reason that carries the raw output.

        :return: Reason object with the captured standard output and standard error under ``details``.
        :rtype: dict[str, Any]
        """
        return {
            "code": "invalid_biblicus_output",
            "message": str(self),
            "details": {"stdout": self.stdout, "stderr": self.stderr, "exit_code": self.exit_code},
        }

    def failure_message(self) -> str:
        """
        Return the single-line explanation of the invalid output.

        :return: The error message.
        :rtype: str
        """
        return str(self)


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


def command_failure_error(*, command: Sequence[str], exit_code: int, stdout: str, stderr: str) -> BiblicusCommandError:
    """
    Build the error for a command that exited with a nonzero status.

    Standard output is parsed as a ``CommandFailure`` envelope. A valid envelope with exit status 2 yields
    :class:`BiblicusInvalidRequestError` and with exit status 1 yields :class:`BiblicusOperationFailedError`.
    Output that is not an envelope yields a plain :class:`BiblicusCommandError` that keeps both streams.

    :param command: The full command line that was run.
    :type command: Sequence[str]
    :param exit_code: The process exit status.
    :type exit_code: int
    :param stdout: Captured standard output, stripped.
    :type stdout: str
    :param stderr: Captured standard error, stripped.
    :type stderr: str
    :return: The error to raise.
    :rtype: BiblicusCommandError
    """
    from biblicus.command_failure import CommandFailure

    try:
        failure = CommandFailure.model_validate_json(stdout)
    except ValidationError:
        return BiblicusCommandError(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)
    arguments = {"command": command, "exit_code": exit_code, "stdout": stdout, "stderr": stderr, "failure": failure}
    if exit_code == INVALID_REQUEST_EXIT_STATUS:
        return BiblicusInvalidRequestError(**arguments)
    if exit_code == OPERATION_FAILED_EXIT_STATUS:
        return BiblicusOperationFailedError(**arguments)
    return BiblicusCommandError(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)


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
    ) -> BiblicusCommandOutput:
        """
        Run a Biblicus command and require exit status zero.

        :param arguments: Arguments after the ``biblicus`` executable.
        :type arguments: Sequence[str]
        :param stdin_text: Text written to standard input.
        :type stdin_text: str or None
        :param timeout_seconds: Seconds before the command is abandoned.
        :type timeout_seconds: float or None
        :return: Captured output.
        :rtype: BiblicusCommandOutput
        :raises BiblicusInvalidRequestError: If a typed command rejected the request (exit status 2).
        :raises BiblicusOperationFailedError: If a typed command's operation failed (exit status 1).
        :raises BiblicusCommandError: If the command exits with a nonzero status without printing a failure envelope.
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
            raise command_failure_error(command=command, exit_code=completed.returncode, stdout=stdout, stderr=stderr)
        return BiblicusCommandOutput(command=tuple(command), stdout=stdout, stderr=stderr)

    def run_typed_command(
        self,
        arguments: Sequence[str],
        *,
        stdin_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> BiblicusCommandOutput:
        """
        Run a typed Biblicus command, which always reports failure as a ``CommandFailure`` envelope.

        :param arguments: Arguments after the ``biblicus`` executable.
        :type arguments: Sequence[str]
        :param stdin_text: Text written to standard input.
        :type stdin_text: str or None
        :param timeout_seconds: Seconds before the command is abandoned.
        :type timeout_seconds: float or None
        :return: Captured output.
        :rtype: BiblicusCommandOutput
        :raises BiblicusInvalidRequestError: If the command rejected the request (exit status 2).
        :raises BiblicusOperationFailedError: If the operation failed (exit status 1).
        :raises BiblicusOutputError: If the command failed without a failure envelope on standard output,
            for example an argument syntax error, which carries the captured standard error.
        :raises BiblicusCommandTimeoutError: If the command exceeds the timeout.
        """
        try:
            return self.run(arguments, stdin_text=stdin_text, timeout_seconds=timeout_seconds)
        except BiblicusFailureEnvelopeError:
            raise
        except BiblicusCommandError as error:
            raise BiblicusOutputError(
                command=error.command,
                stdout=error.stdout,
                stderr=error.stderr,
                exit_code=error.exit_code,
                detail=f"exit status {error.exit_code} without a failure envelope on standard output: {error.failure_message()}",
            ) from error

    def run_json(
        self,
        arguments: Sequence[str],
        *,
        stdin_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        """
        Run a typed Biblicus command and parse its standard output as JSON.

        :param arguments: Arguments after the ``biblicus`` executable.
        :type arguments: Sequence[str]
        :param stdin_text: Text written to standard input.
        :type stdin_text: str or None
        :param timeout_seconds: Seconds before the command is abandoned.
        :type timeout_seconds: float or None
        :return: The decoded JSON value.
        :rtype: Any
        :raises BiblicusInvalidRequestError: If the command rejected the request.
        :raises BiblicusOperationFailedError: If the operation failed.
        :raises BiblicusOutputError: If standard output is not valid JSON or a failure printed no envelope.
        """
        output = self.run_typed_command(arguments, stdin_text=stdin_text, timeout_seconds=timeout_seconds)
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
    ) -> ResponseModelType:
        """
        Run a typed Biblicus command and validate its standard output against a response model.

        :param arguments: Arguments after the ``biblicus`` executable.
        :type arguments: Sequence[str]
        :param response_model: Pydantic model the output must satisfy.
        :type response_model: type[pydantic.BaseModel]
        :param stdin_text: Text written to standard input.
        :type stdin_text: str or None
        :param timeout_seconds: Seconds before the command is abandoned.
        :type timeout_seconds: float or None
        :return: The validated response.
        :rtype: pydantic.BaseModel
        :raises BiblicusInvalidRequestError: If the command rejected the request.
        :raises BiblicusOperationFailedError: If the operation failed.
        :raises BiblicusOutputError: If the output does not satisfy the model or a failure printed no envelope.
        """
        output = self.run_typed_command(arguments, stdin_text=stdin_text, timeout_seconds=timeout_seconds)
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
        :raises BiblicusFailureEnvelopeError: If extraction fails; ``details`` carries the typed URL text diagnostics.
        :raises BiblicusCommandTimeoutError: If the command exceeds the timeout.
        """
        from biblicus.api import UrlTextResponse

        return self.run_typed(
            ["extract", "url-text", "--input-json", "-", "--format", "json"],
            UrlTextResponse,
            stdin_text=request.model_dump_json(),
            timeout_seconds=timeout_seconds,
        )

    def extract_web_metadata(self, request: "WebMetadataRequest") -> "WebMetadataResponse":
        """
        Run ``extract web-metadata``.

        :param request: Validated request.
        :type request: biblicus.api.WebMetadataRequest
        :return: The metadata response.
        :rtype: biblicus.api.WebMetadataResponse
        :raises BiblicusFailureEnvelopeError: If extraction fails.
        """
        from biblicus.api import WebMetadataResponse

        return self.run_typed(
            ["extract", "web-metadata", "--input-json", "-"],
            WebMetadataResponse,
            stdin_text=request.model_dump_json(),
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
        :raises BiblicusFailureEnvelopeError: If the transform fails; ``details`` carries the typed transform diagnostics.
        :raises BiblicusCommandTimeoutError: If the command exceeds the timeout.
        """
        from biblicus.web_transform import TransformResult

        return self.run_typed(
            ["extract", "article-text", "--input-json", "-", "--format", "json"],
            TransformResult,
            stdin_text=request.model_dump_json(),
            timeout_seconds=timeout_seconds,
        )

    def summarize_map_reduce(self, request: "SummarizeMapReduceRequest") -> "TransformResult":
        """
        Run ``summarize map-reduce``.

        :param request: Validated request; ``task`` and ``model`` become flags and the rest is standard input.
        :type request: biblicus.api.SummarizeMapReduceRequest
        :return: The transform result.
        :rtype: biblicus.web_transform.TransformResult
        :raises BiblicusFailureEnvelopeError: If the transform fails; ``details`` carries the typed transform diagnostics.
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
