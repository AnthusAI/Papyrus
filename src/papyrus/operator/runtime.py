from __future__ import annotations

import sys
import traceback

from .commands.auth import run_auth_refresh
from .commands.references import (
  run_assignments_list,
  run_references_list,
  run_references_register,
  run_references_show,
)
from .config import load_operator_config
from .errors import OperatorError
from .help_text import TOP_LEVEL_HELP, print_group_help


OPERATOR_COMMANDS = {
  ("references", "list"),
  ("references", "show"),
  ("references", "register"),
  ("assignments", "list"),
  ("auth", "refresh"),
}


def is_operator_command(group: str, command: str | None) -> bool:
  if command is None:
    return group in {"references", "assignments", "auth", "knowledge"}
  return (group, command) in OPERATOR_COMMANDS


def dispatch_operator_command(group: str, command: str | None, flags: list[str]) -> int:
  if command is None:
    print_group_help(group)
    return 0

  try:
    config = load_operator_config(
      backend_override=_flag_value(flags, "backend"),
      corpus_key_override=_flag_value(flags, "corpus-key"),
    )
    if group == "references" and command == "list":
      return run_references_list(config, flags)
    if group == "references" and command == "show":
      return run_references_show(config, flags)
    if group == "references" and command == "register":
      return run_references_register(config, flags)
    if group == "assignments" and command == "list":
      return run_assignments_list(config, flags)
    if group == "auth" and command == "refresh":
      return run_auth_refresh(flags)
    raise OperatorError(f"Unsupported operator command: papyrus {group} {command}")
  except ValueError as error:
    message = str(error)
    if "unknown backend" in message:
      print(message, file=sys.stderr)
      return 2
    if "PAPYRUS_GRAPHQL_JWT" in message:
      print(_friendly_jwt_message(message), file=sys.stderr)
      return 2
    raise
  except OperatorError as error:
    print(str(error), file=sys.stderr)
    return error.exit_code


def print_top_level_help() -> None:
  print(TOP_LEVEL_HELP)


def _flag_value(flags: list[str], name: str) -> str | None:
  token = f"--{name}"
  for index, value in enumerate(flags):
    if value == token and index + 1 < len(flags):
      return flags[index + 1]
    if value.startswith(f"{token}="):
      return value.split("=", 1)[1]
  return None


def _friendly_jwt_message(message: str) -> str:
  if "expired" in message.lower():
    return "PAPYRUS_GRAPHQL_JWT is expired. Run: papyrus auth refresh --write-env .env"
  return "Missing PAPYRUS_GRAPHQL_JWT. Run: papyrus auth refresh --write-env .env"


def format_unexpected_error(error: BaseException) -> str:
  if isinstance(error, ValueError) and "PAPYRUS_GRAPHQL_JWT" in str(error):
    return _friendly_jwt_message(str(error))
  return str(error)


def should_suppress_traceback(error: BaseException) -> bool:
  if isinstance(error, (OperatorError, ValueError)):
    return True
  return False
