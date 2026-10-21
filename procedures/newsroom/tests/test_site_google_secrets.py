"""`papyrus site google-secrets set|check` against fake STS, SSM, CloudFormation, Amplify and Cognito clients."""
import datetime
import io
import json

import pytest

from papyrus import cli
from papyrus.operator import site_google_secrets as gs
from papyrus_content.operator_errors import OperatorError

ACCOUNT = "123456789012"
APP_ID = "dtestapp0001"
CLIENT_ID = "1234567890-abcdefgh.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-not-a-real-secret-value"
PATH = gs.branch_secret_path(APP_ID, "main")


class ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeAws:
    """One object that is the session and every client, recording calls."""

    def __init__(self, account=ACCOUNT, stack_app_id=APP_ID, apps=(), idp_client_id=None, domain_pool="pool-1", env_vars=None):
        self.account = account
        self.stack_app_id = stack_app_id
        self.apps = list(apps)
        self.idp_client_id = idp_client_id
        self.domain_pool = domain_pool
        self.env_vars = env_vars or {}
        self.parameters = {}
        self.puts = []
        self.session_args = None

    def factory(self, profile, region):
        self.session_args = (profile, region)
        return self

    def client(self, name):
        return {"sts": self, "ssm": self, "cloudformation": self, "amplify": self, "cognito-idp": self}[name]

    def get_caller_identity(self):
        return {"Account": self.account}

    def describe_stacks(self, StackName):
        if self.stack_app_id is None:
            raise ClientError("ValidationError")
        return {"Stacks": [{"Outputs": [{"OutputKey": "CmsAppId", "OutputValue": self.stack_app_id}]}]}

    def list_apps(self, **_):
        return {"apps": self.apps}

    def get_branch(self, appId, branchName):
        return {"branch": {"environmentVariables": self.env_vars}}

    def put_parameter(self, Name, Value, Type, Overwrite):
        assert Type == "SecureString" and Overwrite is True
        self.puts.append(Name)
        self.parameters[Name] = {"Name": Name, "Value": Value, "Type": Type, "Version": len(self.puts),
                                 "LastModifiedDate": datetime.datetime(2026, 10, 21, 12, 0, tzinfo=datetime.timezone.utc)}

    def get_parameter(self, Name, WithDecryption):
        assert WithDecryption
        if Name not in self.parameters:
            raise ClientError("ParameterNotFound")
        return {"Parameter": self.parameters[Name]}

    def describe_user_pool_domain(self, Domain):
        return {"DomainDescription": {"UserPoolId": self.domain_pool} if self.domain_pool else {}}

    def describe_identity_provider(self, UserPoolId, ProviderName):
        if self.idp_client_id is None:
            raise ClientError("ResourceNotFoundException")
        return {"IdentityProvider": {"ProviderDetails": {"client_id": self.idp_client_id, "client_secret": "never-shown"}}}


@pytest.fixture(autouse=True)
def fake_boto_errors(monkeypatch):
    monkeypatch.setattr(gs, "_aws_errors", lambda: (ClientError,))


class Tty(io.StringIO):
    def __init__(self, text="", tty=True):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


def make_site(tmp_path, **overrides):
    site = {
        "siteId": "demo",
        "stackName": "amplify-app-shell-demo-cms",
        "cms": {"cognitoDomainPrefix": "papyrus-demo-cms", "applyCognitoDomainPrefix": True},
        "aws": {"profile": "demo-profile", "accountId": ACCOUNT, "region": "us-west-2"},
    }
    site.update(overrides)
    (tmp_path / "infra").mkdir(exist_ok=True)
    (tmp_path / "infra" / "site.json").write_text(json.dumps(site))
    return tmp_path


def run(tmp_path, aws, args, stdin=None, env=None, prompts=(CLIENT_ID, CLIENT_SECRET)):
    out = io.StringIO()
    answers = iter(prompts)
    code = gs.command(args, env=env or {}, cwd=tmp_path, out=out, stdin=stdin or Tty(),
                      input_fn=lambda _: next(answers), getpass_fn=lambda _: next(answers), session_factory=aws.factory)
    return code, out.getvalue()


def test_path_matches_the_documented_amplify_hash():
    assert gs.branch_secret_path("d11eu9hbs2mipk", "main") == "/amplify/d11eu9hbs2mipk/main-branch-3c5f57c311"


def test_set_writes_both_securestrings_and_confirms_by_fingerprint_only(tmp_path):
    make_site(tmp_path)
    aws = FakeAws()
    code, text = run(tmp_path, aws, ["set"])
    assert code == 0
    assert aws.puts == [f"{PATH}/GOOGLE_CLIENT_ID", f"{PATH}/GOOGLE_CLIENT_SECRET"]
    assert aws.session_args == ("demo-profile", "us-west-2")
    assert CLIENT_SECRET not in text and CLIENT_ID not in text
    assert gs.fingerprint(CLIENT_SECRET) in text and "matches what you entered" in text
    assert "https://papyrus-demo-cms.auth.us-west-2.amazoncognito.com" in text
    assert "https://papyrus-demo-cms.auth.us-west-2.amazoncognito.com/oauth2/idpresponse" in text
    assert "redeploy" in text and "start-job" in text
    assert "PAPYRUS_DISABLE_GOOGLE_OAUTH" in text


def test_set_refuses_a_wrong_account_before_any_write(tmp_path):
    make_site(tmp_path)
    aws = FakeAws(account="999999999999")
    with pytest.raises(OperatorError, match="Wrong AWS account"):
        run(tmp_path, aws, ["set"])
    assert aws.puts == []


def test_set_refuses_without_an_expected_account(tmp_path):
    make_site(tmp_path, aws={})
    aws = FakeAws()
    with pytest.raises(OperatorError, match="No expected AWS account"):
        run(tmp_path, aws, ["set"])
    assert aws.session_args is None


def test_account_flag_overrides_site_json_and_profile_falls_back_to_env(tmp_path):
    make_site(tmp_path, aws={})
    aws = FakeAws(account="555555555555")
    run(tmp_path, aws, ["set", "--account", "555555555555"], env={"AWS_PROFILE": "from-env", "AWS_REGION": "eu-west-1"})
    assert aws.session_args == ("from-env", "eu-west-1")


def test_set_from_flag_and_stdin_never_prompts(tmp_path):
    make_site(tmp_path)
    aws = FakeAws()
    code, _ = run(tmp_path, aws, ["set", "--client-id", CLIENT_ID, "--secret-stdin"], stdin=Tty(CLIENT_SECRET + "\n", tty=False), prompts=())
    assert code == 0
    assert aws.parameters[f"{PATH}/GOOGLE_CLIENT_SECRET"]["Value"] == CLIENT_SECRET
    assert aws.parameters[f"{PATH}/GOOGLE_CLIENT_ID"]["Value"] == CLIENT_ID


def test_there_is_no_secret_argument(tmp_path):
    make_site(tmp_path)
    with pytest.raises(OperatorError, match="usage|Usage"):
        run(tmp_path, FakeAws(), ["set", "--secret", CLIENT_SECRET])


def test_secret_stdin_needs_a_client_id_and_prompting_needs_a_terminal(tmp_path):
    make_site(tmp_path)
    with pytest.raises(OperatorError, match="--client-id"):
        run(tmp_path, FakeAws(), ["set", "--secret-stdin"], stdin=Tty(CLIENT_SECRET, tty=False))
    with pytest.raises(OperatorError, match="No terminal"):
        run(tmp_path, FakeAws(), ["set"], stdin=Tty(tty=False))


@pytest.mark.parametrize("client_id,secret,fragment", [("nope", CLIENT_SECRET, "client id"), (CLIENT_ID, "not-a-secret", "client secret")])
def test_set_validates_shapes_without_echoing_values_or_writing(tmp_path, client_id, secret, fragment):
    make_site(tmp_path)
    aws = FakeAws()
    with pytest.raises(OperatorError, match=fragment) as raised:
        run(tmp_path, aws, ["set"], prompts=(client_id, secret))
    assert secret not in str(raised.value) and aws.puts == []


def test_app_id_falls_back_to_lookup_by_app_name(tmp_path):
    make_site(tmp_path)
    aws = FakeAws(stack_app_id=None, apps=[{"name": "other", "appId": "dother"}, {"name": "demo-cms", "appId": APP_ID}])
    run(tmp_path, aws, ["set"])
    assert aws.puts[0].startswith(f"/amplify/{APP_ID}/")


def test_app_id_not_found_is_an_operator_error(tmp_path):
    make_site(tmp_path)
    with pytest.raises(OperatorError, match="Could not find the CMS app"):
        run(tmp_path, FakeAws(stack_app_id=None), ["check"])


def test_branch_changes_the_secret_path(tmp_path):
    make_site(tmp_path)
    aws = FakeAws()
    run(tmp_path, aws, ["set", "--branch", "staging"])
    assert aws.puts[0] == f"{gs.branch_secret_path(APP_ID, 'staging')}/GOOGLE_CLIENT_ID"


def test_generated_cognito_domain_comes_from_amplify_outputs(tmp_path):
    make_site(tmp_path, cms={"cognitoDomainPrefix": "unused"})
    (tmp_path / "amplify_outputs.json").write_text(json.dumps({"auth": {"oauth": {"domain": "69a74c507e157f784c3c.auth.us-west-2.amazoncognito.com"}}}))
    _, text = run(tmp_path, FakeAws(), ["set"])
    assert "https://69a74c507e157f784c3c.auth.us-west-2.amazoncognito.com/oauth2/idpresponse" in text


def test_generated_cognito_domain_without_outputs_says_where_to_read_it(tmp_path):
    make_site(tmp_path, cms={"cognitoDomainPrefix": "unused"})
    _, text = run(tmp_path, FakeAws(), ["set"])
    assert "oauthCognitoDomain" in text and "unused" not in text


def store(aws, client_id=CLIENT_ID):
    aws.put_parameter(f"{PATH}/GOOGLE_CLIENT_ID", client_id, "SecureString", True)
    aws.put_parameter(f"{PATH}/GOOGLE_CLIENT_SECRET", CLIENT_SECRET, "SecureString", True)


def test_check_healthy_when_parameters_exist_and_the_provider_matches(tmp_path):
    make_site(tmp_path)
    aws = FakeAws(idp_client_id=CLIENT_ID)
    store(aws)
    writes_before = len(aws.puts)
    code, text = run(tmp_path, aws, ["check"])
    assert code == 0 and len(aws.puts) == writes_before
    assert "present" in text and "2026-10-21T12:00:00" in text
    assert "client id matches the stored one" in text
    assert gs.fingerprint(CLIENT_ID) in text
    assert CLIENT_SECRET not in text and CLIENT_ID not in text and "never-shown" not in text
    assert "oauth2/idpresponse" in text and "PAPYRUS_DISABLE_GOOGLE_OAUTH" in text


def test_check_reports_a_different_deployed_client_id(tmp_path):
    make_site(tmp_path)
    aws = FakeAws(idp_client_id="9999-other.apps.googleusercontent.com")
    store(aws)
    code, text = run(tmp_path, aws, ["check"])
    assert code == 1 and "DIFFERS" in text and "9999-other" not in text


def test_check_reports_missing_parameters_and_a_missing_provider(tmp_path):
    make_site(tmp_path)
    code, text = run(tmp_path, FakeAws(idp_client_id=None), ["check"])
    assert code == 1
    assert text.count("MISSING") == 2
    assert "no Google identity provider" in text


def test_check_reports_the_disable_switch_state(tmp_path):
    make_site(tmp_path)
    _, text = run(tmp_path, FakeAws(env_vars={"PAPYRUS_DISABLE_GOOGLE_OAUTH": "1"}), ["check"])
    assert "PAPYRUS_DISABLE_GOOGLE_OAUTH: set to '1' on branch main" in text


def test_check_refuses_a_wrong_account(tmp_path):
    make_site(tmp_path)
    with pytest.raises(OperatorError, match="Wrong AWS account"):
        run(tmp_path, FakeAws(account="999999999999"), ["check"])


def test_missing_site_config_is_an_operator_error(tmp_path):
    with pytest.raises(OperatorError, match="No site config"):
        run(tmp_path, FakeAws(), ["check"])


def test_papyrus_cli_routes_site_and_prints_help(capsys):
    assert cli.main(["site", "google-secrets", "--help"]) == 0
    assert "papyrus site google-secrets" in capsys.readouterr().out
    assert cli.main(["site"]) == 0
    assert "google-secrets" in capsys.readouterr().out
