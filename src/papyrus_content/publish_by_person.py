"""The person-only publish rule (PPY-473f8f): nothing publishes by itself when no one has reviewed it as a whole.

Three kinds of Story reach the publish step without the review a Story written in the newsroom goes through:

* ``pod-loaded``: a Story loaded from a pod (``metadata.pod``); the pod's claims are not the newsroom's records (``pod_claims.py``).
* ``imported``: a Story whose checklist is every step but publishing marked not applicable, ``imported from <source>`` (``story_checklist.mark_imported``).
* ``translation``: a ``{story}--{language}`` lineage the machine wrote; no step of it is ticked, and its checklist is only its provenance
  (``localization_publish.py``).

``publish_item`` asks :func:`require_person_act` before any other gate. A publish of one of these Stories succeeds only when ``by_person`` names a signed-in
person: the console editor pressing Publish (or Save on a live article), or the CLI in the signed-in lane (the signed-in lane, `user_auth_requested()`). Everything else is
refused with the typed code ``person-publish-required`` (``details.storyKind`` names which of the three) and words that say how to proceed: a pod load leaves
the Story a draft, an automatic translation (``languages.auto`` with ``publish: true``, ``--publish-clean``, a scheduled publish, an agent) stays a ready
draft, and a person publishes it by hand. Nothing is forced and nothing falls back.

This is the one rule, kept in this module and nowhere else, until the per-language checklist gate (PPY-473f8f follow-up) replaces it: once every language
lineage has its own checklist that publish checks, the checklist is the gate and this block is lifted. Then delete this module and its one call.
"""
from __future__ import annotations

from typing import Any

from .item_language import localization_original
from .pod_claims import pod_record

PERSON_PUBLISH_REQUIRED = "person-publish-required"
POD_LOADED = "pod-loaded"
IMPORTED = "imported"
TRANSLATION = "translation"

_HOW_TO_PROCEED = {
    POD_LOADED: "This Story was loaded from a pod, and a pod's claims are not a review. The load leaves it a draft: review it, then publish it by hand in the "
                "newsroom console, or with `papyrus ops content publish --id {id}` signed in as yourself.",
    IMPORTED: "This Story was imported, and none of its checklist steps were done. Review it and tick the steps that apply, then publish it by hand in the "
              "newsroom console, or with `papyrus ops content publish --id {id}` signed in as yourself.",
    TRANSLATION: "This translation was written by a machine, and nothing publishes it automatically. It stays a ready draft: read it, then publish it by hand in "
                 "the newsroom console, or with `papyrus ops content publish --id {id}` signed in as yourself.",
}


def story_kind(client, item: dict[str, Any]) -> str | None:
    """Which of the three kinds ``item`` is, or None for a Story that went through the newsroom (and for anything that is not a Story, unless it is a translation)."""
    from .authored_editions import is_authored

    if localization_original(item, getattr(client, "tenant_id", None)) is not None and not is_authored(item):
        return TRANSLATION   # an independently authored companion is not a machine translation: it has its own checklist and the ordinary gates (PPY-219a24)
    from .content_item_lifecycle import is_story_item_type

    if not is_story_item_type(item.get("type")):
        return None   # a Page or a wiki page has no checklist to skip: only Stories are held to the person rule below
    if pod_record(item):
        return POD_LOADED
    if _imported(client, item):
        return IMPORTED
    return None


def _imported(client, item: dict[str, Any]) -> bool:
    from .story_checklist import NOT_APPLICABLE, PUBLISH_KEY, read_steps

    rows = read_steps(client, item.get("lineageId") or item["id"])
    others = [row for row in rows if row.get("stepKey") != PUBLISH_KEY]
    return bool(others) and all(row.get("state") == NOT_APPLICABLE and str(row.get("reason") or "").startswith("imported from") for row in others)


def require_person_act(client, item: dict[str, Any], *, by_person: str | None) -> None:
    """Raises ``PublishError`` (code ``person-publish-required``) when ``item`` is a pod-loaded, imported or translated Story and no person is publishing it."""
    if by_person:
        return
    kind = story_kind(client, item)
    if kind is None:
        return
    from .publishing import PublishError

    raise PublishError(PERSON_PUBLISH_REQUIRED, _HOW_TO_PROCEED[kind].format(id=item["id"]), details={"storyKind": kind})
