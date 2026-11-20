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


def render_story_next(command: RegisteredCommand, result: dict[str, Any]) -> list[str]:
    from .story_commands import story_next_rows

    return story_next_rows(result)


TAB_RENDERERS = {"stories:versions": render_story_versions, "stories:next": render_story_next, "stories:set-stars": render_story_stars}


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


def run_registered_command(route: str, flags: list[str]) -> None:
    from .graphql_authoring import create_authoring_client
    from .mcp_tools import Principal, StaffReads, call_tool

    command = BY_ROUTE[route]
    options = parse_options(flags)
    as_json = bool(options.pop("json", False))
    arguments = arguments_from_options(command, options)
    client, _ = create_authoring_client()
    result = call_tool(Principal("staff", CLI_PRINCIPAL_SUBJECT, is_operator=True), command.tool_name, arguments, staff=StaffReads(client))
    renderer = TAB_RENDERERS.get(route)
    if as_json or renderer is None:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    for line in renderer(command, result):
        print(line)


def usage_line(command: RegisteredCommand) -> str:
    schema = command.schema_for(True)
    required = " ".join(f"--{option_name(name)} VALUE" for name in schema["required"])
    optional = " ".join(f"[--{option_name(name)}{'' if rule['type'] == 'boolean' else ' VALUE'}]" for name, rule in schema["properties"].items() if name not in schema["required"])
    for name, alias in command.cli_flag_aliases.items():
        required = required.replace(f"--{option_name(name)} VALUE", f"--{alias} VALUE")
        optional = optional.replace(f"--{option_name(name)} VALUE", f"--{alias} VALUE")
    return f"{required} {optional}".strip()
