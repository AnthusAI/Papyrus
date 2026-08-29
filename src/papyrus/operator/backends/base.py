from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..config import OperatorConfig
from ..errors import OperatorError
from ..output import OperatorRow


class OperatorBackend(ABC):
  @abstractmethod
  def list_references(
    self,
    *,
    corpus_key: str,
    limit: int,
    status: str,
    order: str,
  ) -> list[OperatorRow]:
    raise NotImplementedError

  @abstractmethod
  def show_reference(self, reference_id: str) -> OperatorRow:
    raise NotImplementedError

  @abstractmethod
  def list_assignments(
    self,
    *,
    limit: int,
    status: str,
    assignment_type: str,
  ) -> list[OperatorRow]:
    raise NotImplementedError

  def register_reference(
    self,
    *,
    story_id: str | None,
    url: str,
    title: str,
    status: str,
    why: str,
    corpus_key: str,
    reference_id: str | None = None,
  ) -> None:
    raise OperatorError("papyrus references register is only supported for --backend local")


def load_fixture_json(fixture_root: Path, filename: str) -> dict[str, Any]:
  path = fixture_root / filename
  if not path.exists():
    raise FileNotFoundError(f"Missing operator CLI fixture: {path}")
  payload = json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(payload, dict):
    raise ValueError(f"Fixture {path} must be a JSON object.")
  return payload


def reference_rows_from_fixture(payload: dict[str, Any], *, kind: str) -> list[OperatorRow]:
  items = payload.get("items") or []
  rows: list[OperatorRow] = []
  for item in items:
    if not isinstance(item, dict):
      continue
    rows.append(
      OperatorRow(
        kind=kind,
        status=str(item.get("status") or ""),
        identifier=str(item.get("id") or ""),
        title=str(item.get("title") or ""),
        extra={
          "corpus": str(item.get("corpus") or item.get("corpusKey") or ""),
          "url": str(item.get("url") or item.get("sourceUri") or ""),
          "why": str(item.get("why") or ""),
        },
      )
    )
  return rows


def assignment_rows_from_fixture(payload: dict[str, Any], *, kind: str) -> list[OperatorRow]:
  items = payload.get("items") or []
  rows: list[OperatorRow] = []
  for item in items:
    if not isinstance(item, dict):
      continue
    rows.append(
      OperatorRow(
        kind=kind,
        status=str(item.get("status") or ""),
        identifier=str(item.get("id") or ""),
        title=str(item.get("title") or ""),
        extra={"type": str(item.get("type") or item.get("assignmentTypeKey") or "")},
      )
    )
  return rows


def create_backend(config: OperatorConfig) -> OperatorBackend:
  if config.backend == "local":
    from .local import LocalPodBackend

    return LocalPodBackend(config)
  from .cloud import CloudBackend

  return CloudBackend(config)
