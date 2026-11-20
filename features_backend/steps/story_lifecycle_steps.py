from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from papyrus_content import story_types
from papyrus_content.content_item_lifecycle import (
    CONTENT_ITEM_STAGES,
    HEAD_STAGE_KEY_FIELD,
    build_new_content_item_version,
    content_item_lineage_for_new_assignment,
    head_stage_fields,
    is_story_item_type,
    require_assignment_content_item_lineage_id,
    with_stage,
    without_sub_tasks,
)

MOMENT_OF_EVERY_WRITE = "2026-11-20T15:00:00Z"
PERSON_WHO_MAKES_EVERY_WRITE = "editor@example.test"
LINEAGE_OF_THE_STORY_ON_THE_BOARD = "content-item-hospitals-abc123"


def create_story(*, title: str, stage: str, section_key: str | None) -> dict:
    return build_new_content_item_version(
        lineage_id=LINEAGE_OF_THE_STORY_ON_THE_BOARD,
        title=title,
        summary=None,
        section_key=section_key,
        stage=stage,
        actor_label=PERSON_WHO_MAKES_EVERY_WRITE,
        now=MOMENT_OF_EVERY_WRITE,
    )


def open_assignment(*, assignment_id: str, title: str, requested_lineage_id: str | None) -> tuple[str, dict | None]:
    return content_item_lineage_for_new_assignment(
        requested_lineage_id=requested_lineage_id,
        assignment_id=assignment_id,
        title=title,
        summary=None,
        section_key="news",
        stage="assignment",
        actor_label=PERSON_WHO_MAKES_EVERY_WRITE,
        now=MOMENT_OF_EVERY_WRITE,
    )


def board_columns_that_hold(story_version: dict) -> list[str]:
    return [stage for stage in CONTENT_ITEM_STAGES if story_version.get(HEAD_STAGE_KEY_FIELD) == stage]


@when("an editor asks which stages a Story can be in")
def ask_for_the_stages_of_a_story(context):
    context.story_lifecycle_stages = list(CONTENT_ITEM_STAGES)


@then("the stages of a Story are, in order:")
def stages_are_in_this_order(context):
    assert context.story_lifecycle_stages == [row["stage"] for row in context.table], context.story_lifecycle_stages


@then('no stage of a Story is called "{stage_name}"')
def no_stage_has_this_name(context, stage_name):
    assert stage_name not in context.story_lifecycle_stages, context.story_lifecycle_stages


@then('placing a new Story at the stage "{stage_name}" is refused, and the refusal lists the stages a Story can be in')
def placing_a_story_at_an_unknown_stage_is_refused(context, stage_name):
    try:
        create_story(title="A Story waiting for a person", stage=stage_name, section_key="news")
    except ValueError as refusal:
        refusal_text = str(refusal)
    else:
        raise AssertionError(f"a Story was created at the stage {stage_name!r}")
    assert stage_name in refusal_text, refusal_text
    stages_missing_from_the_refusal = [stage for stage in CONTENT_ITEM_STAGES if stage not in refusal_text]
    assert stages_missing_from_the_refusal == [], refusal_text


@given("the site names no default Story type")
def site_names_no_default_story_type(context):
    site_without_a_default_story_type = mock.patch.object(story_types, "default_story_type", lambda environ=None: None)
    site_without_a_default_story_type.start()
    context.add_cleanup(site_without_a_default_story_type.stop)


@when('the Story "{title}" is created at the stage "{stage}" in the section "{section_key}"')
def create_a_story_in_a_section(context, title, stage, section_key):
    context.story_lifecycle_new_story = create_story(title=title, stage=stage, section_key=section_key)


@when('the Story "{title}" is created at the stage "{stage}" with no section')
def create_a_story_with_no_section(context, title, stage):
    context.story_lifecycle_new_story = create_story(title=title, stage=stage, section_key=None)


@then("the new Story is version 1 of its lineage and nothing came before it")
def new_story_is_the_first_version(context):
    new_story = context.story_lifecycle_new_story
    assert new_story["versionNumber"] == 1, new_story
    assert new_story["previousVersionId"] is None, new_story
    assert new_story["lineageId"] == LINEAGE_OF_THE_STORY_ON_THE_BOARD, new_story
    assert new_story["id"] == f"{LINEAGE_OF_THE_STORY_ON_THE_BOARD}-v1", new_story


@then("the new Story is a draft that no reader can see")
def new_story_is_a_draft(context):
    new_story = context.story_lifecycle_new_story
    assert new_story["versionState"] == "draft", new_story
    assert new_story["status"] == "draft", new_story
    assert new_story["typeStatus"].endswith("#draft"), new_story
    assert new_story["sectionStatus"].endswith("#draft"), new_story


@then('the new Story is on the board in the column "{stage}"')
def new_story_is_in_this_column(context, stage):
    assert board_columns_that_hold(context.story_lifecycle_new_story) == [stage], context.story_lifecycle_new_story


@then("the new Story has no section")
def new_story_has_no_section(context):
    assert context.story_lifecycle_new_story["section"] is None, context.story_lifecycle_new_story


@then('the new Story has the type "{item_type}"')
def new_story_has_this_type(context, item_type):
    assert context.story_lifecycle_new_story["type"] == item_type, context.story_lifecycle_new_story


@when('the Assignment "{assignment_id}" is opened for the new subject "{title}"')
def open_an_assignment_for_a_new_subject(context, assignment_id, title):
    context.story_lifecycle_first_opening = open_assignment(
        assignment_id=assignment_id, title=title, requested_lineage_id=None
    )
    context.story_lifecycle_latest_opening = context.story_lifecycle_first_opening


@when('the Assignment "{assignment_id}" is opened for the new subject "{title}" again')
def open_the_same_assignment_again(context, assignment_id, title):
    context.story_lifecycle_latest_opening = open_assignment(
        assignment_id=assignment_id, title=title, requested_lineage_id=None
    )


@then('a Story titled "{title}" is created at the stage "{stage}"')
def a_story_is_created_for_the_assignment(context, title, stage):
    _, created_story = context.story_lifecycle_latest_opening
    assert created_story is not None, "the Assignment created no Story"
    assert created_story["title"] == title, created_story
    assert created_story["stage"] == stage, created_story
    assert board_columns_that_hold(created_story) == [stage], created_story


@then("the Assignment works on that Story")
def the_assignment_works_on_the_created_story(context):
    lineage_id, created_story = context.story_lifecycle_latest_opening
    assert created_story["lineageId"] == lineage_id, (lineage_id, created_story)
    assert require_assignment_content_item_lineage_id({"id": "any", "itemLineageId": lineage_id}) == lineage_id


@given('the Story with the lineage "{lineage_id}" already exists')
def a_story_already_exists(context, lineage_id):
    context.story_lifecycle_existing_lineage_id = lineage_id


@when('the Assignment "{assignment_id}" is opened for the Story with the lineage "{lineage_id}"')
def open_an_assignment_for_an_existing_story(context, assignment_id, lineage_id):
    context.story_lifecycle_latest_opening = open_assignment(
        assignment_id=assignment_id, title="Hospitals are paying ransoms", requested_lineage_id=lineage_id
    )


@then("no new Story is created")
def no_new_story_is_created(context):
    _, created_story = context.story_lifecycle_latest_opening
    assert created_story is None, created_story


@then('the Assignment works on the Story with the lineage "{lineage_id}"')
def the_assignment_works_on_this_lineage(context, lineage_id):
    lineage_the_assignment_works_on, _ = context.story_lifecycle_latest_opening
    assert lineage_the_assignment_works_on == lineage_id, lineage_the_assignment_works_on


@then("both openings name the same Story")
def both_openings_name_the_same_story(context):
    first_lineage_id, first_created_story = context.story_lifecycle_first_opening
    second_lineage_id, second_created_story = context.story_lifecycle_latest_opening
    assert first_lineage_id == second_lineage_id, (first_lineage_id, second_lineage_id)
    assert first_created_story["id"] == second_created_story["id"], (first_created_story, second_created_story)


@when('the newsroom asks which Story the Assignment "{assignment_id}" works on and it names none')
def ask_which_story_an_orphan_assignment_works_on(context, assignment_id):
    try:
        require_assignment_content_item_lineage_id({"id": assignment_id})
    except ValueError as refusal:
        context.story_lifecycle_refusal_text = str(refusal)
    else:
        context.story_lifecycle_refusal_text = None


@then('the question is refused, naming the Assignment "{assignment_id}"')
def the_question_is_refused_naming_the_assignment(context, assignment_id):
    assert context.story_lifecycle_refusal_text is not None, "an Assignment with no Story was accepted"
    assert assignment_id in context.story_lifecycle_refusal_text, context.story_lifecycle_refusal_text


@then("the refusal says that every research, reporting and copywriting Assignment is work on one content item")
def the_refusal_explains_the_rule(context):
    assert (
        "Every research, reporting and copywriting Assignment is work on one content item"
        in context.story_lifecycle_refusal_text
    ), context.story_lifecycle_refusal_text


@given('a Story on the board in the column "{stage}"')
def a_story_is_on_the_board(context, stage):
    context.story_lifecycle_story_on_the_board = create_story(
        title="Hospitals are paying ransoms", stage=stage, section_key="news"
    )
    assert board_columns_that_hold(context.story_lifecycle_story_on_the_board) == [stage]


@when('the Story moves to the stage "{stage}"')
def the_story_moves_to_a_stage(context, stage):
    context.story_lifecycle_story_on_the_board = with_stage(context.story_lifecycle_story_on_the_board, stage)


@then('the Story is on the board in the column "{stage}" and in no other column')
def the_story_is_in_exactly_this_column(context, stage):
    moved_story = context.story_lifecycle_story_on_the_board
    assert moved_story["stage"] == stage, moved_story
    assert board_columns_that_hold(moved_story) == [stage], moved_story
    assert moved_story["lineageId"] == LINEAGE_OF_THE_STORY_ON_THE_BOARD, moved_story


@when("a newer version of the Story replaces it")
def a_newer_version_replaces_the_story(context):
    replaced_version = {**context.story_lifecycle_story_on_the_board, "versionState": "superseded"}
    context.story_lifecycle_replaced_version = {**replaced_version, **head_stage_fields(replaced_version)}


@then("the replaced version is in no column of the board")
def the_replaced_version_is_in_no_column(context):
    assert board_columns_that_hold(context.story_lifecycle_replaced_version) == [], context.story_lifecycle_replaced_version
    assert context.story_lifecycle_replaced_version[HEAD_STAGE_KEY_FIELD] is None


@given('a Story whose only version is a draft at the stage "{stage}"')
def a_story_whose_only_version_is_a_draft(context, stage):
    only_version = create_story(title="Hospitals are paying ransoms", stage=stage, section_key="news")
    assert only_version["versionState"] == "draft", only_version
    context.story_lifecycle_only_draft = {**only_version, **head_stage_fields(only_version)}


@then('that draft is on the board in the column "{stage}"')
def the_only_draft_is_in_this_column(context, stage):
    assert board_columns_that_hold(context.story_lifecycle_only_draft) == [stage], context.story_lifecycle_only_draft


@then('a record of the type "{item_type}" is a Story')
def this_type_is_a_story_type(context, item_type):
    assert is_story_item_type(item_type) is True, item_type


@then('a record of the type "{item_type}" is not a Story')
def this_type_is_not_a_story_type(context, item_type):
    assert is_story_item_type(item_type) is False, item_type


@given("these records in the newsroom:")
def these_records_are_in_the_newsroom(context):
    context.story_lifecycle_records = [{"title": row["title"], "type": row["type"]} for row in context.table]


@when("the newsroom lists the records without checklist steps")
def list_the_records_without_checklist_steps(context):
    context.story_lifecycle_listed_titles = [
        record["title"] for record in without_sub_tasks(context.story_lifecycle_records)
    ]


@then('the list is "{first_title}" and "{second_title}"')
def the_list_holds_these_two_titles(context, first_title, second_title):
    assert context.story_lifecycle_listed_titles == [first_title, second_title], context.story_lifecycle_listed_titles
