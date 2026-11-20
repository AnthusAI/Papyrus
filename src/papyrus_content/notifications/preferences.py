"""The reader's preferences page: choose a cadence inside a family you consented to; joining a new family asks for consent (PPY-2f9b22, slice N7).

Consent is per family. A reader consented to a family when they confirmed a list of it, and holds that consent for as long as they hold a list of the family:

* **Choosing another cadence inside a family the reader holds** (every new item to the daily summary, or back) is a move and needs no new confirmation. The rule that moves them
  is Caducus's (``PublicAudience.update_preferences``, with the cadence families of ``list_cadence/family.py``), and a move keeps the family's consent evidence.
* **Joining a family the reader does not hold** (a newsletter they never chose, a family they left, or any list once they have unsubscribed from everything) is not a
  preference: it needs the double opt-in the subscribe form has. The preferences page therefore does not turn it on. It asks Caducus for a confirmation of the reader's own
  address, with the site's consent wording the page showed, and the list begins only when the reader presses the link. Whatever else the same save changed is saved.
* **One exception, kept from before.** A reader suppressed for a bounce or a complaint is sent no confirmation (Caducus ignores a signup for that address), so their own choice on
  their manage page still lifts the suppression, as it did.
* **Nothing enrols a reader.** A list added to the site's settings has no members until readers choose it, and no migration or new feature calls anything here.

``consent_by_family`` reads the consent evidence (wording, time, form) a reader's confirmations stored, grouped by the family of the lists each one covers.
"""
from __future__ import annotations

import time
from typing import Any, Mapping

from caducus.notify.audience import AudienceKeys, PublicAudience, SubscribeRequest
from caducus.notify.audience import tokens

from papyrus_content.list_cadence.family import conflicts, families

Answer = dict[str, Any]

#: Suppressions the reader's own opt-in on their manage page lifts without a confirmation, because Caducus sends none to such an address.
LIFTED_BY_OPT_IN = frozenset({"bounce", "complaint"})


def _answer(status_code: int, **body: Any) -> Answer:
    return {"statusCode": status_code, "body": body}


def _family_map(audience: PublicAudience) -> dict[str, str]:
    return families({entry.id: {"family": entry.family} for entry in audience.settings.lists})


def update_preferences(audience: PublicAudience, keys: AudienceKeys, event: Mapping[str, Any]) -> Answer:
    """Save a reader's choice. ``event`` is ``update_preferences`` as the route sends it: ``token``, ``lists`` and, for a family the reader is joining, the ``consent``
    wording the page showed with ``formId``, ``page``, ``origin``, ``ip`` and ``userAgent`` as evidence (the subscribe form's fields)."""
    token = event.get("token")
    state = audience.preferences_state(token)
    if state["statusCode"] != 200:
        return state
    requested = event.get("lists")
    known = {entry.id for entry in audience.settings.lists}
    chosen = [list_id for list_id in dict.fromkeys(requested if isinstance(requested, list) else []) if list_id in known]
    held = {view["id"] for view in state["body"]["lists"] if view["subscribed"]}
    family_of = _family_map(audience)
    consented = {family_of[list_id] for list_id in held}
    joining = [list_id for list_id in chosen if list_id not in held and family_of[list_id] not in consented]
    claims = tokens.verify(keys.token, token, "manage", time.time())
    # A bounce or a complaint suppresses the address, and Caducus ignores a signup for it, so no confirmation could reach them: their own opt-in on their
    # manage page is what lifts it (their consent was never withdrawn through us). Everything else that joins a family asks.
    if not joining or audience.suppression(claims.key) in LIFTED_BY_OPT_IN:
        return audience.update_preferences(token, chosen)
    if conflicts([list_id for list_id in chosen if list_id not in held], family_of):
        return _answer(400, status="one_cadence_per_family")
    address = audience.address_of(claims.key)
    if address is None:
        return _answer(400, status="invalid")
    asked = audience.subscribe(
        SubscribeRequest(
            address=address, lists=joining, consent=event.get("consent"), form_id=event.get("formId", ""), page=event.get("page", ""),
            origin=event.get("origin", ""), ip=event.get("ip", ""), user_agent=event.get("userAgent", ""),
        )
    )
    if asked["statusCode"] != 202:
        return asked
    kept = [list_id for list_id in chosen if list_id not in joining]
    saved = sorted(held)
    if kept:
        answer = audience.update_preferences(token, kept)
        if answer["statusCode"] != 200:
            return answer
        saved = kept
    return _answer(202, status="check_email", lists=saved, confirming=joining)


def consent_by_family(audience: PublicAudience, address: str) -> dict[str, list[dict[str, Any]]]:
    """The consent evidence one address has stored, grouped by family, oldest first: each record's ``wording``, ``confirmedAt``, ``formId``, ``source`` and the ``lists`` it covered.

    An admin read (Caducus's export); no public route sends it. A record that covers lists of two families appears under each."""
    family_of = _family_map(audience)
    exported = audience.export(address)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in sorted(exported.get("body", {}).get("consent", []), key=lambda row: row.get("confirmedAt", "")):
        for family in dict.fromkeys(family_of.get(list_id, list_id) for list_id in record.get("lists", [])):
            grouped.setdefault(family, []).append(record)
    return grouped
