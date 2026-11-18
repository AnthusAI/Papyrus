"""``papyrus announcements correct``: a correction of a Delivery that went, with the words of a new Delivery's checks.

The words are checked before anything is written, so a text that fails leaves the catalog as it was. What is written is ``Deliveries.supersede`` (the next generation, the old
Delivery marked superseded, the ``supersedes`` relation); the refusals it raises are plain sentences. The old post is not deleted here (the withdraw operation, PPY-efd06c).

The checks are the ones a post's words get when an Announcement is made (``drafting.check_draft``: length, markup, the rule lane and the facts against the Story). Only the X
post has them, so a Delivery on another channel gets the record's own rules (words that are not empty).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from papyrus_content import fact_check

from . import link_reads
from .deliveries import Deliveries, Plan
from .drafting import check_draft
from .eligibility import StoryFacts, load_story
from .post import tagged_link
from .records import RecordError

X = "x"


class ChecksFailed(RecordError):
    """The words did not pass. ``checks`` are all of them, with the problems in plain words; nothing was written."""

    def __init__(self, problems: list[str], checks: list[dict[str, Any]]):
        super().__init__("The corrected text did not pass its checks: " + "; ".join(problems) + ".")
        self.problems, self.checks = problems, checks


class CannotCheck(RecordError):
    """The words cannot be checked, so nothing is corrected."""


def story_of(client: Any, announcement: str, *, item_url_style: str, loader: Callable[..., StoryFacts] = load_story) -> StoryFacts:
    """The Story an X post is about: an X Announcement is about one Story, and the post's facts are checked against it."""
    lineages = sorted({link["objectLineageId"] for link in link_reads.stories_of_announcement(client, announcement)})
    if len(lineages) != 1:
        raise CannotCheck(f"{announcement} is about {len(lineages)} Stories; the facts of a post are checked against one Story, so this text cannot be checked.")
    return loader(client, lineages[0], item_url_style=item_url_style)


def check_words(old: Mapping[str, Any], text: str, *, story: Callable[[], StoryFacts], site_origin: Callable[[], str], judge: Callable[[], fact_check.Judge]) -> list[dict[str, Any]]:
    """The checks of a new Delivery's words. Raises ``ChecksFailed`` when any fails. The Story, the origin and the judge are made only when a check needs them."""
    if not text.strip():
        raise ChecksFailed(["The corrected text is empty"], [{"name": "words", "passed": False, "problems": ["The corrected text is empty"]}])
    if old["channel"] != X:
        return [{"name": "words", "passed": True, "problems": []}]
    facts = story()
    checks = check_draft(text, tagged_link(site_origin().rstrip("/") + facts.path), facts, judge=judge())
    problems = [problem for check in checks if not check["passed"] for problem in check["problems"]]
    if problems:
        raise ChecksFailed(problems, checks)
    return checks


def correct(deliveries: Deliveries, old: Mapping[str, Any], text: str, checks: list[dict[str, Any]], *, by: str, drafted_by: str, now: str | None = None) -> dict[str, Any]:
    """Write the correction: the new Delivery is under the review the old one had, with the same channel, account, mode, audience and picture."""
    plan = Plan(channel=old["channel"], account_id=old["accountId"], approval=old["approval"], approval_policy=old["approvalPolicy"], text=text.strip(), mode=old["mode"],
                audience=old.get("audience") or (), image_key=old.get("imageKey"), drafted_by=drafted_by, checks=[{"name": check["name"], "passed": check["passed"]} for check in checks])
    return deliveries.supersede(old, plan, by=by, now=now)
