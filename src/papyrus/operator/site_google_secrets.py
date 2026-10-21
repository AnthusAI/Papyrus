"""`papyrus site google-secrets set|check`: the Google OAuth client id and secret of a site's CMS app.

Amplify's `secret("GOOGLE_CLIENT_ID")` and `secret("GOOGLE_CLIENT_SECRET")` (amplify/auth/resource.ts) read SSM
SecureStrings at `/amplify/<appId>/<branch>-branch-<hash>/<NAME>`, where `<hash>` is the first 10 hex digits of
sha512(appId + branch). This command writes and inspects exactly those two parameters.

It never prints a value (fingerprints only) and never enables or disables Google OAuth: that switch is the
`PAPYRUS_DISABLE_GOOGLE_OAUTH` branch variable, which the template owns.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from papyrus_content.operator_errors import OperatorError

CLIENT_ID_NAME = "GOOGLE_CLIENT_ID"
CLIENT_SECRET_NAME = "GOOGLE_CLIENT_SECRET"
CLIENT_ID_SUFFIX = ".apps.googleusercontent.com"
CLIENT_SECRET_PREFIX = "GOCSPX-"
DEFAULT_SITE_PATH = Path("infra") / "site.json"
DEFAULT_REGION = "us-east-1"
DISABLE_SWITCH = "PAPYRUS_DISABLE_GOOGLE_OAUTH"

USAGE = """\
Usage: papyrus site google-secrets <set|check> [options]

Run from a site repository. Reads infra/site.json for the CMS app, branch secrets path and Cognito domain.

  set     Store the Google client id and secret as the CMS app's Amplify secrets (SSM SecureString)
  check   Report whether both parameters exist, their fingerprints, and whether the deployed Cognito
          Google provider uses the same client id. Shows no values.

Options:
  --site PATH        Site config (default infra/site.json)
  --profile NAME     AWS profile (default: site.json aws.profile, then AWS_PROFILE)
  --account ID       Expected AWS account, asserted with STS before anything else (default: site.json aws.accountId)
  --region NAME      AWS region (default: site.json aws.region, then AWS_REGION, then us-east-1)
  --app-id ID        Amplify CMS app id (default: the stack's CmsAppId output, then lookup by app name)
  --branch NAME      Amplify branch whose secrets are used (default main)

set only:
  --client-id ID     Google client id (otherwise prompted, visible)
  --secret-stdin     Read the client secret from stdin (otherwise prompted, hidden). Requires --client-id.
                     There is deliberately no --secret argument: it would land in shell history.

This command does not enable or disable Google OAuth. If the site sets PAPYRUS_DISABLE_GOOGLE_OAUTH,
the backend ignores these secrets until the variable is removed.
"""


def fingerprint(value: str) -> str:
    """First 12 hex digits of sha256: enough to compare two values, useless for recovering one."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def branch_secret_path(app_id: str, branch: str) -> str:
    digest = hashlib.sha512(f"{app_id}{branch}".encode("utf-8")).hexdigest()[:10]
    return f"/amplify/{app_id}/{branch}-branch-{digest}"


@dataclass(frozen=True)
class Site:
    site_id: str
    stack_name: str
    cms_app_name: str
    cognito_prefix: str
    apply_prefix: bool
    aws_profile: str | None
    aws_account: str | None
    aws_region: str | None
    root: Path


def load_site(site_path: Path) -> Site:
    if not site_path.is_file():
        raise OperatorError(f"No site config at {site_path}. Run from a site repository, or pass --site <path to infra/site.json>.")
    try:
        raw = json.loads(site_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise OperatorError(f"{site_path} is not valid JSON: {error.msg} (line {error.lineno}).") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("siteId"), str):
        raise OperatorError(f"{site_path} is not a site config (no siteId).")
    cms = raw.get("cms")
    if not isinstance(cms, dict):
        raise OperatorError(f"{site_path} has no cms block: this site has no CMS app to hold Google secrets.")
    aws = raw.get("aws") if isinstance(raw.get("aws"), dict) else {}
    site_id = raw["siteId"]
    return Site(
        site_id=site_id,
        stack_name=raw.get("stackName") or f"amplify-app-shell-{site_id}",
        cms_app_name=cms.get("appName") or f"{site_id}-cms",
        cognito_prefix=str(cms.get("cognitoDomainPrefix") or ""),
        apply_prefix=cms.get("applyCognitoDomainPrefix") is True,
        aws_profile=aws.get("profile"),
        aws_account=aws.get("accountId"),
        aws_region=aws.get("region"),
        root=site_path.resolve().parent.parent,
    )


@dataclass
class Context:
    site: Site
    session: Any
    account: str
    region: str
    app_id: str
    branch: str
    path: str


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: D401 - argparse hook
        raise OperatorError(f"papyrus site google-secrets: {message}\n\n{USAGE}")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="papyrus site google-secrets", add_help=False)
    sub = parser.add_subparsers(dest="action")
    for name in ("set", "check"):
        action = sub.add_parser(name, add_help=False)
        action.add_argument("--site", default=str(DEFAULT_SITE_PATH))
        action.add_argument("--profile")
        action.add_argument("--account")
        action.add_argument("--region")
        action.add_argument("--app-id")
        action.add_argument("--branch", default="main")
        if name == "set":
            action.add_argument("--client-id")
            action.add_argument("--secret-stdin", action="store_true")
    return parser


def _default_session(profile: str | None, region: str) -> Any:
    try:
        import boto3
    except ImportError:
        raise OperatorError("papyrus site google-secrets needs boto3. Install it with `pip install 'papyrus-newsroom[markus]'`.") from None
    return boto3.Session(profile_name=profile, region_name=region)


def _aws_failure(error: Exception, action: str) -> OperatorError:
    """Operator-facing text for a boto failure; carries the error code, never request values."""
    code = ""
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
    hint = " Your AWS session may have expired: run `aws sso login --profile <profile>` and retry." if code in {
        "ExpiredToken", "ExpiredTokenException", "UnrecognizedClientException", "InvalidClientTokenId", "",
    } else ""
    return OperatorError(f"AWS refused {action}: {code or type(error).__name__}.{hint}")


def _is_client_error(error: Exception, *codes: str) -> bool:
    response = getattr(error, "response", None)
    return isinstance(response, dict) and response.get("Error", {}).get("Code") in codes


def _aws_errors() -> tuple[type[BaseException], ...]:
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return ()
    return (BotoCoreError, ClientError)


def _resolve_app_id(site: Site, session: Any, override: str | None) -> str:
    if override:
        return override
    try:
        stacks = session.client("cloudformation").describe_stacks(StackName=site.stack_name).get("Stacks", [])
        for output in (stacks[0].get("Outputs", []) if stacks else []):
            if output.get("OutputKey") == "CmsAppId" and output.get("OutputValue"):
                return output["OutputValue"]
    except _aws_errors() as error:
        if not _is_client_error(error, "ValidationError"):
            raise _aws_failure(error, f"reading stack {site.stack_name}") from None
    try:
        amplify = session.client("amplify")
        token = None
        while True:
            page = amplify.list_apps(**({"nextToken": token} if token else {}), maxResults=100)
            for app in page.get("apps", []):
                if app.get("name") == site.cms_app_name:
                    return app["appId"]
            token = page.get("nextToken")
            if not token:
                break
    except _aws_errors() as error:
        raise _aws_failure(error, "listing Amplify apps") from None
    raise OperatorError(
        f"Could not find the CMS app: stack {site.stack_name} has no CmsAppId output and no Amplify app is named "
        f"{site.cms_app_name}. Is the stack deployed in this account? Or pass --app-id."
    )


def _build_context(options: argparse.Namespace, env: dict[str, str], cwd: Path, session_factory: Callable[[str | None, str], Any]) -> Context:
    site = load_site((cwd / options.site) if not Path(options.site).is_absolute() else Path(options.site))
    expected = options.account or site.aws_account
    if not expected:
        raise OperatorError(
            "No expected AWS account to assert. Pass --account <12-digit id> or set aws.accountId in infra/site.json. "
            "Nothing was read or written."
        )
    profile = options.profile or site.aws_profile or env.get("AWS_PROFILE") or None
    region = options.region or site.aws_region or env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or DEFAULT_REGION
    session = session_factory(profile, region)
    try:
        actual = session.client("sts").get_caller_identity()["Account"]
    except _aws_errors() as error:
        raise _aws_failure(error, "identifying the caller (STS)") from None
    if actual != expected:
        raise OperatorError(
            f"Wrong AWS account: credentials are for {actual}, this site expects {expected}. "
            f"Profile used: {profile or '(default credential chain)'}. Nothing was read or written."
        )
    app_id = _resolve_app_id(site, session, options.app_id)
    return Context(site, session, actual, region, app_id, options.branch, branch_secret_path(app_id, options.branch))


def _cognito_domain(ctx: Context) -> tuple[str, str]:
    """(prefix, how it is known). The prefix is empty when the site is on Amplify's generated domain and no outputs file names it."""
    if ctx.site.apply_prefix and ctx.site.cognito_prefix:
        return ctx.site.cognito_prefix, "infra/site.json cms.cognitoDomainPrefix"
    outputs = ctx.site.root / "amplify_outputs.json"
    try:
        domain = json.loads(outputs.read_text(encoding="utf-8"))["auth"]["oauth"]["domain"]
        return str(domain).split(".")[0], "amplify_outputs.json"
    except (OSError, ValueError, KeyError, TypeError):
        return "", ""


def _print_google_console(ctx: Context, out: TextIO) -> None:
    prefix, source = _cognito_domain(ctx)
    print("", file=out)
    print("Google Cloud Console (APIs & Services, Credentials, this OAuth client):", file=out)
    if prefix:
        origin = f"https://{prefix}.auth.{ctx.region}.amazoncognito.com"
        print(f"  Authorized JavaScript origin:  {origin}", file=out)
        print(f"  Authorized redirect URI:       {origin}/oauth2/idpresponse", file=out)
        print(f"  (Cognito domain prefix {prefix}, from {source})", file=out)
    else:
        print("  This site is on Amplify's generated Cognito domain (cms.applyCognitoDomainPrefix is not true), so the", file=out)
        print("  prefix is not in site.json. Read the stack output oauthCognitoDomain of the backend stack, then add", file=out)
        print("  https://<that domain> as the origin and https://<that domain>/oauth2/idpresponse as the redirect URI.", file=out)


def _print_disable_note(out: TextIO) -> None:
    print("", file=out)
    print(f"This command does not enable or disable Google OAuth. If the CMS branch sets {DISABLE_SWITCH}=1 (Shipped does),", file=out)
    print("the backend ignores these secrets and builds no Google provider until that variable is removed.", file=out)


def _print_header(ctx: Context, out: TextIO) -> None:
    print(f"Site:     {ctx.site.site_id}", file=out)
    print(f"Account:  {ctx.account} ({ctx.region}), asserted with STS", file=out)
    print(f"CMS app:  {ctx.app_id}, branch {ctx.branch}", file=out)
    print(f"SSM path: {ctx.path}/{{{CLIENT_ID_NAME},{CLIENT_SECRET_NAME}}}", file=out)


def _read_parameter(ssm: Any, name: str) -> dict[str, Any] | None:
    try:
        return ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    except _aws_errors() as error:
        if _is_client_error(error, "ParameterNotFound"):
            return None
        raise _aws_failure(error, f"reading {name}") from None


def run_set(options: argparse.Namespace, *, env: dict[str, str], cwd: Path, out: TextIO, stdin: TextIO,
            input_fn: Callable[[str], str], getpass_fn: Callable[[str], str], session_factory: Callable[[str | None, str], Any]) -> int:
    if options.secret_stdin and not options.client_id:
        raise OperatorError("--secret-stdin reads the secret from stdin, so the client id must come from --client-id.")
    if not options.secret_stdin and not stdin.isatty():
        raise OperatorError("No terminal to prompt on. For automation pass --client-id and pipe the secret with --secret-stdin.")
    ctx = _build_context(options, env, cwd, session_factory)
    _print_header(ctx, out)

    client_id = (options.client_id or input_fn(f"Google client id (ends {CLIENT_ID_SUFFIX}): ")).strip()
    if not client_id.endswith(CLIENT_ID_SUFFIX):
        raise OperatorError(f"That does not look like a Google client id (it should end {CLIENT_ID_SUFFIX}). Nothing was written.")
    secret = stdin.read().rstrip("\r\n") if options.secret_stdin else getpass_fn(f"Google client secret (starts {CLIENT_SECRET_PREFIX}, hidden): ").strip()
    if not secret.startswith(CLIENT_SECRET_PREFIX):
        raise OperatorError(f"That does not look like a Google client secret (it should start {CLIENT_SECRET_PREFIX}). Nothing was written.")

    ssm = ctx.session.client("ssm")
    wrote = {CLIENT_ID_NAME: client_id, CLIENT_SECRET_NAME: secret}
    for name, value in wrote.items():
        try:
            ssm.put_parameter(Name=f"{ctx.path}/{name}", Value=value, Type="SecureString", Overwrite=True)
        except _aws_errors() as error:
            raise _aws_failure(error, f"writing {name}") from None

    print("", file=out)
    print("Stored (SecureString), confirmed by fingerprint:", file=out)
    for name, value in wrote.items():
        stored = _read_parameter(ssm, f"{ctx.path}/{name}")
        if stored is None:
            raise OperatorError(f"{name} was written but cannot be read back. Check IAM access to ssm:GetParameter and the KMS key.")
        verdict = "matches what you entered" if fingerprint(stored["Value"]) == fingerprint(value) else "DOES NOT MATCH what you entered"
        print(f"  {name:<20} version {stored.get('Version', '?')}  fingerprint {fingerprint(stored['Value'])}  {verdict}", file=out)
    _print_google_console(ctx, out)
    print("", file=out)
    print("Next: redeploy the CMS app's branch so the Cognito Google provider picks up the values:", file=out)
    print(f"  aws amplify start-job --app-id {ctx.app_id} --branch-name {ctx.branch} --job-type RELEASE --region {ctx.region}", file=out)
    print("Then run `papyrus site google-secrets check` to confirm the deployed provider uses this client id.", file=out)
    _print_disable_note(out)
    return 0


def _idp_client_id(ctx: Context, prefix: str) -> tuple[str, str | None]:
    """(state, client id). States: ok, no-domain, no-idp, unreadable."""
    cognito = ctx.session.client("cognito-idp")
    try:
        pool_id = cognito.describe_user_pool_domain(Domain=prefix).get("DomainDescription", {}).get("UserPoolId")
        if not pool_id:
            return "no-domain", None
        provider = cognito.describe_identity_provider(UserPoolId=pool_id, ProviderName="Google")
        return "ok", provider["IdentityProvider"]["ProviderDetails"].get("client_id")
    except _aws_errors() as error:
        if _is_client_error(error, "ResourceNotFoundException"):
            return "no-idp", None
        return "unreadable", None


def _disable_switch_state(ctx: Context) -> str:
    try:
        branch = ctx.session.client("amplify").get_branch(appId=ctx.app_id, branchName=ctx.branch)["branch"]
    except _aws_errors():
        return "could not read the branch variables"
    value = (branch.get("environmentVariables") or {}).get(DISABLE_SWITCH)
    return f"set to {value!r} on branch {ctx.branch}" if value else f"not set on branch {ctx.branch}"


def run_check(options: argparse.Namespace, *, env: dict[str, str], cwd: Path, out: TextIO,
              session_factory: Callable[[str | None, str], Any]) -> int:
    ctx = _build_context(options, env, cwd, session_factory)
    _print_header(ctx, out)
    ssm = ctx.session.client("ssm")
    healthy = True
    values: dict[str, str] = {}
    print("", file=out)
    print("Parameters:", file=out)
    for name in (CLIENT_ID_NAME, CLIENT_SECRET_NAME):
        parameter = _read_parameter(ssm, f"{ctx.path}/{name}")
        if parameter is None:
            healthy = False
            print(f"  {name:<20} MISSING  (run `papyrus site google-secrets set`)", file=out)
            continue
        values[name] = parameter["Value"]
        modified = parameter.get("LastModifiedDate")
        stamp = modified.isoformat() if hasattr(modified, "isoformat") else str(modified)
        kind = parameter.get("Type", "?")
        warning = "" if kind == "SecureString" else "  WARNING: not a SecureString"
        healthy = healthy and kind == "SecureString"
        print(f"  {name:<20} present  version {parameter.get('Version', '?')}  modified {stamp}  fingerprint {fingerprint(parameter['Value'])}{warning}", file=out)

    print("", file=out)
    print("Deployed Cognito Google provider:", file=out)
    prefix, _ = _cognito_domain(ctx)
    if not prefix:
        print("  unknown: the Cognito domain prefix is not in site.json (generated domain) or amplify_outputs.json.", file=out)
        healthy = False
    else:
        state, deployed = _idp_client_id(ctx, prefix)
        stored = values.get(CLIENT_ID_NAME)
        if state == "no-domain":
            print(f"  no Cognito domain '{prefix}' in {ctx.region}: the CMS backend has not deployed it yet.", file=out)
            healthy = False
        elif state == "no-idp":
            print(f"  domain '{prefix}' exists but has no Google identity provider: the backend deployed without Google "
                  f"(see {DISABLE_SWITCH} below), or has not deployed since the secrets were set.", file=out)
            healthy = False
        elif state == "unreadable":
            print("  could not read the provider (needs cognito-idp:DescribeUserPoolDomain and DescribeIdentityProvider).", file=out)
            healthy = False
        elif stored is None or deployed is None:
            print(f"  provider found, client id fingerprint {fingerprint(deployed) if deployed else '(none)'}; nothing stored to compare.", file=out)
            healthy = False
        elif fingerprint(deployed) == fingerprint(stored):
            print(f"  client id matches the stored one (fingerprint {fingerprint(deployed)}).", file=out)
        else:
            print(f"  client id DIFFERS: deployed {fingerprint(deployed)}, stored {fingerprint(stored)}. Redeploy the CMS branch.", file=out)
            healthy = False
    print(f"  {DISABLE_SWITCH}: {_disable_switch_state(ctx)}", file=out)

    _print_google_console(ctx, out)
    _print_disable_note(out)
    return 0 if healthy else 1


def command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    out: TextIO | None = None,
    stdin: TextIO | None = None,
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    session_factory: Callable[[str | None, str], Any] = _default_session,
) -> int:
    """`args` is everything after `papyrus site google-secrets`."""
    out = out or sys.stdout
    if not args or args[0] in {"--help", "-h"}:
        print(USAGE, file=out)
        return 0
    options = _build_parser().parse_args(args)
    env = dict(os.environ) if env is None else env
    cwd = cwd or Path.cwd()
    if options.action == "set":
        return run_set(options, env=env, cwd=cwd, out=out, stdin=stdin or sys.stdin, input_fn=input_fn,
                       getpass_fn=getpass_fn, session_factory=session_factory)
    return run_check(options, env=env, cwd=cwd, out=out, session_factory=session_factory)


def site_command(command_name: str | None, flags: list[str]) -> int:
    """Entry for `papyrus site <command> [flags]`."""
    if command_name is None or command_name in {"--help", "-h"}:
        print("Usage: papyrus site <command> [options]\n\nCommands:\n  google-secrets  set | check: the CMS app's Google OAuth client id and secret")
        return 0
    if command_name != "google-secrets":
        raise ValueError(f"Unsupported papyrus site command: {command_name}")
    return command(flags)
