"""The one definition of the commands a person or an agent can run on a site, shared by the CLI and the hosted MCP server.

Each command is named by its CLI route, ``papyrus <group> <command>``. The MCP tool carries the same name with an underscore between group and
command (``stories next`` is the tool ``stories_next``), and takes the same arguments: the CLI flag ``--lineage-id`` is the tool argument
``lineageId``. The CLI runs every registered command through ``run_registered_command`` and the MCP service through ``call_tool``; both end in the
same handler on ``StaffReads``, so a command has one implementation, one argument schema and one description.

A command whose CLI route predates the registry keeps its own CLI implementation (``cli_native``); ``CLI_NATIVE_ROUTES_OUTSIDE_THE_REGISTRY_SCHEMA``
lists them so the drift test fails for any new command that is added to one surface only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STRING = {"type": "string", "minLength": 1}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100}
STARS = {"type": "integer", "minimum": 1, "maximum": 5}
LINEAGE = {"lineageId": STRING}
VERSION = {**LINEAGE, "expectedCurrentVersionId": STRING}
REVISION = {**VERSION, "expectedRevision": STRING}
PAGE = {"limit": LIMIT, "nextToken": STRING}

STORY_FLAG = {"lineageId": "story"}

STAFF = "staff"
READER = "reader"


@dataclass(frozen=True)
class RegisteredCommand:
    group: str
    command: str
    audience: str
    handler: str
    description: str
    required: dict[str, dict] = field(default_factory=dict)
    optional: dict[str, dict] = field(default_factory=dict)
    cli_native: bool = False
    cli_available: bool = True
    writes: str = "reads"
    cli_flag_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def route(self) -> str:
        return f"{self.group}:{self.command}"

    @property
    def tool_name(self) -> str:
        return f"{self.group}_{self.command}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {**self.required, **self.optional}, "required": list(self.required), "additionalProperties": False}


def _command(group: str, command: str, audience: str, handler: str, description: str, required: dict | None = None, optional: dict | None = None,
             **flags: bool | str | dict) -> RegisteredCommand:
    return RegisteredCommand(group, command, audience, handler, description, required or {}, optional or {}, **flags)


REGISTRY: tuple[RegisteredCommand, ...] = (
    _command("references", "search", STAFF, "reference_search", "Find References matching a phrase.", {"query": STRING}, PAGE, cli_native=True),
    _command("references", "show", STAFF, "reference_get", "Read a current Reference.", LINEAGE, cli_native=True),
    _command("references", "concept-search", STAFF, "concept_search", "Find concepts matching a phrase.", {"query": STRING}, PAGE),
    _command("references", "concept-get", STAFF, "concept_get", "Read a concept.", {"id": STRING}),
    _command("stories", "search", STAFF, "story_search", "Find Stories matching a phrase.", {"query": STRING}, PAGE),
    _command("stories", "show", STAFF, "story_get", "Read the current version of a Story.", LINEAGE, cli_native=True),
    _command("stories", "versions", STAFF, "story_versions", "List a Story's saved versions.", LINEAGE, cli_flag_aliases=STORY_FLAG),
    _command("stories", "evidence", STAFF, "story_evidence", "Read the evidence linked to a Story.", LINEAGE, PAGE),
    _command("stories", "next", STAFF, "story_next", "Read the next steps in the Story procedure.", LINEAGE, cli_flag_aliases=STORY_FLAG),
    _command("assignments", "list", STAFF, "assignments_list", "List Assignments.", {"storyLineageId": STRING}, PAGE, cli_native=True),
    _command("assignments", "show", STAFF, "assignment_get", "Read an Assignment.", {"id": STRING}, cli_native=True),
    _command("stories", "save-draft", STAFF, "story_save_draft", "Save a new immutable Story draft.",
             {**VERSION, "body": STRING, "reason": STRING}, {"frontMatter": {"type": "string"}}, writes="writes"),
    _command("references", "decide", STAFF, "reference_decide", "Accept or reject a Reference.",
             {**REVISION, "decision": {"type": "string", "enum": ["accept", "reject"]}}, {"note": STRING}, writes="writes"),
    _command("stories", "set-stars", STAFF, "story_star", "Rate a Story with stars.", {**REVISION, "stars": STARS}, cli_native=True),
    _command("reviews", "list", STAFF, "reviews_list", "List review requests.", {"subjectType": STRING, "subjectId": STRING},
             {"state": STRING, "mode": STRING, **PAGE}, cli_native=True),
    _command("reviews", "show", STAFF, "review_get", "Read a review request.", {"id": STRING}, cli_native=True),
    _command("reviews", "answer", STAFF, "review_answer", "Answer a review request.",
             {"id": STRING, "expectedRevision": STRING, "decision": STRING}, {"feedback": STRING, "steer": STRING}, cli_native=True),
    _command("stories", "request-publish", STAFF, "story_request_publish", "Request a person's approval to publish a Story.", VERSION, writes="writes"),
    _command("reader", "comment", READER, "reader_comment", "Comment on a subject under the site's reader policy.",
             {"subject": STRING, "body": STRING}, {"parent": STRING, "ratingContext": {"type": "object"}}, cli_available=False, writes="writes"),
    _command("reader", "submit", READER, "reader_submit", "Submit a link under the site's reader policy.",
             {"url": STRING, "title": STRING}, {"kind": STRING, "note": STRING}, cli_available=False, writes="writes"),
)

BY_TOOL_NAME = {command.tool_name: command for command in REGISTRY}
BY_ROUTE = {command.route: command for command in REGISTRY}

CLI_NATIVE_ROUTES_OUTSIDE_THE_REGISTRY_SCHEMA = frozenset(command.route for command in REGISTRY if command.cli_native)
COMMANDS_THAT_ARE_NOT_OPERATOR_COMMANDS = frozenset(command.route for command in REGISTRY if not command.cli_available)


def option_name(argument: str) -> str:
    """The CLI flag for a tool argument: ``expectedCurrentVersionId`` is ``--expected-current-version-id``."""
    out = []
    for character in argument:
        out.append(f"-{character.lower()}" if character.isupper() else character)
    return "".join(out)


def argument_name(option: str) -> str:
    head, *rest = option.split("-")
    return head + "".join(word.capitalize() for word in rest)


GENERATED_CLI_COMMANDS = tuple(command for command in REGISTRY if command.cli_available and not command.cli_native)
GENERATED_CLI_ROUTES = frozenset(command.route for command in GENERATED_CLI_COMMANDS)
