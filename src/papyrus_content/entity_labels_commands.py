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


def _localizer(models_for):
    from .entity_labels.localize_concept import localize_concept

    return lambda client, node, language, dry_run=False: localize_concept(client, str(node.get("nodeKey") or node["id"]), [language], dry_run=dry_run, models_for=models_for)


def relations_localize(flags: list[str], *, client=None, models_for=None) -> None:
    """papyrus knowledge concepts localize --concept NAME|#HASHTAG|NODEKEY --language TAG [--language TAG ...] [--dry-run] [--json]
           papyrus knowledge concepts localize --needed [--language TAG ...] [--ceiling-usd N] [--dry-run] [--json]

    Names one concept in other languages with the label procedure (the glossary decides what it covers, the house model translates the rest, the bilingual
    judge checks the description, a name another concept already has is held). A clean label is current; a held one raises a review request. Needs a model
    key (OPENAI_API_KEY) and the operator lane (`papyrus --auth iam`). --dry-run makes and prices the labels without saving them. --needed names the concepts that Stories in a language are waiting for (the queue pages
    fill; docs/multilingual-labels.md) in the served languages, or the ones given, and stops at --ceiling-usd; the rest stays queued, so a second run goes on."""
    import argparse

    parser = argparse.ArgumentParser(prog="papyrus knowledge concepts localize", description=relations_localize.__doc__)
    parser.add_argument("--concept")
    parser.add_argument("--language", action="append")
    parser.add_argument("--needed", action="store_true")
    parser.add_argument("--ceiling-usd", type=float)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(flags)
    if args.needed == bool(args.concept):
        raise ValueError("Give --concept NAME (with --language) to name one concept, or --needed to name the concepts pages are waiting for.")
    if not args.needed and not args.language:
        raise ValueError("--language is required with --concept.")
    if args.ceiling_usd is not None and not args.needed:
        raise ValueError("--ceiling-usd goes with --needed.")
    if client is None:
        client, _ = create_authoring_client()
    if args.needed:
        from .entity_labels.wanted import drain

        report = drain(client, languages=args.language, ceiling_usd=args.ceiling_usd, dry_run=args.dry_run, say=lambda line: print(line, file=sys.stderr),
                       **({"localize": _localizer(models_for)} if models_for else {}))
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"Wanted concept names: {'dry run' if args.dry_run else 'drained'}")
            for name in ("named", "skipped", "remaining", "costUsd", "stopped"):
                print(f"{name}\t{report[name]}")
        return
    from .entity_labels.localize_concept import localize_concept

    report = localize_concept(client, args.concept, args.language, dry_run=args.dry_run, models_for=models_for)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    for row in report:
        print("\t".join([row["concept"], row["language"], row["state"], row["name"] or "", f"${row['costUsd']:.4f}", "; ".join(row["reasons"])]))
