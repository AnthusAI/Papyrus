"""Editing publication doctrine and newsroom sections from the CLI, the way the newsroom's workspaces do."""
import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from papyrus import cli as papyrus_cli
from papyrus_content import section_editing
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

NOW = "2026-10-21T12:00:00Z"


def client_with_doctrine_and_section():
    mission = {"id": "item-editorial-doctrine-mission-v1", "lineageId": "item-editorial-doctrine-mission", "versionNumber": 1, "versionState": "current",
               "type": "doctrine", "status": "private", "slug": "editorial-doctrine-mission", "title": "Editorial Mission", "body": ["Old mission."]}
    section = {"id": "news", "title": "News", "shortTitle": "News", "type": "canonical", "editorialMission": "Old mission", "editorialPolicy": "Old policy",
               "enabled": True, "enabledStatus": "enabled", "assignmentGuidance": "Old guidance", "killCriteria": None}
    return FakeAuthoringClient({"Item": [mission], "NewsroomSection": [section]})


def run(argv, client, monkeypatch):
    monkeypatch.setattr(section_editing, "create_authoring_client", lambda tenant=None: (client, {}))
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = papyrus_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def test_doctrine_set_replaces_the_body_with_paragraphs_from_the_file(tmp_path, monkeypatch):
    client = client_with_doctrine_and_section()
    path = tmp_path / "mission.md"
    path.write_text("First paragraph.\r\n\r\nSecond paragraph.\n", encoding="utf-8")
    code, out, _ = run(["sections", "doctrine", "set", "--kind", "mission", "--file", str(path)], client, monkeypatch)
    assert code == 0
    row = client.tables["Item"]["item-editorial-doctrine-mission-v1"]
    assert row["body"] == ["First paragraph.", "Second paragraph."]
    assert row["title"] == "Editorial Mission" and row["editorial"] == '{"kind":"mission"}'
    assert "editorial-doctrine-mission" in out and "1 -> 2 paragraphs" in out


def test_doctrine_set_creates_the_record_when_the_publication_has_none(tmp_path, monkeypatch):
    client = FakeAuthoringClient({})
    path = tmp_path / "policy.md"
    path.write_text("Be accurate.", encoding="utf-8")
    code, _, _ = run(["sections", "doctrine", "set", "--kind", "policy", "--file", str(path)], client, monkeypatch)
    assert code == 0
    created = client.tables["Item"]["item-editorial-doctrine-policy-v1"]
    assert created["slug"] == "editorial-doctrine-policy" and created["body"] == ["Be accurate."] and created["type"] == "doctrine"


def test_doctrine_dry_run_prints_the_change_and_writes_nothing(tmp_path, monkeypatch):
    client = client_with_doctrine_and_section()
    path = tmp_path / "mission.md"
    path.write_text("New.", encoding="utf-8")
    code, out, _ = run(["sections", "doctrine", "set", "--kind", "mission", "--file", str(path), "--dry-run"], client, monkeypatch)
    assert code == 0 and "dry run" in out
    assert client.write_calls() == []


def test_doctrine_with_unknown_kind_exits_2_without_a_traceback(tmp_path, monkeypatch):
    path = tmp_path / "x.md"
    path.write_text("x", encoding="utf-8")
    code, _, err = run(["sections", "doctrine", "set", "--kind", "vibes", "--file", str(path)], client_with_doctrine_and_section(), monkeypatch)
    assert code == 2 and "Traceback" not in err and "mission" in err


def test_doctrine_with_missing_file_exits_2(monkeypatch):
    code, _, err = run(["sections", "doctrine", "set", "--kind", "mission", "--file", "/no/such/file.md"], client_with_doctrine_and_section(), monkeypatch)
    assert code == 2 and "Traceback" not in err


def test_update_changes_only_the_fields_given_and_reports_them(tmp_path, monkeypatch):
    client = client_with_doctrine_and_section()
    guidance = tmp_path / "g.md"
    guidance.write_text("New guidance\n", encoding="utf-8")
    code, out, _ = run(["sections", "update", "--id", "news", "--assignment-guidance-file", str(guidance), "--enabled", "false"], client, monkeypatch)
    assert code == 0
    row = client.tables["NewsroomSection"]["news"]
    assert row["assignmentGuidance"] == "New guidance" and row["enabled"] is False and row["enabledStatus"] == "disabled"
    assert row["editorialMission"] == "Old mission" and row["editorialPolicy"] == "Old policy"
    assert "assignmentGuidance" in out and "enabled" in out and "editorialMission" not in out
    assert row["updatedAt"]


def test_update_that_changes_nothing_writes_nothing(tmp_path, monkeypatch):
    client = client_with_doctrine_and_section()
    same = tmp_path / "m.md"
    same.write_text("Old mission", encoding="utf-8")
    code, out, _ = run(["sections", "update", "--id", "news", "--editorial-mission-file", str(same)], client, monkeypatch)
    assert code == 0 and "unchanged" in out
    assert client.write_calls() == []


def test_update_dry_run_writes_nothing(tmp_path, monkeypatch):
    client = client_with_doctrine_and_section()
    kill = tmp_path / "k.md"
    kill.write_text("Kill it", encoding="utf-8")
    code, out, _ = run(["sections", "update", "--id", "news", "--kill-criteria-file", str(kill), "--dry-run"], client, monkeypatch)
    assert code == 0 and "killCriteria" in out and "dry run" in out
    assert client.write_calls() == []


@pytest.mark.parametrize("args", [
    ["--id", "nope", "--enabled", "true"],
    ["--id", "news"],
    ["--id", "news", "--enabled", "maybe"],
    ["--enabled", "true"],
])
def test_update_operator_errors_exit_2(args, monkeypatch):
    code, _, err = run(["sections", "update", *args], client_with_doctrine_and_section(), monkeypatch)
    assert code == 2 and "Traceback" not in err and err.strip()
