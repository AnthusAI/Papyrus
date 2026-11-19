"""Why was this Story not announced? A question, not a row (design section 13.3, change M).

``papyrus announcements explain --story X`` reads the rules that decide whether a Story is announced and says which one applies to each channel. It writes nothing: no row is
made for a thing that did not happen. The rules are the ones the announce path runs, in the order it runs them, and each answer names its rule by a short code:

1. ``announced``: the Story already has a live Delivery on the channel (the answer says its state and which Announcement).
2. The channel's own rules (``CHANNEL_RULES``): for X, ``eligibility.verdict`` over the site's announcement settings (off, not a Story, retired, not published, type or
   section not announced, below the bar).
3. The floors under every policy (``intake.floor_refusal``): nothing under three stars, and a five only from a person.
4. The source rule (``requireReviewedSource``): a person must have reviewed the Story on its current version.
5. The review policy of the channel (``review_policy.choose``): a rung below ``prepare`` prepares no Delivery.
6. ``would_announce``: nothing stops it; it is announced when the announce agent next runs.

A channel with its own rules (an email list's section rule) adds its entry to ``CHANNEL_RULES`` when it is built; the explanation then lists it with the others.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from papyrus_content.agent_policy.resolve import PolicyState

from .eligibility import StoryFacts, verdict
from .intake import NOT_REVIEWED, PROVISIONAL_NOTE, ReviewStamps, floor_refusal
from .lines import STATE_SHOWN
from .review_policy import choose

STORY_PUBLISHED = "story_published"
X = "x"

ANNOUNCED, WOULD_ANNOUNCE = "announced", "would_announce"

_VERDICT_WORDS = {
    "off": "Announcements are off for this publication, so nothing is announced.",
    "not_a_story": "It is not a Story (a Reference is never announced).",
    "retired": "The Story was retired.",
    "not_published": "The Story is not published yet; only a published Story is announced.",
    "type_not_announced": "Its type is not one of the types this publication announces.",
    "section_not_announced": "Its section is not one of the sections this publication announces.",
    "below_bar": "Its star rating is below the bar this publication set for announcements.",
}


def _x_rule(story: StoryFacts, settings: Mapping[str, Any]) -> tuple[str, str] | None:
    """The channel's own rules for X: the code and the words of the first one that keeps the Story out, or None."""
    decision = verdict(story, settings)
    if decision.eligible:
        return None
    words = _VERDICT_WORDS.get(decision.reason, decision.reason)
    if decision.reason == "below_bar":
        words = f"It has {story.stars or 'no'} {'star' if story.stars == 1 else 'stars'}, and the bar for announcements is {settings.get('minStars')} stars."
    return decision.reason, words


#: Each channel's own rules, by channel: (story, settings) to the code and words of the rule that keeps the Story out, or None.
CHANNEL_RULES: dict[str, Callable[[StoryFacts, Mapping[str, Any]], tuple[str, str] | None]] = {X: _x_rule}


def explain(story: StoryFacts, settings: Mapping[str, Any], policy: PolicyState, stamps: ReviewStamps, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The answer for each channel. ``entries`` are the Story's Announcements as ``lines.story_entries`` reads them."""
    live: dict[str, dict[str, Any]] = {}
    for entry in entries:
        for line in entry["deliveries"]:
            live.setdefault(line["channel"], {**line, "announcement": entry["id"]})
    channels = []
    for channel in sorted({*CHANNEL_RULES, *live}):
        channels.append({"channel": channel, **_answer(channel, story, settings, policy, stamps, live.get(channel))})
    return {"story": story.lineage_id, "title": story.title, "stars": story.stars, "channels": channels}


def _answer(channel: str, story: StoryFacts, settings: Mapping[str, Any], policy: PolicyState, stamps: ReviewStamps, delivery: Mapping[str, Any] | None) -> dict[str, Any]:
    if delivery is not None:
        _, state = STATE_SHOWN.get(delivery["state"], ("", delivery["state"]))
        return {"announced": True, "rule": ANNOUNCED, "words": f"Announced on {channel}: {state.lower()} (Announcement {delivery['announcement']}).", "delivery": delivery["id"]}
    rule = CHANNEL_RULES.get(channel)
    stopped = rule(story, settings) if rule else None
    if stopped:
        return {"announced": False, "rule": stopped[0], "words": stopped[1]}
    floor = floor_refusal(story)
    if floor:
        return {"announced": False, "rule": floor.code, "words": floor.reason}
    if settings.get("requireReviewedSource") and not stamps.reviewed(story.lineage_id, story.version_number):
        return {"announced": False, "rule": NOT_REVIEWED,
                "words": f"{story.lineage_id} version {story.version_number} has not been reviewed by a person, and this publication announces only reviewed Stories. {PROVISIONAL_NOTE}"}
    choice = choose(policy, channel=channel, kind=STORY_PUBLISHED)
    if not choice.prepares:
        return {"announced": False, "rule": "no_delivery", "words": str(choice.reason)}
    return {"announced": False, "rule": WOULD_ANNOUNCE, "words": f"Nothing stops it: it is announced on {channel} when the announce agent next runs ({choice.approval} review)."}
