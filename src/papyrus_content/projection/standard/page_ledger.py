"""The record of what one page has already placed, so no component repeats another's choice.

One :class:`PageLedger` is created each time a page render starts and is shared by every ``::include`` on that page, in document
order. A component draws its candidates in its own order and keeps those it can :meth:`claim`; the first component to claim a key
wins, and a later one moves on to its next candidate. Keys are namespaced (``reference:<key>``) so Stories and threads can share the
mechanism later. A ledger lives for one page: nothing is de-duplicated across pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageLedger:
    seen: set[str] = field(default_factory=set)
    home_page_used: bool = False

    def claim(self, key: str) -> bool:
        """Record ``key`` and return True when it was free; return False when an earlier component on the page already holds it."""
        if key in self.seen:
            return False
        self.seen.add(key)
        return True
