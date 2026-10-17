from __future__ import annotations

import json
import os
from pathlib import Path

_STEERING_CONFIG_RELATIVE = Path("corpora") / "papyrus-steering.yml"


def resolve_papyrus_root() -> Path:
    """Repo root in dev; Lambda task root when corpora/ is bundled beside papyrus_content/."""
    explicit = os.environ.get("PAPYRUS_ROOT", "").strip()
    if explicit:
        return Path(explicit)
    module_parent = Path(__file__).resolve().parent.parent
    if (module_parent / _STEERING_CONFIG_RELATIVE).exists():
        return module_parent
    return Path(__file__).resolve().parents[2]


PAPYRUS_ROOT = resolve_papyrus_root()
BIBLICUS_ROOT = Path(os.environ.get("BIBLICUS_WORKDIR", str(PAPYRUS_ROOT.parent / "Biblicus")))
_DOTENV_OVERRIDE_KEYS = frozenset({
    "PAPYRUS_GRAPHQL_ENDPOINT",
})


def load_dotenv() -> None:
    for filename in (".env", ".env.local"):
        path = PAPYRUS_ROOT / filename
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            if key in os.environ and key not in _DOTENV_OVERRIDE_KEYS:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value


def amplify_outputs_path() -> Path:
    return PAPYRUS_ROOT / "amplify_outputs.json"


def load_amplify_outputs() -> dict:
    path = amplify_outputs_path()
    if not path.exists():
        raise ValueError("Missing amplify_outputs.json. Run `npm run sandbox` or deploy the Amplify backend first.")
    return json.loads(path.read_text(encoding="utf-8"))


def graphql_endpoint() -> str:
    explicit = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").strip()
    if explicit:
        return explicit
    outputs = load_amplify_outputs()
    endpoint = outputs.get("data", {}).get("url") or outputs.get("aws_appsync_graphqlEndpoint")
    if not endpoint:
        raise ValueError("Could not determine GraphQL endpoint from amplify_outputs.json.")
    return str(endpoint)


def graphql_timeout_seconds(default: float = 30.0) -> float:
    raw = os.environ.get("PAPYRUS_GRAPHQL_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def storage_bucket_from_amplify_outputs(filepath: str | Path | None = None) -> str | None:
    path = Path(filepath) if filepath else amplify_outputs_path()
    if not path.is_absolute():
        path = PAPYRUS_ROOT / path
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    storage = parsed.get("storage") or {}
    return storage.get("bucket_name") or storage.get("bucketName")
