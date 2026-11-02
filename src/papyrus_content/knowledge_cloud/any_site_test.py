"""A knowledge run on any site: the corpus key, the generic defaults for a new site, and a site with nothing in it yet."""

import json
from pathlib import Path

import pytest
from moto import mock_aws

from .config import STAGES
from .fakes import APPSYNC_ENDPOINT, make_run
from .stages import run_stage

TESTDATA = Path(__file__).parent / "testdata"
NEW_SITE = {"KNOWLEDGE_PUBLICATION": "newsite", "KNOWLEDGE_APPSYNC_API_ID": "abcdefghij0123456789klmnop", "KNOWLEDGE_BEATS_CONFIG": "", "KNOWLEDGE_CONCEPT_KINDS": ""}


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for name, value in {"AWS_ACCESS_KEY_ID": "t", "AWS_SECRET_ACCESS_KEY": "t", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        yield


def commands(shell, prefix):
    return [call for call in shell.calls if call[: len(prefix)] == prefix]


def value_of(call, flag):
    return call[call.index(flag) + 1]


def all_stages(run):
    return {stage: run_stage(stage, run) for stage in STAGES}


def details(run, stage):
    return run.ledger.table.get_item(Key={"publication": run.config.publication, "runKey": f"2026-W44#manual-1#{stage}"})["Item"]


def without_ai_review(run):
    return {stage: run_stage(stage, run) for stage in STAGES if stage != "ai-review"}


# -- Shipped is unchanged -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("golden, environment", [
    ("shipped_commands.json", None),
    ("shipped_commands_monitor.json", {"KNOWLEDGE_MONITOR_SOURCES": "huggingface"}),
])
def test_a_site_with_its_config_in_place_runs_exactly_the_commands_it_always_ran(tmp_path, golden, environment):
    run, shell = make_run(tmp_path, environment)
    assert set(without_ai_review(run).values()) == {0}
    recorded = [[argument.replace(str(tmp_path), "<work>") for argument in call] for call in shell.calls]
    assert recorded == json.loads((TESTDATA / golden).read_text())


def test_the_corpus_key_is_the_publication_unless_the_site_says_otherwise(tmp_path):
    run, shell = make_run(tmp_path, {"KNOWLEDGE_MONITOR_SOURCES": "routed"})
    assert run.config.corpus_key == "shipped"
    without_ai_review(run)
    keys = [value_of(call, "--corpus-key") for call in shell.calls if "--corpus-key" in call]
    assert keys and set(keys) == {"shipped"}


def test_a_corpus_key_of_its_own_reaches_every_command_that_names_the_corpus(tmp_path):
    run, shell = make_run(tmp_path, {"KNOWLEDGE_CORPUS_KEY": "ai-ml-research", "KNOWLEDGE_MONITOR_SOURCES": "routed"})
    assert run.config.corpus_key == "ai-ml-research" and run.config.publication == "shipped"
    without_ai_review(run)
    export = commands(shell, ["papyrus", "knowledge", "corpus", "export"])[0]
    imports = commands(shell, ["papyrus", "knowledge", "publish-run"])
    assert value_of(export, "--corpus-key") == "ai-ml-research"
    assert len(imports) == 5  # typed-extraction (dry run, apply), publish-run (dry run, apply), publish-relations
    assert {value_of(call, "--corpus-key") for call in imports} == {"ai-ml-research"}
    assert "shipped" not in [value_of(call, "--corpus-key") for call in shell.calls if "--corpus-key" in call]


def test_a_corpus_key_of_its_own_changes_nothing_else(tmp_path):
    plain, plain_shell = make_run(tmp_path / "a", {"KNOWLEDGE_MONITOR_SOURCES": "routed"})
    other, other_shell = make_run(tmp_path / "b", {"KNOWLEDGE_MONITOR_SOURCES": "routed", "KNOWLEDGE_CORPUS_KEY": "ai-ml-research"}, execution="manual-2")
    without_ai_review(plain)
    without_ai_review(other)

    def normal(shell, root):
        return [[argument.replace(str(root), "<work>").replace("ai-ml-research", "shipped") for argument in call] for call in shell.calls]

    assert normal(plain_shell, tmp_path / "a") == normal(other_shell, tmp_path / "b")
    assert other.state.prefix == "publications/shipped/" and other.config.actor_name == "Shipped research agent"


# -- a new site needs none of the operator's files ------------------------------------------------------------------------
def test_a_new_site_without_a_vocabulary_gets_the_generic_one_and_keeps_it_in_its_state(tmp_path):
    run, shell = make_run(tmp_path, NEW_SITE, seeded=False)
    assert run.state.read_text("config/vocabulary.yml") is None
    assert run_stage("corpus-sync", run) == 0 and run_stage("topic-model", run) == 0 and run_stage("typed-extraction", run) == 0
    registry = commands(shell, ["papyrus", "knowledge", "entities", "registry"])[0]
    assert Path(value_of(registry, "--vocabulary")).read_text().count("- {key: ") >= 4
    seeded = run.state.read_text("config/vocabulary.yml")
    assert seeded is not None and "publication: newsite" in seeded
    for kind in ("organization", "product", "person", "topic"):
        assert f"key: {kind}," in seeded
    from ..knowledge_snapshot.registry import read_vocabulary_kinds

    assert read_vocabulary_kinds(run.config_dir / "vocabulary.yml") == ["organization", "product", "person", "topic"]
    typed = commands(shell, ["biblicus", "extract", "typed-entities"])[0]
    assert value_of(typed, "--vocabulary") == str(run.config_dir / "vocabulary.yml")


def test_a_vocabulary_the_operator_wrote_is_never_replaced(tmp_path):
    run, shell = make_run(tmp_path, NEW_SITE)
    run_stage("corpus-sync", run)
    assert "key: maker" in run.state.read_text("config/vocabulary.yml")
    assert "organization" not in (run.config_dir / "vocabulary.yml").read_text()


def test_the_endpoint_file_holds_the_address_appsync_reports_for_the_api_id_when_the_state_has_none(tmp_path):
    run, shell = make_run(tmp_path, NEW_SITE, seeded=False)
    assert run_stage("corpus-sync", run) == 0
    outputs = json.loads(run.state.read_text("config/amplify_outputs.json"))
    assert outputs == {"data": {"url": APPSYNC_ENDPOINT}}
    assert run.command_env()["PAPYRUS_GRAPHQL_ENDPOINT"] == outputs["data"]["url"]


def test_without_an_api_id_nothing_is_invented_for_the_endpoint(tmp_path):
    run, shell = make_run(tmp_path, {**NEW_SITE, "KNOWLEDGE_APPSYNC_API_ID": ""}, seeded=False)
    run_stage("corpus-sync", run)
    assert run.state.read_text("config/amplify_outputs.json") is None


def test_a_new_site_without_beats_or_concept_kinds_snapshots_with_neither(tmp_path):
    run, shell = make_run(tmp_path, NEW_SITE, seeded=False)
    assert set(without_ai_review(run).values()) == {0}
    for prefix in (["papyrus", "knowledge", "snapshot"], ["papyrus", "knowledge", "archive"], ["papyrus", "knowledge", "wiki", "sync"]):
        for call in commands(shell, prefix):
            assert "--beats-config" not in call and "--concept-kinds" not in call, call


def test_a_beats_file_the_site_names_but_does_not_have_is_skipped_not_fatal(tmp_path, capsys):
    run, shell = make_run(tmp_path, {**NEW_SITE, "KNOWLEDGE_BEATS_CONFIG": "web/not-there.json"}, seeded=False)
    assert run_stage("snapshot", run) == 0
    assert "--beats-config" not in commands(shell, ["papyrus", "knowledge", "snapshot"])[0]
    assert "continuing without beats" in capsys.readouterr().out


def test_a_beats_file_that_exists_is_still_used(tmp_path):
    run, shell = make_run(tmp_path, {"KNOWLEDGE_BEATS_CONFIG": "web/scoring.json"})
    assert run_stage("snapshot", run) == 0
    assert value_of(commands(shell, ["papyrus", "knowledge", "snapshot"])[0], "--beats-config").endswith("site/web/scoring.json")


# -- a site with nothing in it yet ---------------------------------------------------------------------------------------
def test_a_site_with_no_items_and_no_records_succeeds_every_stage_with_nothing_to_do(tmp_path):
    run, shell = make_run(tmp_path, NEW_SITE, seeded=False)
    shell.items = 0
    assert all_stages(run) == {stage: 0 for stage in STAGES}
    for stage in STAGES[1:]:
        assert not [call for call in shell.calls if call[:3] == ["biblicus", "analyze", "topics"]]
    assert not commands(shell, ["biblicus", "extract", "typed-entities"])
    assert not commands(shell, ["papyrus", "knowledge", "publish-run"])
    assert not commands(shell, ["papyrus", "knowledge", "snapshot"])
    assert not commands(shell, ["papyrus", "ops", "content", "project"]), "nothing is projected for a run that found nothing"
    for stage in STAGES:
        row = details(run, stage)
        assert row["status"] == "succeeded", stage
        assert json.loads(json.dumps(row["details"], default=str))["status"] == "nothing to do", stage


def test_an_empty_run_still_records_what_it_cost(tmp_path):
    run, shell = make_run(tmp_path, NEW_SITE, seeded=False)
    shell.items = 0
    all_stages(run)
    for stage in STAGES:
        assert details(run, stage)["details"]["cost"]["computeUsd"] > 0, stage
    total = json.loads(run.state.read_text("runs/2026-W44/cost-manual-1.json"))
    assert total["cost"]["totalUsd"] > 0 and total["publication"] == "newsite"


def test_a_site_that_gains_its_first_item_runs_the_whole_pipeline_the_next_time(tmp_path):
    run, shell = make_run(tmp_path, NEW_SITE, seeded=False)
    shell.items = 0
    assert run_stage("corpus-sync", run) == 0 and run.read_state()["empty"] is True
    shell.items = 1
    again, again_shell = make_run(tmp_path, {**NEW_SITE, "KNOWLEDGE_EXECUTION_NAME": "manual-2"}, seeded=False)
    assert run_stage("corpus-sync", again) == 0
    assert again.read_state()["empty"] is False and again.read_state()["documents"] == 1
    assert commands(again_shell, ["biblicus", "extract", "build"])


def test_monitor_records_without_items_are_still_imported_and_counted_but_not_modelled(tmp_path):
    run, shell = make_run(tmp_path, {**NEW_SITE, "KNOWLEDGE_MONITOR_SOURCES": "routed"}, seeded=False)
    shell.items, shell.records = 0, 2
    assert all_stages(run) == {stage: 0 for stage in STAGES}
    assert run.read_state()["empty"] is False and run.read_state()["documents"] == 0
    assert not commands(shell, ["biblicus", "analyze", "topics"]) and not commands(shell, ["biblicus", "extract", "typed-entities"])
    imports = commands(shell, ["papyrus", "knowledge", "publish-run"])
    assert imports and all("--identity" not in call and "--entities" not in call for call in imports)
    assert all("--monitor-records" in call for call in imports)
    assert commands(shell, ["papyrus", "knowledge", "snapshot"]) and commands(shell, ["papyrus", "ops", "content", "project"])
    assert not (run.corpus / "knowledge-run.json").exists(), "no topic run was imported, so there is no previous run to carry"
    assert details(run, "topic-model")["details"]["status"] == "nothing to do"
