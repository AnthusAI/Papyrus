"""Where each translation of a Story stands, in the six words of the Translation lifecycle (PPY-21b8c5; src/papyrus_content/lifecycles/translation.yaml).

The run's own record, the ``LocalizationRequest`` of one language group and language, keeps a finer state (``desired_state.STATES``). This module names what that state means for
the lifecycle: every published Story has, for each language the site publishes, **exactly one** of

* ``wanted``       no run has started for the source as it is now, or the last run failed or stopped and the dispatcher will start it again;
* ``translating``  a run has started, or is waiting for its turn;
* ``held``         the run needs a person (a quotation, a faithfulness error, a predicted cost above the ceiling) and raised its flag; a machine never runs it again;
* ``ready``        the translation is saved for this source and nobody has published it;
* ``published``    the translation is live for this source;
* ``stale``        the request names an older source than the one the Story has now, so the translation no longer matches it.

Nothing here lists a table: one point read for each language.
"""
from __future__ import annotations

from typing import Any, Iterable

from . import desired_state

WANTED, TRANSLATING, HELD, READY, PUBLISHED, STALE = "wanted", "translating", "held", "ready", "published", "stale"
STATES = (WANTED, TRANSLATING, HELD, READY, PUBLISHED, STALE)

#: The request's own state, as the lifecycle names it. ``waiting`` is a run that stopped before spending past its cost ceiling: a person decides, so it is held.
OF_REQUEST = {
    "wanted": WANTED, "failed": WANTED, "stopped": WANTED,
    "started": TRANSLATING,
    "held": HELD, "waiting": HELD,
    "saved": READY, "unchanged": READY,
    "published": PUBLISHED,
}
assert set(OF_REQUEST) == set(desired_state.STATES), "every state a request can have has a place in the lifecycle"


def state_of(request: dict[str, Any] | None, source: dict[str, Any]) -> dict[str, str | None]:
    """``{"state", "reason"}`` for one language: ``request`` is its LocalizationRequest (None when none was ever written), ``source`` the Story's current published primary version."""
    if request is None:
        return {"state": WANTED, "reason": "no translation has been requested for this language yet"}
    if int(request.get("sourceVersionNumber") or 0) < int(source.get("versionNumber") or 0):
        return {"state": STALE, "reason": f"the translation was made for source version {request.get('sourceVersionNumber')}; the Story is at version {source.get('versionNumber')}"}
    state = OF_REQUEST.get(str(request.get("state")))
    if state is None:
        raise ValueError(f"The translation request {request.get('id')} is in the state {request.get('state')!r}, which the lifecycle does not know.")
    return {"state": state, "reason": request.get("reason") or None}


def story_states(client: Any, source: dict[str, Any], languages: Iterable[str]) -> dict[str, dict[str, str | None]]:
    """Exactly one state for each language of one Story: a point read of each language's request."""
    return {language: state_of(desired_state.current(client, source["lineageId"], language), source) for language in languages}
