"""Steps for pod-check-guidelines.feature: a pod's guidelines folder is checked by the guideline checker's own validation (PPY-58f931).

The pod steps (``pod_steps.py``) run ``papyrus pod check`` through the real CLI with the network closed. The guideline steps write the files and run
``papyrus guidelines check`` (``guidelines_cli.check_command``) on the same folder, so both verdicts come from the same code. Ids are ``sample-NNNN``.
"""
from __future__ import annotations

import io
import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml
from behave import given, then, when

from papyrus_content.guidelines import cli as guidelines_cli
from papyrus_content.guidelines import files as guideline_files

GUIDELINES = "guidelines"


def _sample_id(name: str) -> str:
    return f"https://example.org/id/sample-{sum(map(ord, name)) % 10000:04d}"


def _meta(name: str, kind: str, scope: str, severity: str, **more) -> dict:
    return {"id": _sample_id(name), "type": "papyrus:Guideline", "name": name, "description": f"The {name} guideline.", "kind": kind,
            "scope": scope, "severity": severity, **more}


def _write(context, name: str, meta: dict | None, body: str = "Say it plainly.") -> None:
    folder = context.pod / GUIDELINES / name
    folder.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n" + body + "\n" if meta is not None else body + "\n"
    (folder / guideline_files.FILE_NAME).write_text(text, encoding="utf-8")


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


@given('the pod has the guideline "{name}" of kind {kind}, scope {scope} and severity {severity} that avoids "{word}"')
def guideline_valid(context, name, kind, scope, severity, word):
    _write(context, name, _meta(name, kind, scope, severity, avoid=[word]))


@given('the pod has the guideline "{name}" whose front matter has {problem}')
def guideline_broken(context, name, problem):
    meta = _meta(name, "writing", "publication", "error", avoid=["we believe"])
    _BREAKS[problem](meta)
    _write(context, name, meta)


@given('the pod has a guideline file "{name}" with no front matter')
def guideline_no_front(context, name):
    _write(context, name, None, "Just prose.")


@given('the pod has the guidelines "{first}" and "{second}" that share one id')
def guidelines_twins(context, first, second):
    for name in (first, second):
        _write(context, name, {**_meta(name, "writing", "publication", "guidance"), "id": _sample_id("shared")})


@given("the pod has no guidelines folder")
def no_guidelines_folder(context):
    assert not (context.pod / GUIDELINES).exists()


@given("the pod has an empty guidelines folder")
def empty_guidelines_folder(context):
    (context.pod / GUIDELINES).mkdir()


@when("papyrus guidelines check reads the pod's guidelines folder")
def guidelines_check_reads_pod(context):
    target = Path(tempfile.mkdtemp()) / "post.md"
    target.write_text("A post to check.\n", encoding="utf-8")
    out = io.StringIO()

    def closed(*args, **kwargs):
        raise AssertionError("papyrus guidelines check opened a network connection")

    with patch.object(socket.socket, "connect", closed):
        context.gl_status = guidelines_cli.command(["check", "--dir", str(context.pod / GUIDELINES), str(target)], stdout=out)
    context.gl_answer = json.loads(out.getvalue())


@then('the pod report does not say "{text}"')
def report_does_not_say(context, text):
    assert text not in context.output + context.error, (text, context.output, context.error)


@then("papyrus guidelines check accepts the folder")
def guidelines_accepts(context):
    assert context.gl_status == 0 and context.gl_answer["ok"] is True, context.gl_answer


@then('papyrus guidelines check refuses the folder with the key "{key}" and the message "{message}"')
def guidelines_refuses(context, key, message):
    problems = context.gl_answer.get("error", {}).get("details", {}).get("problems", [])
    assert context.gl_status == 2 and context.gl_answer["ok"] is False, context.gl_answer
    assert any(item["key"] == key and message in item["message"] for item in problems), problems
