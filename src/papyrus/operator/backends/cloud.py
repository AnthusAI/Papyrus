from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from papyrus_content.env import load_dotenv
from papyrus_content.graphql_http import authoring_credentials_available

from ..config import OperatorConfig, resolve_default_corpus_key
from ..errors import OperatorError
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
    if self._fixture_root():
      return
    if not authoring_credentials_available():
      raise OperatorError(
        "No AWS credentials for cloud authoring. Set AWS_PROFILE to a profile that can assume the "
        "papyrus-authoring role (for example: aws sso login --profile <profile>).",
        exit_code=2,
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
      if not payload.get("items"):
        self._require_known_corpus(corpus_key)
      rows = [
        OperatorRow(
          kind="cloud-reference",
          status=str(item.get("curationStatus") or item.get("status") or ""),
          identifier=str(item.get("id") or ""),
          title=str(item.get("title") or ""),
          extra={
            "corpus": corpus_key,
            "url": str(item.get("sourceUri") or item.get("url") or ""),
            "why": str(item.get("why") or item.get("ingestionRationale") or ""),
            "lineageId": str(item.get("lineageId") or ""),
          },
        )
        for item in payload.get("items") or []
      ]

    rows = _filter_status(rows, status)
    rows = _sort_reference_rows(rows, order)
    return rows[: max(limit, 1)]

  def _require_known_corpus(self, corpus_key: str) -> None:
    """An empty list is only an empty corpus when the corpus exists; a key that names nothing is an error, not an empty table."""
    from papyrus_content.graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    if client.get_record("KnowledgeCorpus", f"knowledge-corpus-{corpus_key}"):
      return
    served = [str(row.get("id") or "").removeprefix("knowledge-corpus-") for row in client.list_by_index("knowledgeCorporaByRoleAndName", "canonical")]
    hint = f" This site serves {', '.join(served)}." if served else ""
    raise OperatorError(f"Unknown corpus {corpus_key}: no such KnowledgeCorpus.{hint} Pass --corpus-key <key>, or omit it to use the site's own corpus.")

  def show_reference(self, reference_id: str, corpus_key: str | None = None) -> OperatorRow:
    """A Reference by record id (``...-v1``), by lineage id (what ``stories show`` prints), or, on a fixture, by either."""
    if self._fixture_root():
      key = corpus_key or resolve_default_corpus_key(self._config)
      rows = self.list_references(corpus_key=key, limit=10_000, status="", order="newest")
      wanted = {reference_id, re.sub(r"-v\d+$", "", reference_id)}
      for row in rows:
        if {row.identifier, row.extra.get("lineageId", ""), re.sub(r"-v\d+$", "", row.identifier)} & wanted:
          return row
      raise OperatorError(f"Reference not found: {reference_id}")
    self._ensure_auth()
    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.story_reporting import current_reference

    client, _ = create_authoring_client()
    record = current_reference(client, reference_id)
    if record is None:
      raise OperatorError(f"Reference not found: {reference_id}. Pass an id or lineage id that `papyrus stories show` or `references list` prints.")
    record_corpus = str(record.get("corpusId") or "").removeprefix("knowledge-corpus-")
    if corpus_key and record_corpus != corpus_key:
      raise OperatorError(f"Reference {reference_id} is in corpus {record_corpus or 'none'}, not {corpus_key}.")
    return _reference_row(record, record_corpus)

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


def _reference_row(record: dict[str, Any], corpus_key: str) -> OperatorRow:
  return OperatorRow(
    kind="cloud-reference",
    status=str(record.get("curationStatus") or record.get("status") or ""),
    identifier=str(record.get("id") or ""),
    title=str(record.get("title") or ""),
    extra={
      "corpus": corpus_key,
      "url": str(record.get("sourceUri") or record.get("url") or ""),
      "why": str(record.get("why") or record.get("ingestionRationale") or ""),
      "lineageId": str(record.get("lineageId") or ""),
    },
  )


def _filter_status(rows: list[OperatorRow], status: str) -> list[OperatorRow]:
  normalized = status.strip().lower()
  if not normalized or normalized in {"all", "*"}:
    return rows
  return [row for row in rows if row.status.strip().lower() == normalized]


def _sort_reference_rows(rows: list[OperatorRow], order: str) -> list[OperatorRow]:
  reverse = not order.endswith("-oldest")
  return sorted(rows, key=lambda row: row.identifier, reverse=reverse)
