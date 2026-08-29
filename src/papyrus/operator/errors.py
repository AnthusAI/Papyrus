from __future__ import annotations


class OperatorError(Exception):
  """Operator-facing failure with a stable exit code."""

  def __init__(self, message: str, *, exit_code: int = 2) -> None:
    super().__init__(message)
    self.exit_code = exit_code


def jwt_guidance_error(message: str) -> OperatorError:
  return OperatorError(message, exit_code=2)
