"""What the list settings document may hold, and the one validator every write goes through.

::

    {"schemaVersion": 1,
     "lists": {"weekly": {"name": "Weekly", "cadence": "weekly", "sendAt": {"day": "monday", "time": "04:00"}, "timeZone": "America/New_York",
                          "rule": {"sections": [], "types": [], "tags": [], "minStars": 3},
                          "requireReviewedSource": true, "workingDocument": "story", "template": "roundup", "agent": "announce", "rung": "prepare"}}}

* ``cadence`` is ``each`` (a message for every new item), ``daily`` or ``weekly``. A periodic list names ``sendAt`` and ``timeZone``; an every-item list names neither.
* ``rule.minStars`` is three, four or five. Nothing under three stars goes out on any list (the site's quality floor), so a lower number is refused, and so is
  a list that names none: the floor is written down, not assumed.
* ``workingDocument`` is ``story`` (an issue Story that is published to the archive; a weekly list only) or ``delivery`` (no archive page).
* ``emptyPeriod`` is for a periodic list: ``nothing`` (the default: a period with no qualifying item and nothing a person wrote sends nothing and says so) or ``draft_only``
  (the period's draft is made for a person to fill, and goes only if a person adds words and the rung allows). An every-item list has no period, so it names none.
  No placeholder issue is ever sent.
* ``rung`` is optional. It can only narrow what the site's agent policy allows (``announce.effective_rung``).
* ``family`` (optional) names the cadence family: lists that carry the same items at different cadences (every item, daily summary) share one, and a reader holds at most
  one list of a family at a time (slice N2, ``family.py``). A list that names none is its own family, which is how a curated weekly newsletter stays unaffected by a
  reader's daily or every-item choice. Two lists of one family cannot share a cadence: a reader would have nothing to choose between.
* ``agent`` is the automation whose wake runs the list. It is checked against the registered agents when the schedule is reconciled, not here.
"""
from __future__ import annotations

import copy
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from papyrus_content.agent_rungs import RUNGS

SCHEMA_VERSION = 1
CADENCES = ("each", "daily", "weekly")
PERIODIC = ("daily", "weekly")
WORKING_DOCUMENTS = ("story", "delivery")
EMPTY_PERIODS = ("nothing", "draft_only")
WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
#: The site's quality floor: nothing below three stars is public or announced (the 3-star decision, PPY-0e8d66).
QUALITY_FLOOR_STARS = 3
MAX_STARS = 5

LIST_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
AGENT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
TEMPLATE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
LIST_FIELDS = {"name", "cadence", "sendAt", "timeZone", "rule", "requireReviewedSource", "workingDocument", "template", "agent", "rung", "emptyPeriod", "family"}
RULE_FIELDS = {"sections", "types", "tags", "minStars"}

EMPTY_DOCUMENT: dict[str, Any] = {"schemaVersion": SCHEMA_VERSION, "lists": {}}


class ListSettingsError(ValueError):
    """A refusal. ``code`` is ``invalid_input``, ``below_quality_floor``, ``not_authorized`` (not an admin), ``blocked`` (an agent) or ``stale_version``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _invalid(message: str, code: str = "invalid_input") -> ListSettingsError:
    return ListSettingsError(code, message)


def _names(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise _invalid(f"{where} must be a list of names.")
    return [item.strip() for item in value]


def _rule(rule: Any, where: str) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise _invalid(f"{where} must be an object with the rule: sections, types, tags and minStars.")
    extra = sorted(set(rule) - RULE_FIELDS)
    if extra:
        raise _invalid(f"{where} has unknown field(s): {', '.join(extra)}.")
    stars = rule.get("minStars")
    if isinstance(stars, bool) or not isinstance(stars, int):
        raise _invalid(f"{where}.minStars is the lowest star rating the list carries: a whole number from {QUALITY_FLOOR_STARS} to {MAX_STARS}.")
    if stars < QUALITY_FLOOR_STARS:
        raise _invalid(f"A list cannot carry anything under {QUALITY_FLOOR_STARS} stars: {where}.minStars is {stars}.", "below_quality_floor")
    if stars > MAX_STARS:
        raise _invalid(f"Star ratings stop at {MAX_STARS}: {where}.minStars is {stars}.")
    return {"sections": _names(rule.get("sections"), f"{where}.sections"), "types": _names(rule.get("types"), f"{where}.types"),
            "tags": _names(rule.get("tags"), f"{where}.tags"), "minStars": stars}


def _send_at(value: Any, cadence: str, where: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - {"day", "time"}:
        raise _invalid(f"{where} must be an object with the local time ('time', as 06:00)" + (" and the weekday ('day')." if cadence == "weekly" else "."))
    time = value.get("time")
    if not isinstance(time, str) or not CLOCK.match(time):
        raise _invalid(f"{where}.time must be a local time of day such as 06:00 (24 hours).")
    if cadence == "weekly":
        day = value.get("day")
        if day not in WEEKDAYS:
            raise _invalid(f"{where}.day must be a weekday name: {', '.join(WEEKDAYS)}.")
        return {"day": day, "time": time}
    if "day" in value:
        raise _invalid(f"{where}.day is for a weekly list; a daily list sends every day.")
    return {"time": time}


def validate_list(list_id: str, entry: Any) -> dict[str, Any]:
    """One list's settings as they are stored, or a refusal in plain words."""
    if not isinstance(list_id, str) or not LIST_ID.match(list_id):
        raise _invalid(f"A list's id is lowercase letters, digits and hyphens, starting with a letter (at most 40 characters): {list_id!r}.")
    where = f"lists.{list_id}"
    if not isinstance(entry, dict):
        raise _invalid(f"{where} must be an object.")
    extra = sorted(set(entry) - LIST_FIELDS)
    if extra:
        raise _invalid(f"{where} has unknown field(s): {', '.join(extra)}.")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _invalid(f"{where}.name must be a non-empty string.")
    cadence = entry.get("cadence")
    if cadence not in CADENCES:
        raise _invalid(f"{where}.cadence must be one of: {', '.join(CADENCES)}.")
    stored: dict[str, Any] = {"name": name.strip(), "cadence": cadence, "rule": _rule(entry.get("rule"), f"{where}.rule")}
    if cadence in PERIODIC:
        stored["sendAt"] = _send_at(entry.get("sendAt"), cadence, f"{where}.sendAt")
        zone = entry.get("timeZone")
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError, TypeError, OSError):
            raise _invalid(f"{where}.timeZone must be a time zone name such as America/New_York.") from None
        stored["timeZone"] = zone
        empty = entry.get("emptyPeriod", "nothing")
        if empty not in EMPTY_PERIODS:
            raise _invalid(f"{where}.emptyPeriod must be one of: {', '.join(EMPTY_PERIODS)}.")
        stored["emptyPeriod"] = empty
    elif "emptyPeriod" in entry:
        raise _invalid(f"{where} is an every-item list, which has no period, so it names no emptyPeriod.")
    elif "sendAt" in entry or "timeZone" in entry:
        raise _invalid(f"{where} is an every-item list, so it names no sendAt or timeZone: it is woken by a page going live or a rating changing, not by a clock.")
    review = entry.get("requireReviewedSource", False)
    if not isinstance(review, bool):
        raise _invalid(f"{where}.requireReviewedSource must be true or false.")
    stored["requireReviewedSource"] = review
    working = entry.get("workingDocument", "delivery")
    if working not in WORKING_DOCUMENTS:
        raise _invalid(f"{where}.workingDocument must be story or delivery.")
    if working == "story" and cadence != "weekly":
        raise _invalid(f"{where}.workingDocument is story only for a weekly list: an issue Story is published to the archive, and only a weekly issue has an archive page.")
    stored["workingDocument"] = working
    template = entry.get("template")
    if not isinstance(template, str) or not TEMPLATE.match(template):
        raise _invalid(f"{where}.template names the template the Delivery is drafted from (lowercase letters, digits, hyphens and underscores).")
    stored["template"] = template
    agent = entry.get("agent")
    if not isinstance(agent, str) or not AGENT_ID.match(agent):
        raise _invalid(f"{where}.agent names the automation whose wake runs this list.")
    stored["agent"] = agent
    if entry.get("family") is not None:
        family = entry["family"]
        if not isinstance(family, str) or not LIST_ID.match(family):
            raise _invalid(f"{where}.family names the cadence family the list belongs to (lowercase letters, digits and hyphens, starting with a letter).")
        stored["family"] = family
    if entry.get("rung") is not None:
        if entry["rung"] not in RUNGS:
            raise _invalid(f"{where}.rung must be one of: {', '.join(RUNGS)}.")
        stored["rung"] = entry["rung"]
    return stored


def validate_document(document: Any) -> dict[str, Any]:
    """The whole document checked, or a refusal that names the list."""
    if not isinstance(document, dict) or set(document) - {"schemaVersion", "lists"}:
        raise _invalid("The list settings are an object with schemaVersion and lists.")
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise _invalid(f"schemaVersion must be {SCHEMA_VERSION}.")
    lists = document.get("lists")
    if not isinstance(lists, dict):
        raise _invalid("lists must be an object keyed by list id.")
    checked = {list_id: validate_list(list_id, entry) for list_id, entry in lists.items()}
    seen: dict[tuple[str, str], str] = {}
    for list_id, entry in sorted(checked.items()):
        slot = (entry.get("family", list_id), entry["cadence"])
        if slot in seen:
            raise _invalid(f"lists.{list_id} and lists.{seen[slot]} are both {entry['cadence']} lists of the family {slot[0]}: a family has one list for each cadence.")
        seen[slot] = list_id
    return {"schemaVersion": SCHEMA_VERSION, "lists": checked}


def fresh() -> dict[str, Any]:
    return copy.deepcopy(EMPTY_DOCUMENT)
