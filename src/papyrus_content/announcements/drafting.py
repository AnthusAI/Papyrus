"""Drafting the post and checking it, with no one asked to approve it (Ryan, 2026-11-12).

The model (the policy default, GPT-6 Luna) gets the Story's title, dek and summary and nothing else, under the site's writing guidelines and announcement rules.
The draft is then checked automatically, and a draft that fails any check is not posted:

* ``length``: the whole post (draft, blank line, tagged link) weighs at most what X allows (``post.py``);
* ``markup``: no mention, hashtag or cashtag the Story does not already contain (X would make them live), and no link of its own (the link is added);
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
    "or a cashtag; the link is added after your text. The post must weigh at most {limit} on X (most letters count 1, emoji and many non-Latin characters count 2). "
    "Write it in the publication's voice, following the guidelines.\n\n{guidelines}"
)
SCHEMA = {
    "type": "json_schema", "name": "announcement_draft", "strict": True,
    "schema": {"type": "object", "additionalProperties": False, "required": ["text"], "properties": {"text": {"type": "string"}}},
}


class DraftRefused(RuntimeError):
    """A draft cannot even be tried (for example the publication has no writing guidelines). Nothing was drafted."""


@dataclass
class Draft:
    text: str
    link: str
    model: str
    checks: list[dict[str, Any]] = field(default_factory=list)

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


def prompt(story: StoryFacts, guidelines: str) -> tuple[str, str]:
    system = SYSTEM.format(limit=DRAFT_WEIGHT, guidelines=guidelines)
    user = json.dumps({"title": story.title, "dek": story.dek, "summary": story.summary}, ensure_ascii=False)
    return system, user


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def check_draft(text: str, link: str, story: StoryFacts, *, judge: fact_check.Judge, rule_lane: RuleLane | None = None) -> list[dict[str, Any]]:
    """Every check's result: ``{"name", "passed", "problems": [plain words]}``. All checks run, so an editor sees every problem at once."""
    checks: list[dict[str, Any]] = []
    over = too_long_by(compose(text, link))
    checks.append({"name": "length", "passed": over == 0, "problems": [f"Too long for X by {over} characters"] if over else []})
    markup = [f"A post may not invent {found}: it is not in the Story"for found in live_markup(text, story_source(story))]
    if re.search(r"https?://|www\.", text):
        markup.append("The draft has its own link; the announcement adds the Story's link")
    checks.append({"name": "markup", "passed": not markup, "problems": markup})
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
                       model: str = DEFAULT_LLM_MODEL) -> Draft:
    """One model call, then every check. Returns the draft with its checks; it is posted only when ``passed``."""
    if not guidelines.strip():
        raise DraftRefused("This publication has no writing guidelines, so there is no voice to draft in. Save them with papyrus guidelines save --kind writing.")
    system, user = prompt(story, guidelines)
    answer = llm(system, user, SCHEMA)
    text = str((answer or {}).get("text") or "").strip()
    return Draft(text=text, link=link, model=model, checks=check_draft(text, link, story, judge=judge, rule_lane=rule_lane))
