"""`papyrus references list|show` with no --corpus-key: a signed-in session uses the backend's canonical corpus, not the wheel's default."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from papyrus.operator import config as operator_config  # noqa: E402
from papyrus.operator.commands import references as reference_commands  # noqa: E402
from papyrus.operator.errors import OperatorError  # noqa: E402
from papyrus.operator.output import OperatorRow  # noqa: E402
from papyrus_content import steering  # noqa: E402

PACKAGED_DEFAULT = "packaged-default-corpus"


class HostedClient:
    def __init__(self, corpora):
        self.corpora = corpora
        self.tenant_id = None

    def list_by_index(self, index_name, key_value, **_kwargs):
        assert (index_name, key_value) == ("knowledgeCorporaByRoleAndName", "canonical")
        return self.corpora


class RecordingBackend:
    def __init__(self):
        self.corpus_keys = []

    def list_references(self, *, corpus_key, limit, status, order):
        self.corpus_keys.append(corpus_key)
        return [OperatorRow(kind="cloud-reference", status="pending", identifier="reference-1", title="A", extra={"corpus": corpus_key, "url": ""})]

    def show_reference(self, reference_id):
        raise AssertionError("not used")


@pytest.fixture
def empty_site(tmp_path, monkeypatch):
    """No checkout root, no operator config, no steering file of the site's own; the wheel's default is the only one."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(steering, "PAPYRUS_ROOT", tmp_path)
    monkeypatch.setattr(operator_config, "PAPYRUS_ROOT", tmp_path)
    monkeypatch.delenv("PAPYRUS_STEERING_CONFIG", raising=False)
    monkeypatch.delenv("PAPYRUS_OPERATOR_CONFIG", raising=False)
    monkeypatch.delenv("PAPYRUS_OPERATOR_FIXTURE_ROOT", raising=False)
    monkeypatch.setattr(operator_config, "_default_corpus_from_steering", lambda: PACKAGED_DEFAULT)
    monkeypatch.setattr(steering, "resolve_topics_steering_config_path", lambda: "corpora/papyrus-steering.yml")
    return tmp_path


def corpora(*keys):
    return [{"id": f"knowledge-corpus-{key}", "name": key.title(), "role": "canonical"} for key in keys]


def run_list(flags, *, signed_in, hosted, backend="cloud"):
    recorder = RecordingBackend()
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in), \
            mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(HostedClient(hosted), {})), \
            mock.patch.object(reference_commands, "create_backend", return_value=recorder):
        config = operator_config.load_operator_config(backend_override=backend, corpus_key_override=_flag(flags, "--corpus-key"))
        reference_commands.run_references_list(config, flags)
    return recorder.corpus_keys


def _flag(flags, name):
    return flags[flags.index(name) + 1] if name in flags else None


def test_a_signed_in_list_with_no_corpus_chosen_uses_the_backends_canonical_corpus(empty_site, capsys):
    assert run_list(["--limit", "2"], signed_in=True, hosted=corpora("ai-ml-research")) == ["ai-ml-research"]
    assert "corpusKey=ai-ml-research" in capsys.readouterr().out


def test_an_explicit_corpus_key_is_used_without_asking_the_backend(empty_site):
    assert run_list(["--corpus-key", "chosen-corpus"], signed_in=True, hosted=[]) == ["chosen-corpus"]


def test_a_backend_with_several_canonical_corpora_is_an_error_that_says_so(empty_site):
    with pytest.raises(OperatorError, match="--corpus-key"):
        run_list([], signed_in=True, hosted=corpora("one", "two"))


def test_a_backend_with_no_canonical_corpus_is_an_error_that_says_so(empty_site):
    with pytest.raises(OperatorError, match="does not name a single one"):
        run_list([], signed_in=True, hosted=[])


def test_the_iam_lane_keeps_the_packaged_default(empty_site):
    assert run_list([], signed_in=False, hosted=corpora("ai-ml-research")) == [PACKAGED_DEFAULT]


def test_a_steering_file_the_site_chose_still_wins_over_the_backend(empty_site, monkeypatch):
    monkeypatch.setenv("PAPYRUS_STEERING_CONFIG", str(empty_site / "site-steering.yml"))
    monkeypatch.setattr(operator_config, "_default_corpus_from_steering", lambda: "site-chosen-corpus")
    assert run_list([], signed_in=True, hosted=corpora("ai-ml-research")) == ["site-chosen-corpus"]


def test_the_operator_config_default_wins_over_the_backend(empty_site):
    (empty_site / "operator.yaml").write_text("defaultCorpusKey: configured-corpus\n")
    with mock.patch.dict("os.environ", {"PAPYRUS_OPERATOR_CONFIG": str(empty_site / "operator.yaml")}):
        assert run_list([], signed_in=True, hosted=corpora("ai-ml-research")) == ["configured-corpus"]


def test_the_packaged_default_alone_is_not_a_site_choice(empty_site):
    assert steering.steering_config_chosen_by_site() is False
    (empty_site / "corpora").mkdir()
    (empty_site / "corpora" / "papyrus-steering.yml").write_text("x: 1\n")
    assert steering.steering_config_chosen_by_site() is True
