from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from procedures.release.classify_release import (  # noqa: E402
    plan_site_bump,
    release_affects_sites,
    release_notes_marker,
)


@given('a release that changed "{first_path}" and "{second_path}"')
def release_changed_two_paths(context, first_path: str, second_path: str) -> None:
    context.changed_paths = [first_path, second_path]


@when("the release is classified")
def classify_release(context) -> None:
    context.release_notes = release_notes_marker(release_affects_sites(context.changed_paths))


@then('the release notes say "{expected}"')
def release_notes_say(context, expected: str) -> None:
    assert context.release_notes == expected, context.release_notes


@given('a site pinned to Papyrus "{version}"')
def site_pinned(context, version: str) -> None:
    context.pinned_version = version
    context.published_releases = []


@given('the later releases "{first_version}" noted "{first_notes}" and "{second_version}" noted "{second_notes}"')
def two_later_releases(context, first_version: str, first_notes: str, second_version: str, second_notes: str) -> None:
    context.published_releases = [
        {"tagName": f"v{first_version}", "body": first_notes},
        {"tagName": f"v{second_version}", "body": second_notes},
    ]


@given('the later release "{version}" noted "{notes}"')
def one_later_release(context, version: str, notes: str) -> None:
    context.published_releases = [{"tagName": f"v{version}", "body": notes}]


@when("the weekly bump is planned")
def plan_weekly_bump(context) -> None:
    context.bump_plan = plan_site_bump(context.pinned_version, context.published_releases)


@then("no bump is needed")
def no_bump_needed(context) -> None:
    assert context.bump_plan["bump_needed"] is False, context.bump_plan


@then('the bump targets "{version}"')
def bump_targets(context, version: str) -> None:
    assert context.bump_plan["target"] == version, context.bump_plan


@then('the site affecting releases are "{tags}"')
def site_affecting_releases_are(context, tags: str) -> None:
    assert context.bump_plan["site_affecting_releases"] == tags.split(","), context.bump_plan
