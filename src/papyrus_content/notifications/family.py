"""The public audience with cadence families (slice N2, PPY-a19b9d; the rule is in ``list_cadence/family.py``).

Caducus's ``PublicAudience`` writes a reader's lists in one place, ``_set_lists``, which subscribing (on confirmation), saving preferences, importing and every
unsubscribe go through. This audience keeps that one place and adds the family rule to it, so no path can leave a reader on two lists of one family:

* Asking for two new lists of one family at once is refused (``one_cadence_per_family``): the reader has to choose.
* Choosing a list of a family the reader already holds another list of moves them: the old membership is ended, the new one begins now.
* Each membership row records ``since``, kept while the reader stays on the list and begun again only when they join it.
* ``subscriber_page(..., as_of=...)`` pages the members who had joined by ``as_of``: a periodic Delivery passes its period's start, an every-item Delivery none
  (the members at the moment it is sent).

The one-click unsubscribe is Caducus's and needs no change: it leaves only the list the link names, never rejoins one, and a link from a list the reader has moved
off leaves the list they are on alone.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from caducus.notify.audience import PublicAudience, SubscribeRequest
from caducus.notify.audience.service import Answer, answer, rcpt
from caducus.notify.events import parse_timestamp
from caducus.notify.store import Item, Write

from papyrus_content.list_cadence.family import conflicts

REFUSAL = "one_cadence_per_family"


class FamilyAudience(PublicAudience):
    """``families`` is ``{list id: family}``; a list not in it is its own family."""

    def __init__(self, *args: Any, families: Mapping[str, str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._families = dict(families)

    def family_of(self, list_id: str) -> str:
        return self._families.get(list_id, list_id)

    # -- reading ---------------------------------------------------------------------------------------------------

    def since(self, key: str, list_id: str) -> Optional[datetime]:
        """When the reader joined the list; None when they are not on it. A membership written before ``since`` was recorded began at its row's ``at``."""
        row = self._store.get(rcpt(key), "SUB#" + list_id)
        if row is None or row["status"] != "subscribed":
            return None
        return parse_timestamp(row.get("since") or row["at"])

    def subscriber_page(self, list_id: str, cursor: Optional[str], as_of: Optional[datetime] = None) -> Tuple[List[str], Optional[str]]:
        keys, following = super().subscriber_page(list_id, cursor)
        if as_of is None:
            return keys, following
        return [key for key in keys if (joined := self.since(key, list_id)) is not None and joined <= as_of], following

    # -- the rule, where the lists are written -----------------------------------------------------------------

    def _added_together(self, key: Optional[str], wanted: Sequence[str]) -> List[str]:
        held = set(self.subscribed_lists(key)) if key else set()
        return conflicts([list_id for list_id in wanted if list_id not in held], self._families)

    def subscribe(self, request: SubscribeRequest) -> Answer:
        if conflicts(self._requested(request.lists), self._families):
            return answer(400, status=REFUSAL)
        return super().subscribe(request)

    def update_preferences(self, token: Any, lists: Any) -> Answer:
        claims, profile = self._manage(token)
        if profile is not None:
            chosen = [list_id for list_id in (lists if isinstance(lists, list) else []) if self._settings.list_named(list_id)]
            if self._added_together(claims.key, chosen):  # type: ignore[union-attr]
                return answer(400, status=REFUSAL)
        return super().update_preferences(token, lists)

    def import_subscriber(self, address: str, lists: Sequence[str], evidence: Mapping[str, Any], source: str, suppressed: Optional[str] = None) -> str:
        if conflicts([list_id for list_id in lists if self._settings.list_named(list_id)], self._families):
            return "refused"
        return super().import_subscriber(address, lists, evidence, source, suppressed)

    def _set_lists(self, key: str, chosen: Iterable[str], suppressed_manually: bool) -> List[Write]:
        chosen = set(chosen)
        held = set(self.subscribed_lists(key))
        for family in conflicts(sorted(chosen), self._families):
            members = {list_id for list_id in chosen if self.family_of(list_id) == family}
            joining = members - held
            if len(joining) != 1:
                raise ValueError(f"{key} would hold {sorted(members)} of the family {family}, and {sorted(joining)} are new: a reader joins one list of a family at a time.")
            chosen -= members & held
        return super()._set_lists(key, chosen, suppressed_manually)

    def _subscription_row(self, key: str, list_id: str, subscribed: bool, indexed: bool) -> Item:
        row = super()._subscription_row(key, list_id, subscribed, indexed)
        if subscribed:
            before = self._store.get(rcpt(key), "SUB#" + list_id)
            staying = before is not None and before["status"] == "subscribed"
            row["since"] = (before.get("since") or before["at"]) if staying else row["at"]  # type: ignore[union-attr]
        return row
