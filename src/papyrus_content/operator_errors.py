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
    return (f"This call used the operator lane (AWS credentials, chosen with --auth iam or PAPYRUS_GRAPHQL_AUTH=iam); that session may have "
            f"expired or lack access. Run `aws sso login --profile {profile}` and retry.")


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
        "Run it on the operator lane: `papyrus --auth iam ...` with AWS credentials (or PAPYRUS_GRAPHQL_AUTH=iam)."
    )
    if writing:
        raise OperatorError(f"{notice} Nothing was changed.")
    print(f"{command_label}\toperator-lane\tnotice\t{notice} This preview only reads.")


def sso_token_guidance(error: BaseException) -> str | None:
    """What to do when botocore's own SSO token provider fails while the `aws` command may still work, or None when ``error`` is not that failure.

    The AWS CLI and botocore keep SSO tokens in files under ~/.aws/sso/cache, and a newer CLI can refresh into a file that botocore (the library this tool uses) does
    not read, so botocore is left with an expired token and a refresh token the service rejects (PPY-25a4fd). The library does not borrow the CLI's credentials: that
    would hide a problem in the credential chain, so the fix is made on the machine, and this says which."""
    if type(error).__name__ != "TokenRetrievalError" or "botocore" not in type(error).__module__:
        return None
    import shutil

    profile = os.environ.get("AWS_PROFILE", "").strip() or "<profile>"
    lines = [f"The AWS credentials for profile {profile} could not be loaded by this tool's own AWS library: {error}"]
    if shutil.which("aws"):
        lines += [
            "The `aws` command is installed and may still work for the same profile, because it can keep its refreshed SSO token in a file this library does not read.",
            "Fix it on this machine in one of two ways:",
            f"  1. Add this line under the [profile {profile}] section of ~/.aws/config, so the library asks the aws command for its credentials:",
            f"       credential_process = aws configure export-credentials --profile {profile}",
            f"  2. Or sign in again for that profile: `aws sso login --profile {profile}`, then retry.",
        ]
    else:
        lines.append(f"Sign in again for that profile with `aws sso login --profile {profile}`, then retry.")
    return "\n".join(lines)


def is_operator_facing_error(error: BaseException) -> bool:
    return isinstance(error, (OperatorError, GraphQLRequestError, ValueError)) or sso_token_guidance(error) is not None


def exit_code_for_error(error: BaseException) -> int:
    if isinstance(error, OperatorError):
        return error.exit_code
    if is_operator_facing_error(error):
        return OPERATOR_ERROR_EXIT_CODE
    return UNEXPECTED_ERROR_EXIT_CODE


def report_failure_and_exit_code(error: BaseException) -> int:
    print(sso_token_guidance(error) or str(error), file=sys.stderr)
    if not is_operator_facing_error(error):
        traceback.print_exception(error, file=sys.stderr)
    return exit_code_for_error(error)


def run_with_operator_error_handling(entrypoint: Callable[[], int]) -> int:
    try:
        return entrypoint()
    except Exception as error:
        return report_failure_and_exit_code(error)
