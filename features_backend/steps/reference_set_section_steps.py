"""papyrus references set-section (features_backend/reference-set-section.feature). The commands run against an in-memory data client; the site's
function runs in `scripts/test-reference-section.ts`. No network, login or AWS."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.reference_section import DESCRIPTIONS, call_tool  # noqa: E402
from papyrus_content.reference_section_test import FakeClient  # noqa: E402
from papyrus_content.references_commands import references_set_section  # noqa: E402

SECURITY = "machines-on-machines#security"


def run_cli(client, flags):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        references_set_section(flags, client=client)
    return out.getvalue()


@given("an accepted Reference with a note, a four star rating and no section")
def _accepted(context):
    context.client = FakeClient()
    context.before = context.client.vote_view()


@given('an accepted Reference with a note, a four star rating and the section "{section}"')
def _accepted_in(context, section):
    context.client = FakeClient(curationSectionId=section)
    context.before = context.client.vote_view()


@given("a pending Reference")
def _pending(context):
    context.client = FakeClient(curationStatus="pending")


@when('the editor sets its section to "{section}"')
def _set(context, section):
    context.error = None
    try:
        context.output = run_cli(context.client, ["--reference", "ref", "--section", section, "--json"])
    except ValueError as error:
        context.error = str(error)


@when('the editor sets its section to "{section}" with a dry run')
def _dry(context, section):
    context.output = run_cli(context.client, ["--reference", "ref", "--section", section, "--dry-run"])


@when('the editor sets its section by the name "{name}" and then by "{qualified}"')
def _name_then_qualified(context, name, qualified):
    run_cli(context.client, ["--reference", "ref", "--section", name])
    run_cli(context.client, ["--reference", "ref", "--section", qualified])


@when("the editor clears its section")
def _clear(context):
    run_cli(context.client, ["--reference", "ref", "--clear"])


@when("the same change is made once with the command and once with the MCP tool reference_set_section")
def _both(context):
    context.cli_client, context.mcp_client = FakeClient(), FakeClient()
    context.cli_result = json.loads(run_cli(context.cli_client, ["--reference", "ref", "--section", SECURITY, "--json"]))
    context.mcp_result = call_tool(context.mcp_client, {"lineageId": "ref", "section": SECURITY})


@when("the site's function sets, repeats, rejects, clears and operator-sets a section")
def _lambda(context):
    done = subprocess.run(["npx", "tsx", "scripts/test-reference-section.ts"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=240)
    context.lambda_run = done
    assert done.returncode == 0, done.stdout + done.stderr


@then('the Reference is in the section "{section}"')
def _in_section(context, section):
    assert context.client.rows["ref-v2"]["curationSectionId"] == section


@then("the Reference has no section")
def _none(context):
    assert context.client.rows["ref-v2"]["curationSectionId"] is None


@then("its acceptance, note, feedback and rating are identical to before")
def _vote_same(context):
    assert context.client.vote_view() == context.before


@then("the command is refused and nothing is written")
def _refused(context):
    assert context.error and context.client.sent == [] and "curationSectionId" not in context.client.rows["ref-v2"]


@then("the message lists the accepted forms and the enabled sections")
def _lists(context):
    assert "slug" in context.error and "<publication>#<slug>" in context.error
    assert "Available sections:" in context.error and "machines-on-machines#research" in context.error


@then("a disabled section and a malformed qualified form are refused the same way")
def _also(context):
    for value in ("retired", "#security", "other-site#security"):
        _set(context, value)
        assert context.error and "Accepted forms" in context.error and context.client.sent == []


@then("the output says nothing was sent and names the section it would set")
def _dry_output(context):
    assert "dry-run: nothing sent" in context.output and SECURITY in context.output


@then("no section change is sent")
def _nothing(context):
    assert context.client.sent == [] and "curationSectionId" not in context.client.rows["ref-v2"]


@then("the command is refused because the Reference is not accepted")
def _not_accepted(context):
    assert context.error and "only on an accepted Reference" in context.error and context.client.sent == []


@then("both give the same result and leave the same Reference")
def _same(context):
    assert context.cli_result == context.mcp_result and context.cli_client.rows == context.mcp_client.rows
    assert "reference_set_section" in DESCRIPTIONS


@then("it writes only the section, who changed it and when")
def _lambda_writes(context):
    assert "reference section: ok" in context.lambda_run.stdout


@then("the function leaves the acceptance, note, feedback and rating identical to before")
def _lambda_vote(context):
    assert "reference section: ok" in context.lambda_run.stdout


@then("a reader, an unknown section, a disabled section and a pending Reference are refused before any write")
def _lambda_refuses(context):
    assert "reference section: ok" in context.lambda_run.stdout


@then("an operator on AWS credentials can do it and is recorded by role session")
def _lambda_operator(context):
    assert "reference section: ok" in context.lambda_run.stdout
