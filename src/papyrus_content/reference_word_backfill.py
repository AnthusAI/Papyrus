"""Fill the References search word table from the References that already exist (``papyrus references backfill-word-index --site KEY [--write]``).

The word table (``papyrus_knowledge_query.reference_words``) is written by a DynamoDB Streams consumer when a Reference is created or changes, so a
Reference that existed before the table did has no words until this command runs, once per site, right after the table and the consumer are deployed.

It reads each current Reference of a corpus by curation status (``referencesByCurationStatusKey``, the partition read the other backfills use; never a
scan), takes the words the search indexes (title, authors, address and ``externalItemId`` of a Reference that is in a feed) and writes the word rows and
the Reference's pointer row. It changes no Reference. A Reference whose pointer already names the current row is skipped, so running it again writes
nothing (the pointer is written last, so a run cut short is finished by the next one). ``dry_run`` (the CLI's default) reads the pointers and reports
what it would write, and writes nothing.
"""
from __future__ import annotations

from typing import Any, Callable

from papyrus_knowledge_query.reference_words import WordWriter, row_words

STATUSES = ("pending", "accepted", "rejected")   # an archived Reference is in no feed and has no words


def backfill_words(client: Any, writer: WordWriter, *, corpus_id: str, dry_run: bool = True, progress: Callable[[str], None] = lambda line: None) -> dict[str, Any]:
    counts = {"corpusId": corpus_id, "dryRun": dry_run, "scanned": 0, "withoutWords": 0, "alreadyIndexed": 0, "toIndex": 0, "wordRows": 0, "written": 0}
    for status in STATUSES:
        for reference in client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}"):
            if not reference or reference.get("versionState", "current") != "current":
                continue
            counts["scanned"] += 1
            words = row_words(reference)
            if not words:
                counts["withoutWords"] += 1
                continue
            if writer.pointer_is_current(reference):
                counts["alreadyIndexed"] += 1
                continue
            counts["toIndex"] += 1
            counts["wordRows"] += len(words)
            progress(f"{'would index' if dry_run else 'index'}\t{reference['id']}\t{reference.get('title')}\t{len(words)} words")
            if not dry_run:
                writer.apply_change(None, reference)
                counts["written"] += 1
    return counts

