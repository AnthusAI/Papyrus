from __future__ import annotations

from papyrus_content.auth_commands import refresh_jwt
from papyrus_content.env import decode_jwt_claims, is_jwt_expired, load_dotenv, normalize_jwt

from ..config import parse_operator_flags
from ..errors import OperatorError, jwt_guidance_error


def run_auth_refresh(flags: list[str]) -> int:
  options, _ = parse_operator_flags(flags)
  refresh_flags: list[str] = []
  for key, value in options.items():
    if key == "help":
      continue
    if value is True:
      refresh_flags.append(f"--{key}")
    else:
      refresh_flags.append(f"--{key}")
      refresh_flags.append(str(value))

  refresh_jwt(refresh_flags)
  return 0


def ensure_cloud_auth_or_raise() -> None:
  load_dotenv()
  import os

  token = normalize_jwt(os.environ.get("PAPYRUS_GRAPHQL_JWT", ""))
  if not token:
    raise jwt_guidance_error(
      "Missing PAPYRUS_GRAPHQL_JWT. Run: papyrus auth refresh --write-env .env"
    )
  claims = decode_jwt_claims(token)
  if is_jwt_expired(claims):
    raise jwt_guidance_error(
      "PAPYRUS_GRAPHQL_JWT is expired. Run: papyrus auth refresh --write-env .env"
    )
