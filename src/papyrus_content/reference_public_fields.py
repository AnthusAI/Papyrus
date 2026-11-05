"""What a public card needs on the Reference row itself, and the one-time backfill that fills it in (docs/plans/public-blocks-from-indexes.md, PPY-7f1e54).

A public block will ask an index for the rows it shows and draw each card from the row it gets back, with no decision request and no preview request.
Besides the keys (``reference_feed_keys.public_feed_keys``) that takes three copies of what the preview attachment holds:

* ``cardImage``: the address of the picture. The preview's image address (scrubbed of anything that carries identity); for a video, our own thumbnail copy
  (``reference_thumbnails.public_image``), never an address on the platform; for an image an editor chose (``via: editor``), that image.
* ``cardSummary``: the preview's description, scrubbed and NOT clipped. The clip to ``publicData.summaryCharacters`` happens when the card is drawn, so a
  site that changes its length changes nothing in the table.
* ``cardSiteName``: the preview's site name, scrubbed.
* ``cardPageTitle``: the title the page declared for link previews, scrubbed and otherwise as the preview holds it. The card's displayed title is computed from the
  row's own ``title`` and this, when the row is titled with its own address (``home_page/export.displayed_title`` once PR #1236 is in), so a repaired title needs no
  rewrite here and a stock bot-wall title is filtered where the title is chosen.

They are written by the code that already writes the row, at the moment the fact becomes known (a preview is captured, a thumbnail is recorded), and never
recomputed on a schedule. ``papyrus references backfill-public-fields`` is the one command that reads the preview attachments of existing rows: it is run
once per site, previews by default, and writes nothing a second time.

Standard library only (plus ``reference_thumbnails``, which imports Pillow lazily): the router and content-actions bundles ship this module.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Mapping

from .public_text import WithheldReference, public_url, scrub
from .reference_feed_keys import CARD_FIELDS, PUBLIC_FEED_KEY_FIELD, PUBLIC_KEY_FIELDS, public_feed_keys
from .reference_medium import MEDIUM_VIDEO, medium_of
from .reference_thumbnails import EDITOR_IMAGE, public_image

PREVIEW_ROLE = "preview"
PUBLIC_FIELDS = (*PUBLIC_KEY_FIELDS, *CARD_FIELDS)
#: The lowest score the pending partition is read down to: a pending row below it has no public key (``reference_feed_keys.RECOMMENDED_FLOOR``), and the
#: prediction index is read highest first, so the read stops at the first sort key under it.
PENDING_READ_FLOOR_KEY = "0.500000"


def preview_metadata(preview: Mapping[str, Any] | None) -> Mapping[str, Any]:
    metadata = (preview or {}).get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    return metadata if isinstance(metadata, Mapping) else {}


def chosen_preview(attachments: Iterable[Mapping[str, Any] | None]) -> Mapping[str, Any] | None:
    """The preview attachment a card is drawn from: one that has an image address if any does, else any; the latest imported. The one rule the home page
    snapshot (``home_page/export.preview_of``) and the card copies share."""
    previews = [item for item in attachments if item and item.get("role") == PREVIEW_ROLE]
    imaged = [item for item in previews if item.get("sourceUri")]
    chosen = imaged or previews
    return max(chosen, key=lambda item: str(item.get("importedAt") or "")) if chosen else None


def card_fields(reference: Mapping[str, Any], preview: Mapping[str, Any] | None) -> dict[str, str | None]:
    """``{"cardImage", "cardSummary", "cardSiteName", "cardPageTitle"}`` for a Reference and its chosen preview attachment (None when it has none). Every value is public text:
    scrubbed of email-, UUID- and site-subject-shaped strings, the picture address stripped of a query that carries identity or dropped when its path does."""
    metadata = preview_metadata(preview)
    image: str | None = None
    if preview:
        try:
            image = public_url(preview.get("sourceUri"))
        except WithheldReference:
            image = None
    medium = reference.get("medium") or medium_of(reference.get("sourceUri"))
    if medium == MEDIUM_VIDEO and metadata.get("via") != EDITOR_IMAGE:
        # A video's card shows its own thumbnail from our storage, never an address on the platform (a reader's browser must not contact it, and a takedown must
        # not break the card). No copy yet means no image. An image an editor set is the exception: it is theirs.
        image = public_image(reference)
    return {"cardImage": image, "cardSummary": scrub(metadata.get("description")), "cardSiteName": scrub(metadata.get("siteName")),
            "cardPageTitle": scrub(metadata.get("title"))}


def changed_card_fields(reference: Mapping[str, Any], wanted: Mapping[str, str | None]) -> dict[str, str | None]:
    """The card fields whose stored value differs from ``wanted``; an unset field and an empty one are the same."""
    return {name: wanted[name] for name in CARD_FIELDS if (reference.get(name) or None) != (wanted[name] or None)}


def planned_public_fields(reference: Mapping[str, Any], attachments: Callable[[], Iterable[Mapping[str, Any] | None]]) -> dict[str, str | None]:
    """The fields to write for one current Reference, or {} when it is already right.

    The keys follow the row's own facts. The card fields are planned only for a row that can be public (``attachments`` is called then, and only then, so a row
    that cannot be public costs no attachment read); a row that cannot be public keeps whatever card fields it has."""
    keys = public_feed_keys(reference)
    fields: dict[str, str | None] = {name: keys[name] for name in PUBLIC_KEY_FIELDS if (reference.get(name) or None) != keys[name]}
    if keys[PUBLIC_FEED_KEY_FIELD]:
        fields.update(changed_card_fields(reference, card_fields(reference, chosen_preview(attachments()))))
    return fields


def card_update(client: Any, reference: Mapping[str, Any], preview: Mapping[str, Any] | None) -> dict[str, Any]:
    """Write the card fields of one Reference from its preview, only where they differ from the row. Returns the fields written ({} when nothing changed).

    This is the writer every place that captures a preview calls (``reference_images.attach_preview`` and ``enrich_reference_previews``); the thumbnail
    recorder merges ``cardImage`` into its own update instead. One mutation per new Reference, and none when the row already holds the same values."""
    fields = changed_card_fields(reference, card_fields(reference, preview))
    if fields:
        client.update_record("Reference", {"id": reference["id"], **fields})
    return fields


def pending_rows(client: Any, corpus_id: str):
    """The pending rows a public key can exist for, highest stored prediction first, read from the prediction index and stopped at the first row under 0.5.

    This is a backfill read, not a path any page or task takes. An unpredicted row sorts at exactly 0.5 and is returned (it gets no key); a row under 0.5 ends the read."""
    for row in client.iterate_newest_first("referencesByFeedStateAndPrediction", f"{corpus_id}#unrated"):
        if str(row.get("predictionSortKey") or "") < PENDING_READ_FLOOR_KEY:
            return
        yield row


def backfill_public_fields(client: Any, *, corpus_id: str, dry_run: bool = True, progress: Callable[[str], None] = lambda line: None) -> dict[str, Any]:
    """Set the public keys and the card fields on the public rows of one corpus: its accepted rows and its pending rows predicted at 0.5 or more.

    Reads each accepted row from the curation-status index and the pending ones from the prediction index (stopping under 0.5), and for a row that can be
    public reads its preview attachments once. Rejected, archived, unpredicted and low-scored rows are not read or touched. It changes no vote and no other
    field, and everything it writes derives from the row and its preview, so running it again writes nothing. A dry run (the CLI's default) reports each
    change and writes none. The rows must already carry ``feedStateKey`` and ``predictionSortKey`` (``papyrus references backfill-feed-keys``) for the
    pending ones to be found.
    """
    counts: dict[str, Any] = {"corpusId": corpus_id, "dryRun": dry_run, "scanned": 0, "public": 0, "accepted": 0, "recommended": 0, "changed": 0, "alreadyRight": 0,
                              "keysSet": 0, "keysCleared": 0, "cardImagesSet": 0, "cardSummariesSet": 0, "cardSiteNamesSet": 0, "cardPageTitlesSet": 0, "videosWithoutImage": 0,
                              "longestSummary": 0, "written": 0}
    accepted = client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#accepted")
    for row in [*accepted, *pending_rows(client, corpus_id)]:
        if not row or row.get("versionState", "current") != "current":
            continue
        counts["scanned"] += 1
        read: list[Mapping[str, Any] | None] = []

        def attachments() -> list[Mapping[str, Any] | None]:
            if not read:
                read.extend(client.list_reference_attachments_by_lineage(str(row["lineageId"])) if row.get("lineageId") else [])
            return read

        fields = planned_public_fields(row, attachments)
        keys = public_feed_keys(row)
        if keys[PUBLIC_FEED_KEY_FIELD]:
            counts["public"] += 1
            counts["accepted" if row.get("curationStatus") == "accepted" else "recommended"] += 1
            wanted = {**{name: row.get(name) for name in CARD_FIELDS}, **fields}
            counts["longestSummary"] = max(counts["longestSummary"], len(wanted.get("cardSummary") or ""))
            counts["videosWithoutImage"] += int((row.get("medium") or medium_of(row.get("sourceUri"))) == MEDIUM_VIDEO and not wanted.get("cardImage"))
        if not fields:
            counts["alreadyRight"] += 1
            continue
        counts["changed"] += 1
        if PUBLIC_FEED_KEY_FIELD in fields:
            counts["keysSet" if fields[PUBLIC_FEED_KEY_FIELD] else "keysCleared"] += 1
        counts["cardImagesSet"] += int(bool(fields.get("cardImage")))
        counts["cardSummariesSet"] += int(bool(fields.get("cardSummary")))
        counts["cardSiteNamesSet"] += int(bool(fields.get("cardSiteName")))
        counts["cardPageTitlesSet"] += int(bool(fields.get("cardPageTitle")))
        progress(f"{'would write' if dry_run else 'write'}\t{row['id']}\t" + ", ".join(f"{name}={'-' if value is None else 'set'}" for name, value in fields.items()))
        if not dry_run:
            client.update_record("Reference", {"id": row["id"], **fields})
            counts["written"] += 1
    return counts
