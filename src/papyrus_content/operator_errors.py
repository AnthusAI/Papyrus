from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Callable

OPERATOR_ERROR_EXIT_CODE = 2
UNEXPECTED_ERROR_EXIT_CODE = 1


class OperatorError(Exception):
    """Operator-facing failure with a stable exit code."""

    def __init__(self, message: str, *, exit_code: int = OPERATOR_ERROR_EXIT_CODE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class GraphQLRequestError(RuntimeError):
    """The GraphQL API rejected or failed a request; operator-facing, never a traceback."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GraphQLTimeoutError(GraphQLRequestError):
    """The client gave up waiting for the answer. The server may still be working: this is not a failure of the request (PPY-4611d5)."""


def credential_recovery_guidance() -> str:
    from .user_auth_mode import user_auth_requested
    if user_auth_requested():
        return "Check your newsroom identity/publication permissions with `papyrus auth status`; renew with `papyrus login` if needed."
    profile = os.environ.get("AWS_PROFILE", "").strip() or "<profile>"
    return f"Your AWS session may have expired or lack access. Run `aws sso login --profile {profile}` and retry."


def require_operator_lane(command_label: str, writes: str, *, writing: bool) -> None:
    """Say up front that a command is an operator command, before it reads or writes anything.

    The signed-in editor lane cannot change `writes` (the backend gives editors read access to those models), so a write there
    fails late with `Not Authorized`, after a preview that looked fine (PPY-a89c4d). On the signed-in lane a write is refused here,
    and a preview prints one notice line first, so nobody reads the preview as a promise that the write will work."""
    from .user_auth_mode import user_auth_requested
    if not user_auth_requested():
        return
    notice = (
        f"{command_label} is an operator command: it writes {writes}, which the signed-in editor lane cannot change. "
        "Run it on the operator lane (AWS credentials, PAPYRUS_GRAPHQL_AUTH=iam)."
    )
    if writing:
        raise OperatorError(f"{notice} Nothing was changed.")
    print(f"{command_label}\toperator-lane\tnotice\t{notice} This preview only reads.")


def is_operator_facing_error(error: BaseException) -> bool:
    return isinstance(error, (OperatorError, GraphQLRequestError, ValueError))


def exit_code_for_error(error: BaseException) -> int:
    if isinstance(error, OperatorError):
        return error.exit_code
    if is_operator_facing_error(error):
        return OPERATOR_ERROR_EXIT_CODE
    return UNEXPECTED_ERROR_EXIT_CODE


def report_failure_and_exit_code(error: BaseException) -> int:
    print(str(error), file=sys.stderr)
    if not is_operator_facing_error(error):
        traceback.print_exception(error, file=sys.stderr)
    return exit_code_for_error(error)


def run_with_operator_error_handling(entrypoint: Callable[[], int]) -> int:
    try:
        return entrypoint()
    except Exception as error:
        return report_failure_and_exit_code(error)
