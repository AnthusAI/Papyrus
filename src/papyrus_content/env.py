from __future__ import annotations

import atexit
import json
import os
from contextlib import ExitStack
from importlib import resources
from pathlib import Path
from typing import Any

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


# The CLI installs `papyrus_content.site_selection` here at start. A Lambda never does, so it never reaches the sign-in
# registry (and this module imports nothing of it, which keeps the Lambda bundles free of the CLI sign-in library).
_site_selection: Any = None


def install_site_selection(selection: Any) -> None:
    global _site_selection
    _site_selection = selection


def selected_site_endpoint() -> str | None:
    """The GraphQL endpoint of the signed-in site the CLI selected (an explicit site, the working directory's site or the
    only signed-in site), or None when the environment or an amplify_outputs.json decides. Raises when a choice is needed."""
    return _site_selection.endpoint() if _site_selection is not None else None


def site_tenant_id(endpoint: str | None = None) -> str | None:
    """The tenant the signed-in site that owns this endpoint (default: the selected endpoint) publishes; None for a Lambda."""
    return _site_selection.tenant_for(endpoint) if _site_selection is not None else None


def outputs_belong_to_selection(parsed: dict) -> bool:
    """False when an explicit site choice names a different backend than this file: its bucket and pool are not that site's."""
    return _site_selection is None or _site_selection.accepts_outputs(parsed)


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
        raise ValueError(
            "No site is selected and there is no amplify_outputs.json. Sign in to a deployed site with `papyrus login <site>` "
            "(then name it with `papyrus --site <site> ...` or PAPYRUS_SITE, or run from its checkout); "
            "for a sandbox, run `npm run sandbox` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def graphql_endpoint() -> str:
    selected = selected_site_endpoint()
    if selected:
        return selected
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
    if not filepath and not outputs_belong_to_selection(parsed):
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
    if not filepath and not outputs_belong_to_selection(parsed):
        return None
    auth = parsed.get("auth") or {}
    return auth.get("identity_pool_id") or auth.get("identityPoolId")
