"""Resolve Amplify-managed secrets (SSM Parameter Store) for non-GraphQL integrations."""

from __future__ import annotations

import json
import os
import subprocess

from .options import normalize_string


def _is_amplify_secret_placeholder(value: str) -> bool:
    return bool(value) and value.startswith("<") and "will be resolved" in value


def _read_ssm_secret_boto(parameter_name: str) -> str:
    try:
        import boto3
    except ModuleNotFoundError as error:
        raise RuntimeError("boto3 is required to read secrets from SSM in Lambda.") from error
    client = boto3.client("ssm")
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
        raise RuntimeError(f"Failed to read secret from SSM parameter {parameter_name}: {stderr}")
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
