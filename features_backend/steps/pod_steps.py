"""Steps for the pod features (PPY-4834f3): a pod is a folder of notes, and `papyrus pod init|id|check` work on it through the real CLI.

Every run goes through ``papyrus.cli.main`` with the backend client, the network and urlopen made to fail, because a pod command never signs in or
reads a site. The fixture pod is ``features_backend/fixtures/pod``: a valid level 1 pod with a note of every class. When the profile changes its
generated context, refresh the fixture's ``papyrus.context.jsonld`` with ``papyrus pod init`` into an empty folder and copy that file over.
"""
from __future__ import annotations

import io
import json
import shlex
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from behave import given, step, then, when

from papyrus import cli
from papyrus.pod import context as pod_context
from papyrus_content import graphql_authoring

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pod"
EXAMPLE_BASE = "https://example.org/id/"
GIT = ["git", "-c", "user.name=Pod Test", "-c", "user.email=pod-test", "-c", "commit.gpgsign=false"]


def _text(value: str) -> str:
    """A step argument as written in a feature file: `\\"` stands for a quote."""
    return value.replace('\\"', '"')


def _new_pod_dir(context) -> Path:
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    context.pod = Path(directory.name) / "pod"
    return context.pod


def _snapshot(pod: Path) -> dict[str, bytes]:
    if not pod.is_dir():
        return {}
    return {path.relative_to(pod).as_posix(): path.read_bytes() for path in sorted(pod.rglob("*")) if path.is_file() and ".git" not in path.relative_to(pod).parts}


def _write(context, path: str, text: str) -> None:
    target = context.pod / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _run(context, line: str) -> None:
    words = shlex.split(line)
    assert words[0] == "papyrus", line
    if "pod" not in context:
        _new_pod_dir(context)
    argv = [str(context.pod) if word == "POD" else word for word in words[1:]]
    context.before = _snapshot(context.pod)
    context.touched = []

    def touched(label):
        def fake(*args, **kwargs):
            context.touched.append(label)
            raise AssertionError(f"touched {label}")
        return fake

    out, err = io.StringIO(), io.StringIO()
    patches = [
        patch.object(graphql_authoring, "create_authoring_client", touched("create_authoring_client")),
        patch.object(graphql_authoring.PapyrusGraphQLAuthoringClient, "__init__", touched("backend client")),
        patch.object(urllib.request, "urlopen", touched("urlopen")),
        patch.object(socket, "create_connection", touched("network")),
    ]
    for started in patches:
        started.start()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                context.status = cli.main(argv)
            except SystemExit as stop:
                context.status = int(stop.code or 0)
    finally:
        for started in patches:
            started.stop()
    context.output, context.error = out.getvalue(), err.getvalue()


# ---- Given -----------------------------------------------------------------------------------------------------------

@given("a folder of plain notes with no front matter")
def plain_notes(context):
    _new_pod_dir(context)
    _write(context, "about.md", "A plain note.\n")
    _write(context, "ideas/one.md", "Another plain note, in a folder.\n")


@given("an empty pod folder")
def empty_folder(context):
    _new_pod_dir(context).mkdir()


@given("no pod folder yet")
def no_folder(context):
    _new_pod_dir(context)


@given("a started pod")
def started_pod(context):
    _new_pod_dir(context)
    _run(context, f"papyrus pod init POD --id-base {EXAMPLE_BASE}")
    assert context.status == 0, context.error


@given("a copy of the fixture pod")
def fixture_pod(context):
    shutil.copytree(FIXTURE, _new_pod_dir(context))


@given('the pod file "{path}" has this text:')
def file_has_text(context, path):
    _write(context, path, context.text + "\n")


@step('the pod file "{path}" has "{old}" replaced by "{new}"')
def file_replace(context, path, old, new):
    old, new = _text(old), _text(new)
    target = context.pod / path
    text = target.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {path}"
    target.write_text(text.replace(old, new), encoding="utf-8")


@step('the pod file "{path}" loses the text "{old}"')
def file_loses(context, path, old):
    old = _text(old)
    target = context.pod / path
    text = target.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {path}"
    target.write_text(text.replace(old, ""), encoding="utf-8")


@given('the pod file "{path}" is removed')
def file_removed(context, path):
    (context.pod / path).unlink()


@given("the pod is a git repository with everything committed")
def git_committed(context):
    for arguments in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "A pod"]):
        subprocess.run([*GIT, "-C", str(context.pod), *arguments], check=True, capture_output=True)


@given('the id of the pod note "{path}" is changed')
def id_changed(context, path):
    target = context.pod / path
    text = target.read_text(encoding="utf-8")
    start = text.index("id: https://") + len("id: ")
    end = text.index("\n", start)
    changed = text[start:end][:-1] + ("0" if not text[start:end].endswith("0") else "1")
    target.write_text(text[:start] + changed + text[end:], encoding="utf-8")


@given('the pod note "{path}" is renamed to "{new}"')
def note_renamed(context, path, new):
    (context.pod / path).rename(context.pod / new)


@given('a relation-types file in which "{on}" is marked for pods and "{off}" is not')
def relation_types_file(context, on, off):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    context.relation_types = Path(directory.name) / "types.yml"
    context.relation_types.write_text(
        "schemaVersion: 1\nrelationTypes:\n"
        f"  - key: {on}\n    allowedSubjectKinds: [item]\n    allowedObjectKinds: [semanticNode]\n    pod: true\n"
        f"  - key: {off}\n    allowedSubjectKinds: [item]\n    allowedObjectKinds: [semanticNode]\n",
        encoding="utf-8",
    )


# ---- When ------------------------------------------------------------------------------------------------------------

@when('I run the pod command "{line}"')
def run_pod_command(context, line):
    _run(context, line)


@when('a note "{path}" is written with the printed id as an Article')
def note_with_printed_id(context, path):
    new_id = context.output.strip().splitlines()[0]
    _write(context, path, f"---\nid: {new_id}\ntype: papyrus:Article\ntitle: Fresh\n---\nWords.\n")


@when("the pod context is generated from that file")
def generate_from_file(context):
    context.generated = pod_context.generate(context.relation_types)


@when("the pod context is generated from the shipped relation types")
def generate_shipped(context):
    context.generated = pod_context.generate()


@when("the pod context is generated again")
def generate_again(context):
    context.first_generated, context.generated = context.generated, pod_context.generate()


# ---- Then: a run -----------------------------------------------------------------------------------------------------

@then("the pod command exits with status {code:d}")
def exit_status(context, code):
    assert context.status == code, (context.status, context.output, context.error)


@then('the pod command fails with the message "{text}"')
def fails_with(context, text):
    assert context.status != 0 and text in context.error + context.output, (context.status, context.output, context.error)


@then('the pod report says "{text}"')
def report_says(context, text):
    assert text in context.output + context.error, (text, context.output, context.error)


@then('the pod report names the problem "{text}" for the note "{path}"')
def report_names_problem(context, text, path):
    text = _text(text)
    lines = [line.strip() for line in context.output.splitlines()]
    assert any(line.startswith(f"{path}: ") and text in line for line in lines), (text, path, context.output)


@then("the pod folder is exactly as it was")
def folder_unchanged(context):
    assert _snapshot(context.pod) == context.before


@then("every note is exactly as it was")
def notes_unchanged(context):
    now = _snapshot(context.pod)
    notes = {path: data for path, data in context.before.items() if path.endswith(".md")}
    assert {path: now.get(path) for path in notes} == notes


@then("no site, network or sign-in was touched")
def nothing_touched(context):
    assert context.touched == [], context.touched


@then('the pod has the files "{first}" and "{second}"')
def has_files(context, first, second):
    assert (context.pod / first).is_file() and (context.pod / second).is_file()


@then('the pod has neither "{first}" nor "{second}"')
def has_neither(context, first, second):
    assert not (context.pod / first).exists() and not (context.pod / second).exists()


@then('the pod file "{path}" names the id base "{base}"')
def names_base(context, path, base):
    declared = json.loads((context.pod / path).read_text(encoding="utf-8"))["@context"]
    assert declared[0] == "papyrus.context.jsonld" and declared[1]["@base"] == base, declared


@then('the pod prints {count:d} ids, each starting with "{prefix}"')
def prints_ids(context, count, prefix):
    context.ids = context.output.split()
    assert len(context.ids) == count and all(identifier.startswith(prefix) and len(identifier) > len(prefix) for identifier in context.ids), context.output


@then("the printed ids are all different")
def ids_differ(context):
    assert len(set(context.ids)) == len(context.ids)


@then('none of the printed ids contains "{text}"')
def ids_lack(context, text):
    ids = context.output.split()
    assert ids and not any(text in identifier for identifier in ids), ids


# ---- Then: the generated context -------------------------------------------------------------------------------------

def _terms(context) -> dict:
    return json.loads(context.generated)["@context"]


def _quoted(text: str) -> list[str]:
    return [part for index, part in enumerate(text.split('"')) if index % 2 == 1]


@then('the context defines "{key}" as a link to the note it names')
def defines_link(context, key):
    term = _terms(context)[key]
    assert term["@type"] == "@id" and term["@id"] == f"papyrus:{key}", term


@then('the context does not mention "{text}"')
def does_not_mention(context, text):
    assert text not in context.generated


@then("the relation terms of the context are exactly:")
def relation_terms(context):
    found = [name for name, term in _terms(context).items()
             if isinstance(term, dict) and term.get("@id") == f"papyrus:{name}" and term.get("@type") == "@id" and term.get("@container") == "@set"]
    assert found == context.text.split(), found


@then('the context records profile version 1, Vault-LD 0.5.0 and commit "{commit}"')
def records_pin(context, commit):
    pin = json.loads(context.generated)["papyrusPod"]
    assert (pin["profile"], pin["vaultLd"], pin["vaultLdCommit"]) == (1, "0.5.0", commit), pin


@then("the context lists the classes {classes}")
def lists_classes(context, classes):
    assert json.loads(context.generated)["papyrusPod"]["classes"] == _quoted(classes)


@then("the context defines none of {keys}")
def defines_none(context, keys):
    terms = _terms(context)
    assert not [key for key in _quoted(keys) if key in terms]


@then("the two contexts are byte for byte the same")
def same_bytes(context):
    assert context.first_generated.encode() == context.generated.encode()


@then('the pod file "{path}" is exactly the context Papyrus generates')
def file_is_generated(context, path):
    assert (context.pod / path).read_text(encoding="utf-8") == pod_context.generate()
