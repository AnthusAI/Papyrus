from __future__ import annotations

import json
import sys
from pathlib import Path

from kanbus.issue_listing import IssueListingError, list_issues

from ..config import OperatorConfig
from ..errors import OperatorError
from ..output import OperatorRow, pod_reference_to_row
from ..pod_references import (
  RegisterReferenceRequest,
  emit_project_key_warnings,
  find_reference_by_url,
  load_pod_references,
  register_pod_reference,
  resolve_story_id,
)
from .base import OperatorBackend, assignment_rows_from_fixture, load_fixture_json, reference_rows_from_fixture


class LocalPodBackend(OperatorBackend):
  def __init__(self, config: OperatorConfig) -> None:
    self._config = config

  def _pod_root(self) -> Path:
    if self._config.pod_path and self._config.pod_path.exists():
      return self._config.pod_path
    if self._config.fixture_root:
      fixture_pod = self._config.fixture_root / "local-pod" / "anthus-blog"
      if fixture_pod.exists():
        return fixture_pod
    raise OperatorError("Local pod path is not configured or does not exist.")

  def _uses_readonly_fixture_manifest(self, pod_root: Path) -> bool:
    fixture_root = self._config.fixture_root
    return bool(
      fixture_root
      and (fixture_root / "local-pod" / "anthus-blog").exists()
      and pod_root == fixture_root / "local-pod" / "anthus-blog"
    )

  def list_references(
    self,
    *,
    corpus_key: str,
    limit: int,
    status: str,
    order: str,
  ) -> list[OperatorRow]:
    pod_root = self._pod_root()
    if self._uses_readonly_fixture_manifest(pod_root):
      payload = load_fixture_json(self._config.fixture_root, "pod-references.json")
      rows = reference_rows_from_fixture(payload, kind="pod-reference")
    else:
      emit_project_key_warnings(pod_root)
      records = load_pod_references(pod_root, corpus_key=corpus_key)
      rows = [pod_reference_to_row(record) for record in records]

    rows = _filter_status(rows, status)
    reverse = not order.endswith("-oldest")
    rows.sort(key=lambda row: row.identifier, reverse=reverse)
    return rows[: max(limit, 1)]

  def show_reference(self, reference_id: str) -> OperatorRow:
    pod_root = self._pod_root()
    if self._uses_readonly_fixture_manifest(pod_root):
      payload = load_fixture_json(self._config.fixture_root, "pod-references.json")
      for row in reference_rows_from_fixture(payload, kind="pod-reference"):
        if row.identifier == reference_id:
          return row
    else:
      emit_project_key_warnings(pod_root)
      for record in load_pod_references(pod_root):
        if record.identifier == reference_id:
          return pod_reference_to_row(record)
    raise OperatorError(f"Reference not found: {reference_id}")

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
    pod_root = self._pod_root()
    emit_project_key_warnings(pod_root)
    resolved_story = resolve_story_id(
      pod_root=pod_root,
      explicit_story=story_id,
      default_story=self._config.default_story,
    )
    existing = find_reference_by_url(pod_root, corpus_key=corpus_key, url=url)
    if existing is not None and existing.status.strip().lower() == "accepted":
      print(
        f"warning: existing accepted reference {existing.identifier} would be clobbered; refusing re-register.",
        file=sys.stderr,
      )
    result = register_pod_reference(
      pod_root,
      RegisterReferenceRequest(
        story_id=resolved_story,
        url=url,
        title=title,
        status=status,
        why=why,
        corpus_key=corpus_key,
        reference_id=reference_id,
      ),
    )
    if result.message:
      print(result.message)

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
    emit_project_key_warnings(pod_root)
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


def _filter_status(rows: list[OperatorRow], status: str) -> list[OperatorRow]:
  normalized = status.strip().lower()
  if not normalized or normalized in {"all", "*"}:
    return rows
  return [row for row in rows if row.status.strip().lower() == normalized]
