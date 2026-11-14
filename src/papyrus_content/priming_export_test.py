import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import priming_export_fixture as fx  # noqa: E402
from papyrus_content import priming_export as pe  # noqa: E402


@pytest.fixture(autouse=True)
def fake_store(monkeypatch):
    fx.FakeCards.bodies = {}
    monkeypatch.setattr(pe, "AttachmentStore", fx.FakeCards)


def export(site, **kwargs):
    return pe.export_priming(site, fx.PUBLICATION, fx.CORPUS, **kwargs)


def by_id(rows):
    return {item["id"]: item for item in rows[0]}


def test_accepted_and_rejected_references_carry_the_editor_label():
    site = fx.FakeSite(references=[
        fx.reference("a", "accepted", by=fx.EDITOR_ADDRESS, reason="On topic"),
        fx.reference("r", "rejected", by="user:ryan", reason="Not about marks"),
        fx.reference("p", "pending")])
    rows = by_id(export(site))
    assert set(rows) == {"ref-a", "ref-r"}
    accepted = rows["ref-a"]
    assert accepted["labels"] == {"distinctive-relevance": {"label": "include", "explanation": "On topic"}}
    assert accepted["provenance"] == {"source": "corpus", "state": "accepted", "labeledBy": "editor",
                                      "labeledAt": "2026-10-25T10:00:00Z", "modelMade": False}
    assert rows["ref-r"]["labels"]["distinctive-relevance"]["label"] == "exclude"
    assert accepted["occurred_at"] == "2026-09-28T04:00:00Z"


def test_a_machine_curation_is_marked_model_made_with_no_explanation():
    site = fx.FakeSite(references=[fx.reference("m", "accepted", by="papyrus-monitoring-worker", reason="Discovered by the monitor"),
                                   fx.reference("g", "rejected", by="agent:TTAB ruling analyst (Tactus)", reason="because")])
    rows = by_id(export(site))
    for item in rows.values():
        assert item["provenance"]["modelMade"] is True
        assert item["provenance"]["labeledBy"] == "automation"
        assert item["labels"]["distinctive-relevance"]["explanation"] == ""


def test_pending_references_are_exported_without_labels_only_when_asked():
    site = fx.FakeSite(references=[fx.reference("p", "pending")])
    assert export(site)[0] == []
    item = by_id(export(site, include_unlabeled=True))["ref-p"]
    assert item["labels"] == {}
    assert item["provenance"]["state"] == "pending"


def test_other_corpora_and_old_versions_are_left_out():
    other = {**fx.reference("o", "accepted", by="user:x"), "corpusId": "someone-else"}
    old = {**fx.reference("v", "accepted", by="user:x"), "versionState": "superseded"}
    assert export(fx.FakeSite(references=[other, old]))[0] == []


def test_text_is_title_url_summary_and_the_full_body_and_no_address_survives():
    site = fx.FakeSite(references=[fx.reference("t", "accepted", by="user:x", reason=f"Mail {fx.EDITOR_ADDRESS} about it")],
                       cards={"t": {"summary": {"text": "A summary."}, "current": {"textSortKey": "curation-text"}}})
    fx.FakeCards.bodies["t"] = "  The full body.\n\nSecond paragraph.  "
    item = by_id(export(site))["ref-t"]
    assert item["values"]["body"] == "  The full body.\n\nSecond paragraph.  "
    assert item["values"]["text"] == "Title of t\nhttps://example.test/t\n\nA summary.\n\n  The full body.\n\nSecond paragraph.  "
    assert fx.EDITOR_ADDRESS not in json.dumps(item)
    assert "@" not in item["labels"]["distinctive-relevance"]["explanation"]


def test_a_reference_without_a_card_uses_the_extracted_text_reader_else_is_empty():
    site = fx.FakeSite(references=[fx.reference("e", "accepted", by="user:x")])
    assert by_id(export(site))["ref-e"]["values"]["body"] == ""
    assert by_id(export(site, read_extracted=lambda ref, atts: "extracted"))["ref-e"]["values"]["body"] == "extracted"


def ttab_site(stage, by, *, reason="", references=()):
    story = "content-item-zen"
    return fx.FakeSite(
        references=list(references), automations=[fx.automation()], runs=[fx.run(story, "99185689")],
        versions=[fx.version(story, 1, "reporting", "TTAB ruling analyst (Tactus)"),
                  fx.version(story, 2, stage, by, state="current", reason=reason, at="2026-10-26T09:00:00Z")])


@pytest.mark.parametrize("stage,label", [("published", "include"), ("held", "exclude"), ("spiked", "exclude")])
def test_an_editors_stage_decision_labels_the_draft(stage, label):
    rows = export(ttab_site(stage, "papyrus-cli", reason="Editor's note"))[0]
    assert [item["id"] for item in rows] == ["ttab-99185689-2026-10-06"]
    item = rows[0]
    assert item["labels"] == {"distinctive-draft-accept": {"label": label, "explanation": "Editor's note"}}
    assert item["provenance"] == {"source": "ttab-automation", "state": stage, "labeledBy": "editor",
                                  "labeledAt": "2026-10-26T09:00:00Z", "modelMade": False}
    assert item["occurred_at"] == "2026-10-06T00:00:00Z"
    assert item["values"]["url"] == "https://ttab.example.test/99185689/decision.pdf"
    assert "distinctive-relevance" not in item["labels"]


def test_a_stage_a_machine_set_is_model_made():
    item = export(ttab_site("published", "automation:distinctive.ruling.copy-edit", reason="auto"))[0][0]
    assert item["provenance"]["modelMade"] is True
    assert item["provenance"]["labeledBy"] == "automation"
    assert item["labels"]["distinctive-draft-accept"]["explanation"] == ""


def test_a_draft_still_in_the_pipeline_has_no_label_unless_asked():
    site = ttab_site("typesetting", "Ruling copy editor (Tactus)")
    assert export(site)[0] == []
    item = export(site, include_unlabeled=True)[0][0]
    assert item["labels"] == {} and item["provenance"]["state"] == "typesetting"


def test_the_ttab_item_never_gets_a_relevance_label_from_its_draft_but_uses_the_reference_text():
    ref = fx.reference("ttab-ref", "pending", source_uri="https://ttab-reading-room.uspto.gov/ttab-document//legal-proceeding/99185689/decision/EXA_8.pdf")
    site = ttab_site("published", "papyrus-cli", references=[ref])
    rows = export(site)[0]
    ttab = next(item for item in rows if item["id"].startswith("ttab-"))
    assert ttab["values"]["title"] == "Title of ttab-ref"
    assert set(ttab["labels"]) == {"distinctive-draft-accept"}


def test_runs_of_other_publications_failed_runs_and_deleted_stories_are_skipped():
    other = fx.automation(publication="other", procedure="other.proc")
    site = fx.FakeSite(automations=[fx.automation(), other],
                       runs=[fx.run("gone", "1"), fx.run("failed", "2", status="failed"), fx.run("x", "3", procedure="other.proc")],
                       versions=[fx.version("x", 1, "published", "papyrus-cli", state="current"),
                                 fx.version("failed", 1, "published", "papyrus-cli", state="current")])
    rows, skipped = export(site)
    assert rows == [] and skipped["story gone or proceeding unknown"] == 1


def test_the_export_only_reads():
    site = ttab_site("published", "papyrus-cli")
    export(site)
    assert {kind for kind, _ in site.calls} <= {"list", "index", "get"}


def test_output_is_one_json_object_per_line_with_the_import_shape():
    rows = export(fx.FakeSite(references=[fx.reference("a", "accepted", by="user:x")]))[0]
    lines = pe.encode_lines(rows).splitlines()
    parsed = json.loads(lines[0])
    assert list(parsed) == ["id", "occurred_at", "values", "labels", "provenance"]
    assert list(parsed["values"]) == ["title", "url", "summary", "body", "text"]
    assert list(parsed["provenance"]) == ["source", "state", "labeledBy", "labeledAt", "modelMade"]


def test_the_summary_counts_by_classifier_label_and_model_made():
    rows = export(fx.FakeSite(references=[fx.reference("a", "accepted", by="user:x"), fx.reference("b", "accepted", by="user:y"),
                                          fx.reference("c", "rejected", by="papyrus-monitoring-worker")]))[0]
    assert Counter(pe.summary_of(rows)) == Counter({"distinctive-relevance\tinclude\tmodelMade=false": 2,
                                                    "distinctive-relevance\texclude\tmodelMade=true": 1})


def test_the_command_requires_a_publication_and_a_corpus_key():
    with pytest.raises(ValueError):
        pe.cyclotron_export_priming(["--publication", "distinctive"])
