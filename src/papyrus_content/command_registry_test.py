import inspect
import re

import pytest

from . import cli
from .command_registry import (
    BY_ROUTE,
    BY_TOOL_NAME,
    COMMANDS_THAT_ARE_NOT_OPERATOR_COMMANDS,
    GENERATED_CLI_ROUTES,
    REGISTRY,
    argument_name,
    option_name,
)
from .mcp_tools import Principal, StaffReads, list_tools
from .registered_commands import arguments_from_options, run_registered_command

STAFF_PRINCIPAL = Principal("staff", "someone", is_agent=True)
READER_PRINCIPAL = Principal("reader", "someone", site_subject="reader-1")


def tool_names_the_service_lists(principal, **adapters):
    return {tool["name"] for tool in list_tools(principal, **adapters)}


def test_the_tool_list_is_exactly_the_registry_for_each_audience():
    staff = StaffReads(client=object())
    assert tool_names_the_service_lists(STAFF_PRINCIPAL, staff=staff) == {command.tool_name for command in REGISTRY if command.audience == "staff"}
    assert tool_names_the_service_lists(READER_PRINCIPAL, reader=lambda event: {}) == {command.tool_name for command in REGISTRY if command.audience == "reader"}


def test_each_tool_carries_the_registry_description_and_schema():
    staff = StaffReads(client=object())
    for tool in list_tools(STAFF_PRINCIPAL, staff=staff):
        command = BY_TOOL_NAME[tool["name"]]
        assert tool["description"] == command.description
        assert tool["inputSchema"] == command.input_schema


def test_every_handler_method_on_the_staff_adapter_is_a_registered_command():
    registered_handlers = {command.handler for command in REGISTRY if command.audience == "staff"}
    public_handlers = {
        name
        for name, member in inspect.getmembers(StaffReads, predicate=inspect.isfunction)
        if not name.startswith("_") and list(inspect.signature(member).parameters)[1:2] == ["principal"]
    }
    assert public_handlers == registered_handlers


def test_every_registered_staff_command_is_offered_by_the_adapter():
    assert {command.tool_name for command in REGISTRY if command.audience == "staff"} == set(StaffReads.available_tools)


def test_tool_names_are_valid_unique_and_spell_the_cli_route():
    assert len({command.tool_name for command in REGISTRY}) == len(REGISTRY)
    for command in REGISTRY:
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", command.tool_name), command.tool_name
        assert command.tool_name == command.route.replace(":", "_", 1)
        assert BY_ROUTE[command.route] is command


def test_every_registered_operator_command_is_a_cli_command():
    from papyrus.operator.help_dispatch import route_tree

    tree = route_tree()
    for command in REGISTRY:
        if command.route in COMMANDS_THAT_ARE_NOT_OPERATOR_COMMANDS:
            continue
        assert command.command in tree.get(command.group, {}), f"{command.route} is an MCP tool with no CLI command"


def test_the_only_commands_without_a_cli_route_are_the_reader_commands():
    assert COMMANDS_THAT_ARE_NOT_OPERATOR_COMMANDS == {"reader:comment", "reader:submit"}


def test_a_command_without_a_native_cli_implementation_is_run_through_the_registry(monkeypatch):
    ran = []
    monkeypatch.setattr(cli, "run_registered_command", lambda route, flags: ran.append((route, flags)))
    for route in sorted(GENERATED_CLI_ROUTES):
        group, command = route.split(":", 1)
        cli.dispatch(group, command, ["--example", "value"])
    assert [route for route, _ in ran] == sorted(GENERATED_CLI_ROUTES)
    assert GENERATED_CLI_ROUTES == {command.route for command in REGISTRY if command.cli_available and not command.cli_native}


def test_every_tool_argument_is_a_cli_option_and_back():
    for command in REGISTRY:
        for name in {**command.required, **command.optional}:
            assert argument_name(option_name(name)) == name


@pytest.mark.parametrize("command", [command for command in REGISTRY if command.cli_available and not command.cli_native], ids=lambda command: command.route)
def test_cli_options_become_the_same_arguments_the_tool_takes(command):
    options = {}
    expected = {}
    for name, rule in {**command.required, **command.optional}.items():
        value = {"integer": "3", "object": '{"a": 1}'}.get(rule["type"], rule.get("enum", ["text"])[0])
        options[option_name(name)] = value
        expected[name] = {"integer": 3, "object": {"a": 1}}.get(rule["type"], value)
    assert arguments_from_options(command, options) == expected


def test_a_missing_required_option_and_an_unknown_option_are_refused():
    command = BY_ROUTE["references:decide"]
    with pytest.raises(ValueError, match="Missing required option"):
        arguments_from_options(command, {})
    with pytest.raises(ValueError, match="Unknown option"):
        arguments_from_options(command, {"nonsense": "x"})


def test_running_a_registered_command_calls_the_tool_the_mcp_service_calls(monkeypatch, capsys):
    calls = []

    class RecordingStaff:
        available_tools = frozenset({"stories_evidence"})

        def __init__(self, client):
            pass

        def story_evidence(self, principal, **arguments):
            calls.append(arguments)
            return {"evidence": []}

    import papyrus_content.graphql_authoring as graphql_authoring
    import papyrus_content.mcp_tools as mcp_tools

    monkeypatch.setattr(graphql_authoring, "create_authoring_client", lambda *a, **k: (object(), {}))
    monkeypatch.setattr(mcp_tools, "StaffReads", RecordingStaff)
    run_registered_command("stories:evidence", ["--lineage-id", "story-1", "--limit", "5"])
    assert calls == [{"lineageId": "story-1", "limit": 5}]
    assert '"evidence"' in capsys.readouterr().out


def test_a_story_command_accepts_the_story_flag_the_other_story_commands_use():
    command = BY_ROUTE["stories:versions"]
    assert arguments_from_options(command, {"story": "story-1"}) == {"lineageId": "story-1"}
    assert arguments_from_options(command, {"lineage-id": "story-1"}) == {"lineageId": "story-1"}


def test_versions_print_one_tab_separated_row_each_and_json_prints_what_the_tool_returns(monkeypatch, capsys):
    version_rows = [{"id": "story-1-v2", "versionNumber": 2, "versionState": "current", "versionCreatedAt": "2026-11-02", "versionCreatedBy": "ana", "changeReason": "edit"},
                    {"id": "story-1-v1", "versionNumber": 1, "versionState": "superseded", "updatedAt": "2026-11-01"}]

    class VersionStaff:
        available_tools = frozenset({"stories_versions"})

        def __init__(self, client):
            pass

        def story_versions(self, principal, **arguments):
            return {"versions": version_rows}

    import papyrus_content.graphql_authoring as graphql_authoring
    import papyrus_content.mcp_tools as mcp_tools

    monkeypatch.setattr(graphql_authoring, "create_authoring_client", lambda *a, **k: (object(), {}))
    monkeypatch.setattr(mcp_tools, "StaffReads", VersionStaff)
    run_registered_command("stories:versions", ["--story", "story-1"])
    assert capsys.readouterr().out.splitlines() == ["stories\tversions\t2\tcurrent\t2026-11-02\tana\tedit\tstory-1-v2", "stories\tversions\t1\tsuperseded\t2026-11-01\t\t\tstory-1-v1"]
    run_registered_command("stories:versions", ["--story", "story-1", "--json"])
    assert '"versions"' in capsys.readouterr().out


def test_story_next_gives_the_operator_the_full_procedure_and_an_external_principal_only_the_story_scoped_one(monkeypatch):
    import papyrus_content.story_commands as story_commands

    monkeypatch.setattr(story_commands, "operator_story_next", lambda client, lineage_id: {"operator_view": lineage_id})

    class CurrentVersionOnlyStaff(StaffReads):
        def _story_versions(self, lineage_id):
            return [{"id": f"{lineage_id}-v1", "versionState": "current", "versionNumber": 1, "stage": "idea", "bodyMarkus": "", "metadata": "{}"}]

    staff = CurrentVersionOnlyStaff(client=object())
    operator = Principal("staff", "cli", is_operator=True)
    assert staff.story_next(operator, lineageId="story-1") == {"operator_view": "story-1"}
    external_view = staff.story_next(STAFF_PRINCIPAL, lineageId="story-1")
    assert "operator_view" not in external_view
    assert external_view["procedure"]


def test_the_command_line_runs_every_registered_command_as_the_operator(monkeypatch):
    seen = []

    class RecordingStaff:
        available_tools = frozenset({"stories_versions"})

        def __init__(self, client):
            pass

        def story_versions(self, principal, **arguments):
            seen.append(principal.is_operator)
            return {"versions": []}

    import papyrus_content.graphql_authoring as graphql_authoring
    import papyrus_content.mcp_tools as mcp_tools

    monkeypatch.setattr(graphql_authoring, "create_authoring_client", lambda *a, **k: (object(), {}))
    monkeypatch.setattr(mcp_tools, "StaffReads", RecordingStaff)
    run_registered_command("stories:versions", ["--story", "story-1"])
    assert seen == [True]
    assert STAFF_PRINCIPAL.is_operator is False


def test_an_external_principal_asking_for_an_operator_only_option_on_set_stars_is_refused():
    from .mcp_tools import call_tool

    staff = StaffReads(client=object())
    for refused in ({"dryRun": True}, {"agent": "someone"}):
        with pytest.raises(ValueError, match="Invalid tool arguments"):
            call_tool(STAFF_PRINCIPAL, "stories_set-stars", {"lineageId": "story-1", "stars": 3, "expectedCurrentVersionId": "story-1-v1", "expectedRevision": "[]", **refused}, staff=staff)
    with pytest.raises(ValueError, match="Invalid tool arguments"):
        call_tool(STAFF_PRINCIPAL, "stories_set-stars", {"lineageId": "story-1", "stars": 3}, staff=staff)
    with pytest.raises(ValueError, match="0 to 5|1 to 5"):
        call_tool(STAFF_PRINCIPAL, "stories_set-stars", {"lineageId": "story-1", "stars": 0, "expectedCurrentVersionId": "story-1-v1", "expectedRevision": "[]"}, staff=staff)


def test_the_operator_rates_a_story_without_a_revision_and_may_clear_the_rating(monkeypatch):
    import papyrus_content.story_signals as story_signals
    from .mcp_tools import call_tool

    asked = []
    monkeypatch.setattr(story_signals, "set_story_stars", lambda client, lineage_id, stars, *, apply, agent=None: asked.append((lineage_id, stars, apply, agent)) or {"lineageId": lineage_id})
    staff = StaffReads(client=object())
    operator = Principal("staff", "cli", is_operator=True)
    call_tool(operator, "stories_set-stars", {"lineageId": "story-1", "stars": 0, "dryRun": True, "agent": "an agent"}, staff=staff)
    assert asked == [("story-1", 0, False, "an agent")]


def test_assignments_list_is_story_scoped_for_an_external_principal_and_wide_for_the_operator(monkeypatch):
    from .mcp_tools import call_tool

    staff = StaffReads(client=object())
    for refused in ({"queue": "q"}, {"status": "open"}, {"type": "research"}, {"section": "news"}):
        with pytest.raises(ValueError, match="Invalid tool arguments"):
            call_tool(STAFF_PRINCIPAL, "assignments_list", {"storyLineageId": "story-1", **refused}, staff=staff)
    with pytest.raises(ValueError, match="Invalid tool arguments"):
        call_tool(STAFF_PRINCIPAL, "assignments_list", {}, staff=staff)

    import papyrus_content.assignments_commands as assignments_commands

    asked = []
    monkeypatch.setattr(assignments_commands, "operator_assignments_list", lambda client, **filters: asked.append(filters) or {"assignments": []})
    operator = Principal("staff", "cli", is_operator=True)
    assert call_tool(operator, "assignments_list", {"queue": "q", "status": "open"}, staff=staff) == {"assignments": []}
    assert asked == [{"queue": "q", "status": "open", "assignment_type": None, "section": None}]


def test_reviews_are_subject_scoped_for_an_external_principal_and_wide_for_the_operator(monkeypatch):
    from .mcp_tools import call_tool

    staff = StaffReads(client=object())
    with pytest.raises(ValueError, match="Invalid tool arguments"):
        call_tool(STAFF_PRINCIPAL, "reviews_list", {}, staff=staff)
    with pytest.raises(ValueError, match="Invalid tool arguments"):
        call_tool(STAFF_PRINCIPAL, "reviews_list", {"subjectType": "story", "subjectId": "s", "raisedBy": "someone"}, staff=staff)
    with pytest.raises(ValueError, match="Invalid tool arguments"):
        call_tool(STAFF_PRINCIPAL, "reviews_answer", {"id": "r", "decision": "approve"}, staff=staff)

    import papyrus_content.review_requests as review_requests

    asked = []
    monkeypatch.setattr(review_requests, "operator_reviews_list", lambda client, **filters: asked.append(filters) or {"reviews": []})
    operator = Principal("staff", "cli", is_operator=True)
    assert call_tool(operator, "reviews_list", {"raisedBy": "idea-pipeline", "state": "open"}, staff=staff) == {"reviews": []}
    assert asked == [{"state": "open", "mode": None, "raised_by": "idea-pipeline", "subject_type": None, "subject_id": None}]


def test_story_show_gives_the_operator_the_signals_view_and_an_external_principal_only_the_current_version(monkeypatch):
    import papyrus_content.story_commands as story_commands
    from .mcp_tools import call_tool

    monkeypatch.setattr(story_commands, "operator_story_show", lambda client, lineage_id, bucket: {"lineageId": lineage_id, "bucket": bucket})

    class CurrentVersionOnlyStaff(StaffReads):
        def _story_versions(self, lineage_id):
            return [{"id": f"{lineage_id}-v1", "versionState": "current", "versionNumber": 1}]

    staff = CurrentVersionOnlyStaff(client=object())
    operator = Principal("staff", "cli", is_operator=True)
    assert call_tool(operator, "stories_show", {"lineageId": "story-1", "bucket": "week"}, staff=staff) == {"lineageId": "story-1", "bucket": "week"}
    assert call_tool(STAFF_PRINCIPAL, "stories_show", {"lineageId": "story-1"}, staff=staff)["story"]["id"] == "story-1-v1"
    with pytest.raises(ValueError, match="Invalid tool arguments"):
        call_tool(STAFF_PRINCIPAL, "stories_show", {"lineageId": "story-1", "bucket": "week"}, staff=staff)
