"""Drafting the post and checking it, with no one asked to approve it (Ryan, 2026-11-12).

The model (the policy default, GPT-6 Luna) gets the Story's title, dek and summary and nothing else, under the site's writing guidelines and announcement rules.
The draft is then checked automatically, and a draft that fails any check is not posted:

* ``length``: the whole post (draft, blank line, tagged link) weighs at most what X allows (``post.py``);
* ``markup``: no mention, hashtag or cashtag the Story does not already contain (X would make them live), and no link of its own (the link is added);
* ``hashtags``: the draft may add hashtags, but only ones from the list of the Story's own tagged concepts (``hashtags.py``), at most ``MAX_HASHTAGS``, and none when no concept fits;
* ``rules``: the editorial rule lane (``papyrus editorial check``), when the site has it wired;
* ``facts``: the layered fact check (``fact_check.check_claims``) with the Story's own text as the only source. Every sentence of the draft must be verified.

Nothing here trims, rewrites or retries a failed draft: the failure and its reason are recorded, and the editors are told.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from papyrus_content import fact_check
from papyrus_content.model_defaults import DEFAULT_LLM_MODEL

from .eligibility import StoryFacts
from .post import LINK_WEIGHT, MAXIMUM_WEIGHT, SEPARATOR, compose, live_markup, too_long_by, weighted_length

Llm = Callable[[str, str, dict], dict]
#: ``text -> [plain-words problem]``: the editorial rule lane over the draft. None when the site has not wired the lane.
RuleLane = Callable[[str], list[str]]

#: What the draft itself may weigh: X's limit less the link and the blank line before it. Derived from X's rule, not chosen.
DRAFT_WEIGHT = MAXIMUM_WEIGHT - LINK_WEIGHT - len(SEPARATOR)

SYSTEM = (
    "You write one short post for a publication's X account announcing a Story that was just published. Use only what the title, dek and summary below say: add no fact, "
    "number, name, quotation or claim that is not in them, and make no claim of firstness, proof or certainty they do not make. Do not include a link, a mention, a hashtag "
    "or a cashtag in your text; the link is added after your text. The post must weigh at most {limit} on X (most letters count 1, emoji and many non-Latin characters count 2). "
    "Write it in the publication's voice, following the guidelines.\n\n{guidelines}"
)
HASHTAGS_WITH_CHOICES = (
    "\n\nHashtags matter (Ryan, 2026-11-20: a good hashtag is worth more than a few words of the text). The Story's own concepts are offered as hashtagChoices, each with its cost. "
    "Put at most {maximum} of them in `hashtags`, copied exactly: the ones a reader would search for to find this Story. Return an empty list only when none is relevant. "
    "The text limit above already leaves room for a hashtag, so keep `text` within it. Never write a hashtag in `text`."
)
HASHTAGS_NONE = "\n\nThe Story offers no hashtags: return an empty `hashtags` list."
#: How many hashtags a post may carry. Derived from practice on X (more than two reads as spam), not from the API.
MAX_HASHTAGS = 2
#: How far under the limit the draft is told to stay when hashtags are offered: the model cannot count X's weight exactly, and a post over the limit is blocked.
COUNTING_MARGIN = 20
SCHEMA = {
    "type": "json_schema", "name": "announcement_draft", "strict": True,
    "schema": {"type": "object", "additionalProperties": False, "required": ["hashtags", "text"],
               "properties": {"hashtags": {"type": "array", "items": {"type": "string"}}, "text": {"type": "string"}}},
}


class DraftRefused(RuntimeError):
    """A draft cannot even be tried (for example the publication has no writing guidelines). Nothing was drafted."""


@dataclass
class Draft:
    text: str   # the words as posted: the drafted text, then the chosen hashtags
    link: str
    model: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)

    @property
    def post(self) -> str:
        return compose(self.text, self.link)

    @property
    def weight(self) -> int:
        return weighted_length(self.post)

    @property
    def passed(self) -> bool:
        return all(check["passed"] for check in self.checks)

    @property
    def failures(self) -> list[str]:
        return [message for check in self.checks if not check["passed"] for message in check["problems"]]


def story_source(story: StoryFacts) -> str:
    """The Story's own text: the only source the fact check has."""
    return "\n\n".join(part for part in (story.title, story.dek, story.summary, story.body) if part)


def prompt(story: StoryFacts, guidelines: str, learned: str = "", hashtags: list[str] | None = None) -> tuple[str, str]:
    """``learned`` is what people's edits taught (``learned_examples.Read.prompt``): it goes after the guidelines, so a rule in them still outranks an example.
    ``hashtags`` are the Story's own concepts the draft may choose from."""
    # A hashtag takes room from the words, and the model counts weight loosely: the limit it is given leaves room for the shortest hashtag offered and a margin.
    limit = DRAFT_WEIGHT - min(weighted_length(f" {tag}") for tag in hashtags) - COUNTING_MARGIN if hashtags else DRAFT_WEIGHT
    system = SYSTEM.format(limit=limit, guidelines=guidelines) + (f"\n\n{learned}" if learned else "")
    system += HASHTAGS_WITH_CHOICES.format(maximum=MAX_HASHTAGS) if hashtags else HASHTAGS_NONE
    content: dict[str, Any] = {"title": story.title, "dek": story.dek, "summary": story.summary}
    if hashtags:
        content["hashtagChoices"] = [{"tag": tag, "cost": weighted_length(f" {tag}")} for tag in hashtags]
    return system, json.dumps(content, ensure_ascii=False)


def with_hashtags(text: str, chosen: list[str]) -> str:
    return f"{text} {' '.join(chosen)}" if chosen else text


def choose_hashtags(answer: Mapping[str, Any], offered: list[str], *, room: int | None = None) -> tuple[list[str], list[str]]:
    """``(the hashtags to post, the ones the draft chose that were not offered)``: each offered hashtag once, in the order chosen, at most ``MAX_HASHTAGS``.
    ``room`` is the weight left after the drafted words: a hashtag that does not fit is left off (it is optional, so it never fails the post)."""
    allowed = {tag.lower(): tag for tag in offered}
    kept: list[str] = []
    refused: list[str] = []
    for value in (answer or {}).get("hashtags") or []:
        tag = "#" + str(value).strip().lstrip("#")
        if tag.lower() in allowed:
            if allowed[tag.lower()] not in kept:
                kept.append(allowed[tag.lower()])
        else:
            refused.append(tag)
    fitting: list[str] = []
    for tag in kept[:MAX_HASHTAGS]:
        cost = weighted_length(f" {tag}")
        if room is None or cost <= room:
            fitting.append(tag)
            room = None if room is None else room - cost
    return fitting, refused


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def check_draft(text: str, link: str, story: StoryFacts, *, judge: fact_check.Judge, rule_lane: RuleLane | None = None, hashtags: list[str] | None = None,
                refused_hashtags: list[str] | None = None) -> list[dict[str, Any]]:
    """Every check's result: ``{"name", "passed", "problems": [plain words]}``. All checks run, so an editor sees every problem at once.
    ``text`` is the drafted words; the chosen ``hashtags`` count toward the length and are checked as hashtags, and are not claims."""
    checks: list[dict[str, Any]] = []
    over = too_long_by(compose(with_hashtags(text, hashtags or []), link))
    checks.append({"name": "length", "passed": over == 0, "problems": [f"Too long for X by {over} characters"] if over else []})
    markup = [f"A post may not invent {found}: it is not in the Story"for found in live_markup(text, story_source(story))]
    if re.search(r"https?://|www\.", text):
        markup.append("The draft has its own link; the announcement adds the Story's link")
    checks.append({"name": "markup", "passed": not markup, "problems": markup})
    if hashtags or refused_hashtags:
        invented = [f"The draft chose {tag}, which is not one of the Story's concepts" for tag in refused_hashtags or []]
        checks.append({"name": "hashtags", "passed": not invented, "problems": invented})
    if rule_lane is not None:
        problems = rule_lane(text)
        checks.append({"name": "rules", "passed": not problems, "problems": problems})
    claims = [{"claim": sentence, "sources": ["story"]} for sentence in sentences(text)]
    if claims:
        report = fact_check.check_claims(claims, {"story": story_source(story)}, judge=judge, titles={"story": story.title})
        held = [row for row in report["claims"] if row["verdict"] != fact_check.VERIFIED]
        problems = [f"This claim is not in the Story: {row['claim']}" if row["verdict"] != fact_check.UNCHECKED else f"This claim could not be checked: {row['claim']}" for row in held]
    else:
        problems = ["The draft is empty"]
    checks.append({"name": "facts", "passed": not problems, "problems": problems})
    return checks


def draft_announcement(story: StoryFacts, link: str, *, guidelines: str, llm: Llm, judge: fact_check.Judge, rule_lane: RuleLane | None = None,
                       model: str = DEFAULT_LLM_MODEL, learned: str = "", hashtags: list[str] | None = None) -> Draft:
    """One model call, then every check. Returns the draft with its checks; it is posted only when ``passed``. ``hashtags`` are the Story's own concepts the draft may
    choose from (``hashtags.story_hashtags``); the draft's words and its chosen hashtags are checked as what they are."""
    if not guidelines.strip():
        raise DraftRefused("This publication has no writing guidelines, so there is no voice to draft in. Save them with papyrus guidelines save --kind writing.")
    system, user = prompt(story, guidelines, learned, hashtags)
    answer = llm(system, user, SCHEMA)
    text = str((answer or {}).get("text") or "").strip()
    chosen, refused = choose_hashtags(answer or {}, hashtags or [], room=DRAFT_WEIGHT - weighted_length(text))
    return Draft(text=with_hashtags(text, chosen), link=link, model=model, hashtags=chosen,
                 checks=check_draft(text, link, story, judge=judge, rule_lane=rule_lane, hashtags=chosen, refused_hashtags=refused))
