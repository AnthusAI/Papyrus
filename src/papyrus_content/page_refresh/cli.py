"""``papyrus ops content refresh`` and ``papyrus ops content rerender``: flags in, one operation (``operations.py``), the same JSON out.

Two lanes, one result, and neither needs ``cloudfront:CreateInvalidation``: the content-actions function does the purging, and enforces the path
cap and dry-run-first (``budget.py``). The signed-in lane asks the newsroom's ``refreshSitePages`` mutation; the operator lane invokes the
function directly. A raw ``aws cloudfront create-invalidation`` would bypass the guard: do not use it. Mutating, so it writes by default;
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
BOOLEAN_FLAGS = ("fix", "indexes", "all", "dry-run", "json", "no-invalidate", "run")


def split_flags(flags: list[str]) -> tuple[list[str], dict[str, Any]]:
    """``--path`` and ``--under`` may repeat, so it is taken out before the shared flag parser (which keeps only the last of a repeated flag) sees the rest."""
    paths: list[str] = []
    under: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(flags):
        token = flags[index]
        if token == "--under":
            value = flags[index + 1] if index + 1 < len(flags) else None
            if not value or value.startswith("--"):
                raise ValueError("--under needs a URL path prefix, for example --under /posts/.")
            under.append(value)
            index += 2
            continue
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
    if under:
        options["under"] = under
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


def operation_for(paths: list[str], options: dict[str, Any], *, rerender: bool, update_live: bool = False, inspect: bool = False) -> tuple[str, dict[str, Any]]:
    dry_run = not resolve_mutation_apply(options, "refresh")
    guard_arguments: dict[str, Any] = {"dryRun": dry_run, "confirm": parse_boolean_option(options.get("run"), default=False, label="--run")}
    allowed = normalize_string(options.get("force-paths"))
    if allowed:
        if not allowed.isdigit() or int(allowed) < 1:
            raise ValueError("--force-paths needs a whole number of paths you accept for this one call, for example --force-paths 40.")
        guard_arguments["forcePaths"] = int(allowed)
    story = normalize_string(options.get("story"))
    flag = lambda name: parse_boolean_option(options.get(name), default=False, label=f"--{name}")  # noqa: E731
    if rerender:
        chosen = [name for name, present in (("story", bool(story)), ("indexes", flag("indexes")), ("all", flag("all"))) if present]
        if len(chosen) != 1:
            raise ValueError("Pass exactly one of --story LINEAGE, --indexes or --all.")
        arguments: dict[str, Any] = {"scope": chosen[0], "invalidate": not flag("no-invalidate"), **guard_arguments}
        if story:
            arguments["storyLineageId"] = story
        if options.get("under"):
            if chosen[0] != "indexes":
                raise ValueError("--under limits a re-render of the index pages: use it with --indexes.")
            arguments["under"] = list(options["under"])
        return "site_rerender_pages", arguments
    if inspect:
        if bool(story) == bool(paths):
            raise ValueError("inspect-page needs exactly one of --story LINEAGE or --path PATH.")
        arguments = {"fix": parse_boolean_option(options.get("fix"), default=False, label="--fix"), "confirm": guard_arguments["confirm"]}
        arguments.update({"storyLineageId": story} if story else {"path": paths[0]})
        if "forcePaths" in guard_arguments:
            arguments["forcePaths"] = guard_arguments["forcePaths"]
        return "site_inspect", arguments
    if update_live:
        if not story:
            raise ValueError("update-live needs --story LINEAGE.")
        arguments = {"storyLineageId": story, **guard_arguments}
        seconds = normalize_string(options.get("verify-seconds"))
        if seconds:
            arguments["verifySeconds"] = int(seconds)
        return "site_update_live", arguments
    chosen = [name for name, present in (("path", bool(paths)), ("story", bool(story)), ("indexes", flag("indexes"))) if present]
    if len(chosen) != 1:
        raise ValueError("Pass exactly one of --path PATH (repeatable), --story LINEAGE or --indexes.")
    if chosen[0] == "path":
        return "site_refresh_pages", {"paths": paths, **guard_arguments}
    if chosen[0] == "story":
        return "site_refresh_story", {"storyLineageId": story, **guard_arguments}
    return "site_refresh_indexes", guard_arguments


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


def run_operator(name: str, arguments: dict[str, Any], invoke=None) -> dict[str, Any]:
    """The operator lane: invoke the content-actions function and wait for its answer (it does the purging, under its guard)."""
    from ..projection_trigger import content_actions_function

    function_name = content_actions_function()
    if not function_name:
        raise ValueError("No content-actions function is configured for this site (PAPYRUS_CONTENT_ACTIONS_FUNCTION, or custom.publication.contentActionsFunction in amplify_outputs.json), so the refresh cannot run. Page refreshes go through that function and never through CloudFront directly.")
    payload = {"refreshSitePages": {"operation": name, **arguments}, "who": "operator-cli"}
    if invoke is None:
        import boto3
        from botocore.config import Config

        client = boto3.client("lambda", config=Config(read_timeout=120, retries={"max_attempts": 1}))
        invoke = lambda body: client.invoke(FunctionName=function_name, InvocationType="RequestResponse", Payload=json.dumps(body).encode("utf-8"))  # noqa: E731
    response = invoke(payload)
    body = response["Payload"].read() if hasattr(response.get("Payload"), "read") else response.get("Payload")
    if response.get("FunctionError"):
        return {"ok": False, "operation": name, "error": {"code": "function_error", "message": f"The content-actions function failed: {body.decode('utf-8', 'replace') if isinstance(body, bytes) else body}"}}
    return json.loads(body)


def render_inspect(result: dict[str, Any]) -> str:
    lines = [result["verdict"]]
    record = result.get("record") or {}
    for version in record.get("versions", []):
        lines.append(f"  record v{version['version']}: {version['state']}, stage {version['stage']}, by {version['author']}, {version['at']}")
    published = record.get("published")
    if published:
        lines.append(f"  published pointer: version {published['version']}, publishedAt {published['publishedAt']}; current version {record.get('currentVersion')}")
    for key, page in ((result.get("projected") or {}).get("pages") or {}).items():
        lines.append(f"  stored {key}: " + ("MISSING" if page is None else f"lastModified {page['lastModified']}, papyrus-version {page['papyrusVersion']}, rendered from version {page['sourceVersion']}"))
    for path, seen in (((result.get("edge") or {}).get("urls")) or {}).items():
        lines.append(f"  edge {path}: status {seen.get('status')}, age {seen.get('age')}, last-modified {seen.get('lastModified')}, etag {seen.get('etag')}, x-cache {seen.get('xCache')}, s-maxage {seen.get('sMaxAge')}, serving version {seen.get('sourceVersion')}" + (f" ({seen['error']})" if seen.get("error") else ""))
    if (result.get("edge") or {}).get("checked") is False:
        lines.append(f"  edge: not checked ({result['edge']['reason']})")
    if result.get("fix"):
        lines.append("  fix: " + ("ran" if result["fix"]["ran"] else "not run (a dry run, a refusal or nothing to do; see --json)"))
    return "\n".join(lines)


def render_text(result: dict[str, Any]) -> str:
    if result.get("operation") == "site_inspect" and "verdict" in result:
        return render_inspect(result)
    lines: list[str] = []
    if "error" in result and not result.get("invalidation"):
        return f"{result.get('operation')}: refused [{result['error']['code']}]: {result['error']['message']}"
    if "error" in result:
        lines.append(f"{result.get('operation')}: REFUSED [{result['error']['code']}]: {result['error']['message']}")
    if "error" not in result:
        lines.append(f"{result.get('operation')}: {'ok' if result.get('ok') else 'FAILED'}{' (dry run: nothing written or invalidated)' if result.get('dryRun') else ''}")
    if result.get("verdict"):
        lines.append(f"  verdict: {result['verdict']}")
    rendered = result.get("rendered")
    if rendered is not None:
        if rendered.get("scheduled"):
            requested = rendered.get("requested")
            asked = f"asked to rebuild {requested} pages" if requested is not None else "asked to rebuild its pages"
            lines.append(f"  re-render: scheduled in the newsroom function, {asked}; it writes them and then purges them (the outcome is in its log, not here)")
        elif rendered.get("dryRun") or result.get("dryRun"):
            would = rendered.get("wouldWrite") or []
            lines.append(f"  re-render: would write {rendered.get('count', len(would))} pages (a dry run: nothing was written)")
            lines.extend(f"    would write /{key}" for key in would[:50])
            if len(would) > 50:
                lines.append(f"    ... and {len(would) - 50} more (use --json for the full list)")
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
    guard = invalidation.get("guard") or {}
    if guard.get("cap"):
        lines.append(f"  per-call cap: {guard['cap']} paths (more needs --force-paths N)")
    for url, seen in ((result.get("verification") or {}).get("urls") or {}).items():
        lines.append(f"  public {url}: status {seen.get('status')}, serving version {seen.get('sourceVersion')}, age {seen.get('age')}, x-cache {seen.get('xCache')}")
    if result.get("hint"):
        lines.append(f"  {result['hint']}")
    return "\n".join(lines)


def _run(flags: list[str], *, rerender: bool, update_live: bool = False, inspect: bool = False) -> None:
    paths, options = split_flags(flags)
    name, arguments = operation_for(paths, options, rerender=rerender, update_live=update_live, inspect=inspect)
    from ..graphql_authoring import create_authoring_client
    from ..user_auth_mode import user_auth_requested

    client, _claims = create_authoring_client()
    try:
        result = run_signed_in(client, name, arguments) if user_auth_requested() else run_operator(name, arguments)
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


def content_update_live(flags: list[str]) -> None:
    _run(flags, rerender=False, update_live=True)


def content_inspect_page(flags: list[str]) -> None:
    _run(flags, rerender=False, inspect=True)
