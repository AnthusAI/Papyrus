from __future__ import annotations

from papyrus_content.publication import normalize_corpus_key

from ..config import OperatorConfig, parse_operator_flags, resolve_default_corpus_key
from ..errors import OperatorError
from ..output import format_meta_line, print_reference_detail, print_tabular
from ..backends.base import create_backend

REFERENCE_LIST_COLUMNS = ("kind", "status", "id", "title", "corpus", "url")
ASSIGNMENT_LIST_COLUMNS = ("kind", "status", "id", "type", "title")


def run_references_list(config: OperatorConfig, flags: list[str]) -> int:
  options, _ = parse_operator_flags(flags)
  backend_name = str(options.get("backend") or config.backend)
  active_config = _with_overrides(config, options)
  backend = create_backend(active_config)

  limit = int(options.get("limit") or 25)
  status = str(options.get("status") or "")
  order = str(options.get("order") or "newest")
  corpus_key = normalize_corpus_key(str(options.get("corpus-key") or resolve_default_corpus_key(active_config)))

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
  corpus_key = normalize_corpus_key(str(options["corpus-key"])) if options.get("corpus-key") else None
  row = backend.show_reference(positionals[0], corpus_key)
  print_reference_detail(row)
  if active_config.backend == "cloud" and not active_config.fixture_root and (row.extra.get("lineageId") or row.identifier):
    from papyrus_content.console_links import ConsoleLinkError, reference_url, resolve_console_url

    try:
      print(f"console: {reference_url(resolve_console_url(), str(row.extra.get('lineageId') or row.identifier))}")
    except ConsoleLinkError as error:
      print(f"console: unavailable ({error})")
  return 0


def run_references_text(config: OperatorConfig, flags: list[str]) -> int:
  import json as _json

  from papyrus_content.reference_text_read import DEFAULT_LIMIT, NoCapturedText, read_reference_text

  options, positionals = parse_operator_flags(flags)
  reference_id = str(options.get("reference") or "").strip() or (positionals[0] if positionals else "")
  if not reference_id or reference_id is True:
    raise OperatorError("papyrus references text requires --reference ID|LINEAGE")

  def number(name: str, default: int) -> int:
    raw = options.get(name)
    if raw is None:
      return default
    try:
      return int(str(raw))
    except ValueError:
      raise OperatorError(f"--{name} must be a whole number.") from None

  offset, limit = number("offset", 0), number("limit", DEFAULT_LIMIT)
  active_config = _with_overrides(config, options)
  backend = create_backend(active_config)
  if not hasattr(backend, "_ensure_auth"):
    raise OperatorError("papyrus references text reads a site's stored text: use --backend cloud.")
  backend._ensure_auth()
  from papyrus_content.graphql_authoring import create_authoring_client

  client, _ = create_authoring_client()
  try:
    result = read_reference_text(client, reference_id, offset=offset, limit=limit)
  except NoCapturedText as missing:
    if options.get("json"):
      print(_json.dumps({**missing.details, "text": None, "error": "no captured text"}, indent=2))
    else:
      print(f"reference: {missing.details['referenceId']}\nurl: {missing.details['url']}\ncapture: {missing.details['captureStatus']}"
            + (f" ({missing.details['captureReason']})" if missing.details.get("captureReason") else "") + "\nNo captured text is stored for this Reference.")
    return 1
  except ValueError as error:
    raise OperatorError(str(error)) from None
  if options.get("json"):
    print(_json.dumps(result, indent=2))
    return 0
  print(f"reference: {result['referenceId']}")
  print(f"url: {result['url']}")
  print(f"source: {result['source']}" + (f" ({result['sourceKind']})" if result.get("sourceKind") else ""))
  print(f"captured-at: {result['capturedAt'] or 'unknown'}")
  print(f"total-characters: {result['totalCharacters']}")
  print(f"offset: {result['offset']}  returned: {result['returnedCharacters']}")
  print(f"truncated: {'yes (the page was larger than the reader takes and was cut)' if result['truncated'] else 'no'}")
  for flag in result["flags"]:
    print(f"note: {flag}")
  print(f"next: {'--offset ' + str(result['nextOffset']) if result['nextOffset'] is not None else 'end of text'}")
  print("---")
  print(result["text"])
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


def run_references_register(config: OperatorConfig, flags: list[str]) -> int:
  options, _ = parse_operator_flags(flags)
  active_config = _with_overrides(config, options)
  backend_name = str(options.get("backend") or active_config.backend)
  if backend_name != "local":
    raise OperatorError("papyrus references register is only supported for --backend local")

  url = str(options.get("url") or "").strip()
  title = str(options.get("title") or "").strip()
  status = str(options.get("status") or "pending").strip().lower()
  why = str(options.get("why") or "")
  story_id = str(options.get("story") or "").strip() or None
  corpus_key = str(options.get("corpus-key") or resolve_default_corpus_key(active_config))
  reference_id = str(options.get("id") or "").strip() or None

  if not url:
    raise OperatorError("papyrus references register requires --url")
  if not title:
    raise OperatorError("papyrus references register requires --title")

  backend = create_backend(active_config)
  backend.register_reference(
    story_id=story_id,
    url=url,
    title=title,
    status=status,
    why=why,
    corpus_key=corpus_key,
    reference_id=reference_id,
  )
  return 0


def accepted_flags_for(command: str) -> set[str]:
  if command == "papyrus references list":
    return {"--limit", "--status", "--order", "--corpus-key", "--backend"}
  if command == "papyrus references show":
    return {"--corpus-key", "--backend"}
  if command == "papyrus references register":
    return {"--url", "--title", "--status", "--why", "--story", "--corpus-key", "--backend", "--id"}
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
