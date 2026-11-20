"""Agent definition files and papyrus agents validate (features_backend/agent-definition.feature). Files in a temporary folder; the network is closed."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.agent_definitions import cli as agents_cli  # noqa: E402
from papyrus_content.agent_definitions import definition as agent_definition  # noqa: E402

CORE_RULES = ["Place a third-party image without credit", "Add a credit to a generated image", "Write Approved by on any image"]


def _complete(name: str, responsibility: str) -> dict:
    return {
        "schemaVersion": 1, "id": name, "version": 1, "responsibility": responsibility, "procedure": "illustrate_story",
        "wakes": {"changes": [{"kind": "Item", "change": "step_changed", "filter": {"step": "illustration"}}], "schedule": {"cron": "0 6 * * *", "timeZone": "America/New_York"}},
        "serialBy": "subject", "paid": True, "safeToRepeat": False,
        "operations": {"image_search": "observe", "image_apply": "draft"}, "tier": "editorial",
        "template": {
            "trigger": "The Illustration step of a Story becomes ready.", "inputs": "The Story and the site's image style profile.",
            "decision": "Which picture explains the Story or leads it.", "mayWrite": ["Image candidates", "The placed image and its alt text"],
            "mustNever": list(CORE_RULES), "seenAndReversed": "On the Story's page; a person chooses another candidate or removes the picture.",
            "records": "One run record per wake.", "fails": "Closed: a failed run leaves nothing that looks done.",
            "costAndBound": "Bounded by the model provider's rate limit and the site's budget; no counts.", "measured": "How often people keep the picture.",
            "gherkin": ["illustrate-stories.feature"],
        },
    }


def _folder(context, kind: str = "site") -> Path:
    attribute = f"ad_{kind}"
    if not hasattr(context, attribute):
        setattr(context, attribute, Path(tempfile.mkdtemp()) / kind)
        getattr(context, attribute).mkdir()
    return getattr(context, attribute)


def _write(directory: Path, name: str, data: dict) -> None:
    (directory / f"{name}{agent_definition.SUFFIX}").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _read(directory: Path, name: str) -> dict:
    return yaml.safe_load((directory / f"{name}{agent_definition.SUFFIX}").read_text(encoding="utf-8"))


def _edit(context, name: str, change) -> None:
    directory = _folder(context, "site")
    data = _read(directory, name)
    change(data)
    _write(directory, name, data)


@given('a definitions folder with the complete definition "{name}" for the responsibility "{responsibility}"')
@given('a site definitions folder with the complete definition "{name}" for the responsibility "{responsibility}"')
@given('the site folder also has the complete definition "{name}" for the responsibility "{responsibility}"')
def step_complete(context, name, responsibility):
    _write(_folder(context, "site"), name, _complete(name, responsibility))


@given('the engine\'s core definition "{name}" for the responsibility "{responsibility}"')
def step_core(context, name, responsibility):
    _write(_folder(context, "core"), name, _complete(name, responsibility))


@given('the definition "{name}" has no template line "{line}"')
def step_no_line(context, name, line):
    _edit(context, name, lambda data: data["template"].pop(line))


@given('the definition "{name}" has an empty must-never list')
def step_empty_rules(context, name):
    _edit(context, name, lambda data: data["template"].update(mustNever=[]))


@given('the definition "{name}" uses the operation "{operation}" at the rung "{rung}"')
def step_operation(context, name, operation, rung):
    _edit(context, name, lambda data: data["operations"].update({operation: rung}))


@given('the definition "{name}" sets the rung "{rung}"')
def step_rung(context, name, rung):
    _edit(context, name, lambda data: data.update(rung=rung))


@given('the definition "{name}" runs as a container')
def step_container(context, name):
    _edit(context, name, lambda data: data.update(executor="container"))


_BREAKS = {
    'the tier "gpt-6-luna"': lambda data: data.update(tier="gpt-6-luna"),
    'the executor "container"': lambda data: data.update(executor="container"),
    "no wake at all": lambda data: data.pop("wakes"),
    'a schedule with the time zone "Mars/Base"': lambda data: data["wakes"].update(schedule={"cron": "0 6 * * *", "timeZone": "Mars/Base"}),
    "a schedule that is not a cron expression": lambda data: data["wakes"].update(schedule={"cron": "every morning", "timeZone": "America/New_York"}),
    'the serial scope "everything"': lambda data: data.update(serialBy="everything"),
    "no paid flag": lambda data: data.pop("paid"),
    "no safe-to-repeat flag": lambda data: data.pop("safeToRepeat"),
    "no procedure key": lambda data: data.pop("procedure"),
    'an unknown field "mood"': lambda data: data.update(mood="cheerful"),
    "a listen for a change no feed produces": lambda data: data["wakes"].update(changes=[{"kind": "Reference", "change": "ready"}]),
    "a listen for a change of a kind no feed covers": lambda data: data["wakes"].update(changes=[{"kind": "Story", "change": "created"}]),
}


@given('the definition "{name}" listens for the change "{change}" of "{kind}"')
def step_listens(context, name, change, kind):
    _edit(context, name, lambda data: data["wakes"].update(changes=[{"kind": kind, "change": change}]))


@given('the definition "{name}" has {problem}')
def step_breaks(context, name, problem):
    _edit(context, name, _BREAKS[problem])


@given('the definition file "{file}" holds the id "{name}"')
def step_copy(context, file, name):
    data = _read(_folder(context, "site"), name)
    _write(_folder(context, "site"), file, data)
    (_folder(context, "site") / f"{name}{agent_definition.SUFFIX}").unlink()


@given('a site definitions folder that extends "{base}" with the instruction "{instruction}" and the must-never rule "{rule}"')
def step_extends(context, base, instruction, rule):
    _write(_folder(context, "site"), base, {"schemaVersion": 1, "extends": base, "instructions": [instruction], "mustNever": [rule]})


@given('a site definitions folder that extends "{base}" with the instruction "{instruction}"')
def step_extends_instruction(context, base, instruction):
    _write(_folder(context, "site"), base, {"schemaVersion": 1, "extends": base, "instructions": [instruction]})


@given('a site definitions folder that extends "{base}" and removes the core must-never rule "{rule}"')
def step_removes(context, base, rule):
    _write(_folder(context, "site"), base, {"schemaVersion": 1, "extends": base, "removes": [rule]})


@given('a site definitions folder that extends "{base}" and sets the tier "{tier}"')
def step_sets_tier(context, base, tier):
    _write(_folder(context, "site"), base, {"schemaVersion": 1, "extends": base, "tier": tier})


@when("the definition folders are validated")
def step_validate(context):
    context.loaded = agent_definition.load_sets(_folder(context, "site"), _folder(context, "core"))


@when("the engine's core definitions are validated")
def step_validate_core(context):
    context.loaded = agent_definition.load_sets(agent_definition.CORE_DIRECTORY)


@when("papyrus agents validate is run on the folder with the network closed")
def step_cli(context):
    out = io.StringIO()

    def closed(*args, **kwargs):
        raise AssertionError("the offline check opened a network connection")

    with patch.object(socket.socket, "connect", closed), contextlib.redirect_stdout(out):
        context.status = agents_cli.command(["validate", "--dir", str(_folder(context, "site")), "--core", str(_folder(context, "core"))], stdout=out)
    context.answer = json.loads(out.getvalue())


@then("the set is accepted")
def step_accepted_plain(context):
    assert not context.loaded.problems, context.loaded.problems


@then("the set is accepted with {count:d} definition")
def step_accepted(context, count):
    assert not context.loaded.problems and len(context.loaded.definitions) == count, context.loaded.problems


@then('the definition "{name}" lists the operation "{operation}" at the lowest rung "{rung}"')
def step_lists(context, name, operation, rung):
    assert context.loaded.get(name).data["operations"][operation] == rung


@then('the refusal names the definition "{name}", the line "{line}" and the code "{code}"')
def step_names(context, name, line, code):
    assert any(p.definition == name and p.line == line and p.code == code for p in context.loaded.problems), [p.as_dict() for p in context.loaded.problems]


@then('the definition "{name}" is not among the refusals')
def step_not_refused(context, name):
    assert not any(p.definition == name for p in context.loaded.problems), [p.as_dict() for p in context.loaded.problems]


@then('the effective definition "{name}" keeps every core must-never rule')
def step_keeps(context, name):
    assert all(rule in context.loaded.get(name).must_never for rule in CORE_RULES), context.loaded.get(name).must_never


@then('the effective definition "{name}" also has the must-never rule "{rule}"')
def step_has_rule(context, name, rule):
    assert rule in context.loaded.get(name).must_never


@then('the effective definition "{name}" also has the instruction "{instruction}"')
def step_has_instruction(context, name, instruction):
    assert instruction in context.loaded.get(name).instructions


@then('the answer lists the definition "{name}"')
def step_answer_lists(context, name):
    assert any(item["id"] == name for item in context.answer["result"]["definitions"]), context.answer


@then('the answer names the definition "{name}", the line "{line}" and the code "{code}"')
def step_answer_names(context, name, line, code):
    problems = context.answer["error"]["details"]["problems"]
    assert any(p["definition"] == name and p["line"] == line and p["code"] == code for p in problems), problems


# The engine's shipped core definitions (features_backend/rating-agent-definition.feature).
def _shipped(name: str) -> dict:
    return _read(agent_definition.CORE_DIRECTORY, name)


@then('the core set holds the definition "{name}" for the responsibility "{responsibility}"')
def step_core_holds(context, name, responsibility):
    assert context.loaded.get(name).responsibility == responsibility


@then('the definition "{name}" has the tier "{tier}"')
def step_tier(context, name, tier):
    assert context.loaded.get(name).data["tier"] == tier


@then('the definition "{name}" wakes by a daily schedule and by no change')
def step_daily(context, name):
    wakes = context.loaded.get(name).data["wakes"]
    fields = wakes["schedule"]["cron"].split()
    assert set(wakes) == {"schedule"} and fields[2:] == ["*", "*", "*"] and fields[0].isdigit() and fields[1].isdigit(), wakes


@then('the definition "{name}" runs one at a time by "{scope}"')
def step_serial(context, name, scope):
    assert context.loaded.get(name).data["serialBy"] == scope


@then('the definition "{name}" is paid and safe to repeat')
def step_paid(context, name):
    data = context.loaded.get(name).data
    assert data["paid"] is True and data["safeToRepeat"] is True


@then('every operation of the definition "{name}" is named at the lowest rung the operation table allows')
def step_table_rungs(context, name):
    from papyrus_content.images.operations import operation

    operations = context.loaded.get(name).data["operations"]
    assert operations
    for operation_name, rung in operations.items():
        assert operation(operation_name).agent_rung == rung, (operation_name, rung)


@then('the definition "{name}" must never "{start}"')
def step_must_never(context, name, start):
    assert any(rule.startswith(start) for rule in context.loaded.get(name).must_never), context.loaded.get(name).must_never


@then('the definition "{name}" names no rung, pause, budget or model')
def step_no_policy(context, name):
    data = _shipped(name)
    assert not set(data) & set(agent_definition.POLICY_FIELDS), data
    assert data["tier"] in agent_definition.TIERS


@when("papyrus agents validate is run on the engine's core definitions with the network closed")
def step_cli_core(context):
    out = io.StringIO()

    def closed(*args, **kwargs):
        raise AssertionError("the offline check opened a network connection")

    with patch.object(socket.socket, "connect", closed), contextlib.redirect_stdout(out):
        context.status = agents_cli.command(["validate", "--dir", str(agent_definition.CORE_DIRECTORY)], stdout=out)
    context.answer = json.loads(out.getvalue())


@then('the answer lists "{name}" among the definitions using the operation "{operation}"')
def step_answer_operation(context, name, operation):
    listed = next(item for item in context.answer["result"]["definitions"] if item["id"] == name)
    assert operation in listed["operations"], listed


@given('a site definitions folder that extends the core definition "{base}" with the must-never rule "{rule}"')
def step_extends_shipped(context, base, rule):
    _write(_folder(context, "site"), base, {"schemaVersion": 1, "extends": base, "mustNever": [rule]})


@when("the engine's core definitions are validated with that site folder")
def step_validate_shipped_with_site(context):
    context.loaded = agent_definition.load_sets(_folder(context, "site"))


@then('the effective definition "{name}" keeps every must-never rule of the shipped definition')
def step_keeps_shipped(context, name):
    assert all(rule in context.loaded.get(name).must_never for rule in _shipped(name)["template"]["mustNever"])
