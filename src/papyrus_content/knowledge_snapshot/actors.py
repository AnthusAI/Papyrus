"""Who accepted, rejected or edited something: an AI agent for now, people later.

An actor is ``{"actor": "ai" | "human", "name": str | None, "on": "YYYY-MM-DD"}``. The schema has no field for it, so
it rides in strings the rows already have: a node's ``changeReason`` holds one JSON object behind ``REVIEW_MARKER``
(``acceptedBy``, ``rejectedBy``, ``descriptionEditedBy``), and a topic cluster's proposal ``summary`` object holds
``acceptedBy``. Nothing here reads a clock: callers pass the day.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .keys import contains_email

ACTOR_AI = "ai"
ACTOR_HUMAN = "human"
ACTORS = (ACTOR_AI, ACTOR_HUMAN)
REVIEW_MARKER = "papyrus-knowledge-review@1:"
MAXIMUM_NAME_LENGTH = 80


class ActorError(ValueError):
    pass


@dataclass(frozen=True)
class Actor:
    actor: str
    name: str | None
    on: str

    def to_dict(self) -> dict:
        return {"actor": self.actor, "name": self.name, "on": self.on}

    @property
    def is_human(self) -> bool:
        return self.actor == ACTOR_HUMAN


def clean_name(value: Any) -> str | None:
    if value is None:
        return None
    name = " ".join(str(value).split())
    if not name:
        return None
    if contains_email(name):
        raise ActorError("An actor name must not hold an email address.")
    if len(name) > MAXIMUM_NAME_LENGTH:
        raise ActorError(f"An actor name is at most {MAXIMUM_NAME_LENGTH} characters.")
    return name


def make_actor(actor: Any, name: Any, today: str) -> Actor:
    kind = str(actor or "").strip().lower()
    if kind not in ACTORS:
        raise ActorError("--actor is required: ai or human.")
    return Actor(actor=kind, name=clean_name(name), on=today)


def actor_from_dict(value: Any) -> Actor | None:
    """The actor a stored object describes, or ``None`` when it is absent or not in the shape."""
    if not isinstance(value, Mapping) or value.get("actor") not in ACTORS or not isinstance(value.get("on"), str):
        return None
    name = value.get("name")
    return Actor(actor=value["actor"], name=name if isinstance(name, str) and name.strip() else None, on=value["on"])


@dataclass(frozen=True)
class ReviewMarks:
    accepted_by: Actor | None = None
    rejected_by: Actor | None = None
    description_edited_by: Actor | None = None

    def encode(self) -> str:
        body = {
            "acceptedBy": self.accepted_by.to_dict() if self.accepted_by else None,
            "descriptionEditedBy": self.description_edited_by.to_dict() if self.description_edited_by else None,
            "rejectedBy": self.rejected_by.to_dict() if self.rejected_by else None,
        }
        return REVIEW_MARKER + json.dumps(body, sort_keys=True, separators=(",", ":"))

    def replace(self, **changes: Actor | None) -> "ReviewMarks":
        return ReviewMarks(**{**self.__dict__, **changes})


def decode_review(change_reason: Any) -> ReviewMarks:
    if not isinstance(change_reason, str) or not change_reason.startswith(REVIEW_MARKER):
        return ReviewMarks()
    try:
        body = json.loads(change_reason[len(REVIEW_MARKER) :])
    except ValueError:
        return ReviewMarks()
    if not isinstance(body, dict):
        return ReviewMarks()
    return ReviewMarks(
        accepted_by=actor_from_dict(body.get("acceptedBy")),
        rejected_by=actor_from_dict(body.get("rejectedBy")),
        description_edited_by=actor_from_dict(body.get("descriptionEditedBy")),
    )


def actor_from_options(options: Mapping[str, Any], today: str, *, command: str) -> Actor:
    """``--actor ai|human`` (required, no default) and ``--actor-name`` of a review command."""
    raw = options.get("actor")
    if not isinstance(raw, str) or not raw.strip():
        raise ActorError(f"{command} requires --actor ai|human (an AI agent, or a person); there is no default.")
    return make_actor(raw, options.get("actor-name"), today)
