from __future__ import annotations

from ..config import OperatorConfig, parse_operator_flags
from ..errors import OperatorError
from ..output import format_meta_line, print_reference_detail, print_tabular
from ..backends.base import create_backend

REFERENCE_LIST_COLUMNS = ("kind", "status", "id", "title", "corpus")
ASSIGNMENT_LIST_COLUMNS = ("kind", "status", "id", "type", "title")


def run_references_list(config: OperatorConfig, flags: list[str]) -> int:
  options, _ = parse_operator_flags(flags)
  backend_name = str(options.get("backend") or config.backend)
  active_config = _with_overrides(config, options)
  backend = create_backend(active_config)

  limit = int(options.get("limit") or 25)
  status = str(options.get("status") or "")
  order = str(options.get("order") or "newest")
  corpus_key = str(options.get("corpus-key") or active_config.default_corpus_key)

  rows = backend.list_references(corpus_key=corpus_key, limit=limit, status=status, order=order)
  print(format_meta_line(backend=backend_name, corpusKey=corpus_key))
  print_tabular(rows, columns=REFERENCE_LIST_COLUMNS)
  return 0


def run_references_show(config: OperatorConfig, flags: list[str]) -> int:
  options, positionals = parse_operator_flags(flags)
  if not positionals:
    raise OperatorError("papyrus references show requires <reference-id>")
  active_config = _with_overrides(config, options)
  backend = create_backend(active_config)
  row = backend.show_reference(positionals[0])
  print_reference_detail(row)
  return 0


def run_assignments_list(config: OperatorConfig, flags: list[str]) -> int:
  options, _ = parse_operator_flags(flags)
  backend_name = str(options.get("backend") or config.backend)
  active_config = _with_overrides(config, options)
  backend = create_backend(active_config)

  limit = int(options.get("limit") or 25)
  status = str(options.get("status") or "")
  assignment_type = str(options.get("type") or "")

  rows = backend.list_assignments(limit=limit, status=status, assignment_type=assignment_type)
  print(format_meta_line(backend=backend_name))
  if backend_name == "local":
    print("hint=Use kbs for board columns and transitions")
  print_tabular(rows, columns=ASSIGNMENT_LIST_COLUMNS)
  return 0


def accepted_flags_for(command: str) -> set[str]:
  if command == "papyrus references list":
    return {"--limit", "--status", "--order", "--corpus-key", "--backend"}
  if command == "papyrus assignments list":
    return {"--limit", "--status", "--type", "--backend"}
  return set()


def _with_overrides(config: OperatorConfig, options: dict[str, str | int | bool]) -> OperatorConfig:
  from ..config import load_operator_config

  backend_override = str(options["backend"]) if "backend" in options else None
  corpus_override = str(options["corpus-key"]) if "corpus-key" in options else None
  if backend_override or corpus_override:
    return load_operator_config(
      config_path=str(config.config_path) if config.config_path else None,
      backend_override=backend_override,
      corpus_key_override=corpus_override,
    )
  return config
