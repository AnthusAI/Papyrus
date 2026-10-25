import json
from pathlib import Path

import pytest
from moto import mock_aws

from .config import STAGES, iso_week, monday_of
from .fakes import make_run
from .ledger import FAILED, SUCCEEDED
from .stages import StageFailed, run_stage

import datetime as dt


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for name, value in {"AWS_ACCESS_KEY_ID": "t", "AWS_SECRET_ACCESS_KEY": "t", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        yield


def commands(shell, prefix):
    return [call for call in shell.calls if call[: len(prefix)] == prefix]


def test_stages_end_with_projection_and_follow_the_runbook_order():
    assert STAGES == (
        "corpus-sync", "topic-model", "typed-extraction", "publish-run", "ai-review",
        "publish-relations", "snapshot", "archive", "wiki-sync", "projection",
    )


def test_iso_week_and_monday():
    assert iso_week(dt.date(2026, 10, 26)) == "2026-W44"
    assert monday_of(dt.date(2026, 10, 28)) == dt.date(2026, 10, 26)


def test_corpus_sync_exports_reindexes_extracts_and_uploads(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("corpus-sync", run) == 0
    assert commands(shell, ["papyrus", "knowledge", "corpus", "export"])
    assert commands(shell, ["biblicus", "init"]) and commands(shell, ["biblicus", "reindex"])
    assert run.read_state()["extraction"] == "ext1"
    assert run.state.read_text("corpus/raw/papyrus/item-1.md") == "# one"
    assert run.state.read_text("runs/2026-W44/state.json")


def test_the_site_is_checked_out_at_the_deployed_commit_and_nothing_else_is_accepted(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("snapshot", run) == 0
    fetch = commands(shell, ["git", "-C"])[0]
    assert "fetch" in fetch and "d" * 40 in fetch and "https://example.test/site.git" in fetch


def test_a_checkout_that_is_not_the_deployed_commit_is_refused(tmp_path):
    run, shell = make_run(tmp_path)
    shell.head = "b" * 40
    assert run_stage("snapshot", run) == 1
    assert run.ledger.status("snapshot") == FAILED
    assert not commands(shell, ["papyrus", "knowledge", "snapshot"])


def test_topic_model_carries_the_previous_run_id_from_state(tmp_path):
    run, shell = make_run(tmp_path)
    run.state.write_text("corpus/knowledge-run.json", json.dumps({"previousRunId": "prev123"}))
    run_stage("corpus-sync", run)
    assert run_stage("topic-model", run) == 0
    identity = commands(shell, ["biblicus", "analyze", "topic-identity"])[0]
    assert identity[identity.index("--previous") + 1] == "prev123"
    assert run.read_state()["current"] == shell.current


def test_the_first_run_has_no_previous(tmp_path):
    run, shell = make_run(tmp_path)
    run_stage("corpus-sync", run)
    run_stage("topic-model", run)
    assert "--previous" not in commands(shell, ["biblicus", "analyze", "topic-identity"])[0]


def test_publish_run_records_the_run_only_after_the_apply(tmp_path):
    run, shell = make_run(tmp_path)
    for stage in ("corpus-sync", "topic-model", "typed-extraction"):
        assert run_stage(stage, run) == 0
    assert run.state.read_text("corpus/knowledge-run.json") is None
    shell.fail_on = "--apply"
    assert run_stage("publish-run", run) == 1
    assert run.state.read_text("corpus/knowledge-run.json") is None
    shell.fail_on = None
    assert run_stage("publish-run", run) == 0
    record = json.loads(run.state.read_text("corpus/knowledge-run.json"))
    assert record["previousRunId"] == shell.current and record["runOn"] == "2026-10-26"


def test_typed_extraction_imports_front_matter_then_uses_the_registry_and_vocabulary(tmp_path):
    run, shell = make_run(tmp_path)
    for stage in ("corpus-sync", "topic-model"):
        run_stage(stage, run)
    assert run_stage("typed-extraction", run) == 0
    names = [call[2:4] for call in shell.calls if call[:2] == ["papyrus", "knowledge"]]
    assert ["publish-run", "--auth"] in names
    registry = commands(shell, ["papyrus", "knowledge", "entities", "registry"])[0]
    assert "--vocabulary" in registry
    assert commands(shell, ["biblicus", "extract", "typed-entities"])


def test_archive_uses_the_snapshot_options_and_never_replaces(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("snapshot", run) == 0
    assert run_stage("archive", run) == 0
    snapshot = commands(shell, ["papyrus", "knowledge", "snapshot"])[0]
    archive = commands(shell, ["papyrus", "knowledge", "archive"])[0]
    assert snapshot[3:] == archive[3:]
    assert archive[archive.index("--as-of") + 1] == "2026-10-26"
    assert "--replace" not in archive and "--reproject" not in snapshot
    assert archive[archive.index("--concept-kinds") + 1] == "task,concept"


def test_wiki_publish_does_not_trigger_a_projection(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("wiki-sync", run) == 0
    publish = commands(shell, ["papyrus", "knowledge", "wiki", "publish"])[0]
    assert "--no-trigger" in publish and "--apply" in publish
    assert publish[publish.index("--actor") + 1] == "ai"


def test_projection_never_allows_deletions(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("projection", run) == 0
    project = commands(shell, ["papyrus", "ops", "content", "project"])[0]
    assert "--all" in project and "--allow-deletions" not in project
    assert run.ledger.status("projection") == SUCCEEDED


def test_a_stage_that_succeeded_in_this_execution_is_skipped(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("snapshot", run) == 0
    before = len(shell.calls)
    assert run_stage("snapshot", run) == 0
    assert len(shell.calls) == before


def test_another_execution_of_the_same_week_runs_the_stage_again(tmp_path):
    first, shell = make_run(tmp_path)
    run_stage("snapshot", first)
    second, other_shell = make_run(tmp_path / "second", execution="scheduled-2")
    assert run_stage("snapshot", second) == 0
    assert commands(other_shell, ["papyrus", "knowledge", "snapshot"])


def test_a_failing_command_fails_the_stage_and_the_ledger_says_so(tmp_path):
    run, shell = make_run(tmp_path)
    shell.fail_on = "knowledge archive"
    assert run_stage("archive", run) == 1
    assert run.ledger.status("archive") == FAILED


def test_an_injected_failure_is_honoured_only_by_a_test_execution(tmp_path):
    run, shell = make_run(tmp_path / "t", {"KNOWLEDGE_FAIL_STAGE": "snapshot"}, execution="test-fail-1")
    assert run_stage("snapshot", run) == 1
    assert not commands(shell, ["papyrus", "knowledge", "snapshot"])
    scheduled, shell2 = make_run(tmp_path / "s", {"KNOWLEDGE_FAIL_STAGE": "snapshot"}, execution="weekly-2026-10-26")
    assert run_stage("snapshot", scheduled) == 0
    off, shell3 = make_run(tmp_path / "o", {"KNOWLEDGE_FAIL_STAGE": "snapshot", "KNOWLEDGE_ALLOW_TEST_FAILURE": "false"}, execution="test-x")
    assert run_stage("snapshot", off) == 0


class FakeClient:
    def __init__(self, nodes):
        self.nodes = nodes

    def list_records(self, model):
        return self.nodes if model == "SemanticNode" else []

    def list_published_item_summaries(self):
        return []

    def list_semantic_relations_by_object_state(self, _state):
        return []

    def list_semantic_relations_by_subject_state(self, _state):
        return []


class FakeServices:
    def __init__(self, nodes, answers):
        self.client, self.answers, self.key_parameter = FakeClient(nodes), answers, None

    def api_key(self, parameter):
        self.key_parameter = parameter
        return "test-key"

    def record_client(self, _options):
        return self.client

    def model(self, api_key, guidance):
        from .ai_review_test import Model

        return Model(self.answers)


def test_ai_review_reads_the_key_from_ssm_applies_only_evidenced_decisions_and_logs_them(tmp_path, monkeypatch):
    run, shell = make_run(tmp_path)
    for stage in ("corpus-sync", "topic-model", "typed-extraction"):
        run_stage(stage, run)
    from .ai_review_test import TEXT, TYPED, node

    typed_dir = run.run_dir / "typed"
    typed_dir.mkdir(parents=True, exist_ok=True)
    (typed_dir / "output.json").write_text(json.dumps(TYPED))
    texts = run.corpus / "extracted" / "pipeline" / "ext1" / "text"
    texts.mkdir(parents=True)
    (texts / "i1.txt").write_text(TEXT)
    run.push(corpus=True, run=True)
    applied = []
    monkeypatch.setattr("papyrus_content.records.apply_record_changes", lambda client, changes: applied.extend(changes))
    quote = "OpenBMB released VoxCPM2, a 2B-parameter text-to-speech model"
    run.services = FakeServices(
        [node("VoxCPM2"), node("27B")],
        {"VoxCPM2": {"verdict": "accept", "evidence": [quote]}, "27B": {"verdict": "reject", "reason": "a size"}},
    )
    assert run_stage("ai-review", run) == 0
    assert run.services.key_parameter == "/papyrus/shipped/openai-api-key"
    assert sorted(change["expected"]["status"] for change in applied) == ["accepted", "rejected"]
    log = json.loads(run.state.read_text("runs/2026-W44/ai-review.json"))
    assert log["model"] == "gpt-6-luna" and log["summary"]["entity.accept.applied"] == 1
    assert "test-key" not in json.dumps(log)


def test_projection_fails_before_writing_when_the_plugins_differ_from_the_deployed_site(tmp_path):
    run, shell = make_run(tmp_path)
    run.services.variables["PAPYRUS_PLUGINS"] = "reader-steering"
    assert run_stage("projection", run) == 1
    assert not commands(shell, ["papyrus", "ops", "content", "project"])
    assert "newsletter" in (run.ledger.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#manual-1#projection"})["Item"]["error"])


def test_every_site_writing_stage_checks_the_plugins(tmp_path):
    for stage in ("snapshot", "archive", "projection"):
        run, shell = make_run(tmp_path / stage)
        run.services.variables["PAPYRUS_PLUGINS"] = ""
        assert run_stage(stage, run) == 1, stage
        assert not [call for call in shell.calls if call[:2] == ["papyrus", "knowledge"] or call[:3] == ["papyrus", "ops", "content"]], stage


def test_the_plugin_order_does_not_matter_and_the_commands_receive_the_list(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("projection", run) == 0
    assert run.command_env()["PAPYRUS_PLUGINS"] == "newsletter,reader-steering"


def test_the_plugin_check_needs_the_function_name(tmp_path):
    run, shell = make_run(tmp_path, {"KNOWLEDGE_CONTENT_ACTIONS_FUNCTION": ""})
    assert run_stage("snapshot", run) == 1


def test_no_stage_ever_reconciles_replaces_or_deletes(tmp_path):
    for index, stage in enumerate(STAGES):
        if stage == "ai-review":
            continue
        run, shell = make_run(tmp_path / str(index))
        for earlier in STAGES[: STAGES.index(stage)]:
            if earlier != "ai-review":
                run_stage(earlier, run)
        run_stage(stage, run)
        text = " ".join(" ".join(call) for call in shell.calls)
        for forbidden in ("--reconcile", "--allow-deletions", "--replace", "delete"):
            assert forbidden not in text, (stage, forbidden)


def test_without_an_amplify_app_the_site_is_the_branch_tip_and_a_moved_tip_is_refused(tmp_path):
    run, shell = make_run(tmp_path, {"KNOWLEDGE_AMPLIFY_APP_ID": ""})
    assert run_stage("snapshot", run) == 0
    stale, shell = make_run(tmp_path / "stale", {"KNOWLEDGE_AMPLIFY_APP_ID": ""}, execution="manual-2")
    shell.tip = "b" * 40
    assert run_stage("snapshot", stale) == 1


def test_projection_runs_the_papyrus_the_site_pins(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("projection", run) == 0
    install = commands(shell, ["pip", "install"])[0]
    assert "--no-deps" in install and install[-1].endswith("requirements-publication.txt")
    assert commands(shell, ["python", "-c"])[0][2] == "import papyrus_content.projection.lease"


def test_a_pin_without_the_projection_lease_stops_the_projection_before_it_writes(tmp_path):
    run, shell = make_run(tmp_path)
    shell.fail_on = "projection.lease"
    assert run_stage("projection", run) == 1
    assert not commands(shell, ["papyrus", "ops", "content", "project"])
    error = run.ledger.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#manual-1#projection"})["Item"]["error"]
    assert "projection lease" in error


def test_a_site_without_a_pin_cannot_be_projected(tmp_path):
    run, shell = make_run(tmp_path)
    run.clone_site()
    (run.site / "requirements-publication.txt").write_text("boto3\n")
    assert run_stage("projection", run) == 1
    assert not commands(shell, ["papyrus", "ops", "content", "project"])


ENTRY = "_data/knowledge/history/2026-10-26.json"


def test_an_already_archived_week_is_kept_recorded_in_the_ledger_and_the_command_is_not_run(tmp_path):
    run, shell = make_run(tmp_path)
    run.services.objects[ENTRY] = json.dumps({"asOf": "2026-10-26", "runId": "run9da9"}).encode()
    assert run_stage("archive", run) == 0
    assert not commands(shell, ["papyrus", "knowledge", "archive"])
    details = run.ledger.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#manual-1#archive"})["Item"]["details"]
    assert details["archive"] == "kept-existing (run run9da9)"


@pytest.mark.parametrize("stored", [b"{not json", b"[]", b"{}", json.dumps({"asOf": "2026-10-19", "runId": "x"}).encode()])
def test_an_unreadable_or_mismatched_entry_fails_the_stage_and_is_never_replaced(tmp_path, stored):
    run, shell = make_run(tmp_path)
    run.services.objects[ENTRY] = stored
    assert run_stage("archive", run) == 1
    assert not commands(shell, ["papyrus", "knowledge", "archive"])
    assert run.ledger.status("archive") == FAILED


def test_a_week_without_an_entry_is_archived(tmp_path):
    run, shell = make_run(tmp_path)
    assert run_stage("archive", run) == 0
    assert commands(shell, ["papyrus", "knowledge", "archive"])
    assert "--replace" not in commands(shell, ["papyrus", "knowledge", "archive"])[0]


def test_the_projection_report_is_found_among_other_output_and_logged(tmp_path, capsys):
    from .stages import first_json_object

    noisy = 'knowledge\tauth\tiam\thost\n{"written": 3, "deleted": 0, "errors": []}\nProjected: 3 written, 0 deleted\n'
    assert first_json_object(noisy) == {"written": 3, "deleted": 0, "errors": []}
    pretty = '{\n  "written": 3,\n  "deleted": 0\n}\ntrailing line\n'
    assert first_json_object(pretty)["written"] == 3
    metric = '{"_aws": {"Timestamp": 1, "CloudWatchMetrics": []}, "InvalidatedPaths": 1}'
    assert first_json_object(metric + '\n{\n  "ok": true,\n  "written": 1196,\n  "deleted": 0\n}\n')["written"] == 1196
    with pytest.raises(StageFailed):
        first_json_object("no report here")
    with pytest.raises(StageFailed):
        first_json_object(metric)


def test_the_projection_stage_logs_its_report_and_records_the_counts(tmp_path, capsys):
    run, shell = make_run(tmp_path)
    assert run_stage("projection", run) == 0
    assert 'projection report: {"written": 3, "deleted": 0}' in capsys.readouterr().out
    details = run.ledger.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#manual-1#projection"})["Item"]["details"]
    assert details["written"] == 3 and details["deleted"] == 0


# -- monitor records: opt-in, exported as data in corpus-sync, read from the run's file by every later stage -----------------
MONITORED = {"KNOWLEDGE_MONITOR_SOURCES": "huggingface", "KNOWLEDGE_MONITOR_WEEKS": "26"}


def test_a_site_without_monitor_sources_runs_exactly_as_before(tmp_path):
    run, shell = make_run(tmp_path)
    for stage in ("corpus-sync", "topic-model", "typed-extraction", "publish-run", "snapshot", "archive", "wiki-sync"):
        assert run_stage(stage, run) == 0
    assert not [call for call in shell.calls if any(argument.startswith("--monitor") for argument in call)]
    assert run.config.monitor_sources == ()


def test_corpus_sync_exports_the_monitor_records_dated_for_the_week_and_keeps_the_file_in_the_run_state(tmp_path):
    run, shell = make_run(tmp_path, MONITORED)
    assert run_stage("corpus-sync", run) == 0
    [export] = commands(shell, ["papyrus", "knowledge", "corpus", "export"])
    assert export[export.index("--monitor-sources") + 1] == "huggingface"
    assert export[export.index("--monitor-weeks") + 1] == "26"
    assert export[export.index("--corpus-key") + 1] == "shipped"
    assert export[export.index("--as-of") + 1] == "2026-10-26"
    assert json.loads(run.state.read_text("runs/2026-W44/monitor-records.json"))["sources"] == ["huggingface"]


def test_every_later_stage_counts_the_records_from_the_runs_file_even_in_a_fresh_container(tmp_path):
    first, _ = make_run(tmp_path / "first", MONITORED)
    assert run_stage("corpus-sync", first) == 0
    fresh, shell = make_run(tmp_path / "fresh", MONITORED)
    for stage in ("topic-model", "typed-extraction", "publish-run", "snapshot", "archive", "wiki-sync"):
        assert run_stage(stage, fresh) == 0
    expected = str(tmp_path / "fresh" / "runs" / "2026-W44" / "monitor-records.json")
    for prefix in (
        ["papyrus", "knowledge", "publish-run"], ["papyrus", "knowledge", "snapshot"], ["papyrus", "knowledge", "archive"], ["papyrus", "knowledge", "wiki", "sync"],
    ):
        found = commands(shell, prefix)
        assert found, prefix
        assert all(call[call.index("--monitor-records") + 1] == expected for call in found), prefix
    assert Path(expected).exists()


def test_a_monitor_source_the_run_does_not_know_is_refused_before_anything_runs(tmp_path):
    from .config import ConfigError

    with pytest.raises(ConfigError, match="KNOWLEDGE_MONITOR_SOURCES: Unsupported monitor source 'rss'"):
        make_run(tmp_path, {"KNOWLEDGE_MONITOR_SOURCES": "rss"})
