"""The guideline file form and papyrus guidelines check (features_backend/guidelines-files.feature). Files in a temporary folder; the network is closed."""
from __future__ import annotations

import contextlib
import io
import json
import os
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

from papyrus_content.guidelines import cli as guidelines_cli  # noqa: E402
from papyrus_content.guidelines import files as guideline_files  # noqa: E402

ID = "https://example.org/id/{name}"


def _folder(context) -> Path:
    if not hasattr(context, "gl_dir"):
        context.gl_dir = Path(tempfile.mkdtemp()) / "guidelines"
        context.gl_dir.mkdir()
    return context.gl_dir


def _write(context, name: str, meta: dict, body: str = "Say it plainly.") -> None:
    folder = _folder(context) / name
    folder.mkdir(exist_ok=True)
    (folder / guideline_files.FILE_NAME).write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n" + body + "\n", encoding="utf-8")


def _meta(name: str, kind: str, scope: str, severity: str, **more) -> dict:
    return {"id": ID.format(name=name), "type": "papyrus:Guideline", "name": name, "description": f"The {name} guideline.", "kind": kind, "scope": scope,
            "severity": severity, **more}


@given('a guidelines folder with the guideline "{name}" of kind {kind}, scope {scope} and severity {severity} that avoids "{word}"')
def step_avoids(context, name, kind, scope, severity, word):
    _write(context, name, _meta(name, kind, scope, severity, avoid=[word]))


@given('a guidelines folder with the guideline "{name}" of kind {kind}, scope {scope} and severity {severity} that avoids "{word}" in the language {language}')
def step_language(context, name, kind, scope, severity, language, word):
    _write(context, name, _meta(name, kind, scope, severity, language=language, avoid=[word]))


@given('a guidelines folder with the guideline "{name}" of kind {kind}, scope {scope} and severity {severity} that matches the pattern "{pattern}"')
def step_pattern(context, name, kind, scope, severity, pattern):
    _write(context, name, _meta(name, kind, scope, severity, pattern=[pattern]))


@given('the guideline "{name}" of kind {kind}, scope {scope} and severity {severity} that avoids "{word}"')
def step_more_avoids(context, name, kind, scope, severity, word):
    _write(context, name, _meta(name, kind, scope, severity, avoid=[word]))


@given('the guideline "{name}" of kind {kind}, scope {scope} and severity {severity} with only prose')
def step_prose(context, name, kind, scope, severity):
    _write(context, name, _meta(name, kind, scope, severity), "Sound earned, not excited.")


@given('the guideline "{name}" of kind {kind}, scope {scope} and severity {severity} with a maxLength of {limit:d}')
def step_max(context, name, kind, scope, severity, limit):
    _write(context, name, _meta(name, kind, scope, severity, maxLength=limit))


_BREAKS = {
    "no kind": lambda meta: meta.pop("kind"),
    "no id": lambda meta: meta.pop("id"),
    'an unknown key "tone"': lambda meta: meta.update(tone="plain"),
    "a nested value for avoid": lambda meta: meta.update(avoid=[["we believe"]]),
    "a nested object for scope": lambda meta: meta.update(scope={"channel": "x"}),
    'the severity "fatal"': lambda meta: meta.update(severity="fatal"),
    'the kind "video"': lambda meta: meta.update(kind="video"),
    'the scope "channel"': lambda meta: meta.update(scope="channel"),
    "an id that is not a permanent id": lambda meta: meta.update(id="plain claims"),
    "a name that is not the folder's name": lambda meta: meta.update(name="other-name"),
    "a maxLength of zero": lambda meta: meta.update(maxLength=0),
    "a pattern that is not a pattern": lambda meta: meta.update(pattern=["(unclosed"]),
    "a list for severity": lambda meta: meta.update(severity=["error", "warn"]),
}


@given('a guidelines folder with a guideline "{name}" whose front matter has {problem}')
def step_broken(context, name, problem):
    meta = _meta(name, "writing", "publication", "error", avoid=["we believe"])
    _BREAKS[problem](meta)
    _write(context, name, meta)


@given('a guidelines folder with an empty folder "{name}"')
def step_empty(context, name):
    (_folder(context) / name).mkdir()


@given('a guideline file "{name}" with no front matter')
def step_no_front(context, name):
    (_folder(context) / name).mkdir()
    (_folder(context) / name / guideline_files.FILE_NAME).write_text("Just prose.\n", encoding="utf-8")


@given('the guidelines "{first}" and "{second}" that share one id')
def step_twins(context, first, second):
    for name in (first, second):
        _write(context, name, {**_meta(name, "writing", "publication", "guidance"), "id": ID.format(name="shared")})


@given('a file to check that says "{text}"')
def step_text(context, text):
    context.gl_target = Path(tempfile.mkdtemp()) / "post.md"
    context.gl_target.write_text(text + "\n", encoding="utf-8")


@when("the guideline folders are loaded")
def step_load(context):
    context.loaded = guideline_files.load_directory(_folder(context))


def _check(context, *flags):
    out = io.StringIO()

    def closed(*args, **kwargs):
        raise AssertionError("the offline check opened a network connection")

    with patch.object(socket.socket, "connect", closed), patch("papyrus_content.graphql_authoring.create_authoring_client", side_effect=closed), contextlib.redirect_stdout(out):
        context.status = guidelines_cli.command(["check", "--dir", str(_folder(context)), *flags, str(context.gl_target)], stdout=out)
    context.answer = json.loads(out.getvalue())


@when("the file is checked offline with the network closed")
def step_check(context):
    _check(context)


@when('the file is checked offline for the scope "{scope}"')
def step_check_scope(context, scope):
    _check(context, "--scope", scope)


@when('the file is checked offline in the language "{language}"')
def step_check_language(context, language):
    _check(context, "--language", language)


@then("the set is accepted with {count:d} guideline")
@then("the set is accepted with {count:d} guidelines")
def step_accepted(context, count):
    assert not context.loaded.problems and len(context.loaded.guidelines) == count, context.loaded.problems


@then('the guideline "{name}" keeps its prose body')
def step_body(context, name):
    assert next(item for item in context.loaded.guidelines if item.name == name).body == "Say it plainly."


@then("every kind of the file form is a registered guideline kind")
def step_kinds(context):
    from papyrus_content.guidelines.document import kind_names

    assert set(guideline_files.KINDS) <= set(kind_names()), kind_names()


@then("the set is refused")
def step_refused(context):
    assert context.loaded.problems


@then('the refusal names the guideline "{name}", the key "{key}" and the code "{code}"')
def step_names_key(context, name, key, code):
    assert any(p.folder == name and p.key == key and p.code == code for p in context.loaded.problems), context.loaded.problems


@then('the refusal names the guideline "{name}" with the code "{code}"')
def step_names_code(context, name, code):
    assert any(p.folder == name and p.code == code for p in context.loaded.problems), context.loaded.problems


@then('the check finds the phrase "{phrase}" against "{name}" on line {line:d}')
def step_finds_phrase(context, phrase, name, line):
    assert any(f["guideline"] == name and f["match"].lower() == phrase.lower() and f["line"] == line for f in context.answer["result"]["findings"]), context.answer


@then('the check finds the rule "{rule}" against "{name}"')
def step_finds_rule(context, rule, name):
    assert any(f["guideline"] == name and f["rule"] == rule for f in context.answer["result"]["findings"]), context.answer


@then("the check finds nothing")
def step_nothing(context):
    assert context.answer["result"]["findings"] == [], context.answer


@then("the command exits with status {status:d}")
def step_status(context, status):
    assert context.status == status, (context.status, context.answer)


@then('the guideline "{name}" is listed as not checked offline because it needs judgement')
def step_judgement(context, name):
    assert {"guideline": name, "reason": "needs judgement"} in context.answer["result"]["notCheckedOffline"], context.answer


@then('the guideline "{name}" is listed as not checked offline because it is written for {language}')
def step_for_language(context, name, language):
    assert any(item["guideline"] == name and f"written for {language}" in item["reason"] for item in context.answer["result"]["notCheckedOffline"]), context.answer


@then("the check reports {warnings:d} warning and {errors:d} errors")
def step_counts(context, warnings, errors):
    assert context.answer["result"]["summary"] == {"errors": errors, "warnings": warnings}, context.answer


@then('the guideline "{name}" produced no finding')
def step_no_finding(context, name):
    assert all(f["guideline"] != name for f in context.answer["result"]["findings"]), context.answer


@then('the command refuses the guidelines, names "{key}" and exits with status {status:d}')
def step_refuses(context, key, status):
    problems = context.answer["error"]["details"]["problems"]
    assert context.status == status and context.answer["error"]["code"] == "invalid_input" and any(p["key"] == key for p in problems), context.answer


@then("nothing was checked")
def step_unchecked(context):
    assert "result" not in context.answer


@when('an agent runs "papyrus guidelines check --help" with no site and no sign-in')
def step_help(context):
    from papyrus import cli

    opened = []
    out, err = io.StringIO(), io.StringIO()
    environment = {name: value for name, value in os.environ.items() if not name.startswith(("PAPYRUS_", "AWS_"))}
    with patch.dict(os.environ, environment, clear=True), patch("papyrus_content.graphql_authoring.create_authoring_client", side_effect=lambda *a, **k: opened.append(1)), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            context.status = cli.main(["guidelines", "check", "--help"])
        except SystemExit as stop:
            context.status = int(stop.code or 0)
    context.help_output, context.opened = out.getvalue(), opened


@then('the printed usage shows "{flag}" and says it is read only')
def step_help_text(context, flag):
    assert context.status == 0 and flag in context.help_output and "read only" in context.help_output, context.help_output
