"""Runs the registered commands that have no hand-written CLI implementation, through the same handlers the hosted MCP server calls."""
from __future__ import annotations

import json
from typing import Any

from .command_registry import BY_ROUTE, RegisteredCommand, argument_name, option_name
from .options import parse_options

CLI_PRINCIPAL_SUBJECT = "cli"


def render_story_versions(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    return [
        "\t".join([command.group, command.command, str(version.get("versionNumber")), str(version.get("versionState")),
                   str(version.get("versionCreatedAt") or version.get("updatedAt") or ""), str(version.get("versionCreatedBy") or ""),
                   str(version.get("changeReason") or ""), str(version["id"])])
        for version in result["versions"]
    ]


def render_story_stars(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    return ["\t".join(["stories", "set-stars", result["lineageId"], f"previous {result['previous']}", f"stars {result['stars']}", "editor value",
                       "write" if result["applied"] else "dry-run: nothing sent"])]


def render_assignments_list(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    from .assignments_commands import assignments_list_rows

    if all("queueKey" in row for row in result["assignments"]):
        return assignments_list_rows(result)
    return [json.dumps(result, indent=2, ensure_ascii=False)]


def render_assignment_show(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    from .assignments_commands import assignment_show_rows

    return assignment_show_rows(result)


def render_reviews_list(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    from .review_requests import _line

    return [_line(request) for request in result["reviews"]]


def render_review(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    from .review_requests import _line, review_lines

    request = result["review"]
    return review_lines(request) if command.command == "show" else [_line(request)]


def render_story_show(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    from .story_commands import story_show_rows

    return story_show_rows(result)


def render_story_next(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    from .story_commands import story_next_rows

    return story_next_rows(result)


def render_reference_search(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    from .references_search_cli import summarize

    return [summarize(result)]


TAB_RENDERERS = {"references:search": render_reference_search, "stories:versions": render_story_versions, "stories:next": render_story_next, "stories:set-stars": render_story_stars, "assignments:list": render_assignments_list, "assignments:show": render_assignment_show, "reviews:list": render_reviews_list,
                 "reviews:show": render_review, "stories:show": render_story_show, "reviews:answer": render_review}


def arguments_from_options(command: RegisteredCommand, options: dict[str, Any]) -> dict[str, Any]:
    schema = command.schema_for(True)
    properties = schema["properties"]
    known = {option_name(name): name for name in properties}
    known.update({alias: name for name, alias in command.cli_flag_aliases.items()})
    unknown = sorted(set(options) - set(known))
    if unknown:
        raise ValueError(f"Unknown option --{unknown[0]}. Options: {', '.join('--' + flag for flag in known)}.")
    arguments: dict[str, Any] = {}
    for flag, name in known.items():
        if flag not in options:
            continue
        value = options[flag]
        rule = properties[name]
        if rule["type"] == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"--{flag} must be a whole number" + (f" from {rule['minimum']} to {rule['maximum']}." if "minimum" in rule and "maximum" in rule else ".")) from error
        elif rule["type"] == "object":
            value = json.loads(value)
        elif rule["type"] == "boolean":
            value = value is True or str(value).lower() == "true"
        arguments[name] = value
    missing = [option_name(name) for name in schema["required"] if name not in arguments]
    if missing:
        raise ValueError(f"Missing required option --{missing[0]}.")
    return arguments


def run_registered_command(route: str, flags: list[str], *, create_client=None) -> int:
    from .graphql_authoring import create_authoring_client
    from .mcp_tools import Principal, StaffReads, call_tool

    create_authoring_client = create_client or create_authoring_client

    command = BY_ROUTE[route]
    options = parse_options(flags)
    as_json = bool(options.pop("json", False))
    site = options.pop("site", None) if command.signed_in_only else None
    arguments = arguments_from_options(command, options)
    if command.signed_in_only:
        return _run_signed_in(command, arguments, site, as_json)
    client, _ = create_authoring_client()
    result = call_tool(Principal("staff", CLI_PRINCIPAL_SUBJECT, is_operator=True), command.tool_name, arguments, staff=StaffReads(client))
    _print_result(command, result, as_json)
    return 0


def _print_result(command: RegisteredCommand, result: dict[str, Any], as_json: bool) -> None:
    renderer = TAB_RENDERERS.get(command.route)
    if as_json or renderer is None:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    for line in renderer(command, result):
        print(line)


def _run_signed_in(command: RegisteredCommand, arguments: dict[str, Any], site: str | None, as_json: bool) -> int:
    import os
    import sys

    from . import signed_in_lane
    from .mcp_tools import Principal, StaffReads, call_tool

    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "user"
    try:
        try:
            client = signed_in_lane.client(site)
        except ValueError as error:
            raise signed_in_lane.Refusal(f"Not signed in or session unusable: {str(error).splitlines()[0]}") from None
        result = call_tool(Principal("staff", CLI_PRINCIPAL_SUBJECT, is_operator=True), command.tool_name, arguments, staff=StaffReads(client))
    except signed_in_lane.Refusal as refusal:
        print(str(refusal), file=sys.stderr)
        return 2
    _print_result(command, result, as_json)
    return 0


def usage_line(command: RegisteredCommand) -> str:
    schema = command.schema_for(True)
    required = " ".join(f"--{option_name(name)} VALUE" for name in schema["required"])
    optional = " ".join(f"[--{option_name(name)}{'' if rule['type'] == 'boolean' else ' VALUE'}]" for name, rule in schema["properties"].items() if name not in schema["required"])
    for name, alias in command.cli_flag_aliases.items():
        required = required.replace(f"--{option_name(name)} VALUE", f"--{alias} VALUE")
        optional = optional.replace(f"--{option_name(name)} VALUE", f"--{alias} VALUE")
    return f"{required} {optional}".strip()
