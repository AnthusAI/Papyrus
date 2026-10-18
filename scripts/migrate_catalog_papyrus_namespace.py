"""
Move Papyrus extension fields of Biblicus catalog items under ``metadata.papyrus``.

Run ``scripts/migrate_catalog_extensions.py`` from Biblicus first: it moves unknown
top-level item fields into ``metadata``. This script then gathers the Papyrus-owned keys
that landed directly in ``metadata`` into the ``metadata.papyrus`` namespace.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

PAPYRUS_EXTENSION_KEYS_FORMERLY_DIRECTLY_IN_METADATA = (
    "subtitle",
    "summary",
    "identifiers",
    "identifier_resolution",
    "title_subtitle_resolution",
    "summary_resolution",
)
PAPYRUS_QUALITY_RATING_KEY = "quality_rating"


def migrate_catalog_item_metadata(item: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    migrated_item = dict(item)
    metadata = dict(migrated_item.get("metadata") or {})
    papyrus_extension = dict(metadata.get("papyrus") or {})
    changed = False

    for key in PAPYRUS_EXTENSION_KEYS_FORMERLY_DIRECTLY_IN_METADATA:
        if key in metadata:
            papyrus_extension.setdefault(key, metadata.pop(key))
            changed = True

    quality = metadata.pop("quality", None)
    if quality is not None:
        if isinstance(quality, dict):
            papyrus_extension.setdefault(PAPYRUS_QUALITY_RATING_KEY, quality)
        changed = True

    if changed:
        metadata["papyrus"] = papyrus_extension
        migrated_item["metadata"] = metadata
    return migrated_item, changed


def migrate_catalog_file(catalog_path: Path, *, dry_run: bool) -> int:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    migrated_item_count = 0
    for item_identifier, item in list(catalog.get("items", {}).items()):
        migrated_item, changed = migrate_catalog_item_metadata(item)
        if changed:
            catalog["items"][item_identifier] = migrated_item
            migrated_item_count += 1
    if migrated_item_count and not dry_run:
        temporary_path = catalog_path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary_path.replace(catalog_path)
    return migrated_item_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_paths", nargs="+", type=Path, help="Corpus root directories.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing.")
    arguments = parser.parse_args(argv)
    exit_status = 0
    for corpus_path in arguments.corpus_paths:
        catalog_path = corpus_path / "metadata" / "catalog.json"
        if not catalog_path.is_file():
            print(f"{corpus_path}: no catalog at {catalog_path}", file=sys.stderr)
            exit_status = 1
            continue
        migrated_item_count = migrate_catalog_file(catalog_path, dry_run=arguments.dry_run)
        verb = "would migrate" if arguments.dry_run else "migrated"
        print(f"{corpus_path}: {verb} {migrated_item_count} items")
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
