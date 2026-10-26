import pytest

from papyrus import cli
import datetime as dt

from .command import knowledge_cloud_run, latest_successful_commit
from .config import STAGES, CloudRunConfig, ConfigError


def test_papyrus_knowledge_routes_archive_and_cloud_run(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_delegate_content", lambda group, command, flags: seen.append((group, command, flags)))
    cli._map_knowledge("archive", ["--as-of", "2026-10-26"])
    cli._map_knowledge("cloud-run", ["--stage", "snapshot"])
    cli._map_knowledge("runs", ["--site", "shipped"])
    assert seen == [("knowledge", "archive", ["--as-of", "2026-10-26"]), ("knowledge", "cloud-run", ["--stage", "snapshot"]), ("knowledge", "runs", ["--site", "shipped"])]


def test_an_unknown_stage_is_refused():
    with pytest.raises(ValueError, match="--stage must be one of"):
        knowledge_cloud_run(["--stage", "make-coffee"])
    assert "projection" in STAGES


def test_missing_environment_names_the_variable():
    with pytest.raises(ConfigError, match="KNOWLEDGE_STATE_BUCKET"):
        CloudRunConfig.from_environment({"KNOWLEDGE_PUBLICATION": "shipped"})


def test_the_openai_key_parameter_defaults_to_the_publications_ssm_parameter():
    from .fakes import ENVIRONMENT

    assert CloudRunConfig.from_environment(ENVIRONMENT).openai_parameter == "/papyrus/shipped/openai-api-key"


def test_the_deployed_commit_is_that_of_the_successful_job_that_ended_last_whatever_the_order():
    def job(job_id, status, commit, minute):
        return {"jobId": job_id, "status": status, "commitId": commit, "endTime": dt.datetime(2026, 10, 22, 14, minute, tzinfo=dt.timezone.utc)}

    jobs = [
        job("55", "RUNNING", "c55", 59),  # not finished: not live
        job("54", "SUCCEED", "c1b449", 58),  # newest id, ended last: live
        job("53", "SUCCEED", "cdfc0a", 40),
        job("52", "SUCCEED", "cdfc0a", 30),
        job("56", "FAILED", "cfailed", 59),
    ]
    assert latest_successful_commit(jobs, "app", "main") == "c1b449"
    # out of order: the job with the greater id ended earlier (a long build overtaken by a short one)
    reordered = [job("60", "SUCCEED", "slow", 10), job("61", "SUCCEED", "fast", 20)]
    assert latest_successful_commit(reordered, "app", "main") == "fast"
    assert latest_successful_commit(list(reversed(reordered)), "app", "main") == "fast"


def test_no_successful_deploy_is_an_error():
    import pytest

    with pytest.raises(ValueError, match="No successful Amplify deploy"):
        latest_successful_commit([{"jobId": "1", "status": "FAILED", "commitId": "x", "endTime": dt.datetime.now(dt.timezone.utc)}], "app", "main")
