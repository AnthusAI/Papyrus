from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .pod_references import PodReferenceRecord


@dataclass(frozen=True)
class OperatorRow:
  kind: str
  status: str
  identifier: str
  title: str
  extra: dict[str, str]


def pod_reference_to_row(record: PodReferenceRecord) -> OperatorRow:
  return OperatorRow(
    kind="pod-reference",
    status=record.status,
    identifier=record.identifier,
    title=record.title,
    extra={
      "corpus": record.corpus,
      "url": record.url,
      "why": record.why,
      "story": record.story_id,
    },
  )


def format_meta_line(**fields: str) -> str:
  return "\t".join(f"{key}={value}" for key, value in fields.items())


def print_tabular(rows: Sequence[OperatorRow], *, columns: Sequence[str]) -> None:
  print("\t".join(columns))
  for row in rows:
    values: list[str] = []
    for column in columns:
      if column == "kind":
        values.append(row.kind)
      elif column == "status":
        values.append(row.status)
      elif column == "id":
        values.append(row.identifier)
      elif column == "title":
        values.append(row.title)
      elif column == "corpus":
        values.append(row.extra.get("corpus", ""))
      elif column == "type":
        values.append(row.extra.get("type", ""))
      elif column == "url":
        values.append(row.extra.get("url", ""))
      else:
        values.append(row.extra.get(column, ""))
    print("\t".join(values))


def print_reference_detail(row: OperatorRow) -> None:
  print("reference")
  print(f"kind: {row.kind}")
  print(f"id: {row.identifier}")
  print(f"status: {row.status}")
  print(f"title: {row.title}")
  if row.extra.get("corpus"):
    print(f"corpus: {row.extra['corpus']}")
  if row.extra.get("url"):
    print(f"url: {row.extra['url']}")
  if row.extra.get("why"):
    print(f"why: {row.extra['why']}")


def rows_match_status(rows: Iterable[OperatorRow], status: str) -> bool:
  normalized = status.strip().lower()
  return all(row.status.strip().lower() == normalized for row in rows)
