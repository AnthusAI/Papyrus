"""A deterministic, recorded spread sample of pending references for a relevance shadow run.

The oldest-first sweep order says nothing about how the whole pending queue
would be judged. A shadow run wants a SPREAD: every kind of intake, across the
whole import timeline, drawn the same way every time from a seed. The draw is

1. drop what an editor would not weigh as a candidate: bulk housekeeping origins
   (by default the auto-created GROBID citation stubs) and test fixtures;
2. group the rest by intake origin and split the sample size across the origins
   as evenly as their sizes allow (small origins are taken whole);
3. inside each origin pick evenly spaced members of the importedAt order,
   starting from a seeded offset, so the picks cover the whole timeline;
4. order the picks by a seeded hash, so any prefix (a batch) is itself a spread.

The result is a manifest: policy, seed, pool fingerprint, strata and the ordered
lineage ids. Persist it, then decide from it (``--sample-list``) so later batches
stay on the same references even after editors move some out of pending.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

SAMPLE_POLICY = "origin-balanced-importedAt-systematic-v1"
HOUSEKEEPING_ORIGINS = ("grobid-citation-graph",)
TEST_DOI_PREFIX = "10.5555/"
_TRAILING_RUN_HASH = re.compile(r"-[0-9a-f]{12,}$")


def intake_origin(reference: Mapping[str, Any], corpus_id: str) -> str:
    """Where a reference came from: ``<change reason>/<import run family>/<actor>``."""
    run = _TRAILING_RUN_HASH.sub("", str(reference.get("importRunId") or ""))
    family = run.replace(f"knowledge-import-{corpus_id}-", "").replace(corpus_id, "").strip("-") or "-"
    return "/".join((str(reference.get("changeReason") or "unknown"), family,
                     str(reference.get("curationStatusUpdatedBy") or "unknown")))


def change_reason_of_origin(origin: str) -> str:
    return origin.split("/", 1)[0]


def looks_like_test_fixture(reference: Mapping[str, Any]) -> bool:
    """A Crossref test DOI, or a reference an automated test run curated."""
    identifiers = f"{reference.get('sourceUri') or ''} {reference.get('externalItemId') or ''}"
    return TEST_DOI_PREFIX in identifiers or str(reference.get("curationStatusUpdatedBy") or "").startswith("behave-")


def pool_fingerprint(pending: Sequence[Mapping[str, Any]]) -> str:
    rows = sorted(f"{reference['lineageId']}:{reference.get('contentHash') or ''}" for reference in pending)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def allocate(sizes: Mapping[str, int], total: int) -> dict[str, int]:
    """Split ``total`` across strata as evenly as sizes allow; small strata are taken whole."""
    quotas = {name: 0 for name in sizes}
    remaining = min(total, sum(sizes.values()))
    ordered = sorted(sizes, key=lambda name: (sizes[name], name))
    for position, name in enumerate(ordered):
        quotas[name] = min(sizes[name], remaining // (len(ordered) - position))
        remaining -= quotas[name]
    for name in sorted(sizes, key=lambda name: (quotas[name] - sizes[name], name)):
        if remaining == 0:
            break
        if quotas[name] < sizes[name]:
            quotas[name] += 1
            remaining -= 1
    return quotas


def _tiebreak(seed: str, scope: str, lineage_id: str) -> str:
    return hashlib.sha256(f"{seed}:{scope}:{lineage_id}".encode("utf-8")).hexdigest()


def _imported_at(reference: Mapping[str, Any]) -> str:
    return str(reference.get("importedAt") or reference.get("createdAt") or "")


def draw_sample(pending: Sequence[Mapping[str, Any]], *, size: int, seed: str, corpus_id: str,
                include_housekeeping: bool = False) -> dict[str, Any]:
    """Draw the spread sample from the current pending references; the same inputs give the same manifest."""
    if size < 1:
        raise ValueError("--sample must be a positive number.")
    seed = str(seed)
    excluded: Counter[str] = Counter()
    strata: dict[str, list[Mapping[str, Any]]] = {}
    for reference in pending:
        origin = intake_origin(reference, corpus_id)
        if looks_like_test_fixture(reference):
            excluded["test fixture"] += 1
        elif not include_housekeeping and change_reason_of_origin(origin) in HOUSEKEEPING_ORIGINS:
            excluded[f"housekeeping origin {change_reason_of_origin(origin)}"] += 1
        else:
            strata.setdefault(origin, []).append(reference)
    quotas = allocate({origin: len(members) for origin, members in strata.items()}, size)
    chosen: list[Mapping[str, Any]] = []
    for origin in sorted(strata):
        members = sorted(strata[origin], key=lambda reference: (_imported_at(reference),
                                                                _tiebreak(seed, origin, reference["lineageId"])))
        take = quotas[origin]
        offset = random.Random(f"{seed}:{origin}").random()
        chosen.extend(members[int((index + offset) * len(members) / take)] for index in range(take))
    chosen.sort(key=lambda reference: _tiebreak(seed, "order", reference["lineageId"]))
    lineage_ids = [reference["lineageId"] for reference in chosen]
    return {
        "policy": SAMPLE_POLICY, "seed": seed, "requestedSize": size, "size": len(lineage_ids),
        "corpusId": corpus_id, "includeHousekeeping": include_housekeeping,
        "poolSize": len(pending), "poolFingerprint": pool_fingerprint(pending), "excluded": dict(sorted(excluded.items())),
        "strata": {origin: {"pool": len(strata[origin]), "sampled": quotas[origin]} for origin in sorted(strata)},
        "selectionFingerprint": selection_fingerprint(lineage_ids), "lineageIds": lineage_ids,
    }


def selection_fingerprint(lineage_ids: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(lineage_ids).encode("utf-8")).hexdigest()[:16]


def write_manifest(manifest: Mapping[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_manifest(path: str | Path, corpus_id: str) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("policy") != SAMPLE_POLICY or not isinstance(manifest.get("lineageIds"), list):
        raise ValueError(f"{path} is not a {SAMPLE_POLICY} sample manifest.")
    if manifest.get("corpusId") != corpus_id:
        raise ValueError(f"{path} was drawn from {manifest.get('corpusId')}, not {corpus_id}.")
    if manifest.get("selectionFingerprint") != selection_fingerprint(manifest["lineageIds"]):
        raise ValueError(f"{path} was edited after it was drawn (selection fingerprint mismatch).")
    return manifest


def distribution(chosen: Sequence[Mapping[str, Any]], corpus_id: str) -> dict[str, Any]:
    """How a set of references spreads over importedAt (by month) and intake origin."""
    def domain(reference):
        uri = str(reference.get("sourceUri") or "")
        return uri.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.") if uri else "(no source uri)"

    return {
        "count": len(chosen),
        "importedAtRange": [min(map(_imported_at, chosen), default=None), max(map(_imported_at, chosen), default=None)],
        "byImportedMonth": dict(sorted(Counter(_imported_at(reference)[:7] for reference in chosen).items())),
        "byImportedDay": dict(sorted(Counter(_imported_at(reference)[:10] for reference in chosen).items())),
        "byIntakeOrigin": dict(Counter(intake_origin(reference, corpus_id) for reference in chosen).most_common()),
        "bySourceDomain": dict(Counter(domain(reference) for reference in chosen).most_common(12)),
    }
