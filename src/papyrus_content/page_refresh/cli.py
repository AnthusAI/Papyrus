"""``papyrus ops content refresh`` and ``papyrus ops content rerender``: flags in, one operation (``operations.py``), the same JSON out.

Two lanes, one result. The operator lane (AWS credentials) runs the service here. The signed-in lane has no AWS credentials, so it asks the
newsroom's ``refreshSitePages`` mutation, which runs the same service in the content-actions function. Mutating, so it writes by default;
``--dry-run`` shows the paths and invalidates nothing. Exit 1 when the invalidation (or the re-render) failed, 2 for a request that cannot run (nothing was written or invalidated).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ..options import normalize_string, parse_boolean_option, parse_options, resolve_mutation_apply
from .operations import run_operation
from .service import RefreshError, RefreshService

REFRESH_MUTATION = "refreshSitePages"
EXIT_FAILED = 1
EXIT_REFUSED = 2
BOOLEAN_FLAGS = ("indexes", "all", "dry-run", "json", "no-invalidate")


def split_flags(flags: list[str]) -> tuple[list[str], dict[str, Any]]:
    """``--path`` may repeat, so it is taken out before the shared flag parser (which keeps only the last of a repeated flag) sees the rest."""
    paths: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(flags):
        token = flags[index]
        if token in ("--path", "--paths"):
            value = flags[index + 1] if index + 1 < len(flags) else None
            if not value or value.startswith("--"):
                raise ValueError(f"{token} needs a site path, for example {token} /articles/my-story/.")
            if token == "--paths":
                paths.extend(part.strip() for part in value.split(",") if part.strip())
            else:
                paths.append(value)
            index += 2
            continue
        rest.append(token)
        index += 1
    options = parse_options(_explicit(rest))
    return paths, options


def _explicit(flags: list[str]) -> list[str]:
    """Rewrite boolean flags as ``--flag true`` so the shared parser cannot mistake the next word for a value."""
    out: list[str] = []
    index = 0
    while index < len(flags):
        token = flags[index]
        if token.startswith("--") and token[2:] in BOOLEAN_FLAGS:
            out.extend([token, "true"])
            index += 1
            continue
        out.append(token)
        index += 1
    return out


def operation_for(paths: list[str], options: dict[str, Any], *, rerender: bool) -> tuple[str, dict[str, Any]]:
    dry_run = not resolve_mutation_apply(options, "refresh")
    story = normalize_string(options.get("story"))
    flag = lambda name: parse_boolean_option(options.get(name), default=False, label=f"--{name}")  # noqa: E731
    if rerender:
        chosen = [name for name, present in (("story", bool(story)), ("indexes", flag("indexes")), ("all", flag("all"))) if present]
        if len(chosen) != 1:
            raise ValueError("Pass exactly one of --story LINEAGE, --indexes or --all.")
        arguments: dict[str, Any] = {"scope": chosen[0], "invalidate": not flag("no-invalidate"), "dryRun": dry_run}
        if story:
            arguments["storyLineageId"] = story
        return "site_rerender_pages", arguments
    chosen = [name for name, present in (("path", bool(paths)), ("story", bool(story)), ("indexes", flag("indexes"))) if present]
    if len(chosen) != 1:
        raise ValueError("Pass exactly one of --path PATH (repeatable), --story LINEAGE or --indexes.")
    if chosen[0] == "path":
        return "site_refresh_pages", {"paths": paths, "dryRun": dry_run}
    if chosen[0] == "story":
        return "site_refresh_story", {"storyLineageId": story, "dryRun": dry_run}
    return "site_refresh_indexes", {"dryRun": dry_run}


def run_signed_in(client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Ask the newsroom's own mutation; it runs the same operation in the content-actions function."""
    data = client.graphql(
        f"mutation Refresh($input: AWSJSON!) {{ {REFRESH_MUTATION}(input: $input) }}",
        {"input": json.dumps({"operation": name, **arguments})},
    )
    response = data.get(REFRESH_MUTATION)
    response = json.loads(response) if isinstance(response, str) else (response or {})
    if response.get("ok") is False and "error" not in response and response.get("errors"):
        first = response["errors"][0]
        return {"ok": False, "operation": name, "error": {"code": first.get("code", "refused"), "message": first.get("message", str(first))}}
    return response


def run_local(options: dict[str, Any], name: str, arguments: dict[str, Any], client) -> dict[str, Any]:
    from ..project_commands import _context_for, _projection_environment
    from ..projection.runtime import EDGE_DISTRIBUTION_ENV

    environment = _projection_environment(options)
    distribution = (environment.get(EDGE_DISTRIBUTION_ENV) or normalize_string(options.get("distribution-id")) or "").strip() or None
    service = RefreshService(distribution_id=distribution, context=lambda: _context_for(client, options), emit_metric=False)
    return run_operation(name, arguments, service)


def render_text(result: dict[str, Any]) -> str:
    lines: list[str] = []
    if "error" in result:
        return f"{result.get('operation')}: refused [{result['error']['code']}]: {result['error']['message']}"
    verb = "would" if result.get("dryRun") else "did"
    lines.append(f"{result.get('operation')}: {'ok' if result.get('ok') else 'FAILED'}{' (dry run: nothing written or invalidated)' if result.get('dryRun') else ''}")
    rendered = result.get("rendered")
    if rendered is not None:
        if rendered.get("scheduled"):
            lines.append("  re-render: scheduled in the newsroom function; it writes the pages and then purges them (outcome is in its log, not here)")
        elif rendered.get("dryRun"):
            lines.append(f"  re-render: would write {rendered['count']} pages")
        else:
            lines.append(f"  re-render: {'ok' if rendered.get('ok') else 'FAILED'}, wrote {rendered['count']} pages" + (f", deleted {len(rendered['deleted'])}" if rendered.get("deleted") else ""))
            lines.extend(f"    error: {error}" for error in rendered.get("errors", []))
            lines.extend(f"    wrote {key}" for key in rendered.get("written", [])[:50])
            if rendered.get("count", 0) > 50:
                lines.append(f"    ... and {rendered['count'] - 50} more (use --json for the full list)")
    pages = result.get("pages")
    if pages:
        for label, keys in pages.items():
            lines.append(f"  {label} pages: {', '.join(keys) or 'none'}")
    invalidation = result.get("invalidation") or {}
    status = invalidation.get("status")
    count = invalidation.get("count", 0)
    cost = invalidation.get("cost") or {}
    if status == "not-requested":
        lines.append("  invalidation: not requested (--no-invalidate); the edge keeps serving the old pages until their cache lifetime ends")
    elif status == "scheduled":
        lines.append("  invalidation: scheduled together with the re-render")
    else:
        lines.append(f"  invalidation: {'ok' if invalidation.get('ok') else 'FAILED'} ({status}), {count} paths")
        if count:
            lines.append(f"  cost: the first {cost.get('freePathsPerMonth', 1000):,} paths a month are free, then {cost.get('usdPerPathAfterFree', 0.005)} USD each: at most {cost.get('usdAtMost', 0)} USD for {count} paths")
        for request in invalidation.get("requests", []):
            lines.append(f"  CloudFront invalidation {request.get('id')}: {request.get('status')} ({request.get('paths')} paths)")
        if invalidation.get("error"):
            lines.append(f"  error: {invalidation['error']}")
        lines.extend(f"    {path}" for path in invalidation.get("paths", []))
    return "\n".join(lines)


def _run(flags: list[str], *, rerender: bool) -> None:
    paths, options = split_flags(flags)
    name, arguments = operation_for(paths, options, rerender=rerender)
    from ..graphql_authoring import create_authoring_client
    from ..user_auth_mode import user_auth_requested

    client, _claims = create_authoring_client()
    try:
        if user_auth_requested():
            result = run_signed_in(client, name, arguments)
        else:
            result = run_local(options, name, arguments, client)
    except RefreshError as error:
        raise ValueError(error.message) from error
    as_json = parse_boolean_option(options.get("json"), default=False, label="--json")
    print(json.dumps(result, indent=2) if as_json else render_text(result))
    if "error" in result:
        raise SystemExit(EXIT_REFUSED)   # the request could not run at all: nothing was written or invalidated
    if not result.get("ok"):
        if not as_json:
            print("The refresh did not finish: see the invalidation and re-render lines above.", file=sys.stderr)
        raise SystemExit(EXIT_FAILED)


def content_refresh(flags: list[str]) -> None:
    _run(flags, rerender=False)


def content_rerender(flags: list[str]) -> None:
    _run(flags, rerender=True)
