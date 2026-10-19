import pytest

from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.site_cyclotron import (build_site_cyclotron, newsroom_sections_of_tenant,
                                            section_fit_classifier_id, tenant_site_cyclotron_steering)
from papyrus_content.site_sweep import site_sweep_assignment_id
from papyrus_content.site_sweep_test import CYCLOTRON_ID, SECTIONS, prepared, references, section, sweep
from papyrus_content.tenant_section_ids_test import InMemoryNewsroomSectionBackend, section_record
from features_backend.steps.cyclotron_relevance_sweep_steps import SweepClient


def tenant_sections_client(backend, tenant_id):
    client = PapyrusGraphQLAuthoringClient(endpoint="https://example.invalid/graphql",
                                           header_factory=lambda payload: {}, tenant_id=tenant_id)
    client.graphql = backend
    return client


def decided_classifier_ids(client, cyclotron_id):
    return {relation["classifierId"] for relation in client.list_records("SemanticRelation")
            if relation.get("predicate") == "site_decision_is" and relation["classifierId"].startswith(f"{cyclotron_id}/")}


def test_without_a_tenant_the_steering_config_is_returned_untouched(tmp_path):
    steering = prepared(tmp_path)
    assert tenant_site_cyclotron_steering(steering, None) is steering


def test_a_tenant_gets_its_own_cyclotron_id_local_store_and_s3_prefix(tmp_path):
    steering = prepared(tmp_path)
    alpha = tenant_site_cyclotron_steering(steering, "alpha")["siteCyclotron"]
    beta = tenant_site_cyclotron_steering(steering, "beta")["siteCyclotron"]
    assert alpha["cyclotronId"] == f"{CYCLOTRON_ID}-alpha"
    assert alpha["store"]["localPath"].endswith("site-cyclotron-alpha")
    assert alpha["store"]["s3Prefix"] == "s3://example-private-media/cyclotrons/papyrus-sections-alpha"
    assert beta["cyclotronId"] != alpha["cyclotronId"]
    assert beta["store"] != alpha["store"]
    assert steering["siteCyclotron"]["cyclotronId"] == CYCLOTRON_ID
    assert site_sweep_assignment_id(alpha["cyclotronId"]) != site_sweep_assignment_id(beta["cyclotronId"])


def test_a_tenants_sections_come_from_its_own_newsroom_section_rows():
    backend = InMemoryNewsroomSectionBackend()
    alpha, beta = tenant_sections_client(backend, "alpha"), tenant_sections_client(backend, "beta")
    for key in ("security", "cloud"):
        alpha.upsert("NewsroomSection", section_record(key, key.title()))
    beta.upsert("NewsroomSection", section_record("policy", "Policy"))
    assert sorted(row["id"] for row in newsroom_sections_of_tenant(alpha, "alpha")) == ["cloud", "security"]
    assert [row["id"] for row in newsroom_sections_of_tenant(beta, "beta")] == ["policy"]


def test_a_tenant_without_sections_is_refused_with_the_command_that_seeds_them():
    with pytest.raises(ValueError, match="import-sections --tenant gamma"):
        newsroom_sections_of_tenant(tenant_sections_client(InMemoryNewsroomSectionBackend(), "gamma"), "gamma")


def test_two_tenants_with_different_sections_each_get_a_cyclotron_with_only_their_own_sections(tmp_path):
    steering = prepared(tmp_path)
    alpha_sections = [section("security", 1), section("cloud", 2)]
    beta_sections = [section("security", 1), section("policy", 2)]
    alpha_plan = build_site_cyclotron(tenant_site_cyclotron_steering(steering, "alpha"), alpha_sections)
    beta_plan = build_site_cyclotron(tenant_site_cyclotron_steering(steering, "beta"), beta_sections)
    alpha_classifiers = {spec.id for spec in alpha_plan.definition.classifiers}
    beta_classifiers = {spec.id for spec in beta_plan.definition.classifiers}
    assert section_fit_classifier_id("cloud") in alpha_classifiers - beta_classifiers
    assert section_fit_classifier_id("policy") in beta_classifiers - alpha_classifiers
    assert alpha_plan.local_path != beta_plan.local_path


def test_each_tenants_sweep_decides_with_only_its_own_sections_and_leaves_the_other_tenants_decisions_current(tmp_path):
    steering = prepared(tmp_path)
    alpha_steering = tenant_site_cyclotron_steering(steering, "alpha")
    beta_steering = tenant_site_cyclotron_steering(steering, "beta")
    client = SweepClient({"Reference": references()})
    sweep(alpha_steering, client, tmp_path, sections=[section("security", 1), section("cloud", 2)])
    alpha_decisions = decided_classifier_ids(client, f"{CYCLOTRON_ID}-alpha")
    sweep(beta_steering, client, tmp_path, sections=[section("security", 1), section("policy", 2)])
    assert decided_classifier_ids(client, f"{CYCLOTRON_ID}-alpha") == alpha_decisions
    beta_decisions = decided_classifier_ids(client, f"{CYCLOTRON_ID}-beta")
    assert f"{CYCLOTRON_ID}-alpha/{section_fit_classifier_id('cloud')}" in alpha_decisions
    assert f"{CYCLOTRON_ID}-beta/{section_fit_classifier_id('policy')}" in beta_decisions
    assert f"{CYCLOTRON_ID}-beta/{section_fit_classifier_id('cloud')}" not in beta_decisions
    assert f"{CYCLOTRON_ID}-alpha/{section_fit_classifier_id('policy')}" not in alpha_decisions
    assert decided_classifier_ids(client, CYCLOTRON_ID) == set()
    current = [relation for relation in client.list_records("SemanticRelation")
               if relation.get("predicate") == "site_decision_is" and relation["relationState"] == "current"]
    assert all(relation["classifierId"].startswith((f"{CYCLOTRON_ID}-alpha/", f"{CYCLOTRON_ID}-beta/")) for relation in current)
    assert {name for name in client.tables["Assignment"]} >= {site_sweep_assignment_id(f"{CYCLOTRON_ID}-alpha"),
                                                              site_sweep_assignment_id(f"{CYCLOTRON_ID}-beta")}
