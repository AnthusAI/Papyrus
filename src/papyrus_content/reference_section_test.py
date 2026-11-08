"""papyrus references set-section and the MCP tool reference_set_section: one operation, section only (PPY-b5cb8e)."""
import contextlib
import copy
import io
import json

import pytest

from papyrus_content.reference_section import DESCRIPTIONS, TOOLS, SectionError, call_tool, resolve_section, set_reference_section
from papyrus_content.references_commands import references_set_section

SECTIONS = [
    {"id": "machines-on-machines#security", "title": "Security", "shortTitle": "Security", "enabled": True, "enabledStatus": "enabled", "sortOrder": 1},
    {"id": "machines-on-machines#research", "title": "Research Papers", "shortTitle": "Research", "enabled": True, "enabledStatus": "enabled", "sortOrder": 2},
    {"id": "machines-on-machines#retired", "title": "Retired", "shortTitle": "Retired", "enabled": False, "enabledStatus": "disabled", "sortOrder": 3},
]
VOTE = {
    "curationStatus": "accepted", "curationStatusUpdatedAt": "2026-11-01T10:00:00Z", "curationStatusUpdatedBy": "editor@example.org via cli",
    "curationStatusReason": "Worth a video page.", "curationActorKind": "human", "curationReasonCode": None, "curationShareable": True,
    "starRating": 4, "starRatedAt": "2026-11-01T10:05:00Z", "starRatedBy": "editor@example.org", "predictedAcceptProbability": 0.8,
}


class FakeClient:
    """Reads like the authoring client; its graphql applies setReferenceSection the way the site's function does (section and who/when only)."""

    def __init__(self, **fields):
        self.rows = {"ref-v2": {"id": "ref-v2", "lineageId": "ref", "versionNumber": 2, "versionState": "current", **VOTE, **fields},
                     "ref-v1": {"id": "ref-v1", "lineageId": "ref", "versionNumber": 1, "versionState": "superseded", **VOTE}}
        self.sent = []

    def get_record(self, model, record_id):
        return copy.deepcopy(self.rows.get(record_id)) if model == "Reference" else None

    def list_by_index(self, index, key, **_):
        return [copy.deepcopy(row) for row in self.rows.values() if row["lineageId"] == key]

    def list_records(self, model):
        assert model == "NewsroomSection"
        return copy.deepcopy(SECTIONS)

    def graphql(self, query, variables):
        self.sent.append((query, variables))
        row = self.rows[variables["referenceId"]]
        previous = row.get("curationSectionId")
        changed = variables["sectionId"] != previous
        if changed:
            row.update(curationSectionId=variables["sectionId"], curationSectionUpdatedAt="2026-11-08T00:00:00Z", curationSectionUpdatedBy="editor via cli")
        return {"setReferenceSection": {"ok": True, "referenceId": row["id"], "sectionId": variables["sectionId"], "previousSectionId": previous,
                                        "changed": changed, "status": row["curationStatus"]}}

    def vote_view(self):
        return {key: value for key, value in self.rows["ref-v2"].items() if key in VOTE}


@pytest.mark.parametrize("form", ["security", "Security", "machines-on-machines#security"])
def test_slug_name_and_qualified_forms_name_the_same_section(form):
    client = FakeClient()
    result = set_reference_section(client, reference="ref", section=form)
    assert result["sectionId"] == "machines-on-machines#security" and result["changed"] is True
    assert client.rows["ref-v2"]["curationSectionId"] == "machines-on-machines#security"


def test_a_display_name_with_a_space_and_the_id_local_part_work():
    assert resolve_section(SECTIONS, "Research Papers")["id"] == "machines-on-machines#research"
    assert resolve_section(SECTIONS, "research")["id"] == "machines-on-machines#research"


def test_changing_the_section_leaves_the_vote_the_feedback_and_the_rating_identical():
    client = FakeClient()
    before = client.vote_view()
    set_reference_section(client, reference="ref", section="security", agent_label="Claude")
    assert client.vote_view() == before
    (query, variables), = client.sent
    assert "setReferenceSection" in query and set(variables) == {"referenceId", "sectionId", "agentLabel"}
    assert variables == {"referenceId": "ref-v2", "sectionId": "machines-on-machines#security", "agentLabel": "Claude"}
    assert client.rows["ref-v2"]["curationSectionUpdatedBy"] and client.rows["ref-v2"]["curationSectionUpdatedAt"]


def test_it_works_on_the_current_version_of_a_lineage_and_on_a_record_id():
    client = FakeClient()
    assert set_reference_section(client, reference="ref-v2", section="research")["referenceId"] == "ref-v2"
    assert set_reference_section(client, reference="ref", section="security")["previousSectionId"] == "machines-on-machines#research"


def test_an_unknown_section_lists_the_accepted_forms_and_the_available_sections_and_writes_nothing():
    client = FakeClient()
    with pytest.raises(SectionError) as raised:
        set_reference_section(client, reference="ref", section="sports")
    message = str(raised.value)
    assert "sports" in message and "slug" in message and "<publication>#<slug>" in message
    assert "machines-on-machines#security" in message and "machines-on-machines#research" in message and "machines-on-machines#retired" not in message.split("Available sections:")[1]
    assert client.sent == []


def test_a_disabled_section_and_a_malformed_qualified_form_are_refused_with_the_same_help():
    client = FakeClient()
    for value in ("retired", "machines-on-machines#retired", "#security", "other-site#security", "machines-on-machines#"):
        with pytest.raises(SectionError) as raised:
            set_reference_section(client, reference="ref", section=value)
        assert "Accepted forms" in str(raised.value) and "Available sections" in str(raised.value)
    assert client.sent == []


def test_clear_removes_the_section_and_leaves_the_vote_alone():
    client = FakeClient(curationSectionId="machines-on-machines#security")
    before = client.vote_view()
    result = set_reference_section(client, reference="ref", clear=True)
    assert result["sectionId"] is None and result["previousSectionId"] == "machines-on-machines#security" and result["changed"] is True
    assert client.sent[0][1]["sectionId"] is None and client.vote_view() == before


def test_a_section_and_clear_together_or_neither_is_refused():
    client = FakeClient()
    with pytest.raises(ValueError, match="not both"):
        set_reference_section(client, reference="ref", section="security", clear=True)
    with pytest.raises(SectionError, match="Accepted forms|accepted|section is required"):
        set_reference_section(client, reference="ref")
    assert client.sent == []


def test_a_section_can_be_set_only_on_an_accepted_reference():
    client = FakeClient(curationStatus="pending")
    with pytest.raises(ValueError, match="only on an accepted Reference"):
        set_reference_section(client, reference="ref", section="security")
    assert client.sent == []


def test_dry_run_reads_and_reports_but_writes_nothing():
    client = FakeClient()
    result = set_reference_section(client, reference="ref", section="security", dry_run=True)
    assert result["dryRun"] is True and result["changed"] is True and result["sectionId"] == "machines-on-machines#security"
    assert client.sent == [] and "curationSectionId" not in client.rows["ref-v2"]


def test_the_same_section_again_reports_unchanged():
    client = FakeClient(curationSectionId="machines-on-machines#security")
    assert set_reference_section(client, reference="ref", section="security")["changed"] is False


def test_the_cli_prints_a_line_and_json_and_dry_run_sends_nothing(capsys):
    client = FakeClient()
    references_set_section(["--reference", "ref", "--section", "security", "--dry-run"], client=client)
    assert "dry-run: nothing sent" in capsys.readouterr().out and client.sent == []
    references_set_section(["--reference", "ref", "--section", "security", "--agent", "Claude"], client=client)
    assert "machines-on-machines#security\tchanged" in capsys.readouterr().out
    references_set_section(["--reference", "ref", "--clear", "--json"], client=client)
    printed = json.loads(capsys.readouterr().out)
    assert printed["sectionId"] is None and printed["ok"] is True


def test_the_mcp_tool_returns_what_the_cli_prints_as_json():
    cli_client, mcp_client = FakeClient(), FakeClient()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        references_set_section(["--reference", "ref", "--section", "machines-on-machines#security", "--json"], client=cli_client)
    assert call_tool(mcp_client, {"lineageId": "ref", "section": "machines-on-machines#security"}) == json.loads(out.getvalue())
    assert cli_client.sent == mcp_client.sent and cli_client.rows == mcp_client.rows


def test_the_mcp_tool_reports_errors_and_dry_runs_and_is_described():
    client = FakeClient()
    unknown = call_tool(client, {"lineageId": "ref", "section": "sports"})
    assert unknown["ok"] is False and unknown["error"]["code"] == "unknown_section" and "Available sections" in unknown["error"]["message"]
    assert call_tool(client, {"lineageId": "ref", "section": "security", "dryRun": True})["dryRun"] is True and client.sent == []
    assert call_tool(client, {"lineageId": "ref", "nonsense": 1})["error"]["code"] == "invalid_input"
    assert call_tool(client, {"lineageId": "ref", "clear": True})["sectionId"] is None
    assert set(TOOLS) == set(DESCRIPTIONS) == {"reference_set_section"} and TOOLS["reference_set_section"][0] == "staff"
