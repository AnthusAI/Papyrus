from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .env import graphql_jwt_ttl_seconds, load_dotenv
from .options import normalize_non_negative_integer, normalize_string, parse_options


def refresh_jwt(flags: list[str]) -> None:
    load_dotenv()
    options = parse_options(flags)
    ttl_seconds = (
        normalize_non_negative_integer(options.get("ttl-seconds"), "--ttl-seconds")
        or graphql_jwt_ttl_seconds()
    )
    issuer = normalize_string(options.get("issuer")) or normalize_string(os.environ.get("PAPYRUS_JWT_ISSUER")) or "papyrus-cli"
    subject = normalize_string(options.get("subject")) or "papyrus-cli"
    audience = normalize_string(options.get("audience")) or normalize_string(os.environ.get("PAPYRUS_JWT_AUDIENCE")) or "papyrus-authoring"
    scope = (
        normalize_string(options.get("scope"))
        or normalize_string(os.environ.get("PAPYRUS_JWT_REQUIRED_SCOPE"))
        or normalize_string(os.environ.get("PAPYRUS_JWT_AUTHORING_VALUE"))
        or "papyrus:write"
    )
    groups_raw = normalize_string(options.get("groups")) or "editor"
    groups = [entry.strip() for entry in groups_raw.split(",") if entry.strip()] or ["editor"]
    token = _mint_jwt(
        secret=_resolve_secret(options),
        issuer=issuer,
        subject=subject,
        audience=audience,
        scope=scope,
        groups=groups,
        ttl_seconds=ttl_seconds,
    )

    write_env = normalize_string(options.get("write-env"))
    if write_env:
        _upsert_env_token(Path(write_env), token)

    output_format = (normalize_string(options.get("format")) or "plain").lower()
    if output_format == "shell":
        print(f"export PAPYRUS_GRAPHQL_JWT='{token}'")
        return
    if write_env:
        print(f"Updated PAPYRUS_GRAPHQL_JWT in {Path(write_env).resolve()}")
        return
    print(token)


def _is_amplify_secret_placeholder(value: str) -> bool:
    return bool(value) and value.startswith("<") and "will be resolved" in value


def _read_ssm_secret_boto(parameter_name: str) -> str:
    try:
        import boto3
    except ModuleNotFoundError as error:
        raise RuntimeError("boto3 is required to read JWT secrets from SSM in Lambda.") from error
    client = boto3.client("ssm")
    # Amplify branch policies often grant ssm:GetParameters (plural) on secret paths;
    # get_parameter requires ssm:GetParameter (singular) on the same ARNs.
    response = client.get_parameters(Names=[parameter_name], WithDecryption=True)
    parameters = response.get("Parameters") or []
    secret = normalize_string(parameters[0].get("Value") if parameters else None)
    if not secret:
        raise RuntimeError(f"SSM parameter {parameter_name} returned no value.")
    return secret


def _read_ssm_secret_cli(parameter_name: str) -> str:
    command = ["aws", "ssm", "get-parameter", "--name", parameter_name, "--with-decryption", "--output", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"Failed to read JWT secret from SSM parameter {parameter_name}: {stderr}")
    payload = json.loads(result.stdout or "{}")
    secret = normalize_string(((payload.get("Parameter") or {}).get("Value")))
    if not secret:
        raise RuntimeError(f"SSM parameter {parameter_name} returned no value.")
    return secret


def _read_ssm_secret(parameter_name: str) -> str:
    try:
        import boto3  # noqa: F401
    except ModuleNotFoundError:
        return _read_ssm_secret_cli(parameter_name)
    try:
        return _read_ssm_secret_boto(parameter_name)
    except Exception:
        return _read_ssm_secret_cli(parameter_name)


def _jwt_secret_ssm_fallback_paths() -> list[str]:
    """SSM paths for PAPYRUS_JWT_SECRET when AMPLIFY_SSM_ENV_CONFIG is unavailable.

    Production console-chat-responder must not read the Ryan sandbox secret: AppSync
    verifies JWTs with the branch secret under amplify/dbsyytcm9drqa/...
    """
    explicit = normalize_string(os.environ.get("PAPYRUS_JWT_SECRET_SSM_PARAM"))
    if explicit:
        return [explicit]

    graphql = normalize_string(os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT"))
    app_id = normalize_string(os.environ.get("AWS_APP_ID"))
    production_main = (
        app_id == "dbsyytcm9drqa"
        or "64hviw44q5cq5nwjcigmasowlq.appsync-api" in graphql
    )
    paths: list[str] = []
    if production_main:
        paths.append("/amplify/dbsyytcm9drqa/main-branch-cb38ada667/PAPYRUS_JWT_SECRET")
    else:
        paths.append("/amplify/papyrus/ryan-sandbox-adcd88a186/PAPYRUS_JWT_SECRET")
    paths.extend(
        [
            "/amplify/shared/papyrus/PAPYRUS_JWT_SECRET",
            "/amplify/shared/PAPYRUS_JWT_SECRET",
        ]
    )
    return paths


def _resolve_amplify_ssm_secret(name: str) -> str | None:
    raw_config = normalize_string(os.environ.get("AMPLIFY_SSM_ENV_CONFIG"))
    if not raw_config:
        return None
    try:
        config = json.loads(raw_config)
    except json.JSONDecodeError:
        return None
    entry = config.get(name) if isinstance(config, dict) else None
    if not isinstance(entry, dict):
        return None
    parameter_name = normalize_string(entry.get("path")) or normalize_string(entry.get("sharedPath"))
    if not parameter_name:
        return None
    return _read_ssm_secret(parameter_name)


def _resolve_secret(options: dict[str, Any]) -> str:
    explicit = normalize_string(options.get("secret"))
    if explicit:
        return explicit
    secret_env = normalize_string(options.get("secret-env"))
    if secret_env:
        value = normalize_string(os.environ.get(secret_env))
        if value:
            return value
    ssm_param = normalize_string(options.get("ssm-param")) or normalize_string(
        os.environ.get("PAPYRUS_JWT_SECRET_SSM_PARAM")
    )
    if ssm_param:
        try:
            return _read_ssm_secret(ssm_param)
        except Exception:
            pass
    for env_name in ("PAPYRUS_SANDBOX_JWT_SECRET", "PAPYRUS_JWT_SECRET"):
        value = normalize_string(os.environ.get(env_name))
        if value and not _is_amplify_secret_placeholder(value):
            return value
    amplify_secret = _resolve_amplify_ssm_secret("PAPYRUS_JWT_SECRET")
    if amplify_secret:
        return amplify_secret
    for fallback_param in _jwt_secret_ssm_fallback_paths():
        try:
            return _read_ssm_secret(fallback_param)
        except Exception:
            continue
    raise RuntimeError(
        "Could not resolve JWT signing secret. Pass --ssm-param or set PAPYRUS_SANDBOX_JWT_SECRET in .env."
    )


def _mint_jwt(
    *,
    secret: str,
    issuer: str,
    subject: str,
    audience: str,
    scope: str,
    groups: list[str],
    ttl_seconds: int,
) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "iat": now,
        "nbf": now - 30,
        "exp": now + ttl_seconds,
        "scope": scope,
        "groups": groups,
    }
    unsigned = f"{_b64_json(header)}.{_b64_json(payload)}"
    signature = hmac.new(secret.encode("utf-8"), unsigned.encode("utf-8"), hashlib.sha256).digest()
    return f"{unsigned}.{_b64(signature)}"


def _b64_json(value: dict[str, Any]) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _upsert_env_token(path: Path, token: str) -> None:
    line = f"PAPYRUS_GRAPHQL_JWT={token}"
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    replaced = False
    output: list[str] = []
    for current in lines:
        if current.startswith("PAPYRUS_GRAPHQL_JWT="):
            output.append(line)
            replaced = True
        else:
            output.append(current)
    if not replaced:
        output.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
