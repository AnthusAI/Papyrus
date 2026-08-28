from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from papyrus_content.env import decode_jwt_claims, graphql_jwt, is_jwt_expired, load_dotenv

from ..config import OperatorConfig
from ..errors import OperatorError, jwt_guidance_error
from ..output import OperatorRow
from .base import (
  OperatorBackend,
  assignment_rows_from_fixture,
  load_fixture_json,
  reference_rows_from_fixture,
)


class CloudBackend(OperatorBackend):
  def __init__(self, config: OperatorConfig) -> None:
    self._config = config

  def _fixture_root(self) -> Path | None:
    return self._config.fixture_root

  def _ensure_auth(self) -> None:
    load_dotenv()
    import os

    token = os.environ.get("PAPYRUS_GRAPHQL_JWT", "").strip()
    if not token:
      if self._fixture_root():
        return
      raise jwt_guidance_error(
        "Missing PAPYRUS_GRAPHQL_JWT. Run: papyrus auth refresh --write-env .env"
      )
    claims = decode_jwt_claims(token)
    if is_jwt_expired(claims):
      raise jwt_guidance_error(
        "PAPYRUS_GRAPHQL_JWT is expired. Run: papyrus auth refresh --write-env .env"
      )

  def list_references(
    self,
    *,
    corpus_key: str,
    limit: int,
    status: str,
    order: str,
  ) -> list[OperatorRow]:
    self._ensure_auth()
    fixture_root = self._fixture_root()
    if fixture_root:
      payload = load_fixture_json(fixture_root, "cloud-references.json")
      rows = reference_rows_from_fixture(payload, kind="cloud-reference")
    else:
      self._ensure_auth()
      from papyrus_newsroom.reference_curation_signals import reference_list

      payload = reference_list(
        corpus_key=corpus_key,
        limit=limit,
        status=status,
        order=order,
      )
      rows = [
        OperatorRow(
          kind="cloud-reference",
          status=str(item.get("curationStatus") or item.get("status") or ""),
          identifier=str(item.get("id") or ""),
          title=str(item.get("title") or ""),
          extra={"corpus": corpus_key},
        )
        for item in payload.get("items") or []
      ]

    rows = _filter_status(rows, status)
    rows = _sort_reference_rows(rows, order)
    return rows[: max(limit, 1)]

  def show_reference(self, reference_id: str) -> OperatorRow:
    rows = self.list_references(corpus_key=self._config.default_corpus_key, limit=10_000, status="", order="newest")
    for row in rows:
      if row.identifier == reference_id:
        return row
    raise OperatorError(f"Reference not found: {reference_id}")

  def list_assignments(
    self,
    *,
    limit: int,
    status: str,
    assignment_type: str,
  ) -> list[OperatorRow]:
    fixture_root = self._fixture_root()
    if fixture_root:
      payload = load_fixture_json(fixture_root, "cloud-assignments.json")
      rows = assignment_rows_from_fixture(payload, kind="newsroom-assignment")
    else:
      self._ensure_auth()
      from papyrus_content.graphql_authoring import create_authoring_client

      client, _ = create_authoring_client()
      assignments = client.list_records("Assignment")
      rows = [
        OperatorRow(
          kind="newsroom-assignment",
          status=str(item.get("status") or ""),
          identifier=str(item.get("id") or ""),
          title=str(item.get("title") or ""),
          extra={"type": str(item.get("assignmentTypeKey") or "")},
        )
        for item in assignments
      ]

    if status:
      rows = [row for row in rows if row.status == status]
    if assignment_type:
      rows = [row for row in rows if row.extra.get("type") == assignment_type]
    return rows[: max(limit, 1)]


def _filter_status(rows: list[OperatorRow], status: str) -> list[OperatorRow]:
  normalized = status.strip().lower()
  if not normalized or normalized in {"all", "*"}:
    return rows
  return [row for row in rows if row.status.strip().lower() == normalized]


def _sort_reference_rows(rows: list[OperatorRow], order: str) -> list[OperatorRow]:
  reverse = not order.endswith("-oldest")
  return sorted(rows, key=lambda row: row.identifier, reverse=reverse)
