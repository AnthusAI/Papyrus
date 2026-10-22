import pytest

from papyrus import cli
from .command import knowledge_cloud_run
from .config import STAGES, CloudRunConfig, ConfigError


def test_papyrus_knowledge_routes_archive_and_cloud_run(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_delegate_content", lambda group, command, flags: seen.append((group, command, flags)))
    cli._map_knowledge("archive", ["--as-of", "2026-10-26"])
    cli._map_knowledge("cloud-run", ["--stage", "snapshot"])
    assert seen == [("knowledge", "archive", ["--as-of", "2026-10-26"]), ("knowledge", "cloud-run", ["--stage", "snapshot"])]


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
