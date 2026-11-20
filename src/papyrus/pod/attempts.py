"""The attempt lines of a Delivery note.

An attempt is one line a person writes after trying to send: ``1 2026-11-16T14:01Z sent by ryan``, that is the attempt's number, the time in UTC, how it
ended (``sent`` or ``refused``) and, after that, either ``by <name>`` or the provider's code. The log only grows: ``papyrus pod check`` fails when an earlier
line differs from the last commit. A load turns each line into the entry of the same Delivery record's ``attempts`` field.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .profile import ATTEMPT_OUTCOMES

LINE = re.compile(r"^(?P<number>[0-9]+) (?P<at>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2})?Z) (?P<outcome>[a-z]+)(?: (?P<rest>\S.*))?$")


@dataclass(frozen=True)
class Attempt:
    number: int
    at: str                 # UTC, to the second: 2026-11-16T14:01:00Z
    outcome: str
    by: str | None = None
    code: str | None = None


def parse(line: object, position: int) -> tuple[Attempt | None, str | None]:
    """The attempt a line says, or the reason it is not one. ``position`` is the line's place in the list, counting from 1: attempt numbers run 1, 2, 3."""
    if not isinstance(line, str) or "\n" in line or not (match := LINE.match(line)):
        return None, "is not an attempt line; write `1 2026-11-16T14:01Z sent by ryan`: its number, the time in UTC, sent or refused, then `by <name>` or the provider's code"
    if int(match["number"]) != position:
        return None, f"is numbered {match['number']}, and the attempt in place {position} is numbered {position}"
    if match["outcome"] not in ATTEMPT_OUTCOMES:
        return None, f"ended {match['outcome']!r}; an attempt ended {' or '.join(ATTEMPT_OUTCOMES)}"
    at = match["at"] if match["at"].count(":") == 2 else match["at"][:-1] + ":00Z"
    try:
        import datetime
        datetime.datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None, f"has the time {match['at']}, which is not a real time"
    rest = match["rest"]
    if rest and rest.startswith("by "):
        return Attempt(position, at, match["outcome"], by=rest[3:].strip() or None), None
    return Attempt(position, at, match["outcome"], code=rest), None
