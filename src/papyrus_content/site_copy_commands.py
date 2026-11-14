"""CLI entry for ``papyrus ops site copy``: copy one site's backend data into another site's backend.

Dry run is the default. Writing needs an explicit ``--apply``. See docs/site-copy.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .options import normalize_string, parse_options
from .site_copy import DEFAULT_SKIP_MEDIA_PREFIXES, CopyConfig, SiteCopier, SiteCopyError, parse_key_map, render_plan

DEFAULT_REGION = "us-east-1"
USAGE = (
    "papyrus ops site copy --from-api ID --corpus-key-map OLD=NEW [--to-api ID] "
    "[--from-media-bucket B] [--to-media-bucket B] [--models A,B] [--media-prefixes P,Q] [--skip-media-prefix P ...] "
    "[--owner-map FILE] [--keep-unmapped-owners] [--region R] [--from-profile P] [--to-profile P] "
    "[--apply | --dry-run] [--verify] [--json]"
)


def make_session(profile: str | None, region: str) -> Any:
    import boto3

    return boto3.Session(profile_name=profile, region_name=region) if profile else boto3.Session(region_name=region)


def split_list(text: str | None) -> list[str] | None:
    values = [part.strip() for part in (text or "").split(",") if part.strip()]
    return values or None


def load_owner_map(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()):
        raise SiteCopyError("--owner-map must be a JSON object of old owner value to new owner value.")
    return parsed


def take_repeated_flag(flags: list[str], name: str) -> tuple[list[str], list[str]]:
    """Remove every ``--name VALUE`` pair from the flags (parse_options keeps only the last) and return the values."""
    kept: list[str] = []
    values: list[str] = []
    index = 0
    while index < len(flags):
        if flags[index] == f"--{name}" and index + 1 < len(flags) and not flags[index + 1].startswith("--"):
            values.append(flags[index + 1])
            index += 2
            continue
        kept.append(flags[index])
        index += 1
    return kept, values


def build_config(options: dict[str, Any], skip_prefixes: list[str] | None = None) -> tuple[CopyConfig, bool, bool]:
    from_api = normalize_string(options.get("from-api"))
    if not from_api:
        raise SiteCopyError(f"--from-api is required. Usage: {USAGE}")
    apply = bool(options.get("apply"))
    if apply and options.get("dry-run"):
        raise SiteCopyError("Pass either --apply or --dry-run, not both. The default is a dry run.")
    verify = bool(options.get("verify"))
    if apply and verify and not (options.get("to-api") or options.get("to-media-bucket")):
        raise SiteCopyError("--apply needs a target: pass --to-api and/or --to-media-bucket.")
    from_bucket = normalize_string(options.get("from-media-bucket"))
    to_bucket = normalize_string(options.get("to-media-bucket"))
    if to_bucket and not from_bucket:
        raise SiteCopyError("--to-media-bucket needs --from-media-bucket.")
    key_map = parse_key_map(normalize_string(options.get("corpus-key-map")))
    if not key_map:
        raise SiteCopyError("--corpus-key-map OLD=NEW is required (for example p-apyr-us=machines-on-machines).")
    config = CopyConfig(
        from_api=from_api,
        to_api=normalize_string(options.get("to-api")),
        key_map=key_map,
        from_bucket=from_bucket,
        to_bucket=to_bucket,
        models=split_list(normalize_string(options.get("models"))),
        media_prefixes=split_list(normalize_string(options.get("media-prefixes"))),
        owner_map=load_owner_map(normalize_string(options.get("owner-map"))),
        keep_unmapped_owners=bool(options.get("keep-unmapped-owners")),
        skip_media_prefixes=(
            tuple(prefix for prefix in skip_prefixes if prefix != "none")
            if skip_prefixes
            else DEFAULT_SKIP_MEDIA_PREFIXES
        ),
    )
    if config.to_api and config.to_api == config.from_api and normalize_string(options.get("from-profile")) == normalize_string(options.get("to-profile")):
        raise SiteCopyError("The source and the target are the same API.")
    return config, apply, verify


def site_copy(flags: list[str], session_factory: Callable[[str | None, str], Any] = make_session) -> int:
    flags, skip_prefixes = take_repeated_flag(flags, "skip-media-prefix")
    options = parse_options(flags)
    config, apply, verify = build_config(options, skip_prefixes)
    region = normalize_string(options.get("region")) or DEFAULT_REGION
    from_session = session_factory(normalize_string(options.get("from-profile")), region)
    to_session = session_factory(normalize_string(options.get("to-profile")), region)
    copier = SiteCopier(
        config,
        from_session.client("dynamodb"),
        to_session.client("dynamodb") if config.to_api else None,
        from_session.client("s3") if config.from_bucket else None,
        to_session.client("s3") if config.to_bucket else None,
    )
    if verify and not apply:
        plan = copier.verify()
    else:
        plan = copier.run(apply=apply)
        if apply and verify and plan.applied:
            checked = copier.verify()
            plan.verify, plan.verify_media = checked.verify, checked.verify_media
            plan.errors.extend(checked.errors)
    if options.get("json"):
        print(json.dumps(plan.to_dict(), indent=2, default=str))
    else:
        mode = "verify" if verify and not apply else ("applied" if plan.applied else "dry run, nothing written")
        print(f"ops site copy ({mode}): ok={plan.ok}")
        print(render_plan(plan))
    return 0 if plan.ok else 1
