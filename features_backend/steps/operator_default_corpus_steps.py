"""Default corpus of `papyrus references list|show` (features_backend/operator-default-corpus.feature). The backend is a fake; nothing leaves the process."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus.operator import config as operator_config  # noqa: E402
from papyrus.operator.commands import references as reference_commands  # noqa: E402
from papyrus.operator.errors import OperatorError  # noqa: E402
from papyrus_content import steering  # noqa: E402
from test_operator_default_corpus import PACKAGED_DEFAULT, HostedClient, RecordingBackend, corpora  # noqa: E402

CONTROLLED = ("PAPYRUS_STEERING_CONFIG", "PAPYRUS_OPERATOR_CONFIG", "PAPYRUS_OPERATOR_FIXTURE_ROOT")


@given("an empty directory with no steering file and no operator configuration of its own")
def _empty(context):
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    root = Path(temporary.name)
    here = os.getcwd()
    os.chdir(root)
    context.add_cleanup(lambda: os.chdir(here))
    environment = mock.patch.dict(os.environ, {})
    environment.start()
    context.add_cleanup(environment.stop)
    for name in CONTROLLED:
        os.environ.pop(name, None)
    for target, name, value in (
        (steering, "PAPYRUS_ROOT", root), (operator_config, "PAPYRUS_ROOT", root),
        (operator_config, "_default_corpus_from_steering", lambda: PACKAGED_DEFAULT),
        (steering, "resolve_topics_steering_config_path", lambda: "corpora/papyrus-steering.yml"),
    ):
        patcher = mock.patch.object(target, name, value)
        patcher.start()
        context.add_cleanup(patcher.stop)
    context.root, context.hosted, context.corpus_keys, context.out, context.failure = root, [], [], "", None


@given('the signed-in site serves the one canonical corpus "{key}"')
def _one(context, key):
    context.hosted = corpora(key)


@given('the signed-in site serves the canonical corpora "{first}" and "{second}"')
def _two(context, first, second):
    context.hosted = corpora(first, second)


@given("the signed-in site serves no canonical corpus")
def _none(context):
    context.hosted = []


@given('the site chose a steering file whose canonical corpus is "{key}"')
def _chose(context, key):
    os.environ["PAPYRUS_STEERING_CONFIG"] = str(context.root / "site-steering.yml")
    patcher = mock.patch.object(operator_config, "_default_corpus_from_steering", lambda: key)
    patcher.start()
    context.add_cleanup(patcher.stop)


def _list(context, flags, signed_in):
    recorder = RecordingBackend()
    out = io.StringIO()
    context.failure = None
    with contextlib.redirect_stdout(out), mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in), \
            mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(HostedClient(context.hosted), {})), \
            mock.patch.object(reference_commands, "create_backend", return_value=recorder):
        try:
            key = flags[flags.index("--corpus-key") + 1] if "--corpus-key" in flags else None
            config = operator_config.load_operator_config(backend_override="cloud", corpus_key_override=key)
            reference_commands.run_references_list(config, flags)
        except OperatorError as error:
            context.failure = error
    context.out, context.corpus_keys = out.getvalue(), recorder.corpus_keys


@when("a signed-in person lists references with no corpus key")
def _list_signed_in(context):
    _list(context, [], True)


@when('a signed-in person lists references with the corpus key "{key}"')
def _list_with_key(context, key):
    _list(context, ["--corpus-key", key], True)


@when("an operator on the IAM lane lists references with no corpus key")
def _list_iam(context):
    _list(context, [], False)


@then('the references are listed from the corpus "{key}"')
def _listed_from(context, key):
    assert context.failure is None, context.failure
    assert context.corpus_keys == [key], context.corpus_keys


@then("the references are listed from the corpus the tool ships as its default")
def _listed_default(context):
    assert context.corpus_keys == [PACKAGED_DEFAULT], context.corpus_keys


@then('the printed header names the corpus "{key}"')
def _header(context, key):
    assert f"corpusKey={key}" in context.out, context.out


@then("the command fails and tells the person to pass a corpus key")
def _fails(context):
    assert isinstance(context.failure, OperatorError) and "--corpus-key" in str(context.failure), context.failure
    assert context.corpus_keys == []
