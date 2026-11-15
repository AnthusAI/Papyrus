"""`papyrus knowledge concepts label-backfill` and `labels` (docs/multilingual-labels.md)."""
from __future__ import annotations

import json
import sys

from .graphql_authoring import create_authoring_client
from .options import normalize_positive_integer, parse_boolean_option, parse_options


def relations_label_backfill(flags: list[str], *, client=None) -> None:
    """papyrus knowledge concepts label-backfill [--limit N] [--apply] [--json]

    Gives every concept its language (the site's primary language) and its name rows, so a concept is found by name with one index query. DRY RUN IS THE
    DEFAULT. Operator lane (IAM): editors cannot write concepts. Run it again after an interruption: a concept already in order is skipped."""
    from .entity_labels.backfill import backfill_entity_labels

    options = parse_options(flags)
    apply = parse_boolean_option(options.get("apply"), default=False, label="--apply")
    limit = normalize_positive_integer(options.get("limit"), "--limit")
    if client is None:
        client, _ = create_authoring_client()
    report = backfill_entity_labels(client, apply=apply, limit=limit, say=lambda line: print(line, file=sys.stderr))
    if options.get("json"):
        print(json.dumps(report, indent=2))
        return
    print(f"Concept name rows: {'APPLY' if apply else 'dry run (nothing written; add --apply to write)'}")
    for name in ("concepts", "language", "created", "updated", "deleted", "stale") + (() if apply else ("wouldChange",)):
        print(f"{name}\t{report[name]}")


def relations_labels(flags: list[str], *, client=None) -> None:
    """papyrus knowledge concepts labels --concept NAME|#HASHTAG|NODEKEY [--json]  (read only: every name of the concept in every language)."""
    from .entity_labels.keys import CONCEPT, entity_key
    from .entity_labels.primary import lineage_of
    from .entity_labels.store import LabelStore
    from .section_concepts import resolve_concept

    options = parse_options(flags)
    text = options.get("concept")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("--concept is required.")
    if client is None:
        client, _ = create_authoring_client()
    node = resolve_concept(client, text, allow_rejected=True)
    if node is None:
        raise ValueError(f"No concept is named {text!r}.")
    rows = sorted(LabelStore(client).of_entity(entity_key(CONCEPT, lineage_of(node))), key=lambda row: row["sortKey"])
    if options.get("json"):
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    print(f"{node.get('displayName')}\t{node.get('nodeKey')}\tlanguage {node.get('language') or '(none yet)'}")
    for row in rows:
        print("\t".join([row["language"], row["role"], row["text"], row.get("origin") or "", row.get("syncState") or "", row.get("equivalence") or ""]))
