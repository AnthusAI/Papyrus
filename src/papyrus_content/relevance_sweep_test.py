"""The decide-relevance command will not seed a site's store from a doctrine file it did not name."""
from types import SimpleNamespace
from unittest import mock

import pytest

from papyrus_content import cli
from papyrus_content.newsroom_doctrine import DEFAULT_PUBLICATION_DOCTRINE_PATH

STEERING = {"relevanceCyclotron": {"corpusKey": "other-site"}, "publication": {"name": "Other Site"}}
SWEEP_RESULT = SimpleNamespace(applied=True, pending=[], sample=None, decided=0, reviews=0, primed=0,
                               priming_failed=0, status={}, auto_rejected=[], warnings=[],
                               to_json=lambda: {"applied": True})


@pytest.fixture
def sweep():
    """Stands in for everything past argument handling, and records whether it was reached."""
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(object(), None)) as client, \
         mock.patch("papyrus_content.steering.require_steering_config", return_value=STEERING), \
         mock.patch("papyrus_content.relevance_sweep.require_corpus_config", return_value={}), \
         mock.patch("papyrus_content.relevance_sweep.relevance_corpus_key", return_value="other-site"), \
         mock.patch("papyrus_content.relevance_sweep.knowledge_corpus_id", return_value="other-site-corpus"), \
         mock.patch("papyrus_content.relevance_sweep.run_decide_relevance", return_value=SWEEP_RESULT) as run:
        yield SimpleNamespace(client=client, run=run)


@pytest.fixture
def other_doctrine(tmp_path):
    path = tmp_path / "other-doctrine.yml"
    path.write_text("schemaVersion: 1\ndoctrine:\n  - kind: mission\n    body:\n      - Other Site covers local gardening.\n"
                    "  - kind: policy\n    body:\n      - Be kind.\n", encoding="utf-8")
    return path


def test_apply_without_an_explicit_doctrine_exits_before_any_write_or_model_call(sweep, capsys):
    exit_code = cli.main(["references", "decide-relevance", "--apply"])

    assert exit_code != 0
    error = capsys.readouterr().err
    assert "--doctrine" in error
    assert "Threat Intelligence" in error
    sweep.client.assert_not_called()
    sweep.run.assert_not_called()


def test_apply_with_a_bare_doctrine_flag_is_still_refused(sweep):
    assert cli.main(["references", "decide-relevance", "--apply", "--doctrine"]) != 0
    sweep.run.assert_not_called()


def test_apply_with_an_explicit_doctrine_proceeds_and_uses_that_file(sweep, other_doctrine, capsys):
    exit_code = cli.main(["references", "decide-relevance", "--apply", "--doctrine", str(other_doctrine)])

    assert exit_code == 0
    sweep.run.assert_called_once()
    assert sweep.run.call_args.args[2] == [{"kind": "mission", "body": ["Other Site covers local gardening."]},
                                           {"kind": "policy", "body": ["Be kind."]}]
    assert "explicit" in capsys.readouterr().out


def test_dry_run_reports_the_default_doctrine_path_and_first_mission_line(sweep, capsys):
    sweep.run.return_value = SimpleNamespace(**{**vars(SWEEP_RESULT), "applied": False})

    exit_code = cli.main(["references", "decide-relevance"])

    assert exit_code == 0
    line = next(line for line in capsys.readouterr().out.splitlines() if "\tdoctrine\t" in line)
    assert str(DEFAULT_PUBLICATION_DOCTRINE_PATH.resolve()) in line
    assert "default" in line
    assert "Anthus Threat Intelligence publishes" in line
    assert sweep.run.call_args.kwargs["apply"] is False


def test_dry_run_reports_an_explicit_doctrine_path(sweep, other_doctrine, capsys):
    sweep.run.return_value = SimpleNamespace(**{**vars(SWEEP_RESULT), "applied": False})

    cli.main(["references", "decide-relevance", "--doctrine", str(other_doctrine)])

    line = next(line for line in capsys.readouterr().out.splitlines() if "\tdoctrine\t" in line)
    assert str(other_doctrine.resolve()) in line
    assert "Other Site covers local gardening." in line
