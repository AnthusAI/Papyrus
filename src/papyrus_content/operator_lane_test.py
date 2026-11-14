"""``require_operator_lane``: an operator command says so up front on the signed-in lane (PPY-a89c4d)."""
from __future__ import annotations

from unittest import mock

import pytest

from .operator_errors import OperatorError, require_operator_lane


def test_signed_in_write_is_refused_with_the_lane_named(capsys):
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True):
        with pytest.raises(OperatorError) as raised:
            require_operator_lane("references backfill-medium", "Reference records", writing=True)
    message = str(raised.value)
    assert "references backfill-medium is an operator command" in message
    assert "PAPYRUS_GRAPHQL_AUTH=iam" in message and message.endswith("Nothing was changed.")
    assert capsys.readouterr().out == ""


def test_signed_in_preview_prints_one_notice_and_goes_on(capsys):
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True):
        require_operator_lane("references backfill-medium", "Reference records", writing=False)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and "\toperator-lane\tnotice\t" in lines[0] and "only reads" in lines[0]


@pytest.mark.parametrize("writing", [True, False])
def test_operator_lane_is_silent(capsys, writing):
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=False):
        require_operator_lane("references backfill-medium", "Reference records", writing=writing)
    assert capsys.readouterr().out == ""
