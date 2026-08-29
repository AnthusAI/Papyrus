from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from papyrus_content.env import PAPYRUS_ROOT
from papyrus_content.steering import load_steering_config

VALID_BACKENDS = frozenset({"local", "cloud"})
DEFAULT_OPERATOR_CONFIG_RELATIVE = Path(".papyrus") / "operator-cli.config.yaml"


@dataclass(frozen=True)
class OperatorConfig:
  backend: str
  default_corpus_key: str
  publication_key: str
  pod_path: Path | None
  default_story: str | None
  graphql_endpoint: str | None
  config_path: Path | None
  fixture_root: Path | None


def _optional_string(value: Any) -> str | None:
  if value is None:
    return None
  normalized = str(value).strip()
  return normalized or None


def _resolve_path(value: str | None, *, base: Path) -> Path | None:
  if not value:
    return None
  path = Path(value)
  if not path.is_absolute():
    path = base / path
  return path.resolve()


def _default_corpus_from_steering() -> str:
  steering = load_steering_config()
  if steering:
    return str(steering.get("canonicalTopicSet", {}).get("corpusKey") or "threat-intelligence")
  return "threat-intelligence"


def _load_yaml_config(path: Path) -> dict[str, Any]:
  if not path.exists():
    return {}
  parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
  return parsed if isinstance(parsed, dict) else {}


def resolve_operator_config_path(explicit: str | None = None) -> Path | None:
  configured = explicit or os.environ.get("PAPYRUS_OPERATOR_CONFIG")
  if configured:
    path = Path(configured)
    if not path.is_absolute():
      path = PAPYRUS_ROOT / path
    return path.resolve()
  default = PAPYRUS_ROOT / DEFAULT_OPERATOR_CONFIG_RELATIVE
  return default if default.exists() else None


def load_operator_config(
  *,
  config_path: str | None = None,
  backend_override: str | None = None,
  corpus_key_override: str | None = None,
) -> OperatorConfig:
  fixture_root = _resolve_path(os.environ.get("PAPYRUS_OPERATOR_FIXTURE_ROOT"), base=PAPYRUS_ROOT)
  resolved_config_path = resolve_operator_config_path(config_path)
  raw = _load_yaml_config(resolved_config_path) if resolved_config_path else {}

  local_section = raw.get("local") if isinstance(raw.get("local"), dict) else {}
  cloud_section = raw.get("cloud") if isinstance(raw.get("cloud"), dict) else {}

  default_corpus = (
    corpus_key_override
    or _optional_string(raw.get("defaultCorpusKey"))
    or _default_corpus_from_steering()
  )
  publication_key = _optional_string(raw.get("publicationKey")) or default_corpus
  pod_path = _resolve_path(_optional_string(local_section.get("podPath")), base=PAPYRUS_ROOT)
  default_story = _optional_string(local_section.get("defaultStory"))
  graphql_endpoint = (
    _optional_string(cloud_section.get("graphqlEndpoint"))
    or _optional_string(os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT"))
  )

  backend = _resolve_backend(
    backend_override=backend_override,
    configured_backend=_optional_string(raw.get("backend")),
    graphql_endpoint=graphql_endpoint,
    pod_path=pod_path,
  )

  return OperatorConfig(
    backend=backend,
    default_corpus_key=default_corpus,
    publication_key=publication_key,
    pod_path=pod_path,
    default_story=default_story,
    graphql_endpoint=graphql_endpoint,
    config_path=resolved_config_path,
    fixture_root=fixture_root,
  )


def _resolve_backend(
  *,
  backend_override: str | None,
  configured_backend: str | None,
  graphql_endpoint: str | None,
  pod_path: Path | None,
) -> str:
  for candidate in (
    backend_override,
    _optional_string(os.environ.get("PAPYRUS_BACKEND")),
    configured_backend,
  ):
    if candidate:
      normalized = candidate.strip().lower()
      if normalized not in VALID_BACKENDS:
        raise ValueError(
          f"unknown backend {candidate!r}. Use one of: {', '.join(sorted(VALID_BACKENDS))}."
        )
      return normalized

  if graphql_endpoint:
    return "cloud"
  if pod_path and pod_path.exists():
    return "local"
  return "cloud"


def parse_operator_flags(argv: list[str]) -> tuple[dict[str, str | int | bool], list[str]]:
  options: dict[str, str | int | bool] = {}
  positionals: list[str] = []
  index = 0
  while index < len(argv):
    token = argv[index]
    if token == "--":
      positionals.extend(argv[index + 1 :])
      break
    if token.startswith("--"):
      key = token[2:]
      if "=" in key:
        name, value = key.split("=", 1)
        options[name] = value
        index += 1
        continue
      if key in {"help", "h"}:
        options["help"] = True
        index += 1
        continue
      if index + 1 < len(argv) and not argv[index + 1].startswith("--"):
        options[key] = argv[index + 1]
        index += 2
        continue
      options[key] = True
      index += 1
      continue
    positionals.append(token)
    index += 1
  return options, positionals
