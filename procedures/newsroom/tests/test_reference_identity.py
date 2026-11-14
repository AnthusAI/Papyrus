"""The identity gate: keys, every entry path, and the read-only duplicates report. Synthetic content only."""
from __future__ import annotations

import copy

import pytest

from papyrus_content.reference_duplicates_report import build_duplicates_report, render_text
from papyrus_content.reference_identity import (IdentityIndex, arxiv_id, canonical_url_key, doi_of, identity_groups, identity_keys, split_by_identity,
                                                title_candidate_key)
from procedures.newsroom.tests import reference_identity_support as support
from procedures.newsroom.tests.reference_identity_support import HELD_ARXIV_ADDRESS, OTHER_ARXIV_ADDRESS, held_reference

PAGE_FORMS = [
    "https://example.org/a/b",
    "HTTPS://Example.ORG/a/b#section",
    "http://example.org/a/b",
    "https://www.example.org/a/b/",
    "https://example.org:443/a/b?utm_source=feed&fbclid=1",
    "https://example.org/a/b?x=1&y=2",
]


def test_every_form_of_one_page_has_one_url_key():
    keys = {canonical_url_key(form) for form in PAGE_FORMS[:5]}
    assert keys == {"url:example.org/a/b"}
    assert canonical_url_key("https://example.org/a/b?y=2&x=1") == canonical_url_key("https://example.org/a/b?x=1&y=2")
    assert canonical_url_key("https://example.org/a/b?x=1") != canonical_url_key("https://example.org/a/b")


def test_an_internationalised_host_has_one_key_in_unicode_or_punycode():
    assert canonical_url_key("https://bücher.example/p") == canonical_url_key("https://xn--bcher-kva.example/p")


@pytest.mark.parametrize("value", ["", "ftp://example.org/x", "not a url", "https://user:pw@example.org/x", None, 5])
def test_something_that_is_not_an_address_has_no_url_key(value):
    assert canonical_url_key(value) is None


@pytest.mark.parametrize("address", [
    "https://arxiv.org/abs/2401.01234", "https://arxiv.org/abs/2401.01234v2", "http://www.arxiv.org/pdf/2401.01234.pdf",
    "https://arxiv.org/pdf/2401.01234v3", "https://arxiv.org/html/2401.01234v1", "https://export.arxiv.org/abs/2401.01234",
    "https://doi.org/10.48550/arXiv.2401.01234", "doi:10.48550/arxiv.2401.01234v2", "https://ar5iv.labs.arxiv.org/html/2401.01234",
])
def test_every_arxiv_form_of_one_paper_has_one_arxiv_key(address):
    assert arxiv_id(address) == "2401.01234"
    assert "arxiv:2401.01234" in identity_keys({"sourceUri": address})


def test_an_old_style_arxiv_id_is_recognised_and_other_hosts_are_not():
    assert arxiv_id("https://arxiv.org/abs/hep-th/9901001v1") == "hep-th/9901001"
    assert arxiv_id("https://example.org/abs/2401.01234") is None
    assert arxiv_id("https://arxiv.org/list/cs.AI/recent") is None


@pytest.mark.parametrize("address", ["https://doi.org/10.1145/3290605.3300233", "https://dx.doi.org/10.1145/3290605.3300233",
                                     "doi:10.1145/3290605.3300233", "10.1145/3290605.3300233", "https://dl.acm.org/doi/pdf/10.1145/3290605.3300233",
                                     "https://doi.org/10.1145/3290605.3300233".upper().replace("HTTPS", "https")])
def test_every_doi_form_has_one_lowercase_doi_key(address):
    assert doi_of(address) == "10.1145/3290605.3300233"


def test_an_arxiv_doi_joins_the_arxiv_paper_and_a_declared_doi_field_counts():
    assert {"arxiv:2401.01234", "doi:10.48550/arxiv.2401.01234"} <= identity_keys({"sourceUri": "https://doi.org/10.48550/arXiv.2401.01234"})
    assert identity_keys({"sourceUri": "https://example.org/x", "doi": "10.48550/arXiv.2401.01234"}) >= {"arxiv:2401.01234"}


def test_captured_text_counts_only_when_fully_captured():
    digest = "a" * 64
    assert f"text:{digest}" in identity_keys({"capturedTextSha256": digest, "captureState": "full"})
    assert not any(key.startswith("text:") for key in identity_keys({"capturedTextSha256": digest, "captureState": "thin"}))
    assert not any(key.startswith("text:") for key in identity_keys({"capturedTextSha256": digest}))


def test_the_same_title_is_not_identity_and_is_a_candidate_key():
    one = held_reference("https://example.org/one", number=1, title="Scaling Laws, Revisited")
    two = held_reference("https://other.example/two", number=2, title="scaling laws revisited")
    assert not (identity_keys(one) & identity_keys(two))
    assert title_candidate_key(one) == title_candidate_key(two) == "scaling laws revisited"
    assert title_candidate_key({"title": "https://example.org/x"}) is None
    assert IdentityIndex([one]).hits(two) == []


def test_groups_join_transitively_through_arxiv_and_doi_rows():
    rows = [held_reference("https://arxiv.org/abs/2401.01234", number=1), held_reference("https://doi.org/10.48550/arXiv.2401.01234", number=2),
            held_reference("https://arxiv.org/pdf/2401.01234v2", number=3), held_reference("https://example.org/alone", number=4)]
    (group,) = identity_groups(rows)
    assert [member["id"] for member in group["members"]] == ["reference-held-1-v1", "reference-held-2-v1", "reference-held-3-v1"]
    assert "arxiv:2401.01234" in group["keys"]


def test_superseded_versions_do_not_make_groups():
    old = {**held_reference("https://example.org/a", number=1), "versionState": "superseded"}
    assert identity_groups([old, held_reference("https://example.org/a", number=2)]) == []


def test_split_by_identity_reports_held_documents_and_batch_repeats_without_changing_anything():
    rows = [held_reference(HELD_ARXIV_ADDRESS, status="accepted")]
    before = copy.deepcopy(rows)
    items = [{"source_uri": OTHER_ARXIV_ADDRESS, "title": "x"}, {"source_uri": "https://example.org/new", "title": "y"},
             {"source_uri": "https://www.example.org/new/", "title": "y again"}]
    fresh, reported = split_by_identity(IdentityIndex(rows), items, corpus_id="knowledge-corpus-alpha-site")
    assert [item["source_uri"] for item in fresh] == ["https://example.org/new"]
    assert [(row["action"], row["status"]) for row in reported] == [("existing", "accepted"), ("duplicate-in-batch", "new")]
    assert rows == before


# --- every path that creates a Reference ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["monitor", "editor", "research", "chat", "catalog", "citation"])
@pytest.mark.parametrize("corpus", [support.FIRST_CORPUS, support.SECOND_CORPUS])
def test_each_entry_path_returns_the_held_document_and_creates_nothing(path, corpus):
    client = support.publication_holding(HELD_ARXIV_ADDRESS, corpus=corpus, held_in=support.FIRST_CORPUS, status="accepted")
    held_before = copy.deepcopy(client.references())
    client.writes.clear()
    if path == "monitor":
        result = support.through_monitor_delivery(client, OTHER_ARXIV_ADDRESS, corpus=corpus)
        assert result["identityMatched"] is True and result["referenceId"] == "reference-held-1-v1"
        assert ("create", "Reference") not in client.writes
        (held,) = client.references()
        assert {k: v for k, v in held.items() if k not in {"discoveredByMonitorId", "discoveryDetails"}} == held_before[0]
        assert ("discoveredByMonitorId" in held) == (corpus == support.FIRST_CORPUS)
        return
    elif path == "editor":
        result = support.through_editor_intake(client, OTHER_ARXIV_ADDRESS, corpus=corpus)
        assert result["reusedExisting"] is True and result["id"] == "reference-held-1-v1" and "arxiv:2401.01234" in result["matchedBy"]
        assert client.writes == []
    elif path == "research":
        result = support.through_research_intake(client, OTHER_ARXIV_ADDRESS, corpus=corpus)
        assert result["registeredReferenceCount"] == 0 and result["references"][0]["referenceId"] == "reference-held-1-v1"
        assert result["references"][0]["action"] == "existing" and client.writes == []
    elif path == "chat":
        result = support.through_chat_create(client, OTHER_ARXIV_ADDRESS, corpus=corpus, skip_existing=False)
        assert result["skipped"] is True and result["referenceId"] == "reference-held-1-v1" and client.writes == []
    elif path == "catalog":
        result = support.through_catalog_import(client, OTHER_ARXIV_ADDRESS, corpus=corpus)
        assert [change for change in result["changes"] if change["modelName"] == "Reference"] == []
    else:
        result = support.through_citation_graph(client, OTHER_ARXIV_ADDRESS, corpus=corpus)
        assert result["isNew"] is False and result["record"]["id"] == "reference-held-1-v1"
    assert client.references() == held_before
    assert client.references()[0]["curationStatus"] == "accepted"
    assert support.created_references(client) == []


@pytest.mark.parametrize("path", ["monitor", "editor", "chat", "catalog", "citation"])
def test_a_document_nobody_holds_is_still_created_or_planned(path):
    client = support.publication_holding("https://example.org/something-else", status="accepted")
    new_address = "https://example.org/a-new-paper"
    if path == "monitor":
        support.through_monitor_delivery(client, new_address)
        assert len(support.created_references(client)) == 1
    elif path == "editor":
        assert "reusedExisting" not in support.through_editor_intake(client, new_address)
        assert len(support.created_references(client)) == 1
    elif path == "chat":
        assert support.through_chat_create(client, new_address)["applied"] is True
        assert len(support.created_references(client)) == 1
    elif path == "catalog":
        assert [change["action"] for change in support.through_catalog_import(client, new_address)["changes"] if change["modelName"] == "Reference"] == ["create"]
    else:
        assert support.through_citation_graph(client, new_address)["isNew"] is True


def test_research_intake_registers_a_document_nobody_holds_in_a_dry_run():
    client = support.publication_holding("https://example.org/something-else")
    result = support.through_research_intake(client, "https://example.org/a-new-paper", dry_run=True)
    assert result["references"] == [] or all(row["action"] != "existing" for row in result["references"])
    assert result["dedupedProposalCount"] == 1


def test_research_intake_never_resets_an_accepted_reference_to_pending():
    address = "https://example.org/a-paper"
    client = support.publication_holding(address, status="accepted")
    first = support.through_research_intake(client, address)
    second = support.through_research_intake(client, address + "/")
    assert first["registeredReferenceCount"] == second["registeredReferenceCount"] == 0
    assert client.references()[0]["curationStatus"] == "accepted" and client.writes == []


def test_a_rejected_reference_is_also_reported_and_left_rejected():
    client = support.publication_holding(HELD_ARXIV_ADDRESS, status="rejected")
    result = support.through_editor_intake(client, OTHER_ARXIV_ADDRESS)
    assert result["curationStatus"] == "rejected" and client.references()[0]["curationStatus"] == "rejected"


def test_a_catalog_reimport_updates_its_own_lineage_but_does_not_turn_a_decided_reference_back_to_pending():
    client = support.publication_holding("https://example.org/a-paper", status="accepted")
    row = client.rows[("Reference", "reference-held-1-v1")]
    row["lineageId"], row["id"] = "reference-knowledge-corpus-alpha-site-item-new", "reference-knowledge-corpus-alpha-site-item-new-v1"
    client.rows = {("Reference", row["id"]): row}
    result = support.through_catalog_import(client, "https://example.org/a-paper", skip_existing=False)
    assert [change for change in result["changes"] if change["modelName"] == "Reference"] == []


# --- the report ---------------------------------------------------------------------------------------------------------------------------

def report_rows():
    return [held_reference("https://arxiv.org/abs/2401.01234", number=1, status="accepted", title="Paper One"),
            held_reference("https://arxiv.org/pdf/2401.01234v2", number=2, status="pending", title="Paper One"),
            held_reference("https://doi.org/10.48550/arXiv.2401.01234", number=3, corpus=support.SECOND_CORPUS, status="pending", title="Paper One"),
            held_reference("https://example.org/story", number=4, title="Same Words"),
            held_reference("https://other.example/post", number=5, title="same   words!"),
            held_reference("https://example.org/alone", number=6, title="Alone")]


def test_the_report_groups_by_identity_and_counts_same_titles_as_candidates_only():
    report = build_duplicates_report(report_rows())
    assert report["references"] == 6
    assert report["identity"]["groups"] == 1 and report["identity"]["extraRows"] == 2
    assert report["identity"]["byKind"]["arxiv"] == {"groups": 1, "extraRows": 2}
    assert report["identity"]["byKind"]["url"] == {"groups": 0, "extraRows": 0}
    assert report["identity"]["groupsAcrossCorpora"] == 1 and report["identity"]["groupsWithDifferentStatuses"] == 1
    assert report["identity"]["groupsHoldingAccepted"] == 1
    titles = report["sameTitleCandidates"]
    assert titles["groups"] == 2 and titles["groupsNotAlreadyOneIdentity"] == 1 and "candidates only" in titles["note"]
    assert "candidates, not duplicates" in render_text(report)


def test_the_report_uses_captured_text_hashes_when_attachments_are_given():
    rows = [{**held_reference("https://example.org/one", number=1), "lineageId": "lineage-one", "captureState": "full"},
            {**held_reference("https://mirror.example/one", number=2), "lineageId": "lineage-two", "captureState": "full"}]
    attachments = [{"referenceLineageId": "lineage-one", "role": "extracted_text", "sha256": "b" * 64},
                   {"referenceLineageId": "lineage-two", "role": "extracted_text", "sha256": "b" * 64}]
    assert build_duplicates_report(rows)["identity"]["groups"] == 0 and build_duplicates_report(rows)["withCapturedTextHash"] == 0
    assert build_duplicates_report(rows, attachments)["withCapturedTextHash"] == 2
    with_text = build_duplicates_report(rows, attachments)
    assert with_text["identity"]["byKind"]["text"] == {"groups": 1, "extraRows": 1}


def test_the_report_command_reads_and_writes_nothing(capsys, monkeypatch):
    import json
    import papyrus_content.references_commands as commands

    client = support.RecordingMemory("knowledge-corpus-alpha-site")
    for row in report_rows():
        client.rows[("Reference", row["id"])] = row
    before = copy.deepcopy(client.rows)
    monkeypatch.setattr(commands, "create_authoring_client", lambda *args, **kwargs: (client, {}))
    commands.references_duplicates(["--format", "json"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["identity"]["groups"] == 1
    commands.references_duplicates(["--groups", "--skip-text-hashes"])
    assert "member\treference-held-1-v1" in capsys.readouterr().out
    assert client.writes == [] and client.rows == before
    with pytest.raises(ValueError):
        commands.references_duplicates(["--format", "xml"])


def test_the_identity_module_loads_from_the_router_zip_closure():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("monitoring_build", root / "infra/monitoring/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    modules = set(build.router_modules())
    assert {"reference_identity", "monitoring", "monitoring_intake", "assignments_workflow"} <= modules
    assert "reference_duplicates_report" not in modules
    import ast
    source = (root / "src/papyrus_content/reference_identity.py").read_text()
    imported = {node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "typing", "urllib.parse", "monitoring", "re"} | {None}
