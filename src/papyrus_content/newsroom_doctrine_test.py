"""Writing a publication's doctrine needs the file named; describing a choice reports the file and its mission."""
from unittest import mock

import pytest

from papyrus_content import cli
from papyrus_content.newsroom_doctrine import (DEFAULT_PUBLICATION_DOCTRINE_PATH, describe_doctrine_choice,
                                               require_explicit_doctrine)


def test_a_writing_run_without_the_flag_is_refused_in_plain_language_naming_the_flag():
    with pytest.raises(ValueError) as error:
        require_explicit_doctrine({}, "references decide-relevance --apply")

    message = str(error.value)
    assert "--doctrine <path>" in message
    assert "Threat Intelligence" in message
    assert "references decide-relevance --apply" in message


def test_a_flag_without_a_value_does_not_count_as_naming_a_file():
    with pytest.raises(ValueError):
        require_explicit_doctrine({"doctrine": True}, "references decide-relevance --apply")


def test_a_named_doctrine_file_is_accepted():
    require_explicit_doctrine({"doctrine": "corpora/x.yml"}, "references decide-relevance --apply")


def test_describing_no_file_reports_the_default_and_its_first_mission_line():
    choice = describe_doctrine_choice()

    assert choice["isDefault"] is True
    assert choice["path"] == str(DEFAULT_PUBLICATION_DOCTRINE_PATH.resolve())
    assert choice["firstMissionLine"].startswith("Anthus Threat Intelligence publishes")


def test_import_doctrine_without_a_config_file_exits_before_any_write(capsys):
    with mock.patch("papyrus_content.newsroom_commands.create_authoring_client") as client:
        exit_code = cli.main(["newsroom", "import-doctrine"])

    assert exit_code != 0
    assert "--config" in capsys.readouterr().err
    client.assert_not_called()
