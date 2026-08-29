from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import yaml

from .errors import OperatorError


REFERENCE_STATUSES = frozenset({"accepted", "pending", "rejected"})


@dataclass(frozen=True)
class PodReferenceRecord:
  identifier: str
  status: str
  title: str
  corpus: str
  url: str
  why: str
  story_id: str
  path: Path


@dataclass(frozen=True)
class RegisterReferenceRequest:
  story_id: str
  url: str
  title: str
  status: str
  why: str
  corpus_key: str
  reference_id: str | None = None


@dataclass(frozen=True)
class RegisterReferenceResult:
  action: str
  reference_id: str | None = None
  story_id: str | None = None
  message: str = ""


def normalize_reference_url(url: str) -> str:
  parsed = urlparse(url.strip())
  if not parsed.scheme or not parsed.netloc:
    raise OperatorError(f"Invalid reference URL: {url}")
  normalized = parsed._replace(fragment="")
  path = normalized.path.rstrip("/") or "/"
  return urlunparse(normalized._replace(path=path))


def load_pod_project_key(pod_root: Path) -> str | None:
  config_path = pod_root / ".kanbus.yml"
  if not config_path.exists():
    return None
  parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
  if not isinstance(parsed, dict):
    return None
  project_key = parsed.get("project_key")
  return str(project_key).strip() if project_key else None


def project_key_prefix_warnings(pod_root: Path) -> list[str]:
  project_key = load_pod_project_key(pod_root)
  if not project_key:
    return []
  issues_dir = pod_root / "project" / "issues"
  if not issues_dir.exists():
    return []
  warnings: list[str] = []
  expected_prefix = f"{project_key}-"
  for issue_path in sorted(issues_dir.glob("*.json")):
    try:
      payload = json.loads(issue_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
      continue
    issue_id = str(payload.get("id") or issue_path.stem)
    if not issue_id.startswith(expected_prefix):
      warnings.append(
        f"Kanbus issue {issue_id} uses a legacy prefix; project_key is {project_key!r}. "
        "Kanbus does not remint ids on project_key change — pass --story explicitly."
      )
  return warnings


def emit_project_key_warnings(pod_root: Path) -> None:
  for warning in project_key_prefix_warnings(pod_root):
    print(f"warning: {warning}", file=sys.stderr, flush=True)


def resolve_story_id(*, pod_root: Path, explicit_story: str | None, default_story: str | None) -> str:
  story_id = (explicit_story or default_story or "").strip()
  if not story_id:
    raise OperatorError(
      "papyrus references register --backend local requires --story <story-id> "
      "or local.defaultStory in operator CLI config."
    )
  issue_path = pod_root / "project" / "issues" / f"{story_id}.json"
  if not issue_path.exists():
    raise OperatorError(f"Story not found in pod Kanbus project: {story_id}")
  return story_id


def iter_pod_reference_files(pod_root: Path) -> list[Path]:
  stories_dir = pod_root / "stories"
  if not stories_dir.exists():
    return []
  paths: list[Path] = []
  for story_dir in sorted(stories_dir.iterdir()):
    refs_dir = story_dir / "references"
    if refs_dir.is_dir():
      paths.extend(sorted(refs_dir.glob("*.json")))
  return paths


def load_pod_reference(path: Path, *, story_id: str | None = None) -> PodReferenceRecord | None:
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except json.JSONDecodeError:
    return None
  if not isinstance(payload, dict):
    return None
  resolved_story = story_id or path.parent.parent.name
  return PodReferenceRecord(
    identifier=str(payload.get("id") or path.stem),
    status=str(payload.get("status") or ""),
    title=str(payload.get("title") or ""),
    corpus=str(payload.get("corpus") or payload.get("corpusKey") or ""),
    url=str(payload.get("url") or ""),
    why=str(payload.get("why") or ""),
    story_id=resolved_story,
    path=path,
  )


def load_pod_references(pod_root: Path, *, corpus_key: str | None = None) -> list[PodReferenceRecord]:
  manifest = pod_root / "pod-references.json"
  if manifest.exists():
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else []
    records: list[PodReferenceRecord] = []
    for item in items or []:
      if not isinstance(item, dict):
        continue
      records.append(
        PodReferenceRecord(
          identifier=str(item.get("id") or ""),
          status=str(item.get("status") or ""),
          title=str(item.get("title") or ""),
          corpus=str(item.get("corpus") or item.get("corpusKey") or corpus_key or ""),
          url=str(item.get("url") or ""),
          why=str(item.get("why") or ""),
          story_id=str(item.get("story") or item.get("storyId") or ""),
          path=manifest,
        )
      )
    return records

  records: list[PodReferenceRecord] = []
  for ref_path in iter_pod_reference_files(pod_root):
    record = load_pod_reference(ref_path)
    if record is None:
      continue
    if corpus_key and record.corpus and record.corpus != corpus_key:
      continue
    records.append(record)
  return records


def find_reference_by_url(pod_root: Path, *, corpus_key: str, url: str) -> PodReferenceRecord | None:
  normalized = normalize_reference_url(url)
  for record in load_pod_references(pod_root, corpus_key=corpus_key):
    if record.corpus == corpus_key and record.url and normalize_reference_url(record.url) == normalized:
      return record
  return None


def derive_reference_id(url: str) -> str:
  digest = hashlib.sha1(normalize_reference_url(url).encode("utf-8")).hexdigest()[:8]
  return f"ref-{digest}"


def validate_register_request(request: RegisterReferenceRequest) -> None:
  status = request.status.strip().lower()
  if status not in REFERENCE_STATUSES:
    raise OperatorError(f"Unsupported reference status: {request.status}")
  why = request.why.strip()
  if status == "rejected":
    return
  if not why:
    raise OperatorError("accepted and pending references require a non-empty --why")


def register_pod_reference(pod_root: Path, request: RegisterReferenceRequest) -> RegisterReferenceResult:
  validate_register_request(request)
  status = request.status.strip().lower()
  why = request.why.strip()

  if status == "rejected" and not why:
    return RegisterReferenceResult(
      action="rejected",
      message="Reference rejected; no pod reference row written.",
    )

  normalized_url = normalize_reference_url(request.url)
  existing = find_reference_by_url(pod_root, corpus_key=request.corpus_key, url=normalized_url)
  if existing is not None:
    if existing.status.strip().lower() == "accepted":
      raise OperatorError(
        f"Reference already accepted for URL {normalized_url} (id={existing.identifier}, story={existing.story_id}). "
        "Re-register refused to avoid clobbering accepted metadata."
      )
    raise OperatorError(
      f"Reference already exists for URL {normalized_url} (id={existing.identifier}, story={existing.story_id}). "
      "Re-register refused."
    )

  reference_id = (request.reference_id or derive_reference_id(normalized_url)).strip()
  if not reference_id:
    reference_id = derive_reference_id(normalized_url)

  refs_dir = pod_root / "stories" / request.story_id / "references"
  refs_dir.mkdir(parents=True, exist_ok=True)
  target = refs_dir / f"{reference_id}.json"
  if target.exists():
    raise OperatorError(f"Reference id already exists: {reference_id}")

  payload: dict[str, Any] = {
    "id": reference_id,
    "status": status,
    "title": request.title.strip(),
    "corpus": request.corpus_key,
    "url": normalized_url,
    "why": why,
    "story": request.story_id,
  }
  target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
  return RegisterReferenceResult(
    action="created",
    reference_id=reference_id,
    story_id=request.story_id,
    message=f"Wrote pod reference {reference_id} under stories/{request.story_id}/references/",
  )
