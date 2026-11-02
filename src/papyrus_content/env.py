from __future__ import annotations

import atexit
import json
import os
from contextlib import ExitStack
from importlib import resources
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

_PACKAGED_CORPORA = ("data", "corpora")
_resource_files = ExitStack()
atexit.register(_resource_files.close)


def packaged_corpora_file(name: str) -> Path | None:
    """A default config shipped inside the wheel (``papyrus_content/data/corpora/``), or None if it is not packaged."""
    reference = resources.files(__package__).joinpath(*_PACKAGED_CORPORA, name)
    if not reference.is_file():
        return None
    return Path(_resource_files.enter_context(resources.as_file(reference)))


def resolve_corpora_file(relative: str | Path) -> Path:
    """``<PAPYRUS_ROOT>/<relative>`` when it exists (a checkout, the Lambda task root or PAPYRUS_ROOT),
    else the copy packaged in the wheel for a ``corpora/<name>`` path, else the root path (which may not exist)."""
    relative = Path(relative)
    rooted = PAPYRUS_ROOT / relative
    if rooted.exists() or len(relative.parts) != 2 or relative.parts[0] != "corpora":
        return rooted
    return packaged_corpora_file(relative.name) or rooted


def required_environment_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required.")
    return value


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
            if key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value


def amplify_outputs_path() -> Path:
    """The site's amplify_outputs.json: PAPYRUS_SITE_ROOT, then the working directory, then the Papyrus root."""
    candidates = []
    site_root = os.environ.get("PAPYRUS_SITE_ROOT", "").strip()
    if site_root:
        candidates.append(Path(site_root))
    candidates.append(Path.cwd())
    for root in candidates:
        if (root / "amplify_outputs.json").exists():
            return root / "amplify_outputs.json"
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


def identity_pool_id_from_amplify_outputs(filepath: str | Path | None = None) -> str | None:
    """The Cognito identity pool the signed-in user lane trades its ID token with for S3 credentials."""
    explicit = (os.environ.get("PAPYRUS_IDENTITY_POOL_ID") or "").strip()
    if explicit:
        return explicit
    path = Path(filepath) if filepath else amplify_outputs_path()
    if not path.is_absolute():
        path = PAPYRUS_ROOT / path
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    auth = parsed.get("auth") or {}
    return auth.get("identity_pool_id") or auth.get("identityPoolId")
