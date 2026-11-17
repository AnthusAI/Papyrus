"""The guideline file form of the writing guidelines: front matter read with the standard library, the fixed-name field files and their round trip, and the commands that
move a set between a folder and a site. In-memory; no network."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from papyrus_content.guidelines import GuidelineError, field_files, files as guideline_files, front_matter
from papyrus_content.guidelines import cli as guidelines_cli
from papyrus_content.guidelines.operations_test import world

ROOT = Path(__file__).resolve().parents[3]
SLUG = "editorial-doctrine-writing"


@pytest.mark.parametrize("text, expected", [
    ('name: plain-claims\nseverity: "error"\n', {"name": "plain-claims", "severity": "error"}),
    ("avoid: [\"we believe\", 'we think', arguably]\n", {"avoid": ["we believe", "we think", "arguably"]}),
    ("avoid:\n- we believe\n- 'x: y'\nmaxLength: 120\n", {"avoid": ["we believe", "x: y"], "maxLength": 120}),
    ("avoid:\n  - a\n  - b\nlanguage: '*'\n", {"avoid": ["a", "b"], "language": "*"}),
    ("id: https://example.org/id/2b9d\ndescription: State a claim as fact. Never \"we believe\".\n", {"id": "https://example.org/id/2b9d", "description": 'State a claim as fact. Never "we believe".'}),
    ("ratio: 0.45\nflag: true # a comment\nnothing: null\n", {"ratio": 0.45, "flag": True, "nothing": None}),
])
def test_flat_front_matter_is_read_without_a_yaml_library(text, expected):
    assert front_matter.loads(text) == expected == yaml.safe_load(text)


@pytest.mark.parametrize("text", ["scope:\n  channel: x\n", "avoid:\n- - a\n", "avoid:\n- k: v\n", "scope: {a: 1}\n", "not a key\n", "a: 1\na: 2\n", "x: |\n  text\n", 'x: "open\n'])
def test_nested_or_unreadable_front_matter_is_not_flat(text):
    try:
        value = front_matter.loads(text)
    except front_matter.FrontMatterError:
        return
    assert any(isinstance(item, (dict, list)) and item not in ([],) for item in value.values()), value


def test_what_the_writer_writes_the_reader_reads():
    meta = {"id": "urn:uuid:1", "name": "x", "description": 'A "quoted" line: with a colon and é.', "avoid": ["a, b", "c"], "maxLength": 80, "note": "it's"}
    assert front_matter.loads(front_matter.dumps(meta)) == meta


def test_every_writing_field_has_a_file_form_and_a_distinct_kebab_name():
    field_files.assert_registered()
    assert len(set(field_files.NAME_OF.values())) == len(field_files.NAME_OF)
    assert field_files.NAME_OF["voicePatterns"] == "voice-patterns" and field_files.NAME_OF["bodyMarkus"] == "body-markus"


def test_the_repository_style_profiles_round_trip_through_files():
    for name in ("anthus", "pilobolus"):
        document = yaml.safe_load((ROOT / "publications" / name / "style-profile.yml").read_text())
        files = field_files.files_from_document(document, slug=SLUG)
        assert field_files.view_of(files).document == document
        assert field_files.files_from_document(document, slug=SLUG) == files   # the same bytes every time


def test_sentences_with_line_breaks_and_unusual_text_round_trip():
    document = {"schemaVersion": 2, "tone": ["one\ntwo", "- starts like a bullet", "  indented"], "bodyMarkus": "# Heading\n\ntext\n\n\n", "audience": "Ünïcode ✓"}
    assert field_files.view_of(field_files.files_from_document(document, slug=SLUG)).document == document


def test_windows_line_endings_do_not_round_trip_so_a_conversion_would_refuse_them():
    document = {"schemaVersion": 2, "bodyMarkus": "a\r\nb"}
    assert field_files.view_of(field_files.files_from_document(document, slug=SLUG)).document != document


def test_a_set_is_for_one_lineage():
    files = field_files.files_from_document({"schemaVersion": 2, "tone": ["Warm."]}, slug=SLUG)
    with pytest.raises(GuidelineError) as error:
        field_files.view_of(files, section="news")
    assert {item["code"] for item in error.value.details["problems"]} == {"wrong_lineage"}
    with pytest.raises(GuidelineError):
        field_files.view_of(files, language="es")
    with pytest.raises(GuidelineError) as empty:
        field_files.view_of({})
    assert empty.value.details["problems"][0]["code"] == "empty"


def test_the_hash_covers_every_path_and_byte():
    a = {"x/GUIDELINE.md": "1"}
    assert field_files.set_digest(a) == field_files.set_digest(dict(a)) != field_files.set_digest({"y/GUIDELINE.md": "1"}) != field_files.set_digest({"x/GUIDELINE.md": "2"})


def test_a_folder_is_read_and_written_byte_for_byte_and_never_outside_itself(tmp_path):
    files = {"a/GUIDELINE.md": "line\r\nline\n", "a/examples/before.md": "x"}
    guideline_files.write_directory(tmp_path / "out", files)
    assert guideline_files.read_directory(tmp_path / "out") == files
    (tmp_path / "out" / ".DS_Store").write_bytes(b"\x00")
    assert guideline_files.read_directory(tmp_path / "out") == files
    with pytest.raises(ValueError):
        guideline_files.write_directory(tmp_path / "out", {"../escape/GUIDELINE.md": "x"})


def test_the_conversion_command_reports_without_applying_and_only_an_admin_applies(capsys):
    backend, files = world(saved=False)
    out = io.StringIO()
    status = guidelines_cli.convert_command(["--section", "news", "--language", "es"], out, client_factory=lambda: backend, files=files)
    answer = json.loads(out.getvalue())
    assert status == 0 and answer["result"]["applied"] is False and answer["result"]["lineages"] == []
    out = io.StringIO()
    status = guidelines_cli.convert_command(["--apply"], out, client_factory=lambda: backend, files=files)
    assert status == 2 and json.loads(out.getvalue())["error"]["code"] == "not_authorized" and not backend.items


def test_an_agent_reads_the_rule_files_with_their_severity():
    from papyrus_content.guidelines.agent_text import writing_text

    text = writing_text({"audience": "Readers", "guidelineFiles": [{"name": "plain-claims", "severity": "error", "avoid": ["we believe"], "body": "Say it plainly."}]})
    assert "plain-claims (error): Say it plainly. Avoid: we believe." in text
