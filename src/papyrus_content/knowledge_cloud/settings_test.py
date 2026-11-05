"""The settings a site commits for its knowledge run (settings.py): where they come from, which copy wins, and what the log says."""

import pytest
from moto import mock_aws

from .fakes import make_run
from .settings import SettingsError
from .stages import run_stage

COMMITTED = {
    "vocabulary.yml": "description: a publication about harbour logistics\nentity_kinds:\n  - {key: vessel, label: ship}\n",
    "stop-words.txt": "harbour\n",
    "review-guidance.md": "Prefer named vessels.\n",
}


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for name, value in {"AWS_ACCESS_KEY_ID": "t", "AWS_SECRET_ACCESS_KEY": "t", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        yield


def test_committed_settings_fill_config_and_the_log_says_so(tmp_path, capsys):
    run, _ = make_run(tmp_path, settings=COMMITTED)
    assert run_stage("corpus-sync", run) == 0
    for name, text in COMMITTED.items():
        assert (run.config_dir / name).read_text() == text
    log = capsys.readouterr().out
    assert log.count("config/vocabulary.yml: committed settings") == 1
    assert "config/stop-words.txt: committed settings" in log and "config/review-guidance.md: committed settings" in log


def test_a_file_the_site_did_not_commit_is_none_or_the_generic_default(tmp_path, capsys):
    run, _ = make_run(tmp_path, settings={"stop-words.txt": "harbour\n"})
    run_stage("corpus-sync", run)
    assert "key: organization," in (run.config_dir / "vocabulary.yml").read_text()
    assert not (run.config_dir / "review-guidance.md").exists()
    log = capsys.readouterr().out
    assert "config/vocabulary.yml: generic default" in log and "config/review-guidance.md: none" in log


def test_an_old_copy_in_the_run_state_never_overrides_the_committed_settings_and_is_reported(tmp_path, capsys):
    run, _ = make_run(tmp_path, settings=COMMITTED)
    run.state.write_text("config/vocabulary.yml", "entity_kinds:\n  - {key: stale, label: old}\n")
    run.state.write_text("config/stop-words.txt", "stale\n")
    run_stage("corpus-sync", run)
    assert "key: vessel" in (run.config_dir / "vocabulary.yml").read_text()
    assert (run.config_dir / "stop-words.txt").read_text() == "harbour\n"
    log = capsys.readouterr().out
    assert "config/vocabulary.yml: committed settings" in log
    assert "no longer reads: stop-words.txt, vocabulary.yml" in log


def test_without_committed_settings_an_old_copy_in_the_run_state_is_not_used_either(tmp_path, capsys):
    run, _ = make_run(tmp_path, seeded=False)
    run.state.write_text("config/vocabulary.yml", "entity_kinds:\n  - {key: stale, label: old}\n")
    run_stage("corpus-sync", run)
    assert "key: stale" not in (run.config_dir / "vocabulary.yml").read_text()
    log = capsys.readouterr().out
    assert "config/vocabulary.yml: generic default" in log and "no longer reads: vocabulary.yml" in log


def test_the_stop_words_and_the_vocabulary_reach_the_commands_that_use_them(tmp_path):
    run, shell = make_run(tmp_path, settings=COMMITTED)
    for stage in ("corpus-sync", "topic-model"):
        assert run_stage(stage, run) == 0
    topic = next(call for call in shell.calls if call[:3] == ["papyrus", "knowledge", "topic-config"])
    assert topic[topic.index("--stop-words") + 1] == str(run.config_dir / "stop-words.txt")


def test_a_missing_archive_fails_the_stage_instead_of_running_on_the_default(tmp_path):
    run, _ = make_run(tmp_path, settings=COMMITTED)
    run.services.assets.clear()
    with pytest.raises(SettingsError, match="not there"):
        run.pull()


def test_a_file_that_is_not_a_settings_file_is_refused(tmp_path):
    run, _ = make_run(tmp_path, settings={**COMMITTED, "notes.txt": "x"})
    with pytest.raises(SettingsError, match="notes.txt"):
        run.pull()


def test_the_committed_vocabularies_of_the_sites_with_job_stacks_are_valid():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3] / "infra" / "amplify-app-shell" / "examples" / "knowledge-run-settings"
    from ..knowledge_snapshot.registry import read_vocabulary_kinds

    found = sorted(path for path in root.glob("*/vocabulary.yml"))
    assert [path.parent.name for path in found] == ["machines-on-machines", "shipped"]
    for path in found:
        document = yaml.safe_load(path.read_text())
        assert document["publication"] == path.parent.name
        assert read_vocabulary_kinds(path) and document["relation_types"]
