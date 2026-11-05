"""papyrus stories share / shares / share-revoke (features_backend/story-share-links.feature)."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from papyrus_content import story_share_commands as commands
from papyrus_content.operator_errors import OperatorError

TOKEN = "T" * 43


class Recorder:
    endpoint = "https://appsync.example/graphql"

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def graphql(self, document, variables):
        self.calls.append((document, json.loads(variables["input"])))
        field = document.split("{ ", 1)[1].split("(")[0]
        return {field: json.dumps(self.answer)}


def run(function, flags, answer=None, signed_in=True):
    recorder = Recorder(answer or {"ok": True})
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in), \
         mock.patch.object(commands, "create_authoring_client", return_value=(recorder, {})), \
         mock.patch.object(commands, "_origin", return_value="https://console.example.org"):
        function(flags)
    return recorder


def test_share_defaults_to_anyone_current_version_and_thirty_days(capsys):
    made = {"ok": True, "path": f"/api/share/{TOKEN}", "share": {"shareId": "abc", "version": "current", "expiresAt": "2026-12-04T12:00:00Z"}}
    recorder = run(commands.stories_share, ["--story", "item-1"], made)
    assert recorder.calls == [(commands.CREATE, {"lineageId": "item-1", "viewers": "anyone", "expiresInDays": 30})]
    printed = capsys.readouterr().out
    assert printed.count(f"https://console.example.org/api/share/{TOKEN}") == 1 and "shown once" in printed


def test_share_can_pin_a_version_require_sign_in_and_choose_the_expiry(capsys):
    made = {"ok": True, "path": f"/api/share/{TOKEN}", "share": {"shareId": "abc", "version": 3, "expiresAt": "x"}}
    recorder = run(commands.stories_share, ["--story", "item-1", "--version", "3", "--signed-in", "--expires", "90"], made)
    assert recorder.calls[0][1] == {"lineageId": "item-1", "viewers": "signed-in", "expiresInDays": 90, "version": 3}
    assert "editor or admin" in capsys.readouterr().out


@pytest.mark.parametrize("expires", ["0", "1", "31", "365", "never", "-7", "7.5", ""])
def test_there_is_no_link_that_never_expires(expires):
    with pytest.raises(ValueError):
        run(commands.stories_share, ["--story", "item-1", "--expires", expires])


@pytest.mark.parametrize("version", ["0", "-1", "two", "1.5"])
def test_a_version_is_a_saved_version_number(version):
    with pytest.raises(ValueError):
        run(commands.stories_share, ["--story", "item-1", "--version", version])


def test_dry_run_asks_nothing_and_prints_the_plan(capsys):
    recorder = run(commands.stories_share, ["--story", "item-1", "--dry-run", "--json"])
    assert recorder.calls == []
    assert json.loads(capsys.readouterr().out) == {"ok": True, "dryRun": True, "wouldShare": {"lineageId": "item-1", "viewers": "anyone", "version": "current", "expiresInDays": 30}}
    recorder = run(commands.stories_share_revoke, ["--story", "item-1", "--share", "abc", "--dry-run"])
    assert recorder.calls == [] and "dry run" in capsys.readouterr().out


def test_the_story_is_required():
    with pytest.raises(ValueError):
        run(commands.stories_share, [])


def test_without_a_signed_in_session_it_says_how_to_sign_in_and_asks_nothing():
    with pytest.raises(OperatorError, match="papyrus login"):
        run(commands.stories_share, ["--story", "item-1"], signed_in=False)
    with pytest.raises(OperatorError):
        run(commands.stories_shares, ["--story", "item-1"], signed_in=False)


def test_a_refusal_from_the_newsroom_is_reported_in_its_words():
    refusal = {"ok": False, "errors": [{"code": "share-refused", "message": "Only editors and admins can share a draft."}]}
    with pytest.raises(OperatorError, match="Only editors and admins"):
        run(commands.stories_share, ["--story", "item-1"], refusal)


def test_shares_lists_the_links_and_never_a_url(capsys):
    shares = [{"shareId": "abc", "state": "active", "createdBy": "Ed", "viewers": "anyone", "version": "current", "expiresAt": "2026-12-04T12:00:00Z", "lastOpenedOn": None, "openCount": 0}]
    run(commands.stories_shares, ["--story", "item-1"], {"ok": True, "shares": shares})
    printed = capsys.readouterr().out
    assert "abc" in printed and "by Ed" in printed and "last opened never" in printed and "http" not in printed and "/api/share/" not in printed


def test_share_revoke_names_the_story_and_the_share(capsys):
    recorder = run(commands.stories_share_revoke, ["--story", "item-1", "--share", "abc"], {"ok": True, "changed": True, "share": {}})
    assert recorder.calls == [(commands.REVOKE, {"lineageId": "item-1", "shareId": "abc"})]
    assert "revoked" in capsys.readouterr().out
    with pytest.raises(ValueError):
        run(commands.stories_share_revoke, ["--story", "item-1"])
