import json
from pathlib import Path

import pytest

from .reference_feed_keys import feed_keys, star_feed_key
from .tenant_knowledge_keys import (REFERENCE_FEED_KEY, TenantKeyError, corpus_id_for_key, corpus_key_of, global_key, is_corpus_id, key_tenant,
                                    tenant_corpus_id)
from .tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE, TenantError

TENANT_VECTORS = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "reference-feed-key-vectors.json").read_text())["tenant"]


def _environment(monkeypatch, vector):
    monkeypatch.delenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    if vector["mode"] == "shared":
        monkeypatch.setenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, "shared")
    if vector["environmentTenantId"]:
        monkeypatch.setenv("PAPYRUS_TENANT_ID", vector["environmentTenantId"])


def _run(vector):
    tenant, value = vector["tenantId"], vector["input"]
    call = vector["call"]
    if call == "globalKey":
        return global_key(value, tenant)
    if call == "corpusId":
        return tenant_corpus_id(value, tenant)
    if call == "corpusIdForKey":
        return corpus_id_for_key(value, tenant)
    if call == "corpusKeyOf":
        return corpus_key_of(value)
    if call == "feedKeys":
        return {key: found for key, found in feed_keys(value).items() if key in vector["key"]}
    if call == "starFeedKey":
        return star_feed_key(value["corpusId"], value["stars"])
    raise AssertionError(f"unknown call {call}")


def test_the_tenant_vectors_the_typescript_twin_is_tested_against(monkeypatch):
    for vector in TENANT_VECTORS:
        _environment(monkeypatch, vector)
        if vector.get("refused"):
            with pytest.raises(TenantError):
                _run(vector)
        else:
            assert _run(vector) == vector["key"], vector["name"]


def test_a_shared_stack_with_no_tenant_names_what_to_pass(monkeypatch):
    monkeypatch.setenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, "shared")
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    with pytest.raises(TenantKeyError, match="PAPYRUS_TENANT_ID"):
        global_key(REFERENCE_FEED_KEY)
    with pytest.raises(TenantKeyError):
        key_tenant()


def test_a_dedicated_stack_never_reads_or_validates_a_tenant(monkeypatch):
    monkeypatch.delenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setenv("PAPYRUS_TENANT_ID", "alpha")
    assert key_tenant("not a tenant") is None
    assert global_key("references") == "references"
    assert tenant_corpus_id("knowledge-corpus-demo") == "knowledge-corpus-demo"


def test_a_corpus_id_in_either_form_is_recognised_and_reduced_to_its_key():
    assert is_corpus_id("knowledge-corpus-demo") and is_corpus_id("alpha.knowledge-corpus-demo")
    assert not is_corpus_id("demo") and not is_corpus_id("alpha.demo")
    assert corpus_key_of("demo") == "demo"


def _shared(monkeypatch, tenant=None):
    monkeypatch.setenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, "shared")
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    if tenant:
        monkeypatch.setenv("PAPYRUS_TENANT_ID", tenant)


def test_own_corpora_keeps_every_row_on_a_dedicated_stack_and_the_tenants_on_a_shared_one(monkeypatch):
    rows = [{"id": "alpha.knowledge-corpus-a"}, {"id": "beta.knowledge-corpus-b"}, {"id": "knowledge-corpus-old"}]
    from .tenant_knowledge_keys import own_corpora
    monkeypatch.delenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, raising=False)
    assert own_corpora(rows, "alpha") == rows
    _shared(monkeypatch)
    assert own_corpora(rows, "alpha") == [{"id": "alpha.knowledge-corpus-a"}]
    with pytest.raises(TenantKeyError):
        own_corpora(rows)


def test_a_concept_lineage_id_carries_the_tenant_on_a_shared_stack_only(monkeypatch):
    from .ids import semantic_node_lineage_id_for
    monkeypatch.delenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, raising=False)
    assert semantic_node_lineage_id_for("concept:ai", "alpha") == "semantic-node-concept-ai"
    _shared(monkeypatch)
    assert semantic_node_lineage_id_for("concept:ai", "alpha") == "alpha.semantic-node-concept-ai"
    assert semantic_node_lineage_id_for("concept:ai", "beta") != semantic_node_lineage_id_for("concept:ai", "alpha")


def test_a_corpus_id_from_a_corpus_config_is_tenant_unique_on_a_shared_stack(monkeypatch):
    from .ids import knowledge_corpus_id
    monkeypatch.delenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, raising=False)
    assert knowledge_corpus_id({"key": "Demo Site"}, "alpha") == "knowledge-corpus-demo-site"
    _shared(monkeypatch)
    assert knowledge_corpus_id({"key": "Demo Site"}, "alpha") == "alpha.knowledge-corpus-demo-site"
    with pytest.raises(TenantKeyError):
        knowledge_corpus_id({"key": "Demo Site"})


def test_the_catalog_writes_every_global_key_of_a_new_reference_through_the_builder(monkeypatch):
    from .catalog import reference_record
    item = {"item_id": "lead", "title": "T", "source_uri": "https://example.test/a", "curation_status": "accepted"}
    context = {"corpusId": "alpha.knowledge-corpus-demo", "importRunId": "run", "now": "2026-11-13T12:00:00Z", "tenantId": "alpha"}
    _shared(monkeypatch)
    row = reference_record(item, context)["expected"]
    assert (row["newsroomFeedKey"], row["reviewedFeedKey"]) == ("alpha#references", "alpha#references#reviewed")
    assert row["curationStatusKey"].startswith("alpha.knowledge-corpus-demo#")
    monkeypatch.delenv(TENANCY_MODE_ENVIRONMENT_VARIABLE)
    plain = reference_record(item, {**context, "corpusId": "knowledge-corpus-demo"})["expected"]
    assert (plain["newsroomFeedKey"], plain["reviewedFeedKey"]) == ("references", "references#reviewed")
