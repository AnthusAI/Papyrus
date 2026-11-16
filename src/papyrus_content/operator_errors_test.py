import sys

from papyrus_content.operator_errors import report_failure_and_exit_code, sso_token_guidance


def _token_error():
    from botocore.exceptions import TokenRetrievalError

    return TokenRetrievalError(provider="sso", error_msg="Token has expired and refresh failed")


def test_a_botocore_sso_token_failure_names_the_two_fixes_and_prints_no_traceback(monkeypatch, capsys):
    monkeypatch.setenv("AWS_PROFILE", "papyrus-production")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/aws")
    text = sso_token_guidance(_token_error())
    assert "credential_process = aws configure export-credentials --profile papyrus-production" in text and "aws sso login --profile papyrus-production" in text
    assert report_failure_and_exit_code(_token_error()) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_without_the_aws_command_only_the_sign_in_is_offered(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "p")
    monkeypatch.setattr("shutil.which", lambda name: None)
    text = sso_token_guidance(_token_error())
    assert "aws sso login --profile p" in text and "credential_process" not in text


def test_any_other_error_is_left_alone():
    assert sso_token_guidance(RuntimeError("boom")) is None
