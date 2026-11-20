from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from papyrus_content.section_labels import read_descriptions, section_sources


class NewsroomThatRecordsEveryRead:
    def __init__(self, sections_by_id: dict[str, dict]) -> None:
        self.sections_by_id = sections_by_id
        self.section_ids_read_one_at_a_time: list[str] = []
        self.calls_that_were_not_a_read_by_id: list[str] = []

    def get_record(self, model_name: str, record_id: str):
        assert model_name == "NewsroomSection", model_name
        self.section_ids_read_one_at_a_time.append(record_id)
        return self.sections_by_id.get(record_id)

    def __getattr__(self, name_of_any_other_call: str):
        def record_the_call_and_fail(*arguments, **named_arguments):
            self.calls_that_were_not_a_read_by_id.append(name_of_any_other_call)
            raise AssertionError(f"the newsroom was asked to {name_of_any_other_call}, which is not a read of one section by id")

        return record_the_call_and_fail


def write_sections_file(context, file_content) -> str:
    directory = Path(tempfile.mkdtemp(prefix="section-names-for-translation-"))
    context.add_cleanup(shutil.rmtree, directory, True)
    sections_file_path = directory / "sections.json"
    sections_file_path.write_text(json.dumps(file_content), encoding="utf-8")
    return str(sections_file_path)


def rows_of_the_sections_file(table) -> list[dict[str, str]]:
    return [{"id": row["id"], "label": row["label"], "description": row["description"]} for row in table]


def name_sections_for_translation(context, section_ids: list[str]) -> None:
    context.section_naming_refusal = None
    context.section_names_by_id = {}
    try:
        named_sections = section_sources(
            context.section_naming_newsroom,
            context.section_naming_publication_language,
            read_descriptions(context.section_naming_sections_file_path),
            section_ids,
        )
    except ValueError as refusal:
        context.section_naming_refusal = str(refusal)
        return
    context.section_names_by_id = {named_section.entity_id: named_section for named_section in named_sections}


def the_named_section(context, section_id: str):
    assert context.section_naming_refusal is None, context.section_naming_refusal
    assert section_id in context.section_names_by_id, sorted(context.section_names_by_id)
    return context.section_names_by_id[section_id]


@given('a publication written in "{language}" with these sections in the newsroom:')
def a_publication_with_sections(context, language):
    context.section_naming_publication_language = language
    context.section_naming_newsroom = NewsroomThatRecordsEveryRead(
        {
            row["id"]: {"id": row["id"], "title": row["title"], "editorialMission": row["editorial mission"] or None}
            for row in context.table
        }
    )
    context.section_naming_sections_file_path = None


@given("the site's sections file says:")
def the_sections_file_is_a_plain_list(context):
    context.section_naming_sections_file_path = write_sections_file(context, rows_of_the_sections_file(context.table))


@given('the site\'s sections file holds its list under "sections":')
def the_sections_file_holds_its_list_under_a_key(context):
    context.section_naming_sections_file_path = write_sections_file(
        context, {"sections": rows_of_the_sections_file(context.table)}
    )


@given("the site has no sections file")
def the_site_has_no_sections_file(context):
    context.section_naming_sections_file_path = None


@when('the newsroom names the section "{section_id}" for translation')
def name_one_section(context, section_id):
    name_sections_for_translation(context, [section_id])


@when('the newsroom names the sections "{first_section_id}" and "{second_section_id}" for translation')
def name_two_sections(context, first_section_id, second_section_id):
    name_sections_for_translation(context, [first_section_id, second_section_id])


@then('the section "{section_id}" is to be translated from the name "{name}"')
def the_section_is_translated_from_this_name(context, section_id, name):
    named_section = the_named_section(context, section_id)
    assert named_section.name == name, named_section
    assert named_section.kind == "section", named_section


@then('its description for the translator is "{description}"')
def the_description_for_the_translator(context, description):
    only_named_section = next(iter(context.section_names_by_id.values()))
    assert only_named_section.description == description, only_named_section


@then("it has no description for the translator")
def no_description_for_the_translator(context):
    only_named_section = next(iter(context.section_names_by_id.values()))
    assert only_named_section.description == "", only_named_section


@then('the translator is told that it covers "{summary}"')
def the_translator_is_told_what_it_covers(context, summary):
    only_named_section = next(iter(context.section_names_by_id.values()))
    assert only_named_section.summary == summary, only_named_section


@then('every name to be translated is marked as written in "{language}"')
def every_name_is_in_the_publication_language(context, language):
    assert context.section_names_by_id, "no section was named"
    languages_of_the_names = {named_section.language for named_section in context.section_names_by_id.values()}
    assert languages_of_the_names == {language}, languages_of_the_names


@then('naming is refused, saying there is no section "{section_id}"')
def naming_is_refused(context, section_id):
    assert context.section_naming_refusal is not None, "a section that does not exist was named"
    assert "There is no section" in context.section_naming_refusal, context.section_naming_refusal
    assert section_id in context.section_naming_refusal, context.section_naming_refusal
    assert context.section_names_by_id == {}, context.section_names_by_id


@then('the newsroom read the section "{first_section_id}" once and the section "{second_section_id}" once')
def each_section_was_read_once(context, first_section_id, second_section_id):
    assert context.section_naming_newsroom.section_ids_read_one_at_a_time == [first_section_id, second_section_id], (
        context.section_naming_newsroom.section_ids_read_one_at_a_time
    )


@then("the newsroom never listed the sections")
def the_sections_were_never_listed(context):
    assert context.section_naming_newsroom.calls_that_were_not_a_read_by_id == [], (
        context.section_naming_newsroom.calls_that_were_not_a_read_by_id
    )
