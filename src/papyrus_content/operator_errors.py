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


def credential_recovery_guidance() -> str:
    from .cli_user_auth import user_auth_requested
    if user_auth_requested():
        return "Check your newsroom identity/publication permissions with `papyrus auth status`; renew with `papyrus login` if needed."
    profile = os.environ.get("AWS_PROFILE", "").strip() or "<profile>"
    return f"Your AWS session may have expired or lack access. Run `aws sso login --profile {profile}` and retry."


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
