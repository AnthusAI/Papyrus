"""A site's idea rules (PPY-10a5e5): the settings that decide what an idea must show before it is filed.

They are the ``ideaRules`` object of a router publication's ``monitorStories`` setting (``monitoring_stories.validate_monitor_stories``), so a site changes them
in its own configuration and not in code. Every field has the standard (news) value as its default, so a site that sets nothing behaves exactly as before.

* ``minimumReferences`` (default 2): how many accepted References a context-pack idea must cite, and how many one sentence must cite together.
* ``requireJointSentence`` (default true): at least one body sentence of a context-pack idea cites ``minimumReferences`` References together.
* ``passingVerdicts`` (default ``["adds"]``): the point check's verdicts that let an idea through. A site may also accept ``"restates"`` or ``"unsupported"``.
* ``checkRepeats`` / ``checkProcessTalk`` (default true): whether a repeated point or talk about how the story came to be fails the point check.
* ``mode`` (default ``"evidence"``): ``"premise-led"`` starts from one real Reference and states an invented premise separately (``premise``), which is kept
  apart from the cited sentences, shown as invented, and is not judged against the source.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import point_check

MODES = ("evidence", "premise-led")
VERDICTS = (point_check.ADDS, point_check.RESTATES, point_check.UNSUPPORTED)
KEYS = ("minimumReferences", "requireJointSentence", "passingVerdicts", "checkRepeats", "checkProcessTalk", "mode")


@dataclass(frozen=True)
class IdeaRules:
    minimum_references: int = 2
    require_joint_sentence: bool = True
    passing_verdicts: tuple[str, ...] = (point_check.ADDS,)
    check_repeats: bool = True
    check_process_talk: bool = True
    mode: str = "evidence"

    @property
    def premise_led(self) -> bool:
        return self.mode == "premise-led"

    def as_setting(self) -> dict[str, Any]:
        return {"minimumReferences": self.minimum_references, "requireJointSentence": self.require_joint_sentence, "passingVerdicts": list(self.passing_verdicts),
                "checkRepeats": self.check_repeats, "checkProcessTalk": self.check_process_talk, "mode": self.mode}


DEFAULT = IdeaRules()


def validate_idea_rules(publication_id: str, raw: Any) -> dict[str, Any]:
    """The normalized ``monitorStories.ideaRules`` setting (a dict with every key). Absent means the defaults."""
    where = f"router publication {publication_id} monitorStories.ideaRules"
    if raw is None:
        return DEFAULT.as_setting()
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be an object")
    unknown = sorted(set(raw) - set(KEYS))
    if unknown:
        raise ValueError(f"{where} has unknown keys: {', '.join(unknown)}")
    setting = {**DEFAULT.as_setting(), **raw}
    minimum = setting["minimumReferences"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValueError(f"{where}.minimumReferences must be a whole number of at least 1")
    for key in ("requireJointSentence", "checkRepeats", "checkProcessTalk"):
        if not isinstance(setting[key], bool):
            raise ValueError(f"{where}.{key} must be true or false")
    verdicts = setting["passingVerdicts"]
    if not isinstance(verdicts, list) or not verdicts or len(set(verdicts)) != len(verdicts) or any(v not in VERDICTS for v in verdicts):
        raise ValueError(f"{where}.passingVerdicts must be a non-empty list of distinct verdicts from {', '.join(VERDICTS)}")
    if setting["mode"] not in MODES:
        raise ValueError(f"{where}.mode must be one of {', '.join(MODES)}")
    return setting


def rules_of(setting: dict[str, Any] | None) -> IdeaRules:
    """The rules a normalized setting describes (``None`` is the defaults)."""
    if not setting:
        return DEFAULT
    return IdeaRules(setting["minimumReferences"], setting["requireJointSentence"], tuple(setting["passingVerdicts"]), setting["checkRepeats"], setting["checkProcessTalk"], setting["mode"])
