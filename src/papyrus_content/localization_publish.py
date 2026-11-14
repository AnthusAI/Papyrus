"""Publishing a translation: the rules that hold a localization back (docs/story-translation-procedure.md, "Publishing a translation").

A translation is published through the ordinary publish path (``publishing.publish_item``), as a person's act. Because it is a Story lineage of its
own (``{story}--{language}``) that the machine wrote, three of that path's rules read differently for it, and this module is where they are decided:

* **Its checklist is its provenance.** The English Story's checklist (research, draft, the review lenses, the cover, the rating) describes how a person
  or an agent writes a Story; a translation has none of those steps. The steps that apply to it (translate, faithfulness, copy edit) are proven by the
  records of the run that saved the version, which the run itself writes, so there is no sub-task Item and nothing to tick by hand.
* **A held translation does not publish until a person clears it.** The run holds a translation when an error-severity faithfulness finding remains
  (or its cost ran past its ceiling) and raises a flag review request (:func:`hold_request_id`). The version carries ``metadata.localization.outcome:
  held``; publishing it needs that request answered ``approve`` or ``acknowledge`` by a person. An open or rejected request keeps it back. A clean
  translation needs no clearance.
* **It is published only while its original is.** Its page is served beside the original's (hreflang, the original link in the label), so the original's
  published row must exist. The projection serves it by the same rule (``projection/source.py``), so taking the original down takes the translation
  off the site without touching its record, and publishing the original again brings it back.

Ratings: a translation has no rating of its own (the localize run does not copy the original's, and a machine never creates one). One star rating serves
every language of a Story (plan decision 10), so the rating gate is the original's, which it passed when it was published. Never read here.
"""
from __future__ import annotations

import json
from typing import Any

from .item_language import localization_original

ORIGINAL_UNPUBLISHED = "original-unpublished"
TRANSLATION_HELD = "translation-held"


def hold_request_id(run_key: str) -> str:
    """The id of the flag review request a held run raises: one per run key, so the same run raises it once and publishing finds it again."""
    return f"localize-{run_key[:24]}"


def _localization_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata")
    if isinstance(metadata, str):
        metadata = json.loads(metadata) if metadata.strip() else {}
    return (metadata or {}).get("localization") or {}


def original_of(client, item: dict[str, Any]) -> str | None:
    """The primary lineage ``item`` translates, or None when it is a Story of its own."""
    return localization_original(item, getattr(client, "tenant_id", None))


def require_publishable(client, item: dict[str, Any], original: str) -> None:
    """Raises ``PublishError`` unless the localization version ``item`` of the Story ``original`` may be published now: its original is published, and a
    hold on this version has been cleared by a person."""
    from .publishing import PublishError, published_item_id_for

    live = client.get_record("PublishedItem", published_item_id_for(original))
    if live is None or live.get("status") not in (None, "published"):
        raise PublishError(ORIGINAL_UNPUBLISHED, f"The original ({original}) is not published. A translation is published only while its original is: "
                           f"publish {original} first.")
    localization = _localization_metadata(item)
    if localization.get("outcome") != "held":
        return
    from .review_requests import read_review

    request_id = hold_request_id(str(localization.get("runKey") or ""))
    row = client.get_record("ReviewRequest", request_id)
    outcome = read_review(row)["outcome"] if row is not None else "missing"
    if outcome == "approved":
        return
    raise PublishError(
        TRANSLATION_HELD,
        f"This {item.get('language')} translation is held ({localization.get('reason') or 'its checks found a problem'}). It publishes after a person clears it: "
        f"answer review request {request_id} with approve or acknowledge (papyrus reviews answer --id {request_id} --decision approve). "
        f"The review request is {outcome}.",
    )
