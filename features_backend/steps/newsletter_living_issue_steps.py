"""The living issue (features_backend/readers/newsletter-living-issue.feature): the blocks, pins, exclusions, the floor and approval, through ``living_issue``."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter import living_issue as li  # noqa: E402

AT = "2027-01-13T10:00:00Z"


def found(*ids):
    return [(item, "tools", "reached three stars") for item in ids]


def attempt(context, call):
    context.error = None
    try:
        return call()
    except li.IssueError as error:
        context.error = error
        return context.issue


@given("an open issue where an editor wrote the intro")
def intro_written(context) -> None:
    context.issue = li.edit_field(li.Issue("weekly", "2027-02"), base=1, actor="Ann", human=True, name="intro", value="Ann's words")
    context.older = 1


@given("an open issue with two machine entries")
def two_entries(context) -> None:
    context.issue = li.insert(li.Issue("weekly", "2027-02"), base=1, actor="inserter", found=found("a", "b"), at=AT)


@given("an open issue with no entries")
def no_entries(context) -> None:
    context.issue = li.Issue("weekly", "2027-02")


@given("an open issue with a pinned entry")
def pinned(context) -> None:
    two_entries(context)
    context.issue = li.edit_entry(context.issue, base=context.issue.version, actor="Ed", item_id="a", copy="My blurb")


@given("an admin approved the issue")
def approved(context) -> None:
    two_entries(context)
    context.issue = li.approve(context.issue, actor="Ann", admin=True, send_at=AT)


@when("an article reaches three stars and the inserter adds it")
def inserter_adds(context) -> None:
    context.before = context.issue
    context.issue = li.insert(context.issue, base=context.issue.version, actor="inserter", found=found("new"), at=AT)


@then("the issue has the article as a machine entry added by the inserter with the reason")
def has_entry(context) -> None:
    entry = context.issue.entry("new")
    assert (entry.added_by, entry.reason) == ("inserter", "reached three stars")


@then("the intro and every human field are exactly as the editor left them")
def human_untouched(context) -> None:
    assert context.issue.fields == context.before.fields and context.issue.touched == context.before.touched and context.issue.headings == context.before.headings


@when("an editor removes one with a reason")
def remove_with_reason(context) -> None:
    context.issue = li.remove_entry(context.issue, base=context.issue.version, actor="Ed", item_id="a", reason="Off topic", at=AT)


@when("an editor tries to remove one without a reason")
def remove_without_reason(context) -> None:
    attempt(context, lambda: li.remove_entry(context.issue, base=context.issue.version, actor="Ed", item_id="a", reason="", at=AT))


@then("the removal is refused")
def removal_refused(context) -> None:
    assert isinstance(context.error, li.NotAllowed)


@when("the inserter runs again with that article and a new one")
def run_again(context) -> None:
    context.issue = li.insert(context.issue, base=context.issue.version, actor="inserter", found=found("a", "c"), at=AT)


@then("the removed article is not added back")
def not_added_back(context) -> None:
    assert context.issue.entry("a") is None and context.issue.entry("c") is not None


@then("the issue shows who removed it, when and why")
def shows_removal(context) -> None:
    record = context.issue.exclusions[0]
    assert (record.by, record.at, record.reason) == ("Ed", AT, "Off topic")


@when("the editor restores it")
def restore(context) -> None:
    context.issue = li.restore_entry(context.issue, base=context.issue.version, actor="Ed", item_id="a", at=AT)


@then("the inserter may add it again")
def may_add(context) -> None:
    again = li.insert(context.issue, base=context.issue.version, actor="inserter", found=found("a"), at=AT)
    assert again.entry("a") is not None


@when("an editor rewrites one entry's blurb")
def rewrite_blurb(context) -> None:
    context.issue = li.edit_entry(context.issue, base=context.issue.version, actor="Ed", item_id="a", copy="My blurb")


@then("the entry is pinned and keeps the editor's words")
def entry_pinned(context) -> None:
    entry = context.issue.entry("a")
    assert entry.pinned and entry.copy == "My blurb"


@when("an agent and an editor both start from the same version")
def same_version(context) -> None:
    context.base = context.issue.version


@when("the editor writes the intro and the agent adds an entry")
def both_write(context) -> None:
    context.issue = li.edit_field(context.issue, base=context.base, actor="Ed", human=True, name="intro", value="Hello.")
    context.issue = li.insert(context.issue, base=context.base, actor="inserter", found=found("c"), at=AT)


@then("both changes are kept as two versions with two actors")
def both_kept(context) -> None:
    assert context.issue.fields["intro"] == "Hello." and context.issue.entry("c") is not None
    assert [version.actor for version in context.issue.log[-2:]] == ["Ed", "inserter"]


@when("a second person who started from the older version writes the intro")
def second_writer(context) -> None:
    attempt(context, lambda: li.edit_field(context.issue, base=context.older, actor="Bo", human=True, name="intro", value="Bo's words"))


@then("the second writer is told and sees the newer text")
def told(context) -> None:
    assert isinstance(context.error, li.Conflict) and context.error.current == "Ann's words"


@then("nothing is overwritten")
def nothing_overwritten(context) -> None:
    assert context.issue.fields["intro"] == "Ann's words"


@when("an agent tries to improve the intro")
def agent_intro(context) -> None:
    attempt(context, lambda: li.edit_field(context.issue, base=context.issue.version, actor="agent", human=False, name="intro", value="Better"))


@then("the agent is told to post a suggestion and the intro is unchanged")
def suggestion(context) -> None:
    assert isinstance(context.error, li.NeedsSuggestion) and context.issue.fields["intro"] == "Ann's words"


@when("its rating falls to two stars")
def rating_falls(context) -> None:
    context.issue = li.drop_below_floor(context.issue, actor="inserter", stars={"a": 2, "b": 3}, floor=3)


@then("the entry is removed as below the floor even though it is pinned")
def removed_below_floor(context) -> None:
    assert context.issue.entry("a") is None and context.issue.removed[0][1] == li.BELOW_FLOOR and not context.issue.exclusions


@then("when it is rated three stars again the inserter adds it back with the editor's copy")
def added_back(context) -> None:
    back = li.insert(context.issue, base=context.issue.version, actor="inserter", found=found("a"), at=AT)
    assert back.entry("a").copy == "My blurb"


@when("an editor changes the intro")
def editor_intro(context) -> None:
    context.issue = li.edit_field(context.issue, base=context.issue.version, actor="Ed", human=True, name="intro", value="New")


@then("the issue is back in draft with the note \"edited after approval; approve again\"")
def back_in_draft(context) -> None:
    assert context.issue.status == "draft" and context.issue.note == "edited after approval; approve again"


@then("the issue is no longer ready to send")
def not_ready(context) -> None:
    assert not li.ready_to_send(context.issue)


@then("the inserter resumes")
def resumes(context) -> None:
    assert li.insert(context.issue, base=context.issue.version, actor="inserter", found=found("c"), at=AT).entry("c") is not None


@when("the inserter runs with a new article")
def runs_when_approved(context) -> None:
    context.before = context.issue
    context.issue = li.insert(context.issue, base=context.issue.version, actor="inserter", found=found("c"), at=AT)


@then("the issue is unchanged")
def unchanged(context) -> None:
    assert context.issue is context.before


@when("an editor tries to approve")
def editor_approves(context) -> None:
    attempt(context, lambda: li.approve(context.issue, actor="Ed", admin=False, send_at=AT))


@then("the approval is refused")
def approval_refused(context) -> None:
    assert isinstance(context.error, li.NotAllowed) and context.issue.status == "draft"


@when("an admin tries to approve")
def admin_approves_empty(context) -> None:
    attempt(context, lambda: li.approve(context.issue, actor="Ann", admin=True, send_at=AT))


@then("the approval is refused because the issue has no entries")
def refused_empty(context) -> None:
    assert isinstance(context.error, li.NotAllowed) and "no entries" in str(context.error)


@then("the issue is ready to send")
def ready(context) -> None:
    assert li.ready_to_send(context.issue)
