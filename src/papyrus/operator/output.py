from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class OperatorRow:
  kind: str
  status: str
  identifier: str
  title: str
  extra: dict[str, str]


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


def rows_match_status(rows: Iterable[OperatorRow], status: str) -> bool:
  normalized = status.strip().lower()
  return all(row.status.strip().lower() == normalized for row in rows)
