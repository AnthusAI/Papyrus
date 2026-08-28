from __future__ import annotations

import json
from pathlib import Path

from kanbus.issue_listing import IssueListingError, list_issues

from ..config import OperatorConfig
from ..errors import OperatorError
from ..output import OperatorRow
from .base import OperatorBackend, assignment_rows_from_fixture, load_fixture_json, reference_rows_from_fixture


class LocalPodBackend(OperatorBackend):
  def __init__(self, config: OperatorConfig) -> None:
    self._config = config

  def _pod_root(self) -> Path:
    if self._config.fixture_root:
      fixture_pod = self._config.fixture_root / "local-pod" / "anthus-blog"
      if fixture_pod.exists():
        return fixture_pod
    if self._config.pod_path and self._config.pod_path.exists():
      return self._config.pod_path
    raise OperatorError("Local pod path is not configured or does not exist.")

  def list_references(
    self,
    *,
    corpus_key: str,
    limit: int,
    status: str,
    order: str,
  ) -> list[OperatorRow]:
    fixture_root = self._config.fixture_root
    if fixture_root and (fixture_root / "local-pod" / "anthus-blog").exists():
      payload = load_fixture_json(fixture_root, "pod-references.json")
      rows = reference_rows_from_fixture(payload, kind="pod-reference")
    else:
      rows = _collect_pod_reference_rows(self._pod_root(), corpus_key=corpus_key)

    rows = _filter_status(rows, status)
    reverse = not order.endswith("-oldest")
    rows.sort(key=lambda row: row.identifier, reverse=reverse)
    return rows[: max(limit, 1)]

  def show_reference(self, reference_id: str) -> OperatorRow:
    rows = self.list_references(
      corpus_key=self._config.default_corpus_key,
      limit=10_000,
      status="",
      order="newest",
    )
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
    fixture_root = self._config.fixture_root
    if fixture_root and (fixture_root / "local-pod" / "anthus-blog").exists():
      payload = load_fixture_json(fixture_root, "pod-stories.json")
      rows = assignment_rows_from_fixture(payload, kind="pod-story")
      if status:
        rows = [row for row in rows if row.status == status]
      if assignment_type:
        rows = [row for row in rows if row.extra.get("type") == assignment_type]
      return rows[: max(limit, 1)]

    pod_root = self._pod_root()
    try:
      issues = list_issues(pod_root, issue_type="story", status=status or None)
    except IssueListingError as error:
      raise OperatorError(str(error)) from error

    rows = [
      OperatorRow(
        kind="pod-story",
        status=issue.status,
        identifier=issue.identifier,
        title=issue.title,
        extra={"type": issue.issue_type},
      )
      for issue in issues
      if issue.issue_type == "story"
    ]
    if assignment_type:
      rows = [row for row in rows if row.extra.get("type") == assignment_type]
    return rows[: max(limit, 1)]


def _collect_pod_reference_rows(pod_root: Path, *, corpus_key: str) -> list[OperatorRow]:
  manifest = pod_root / "pod-references.json"
  if manifest.exists():
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
      return reference_rows_from_fixture(payload, kind="pod-reference")

  rows: list[OperatorRow] = []
  stories_dir = pod_root / "stories"
  if not stories_dir.exists():
    return rows

  for story_dir in sorted(stories_dir.iterdir()):
    if not story_dir.is_dir():
      continue
    refs_dir = story_dir / "references"
    if not refs_dir.exists():
      continue
    for ref_path in sorted(refs_dir.glob("*.json")):
      payload = json.loads(ref_path.read_text(encoding="utf-8"))
      if not isinstance(payload, dict):
        continue
      rows.append(
        OperatorRow(
          kind="pod-reference",
          status=str(payload.get("status") or ""),
          identifier=str(payload.get("id") or ref_path.stem),
          title=str(payload.get("title") or ""),
          extra={"corpus": str(payload.get("corpus") or payload.get("corpusKey") or corpus_key)},
        )
      )
  return rows


def _filter_status(rows: list[OperatorRow], status: str) -> list[OperatorRow]:
  normalized = status.strip().lower()
  if not normalized or normalized in {"all", "*"}:
    return rows
  return [row for row in rows if row.status.strip().lower() == normalized]
