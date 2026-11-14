"""Amplify job-log behaviour through the real papyrus-infra CLI, a fake aws command and a local log server."""
import http.server
import os
import subprocess
import threading
from pathlib import Path

from behave import given, when, then

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / 'packages' / 'papyrus' / 'bin' / 'papyrus-infra.mjs'
FIXTURES = REPO_ROOT / 'features_backend' / 'fixtures' / 'amplify-job-log'


def _serve_log(context, scenario_name):
    import json
    scenario_file = FIXTURES / f'{scenario_name}.json'
    log_text = json.loads(scenario_file.read_text())['log'].encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(log_text)

        def log_message(self, *arguments):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    context.add_cleanup(server.shutdown)
    context.add_cleanup(server.server_close)
    context.scenario_file = scenario_file
    context.log_url = f'http://127.0.0.1:{server.server_address[1]}/build.log'


def _run(context, arguments, with_fake_aws=True):
    environment = dict(os.environ)
    if with_fake_aws:
        import tempfile
        bin_directory = tempfile.TemporaryDirectory()
        context.add_cleanup(bin_directory.cleanup)
        fake = Path(bin_directory.name) / 'aws'
        fake.write_text((FIXTURES / 'fake-aws.mjs').read_text())
        fake.chmod(0o755)
        environment.update(PATH=f'{bin_directory.name}:{environment["PATH"]}',
                           FAKE_AWS_SCENARIO=str(context.scenario_file), FAKE_LOG_URL=context.log_url)
    context.result = subprocess.run(['node', str(CLI), *arguments], capture_output=True, text=True, env=environment, timeout=60)


@given('a failed Amplify job whose build log ends with an out of memory error')
def step_heap(context):
    _serve_log(context, 'heap-out-of-memory')


@given('a failed Amplify job whose backend stack rejected an unknown plugin')
def step_unknown_plugin(context):
    _serve_log(context, 'unknown-plugin')


@given('a failed Amplify job whose build log reports a missing Python module')
def step_missing_module(context):
    _serve_log(context, 'missing-cli-login')


@when('the operator asks for the job log of the latest failed job')
def step_ask_latest_failed(context):
    _run(context, ['amplify', 'job-log', '--app-id', 'dexample0001', '--latest-failed'])
    assert context.result.returncode == 0, context.result.stderr


@when('the operator asks for a job log without an application id')
def step_ask_without_app_id(context):
    _run(context, ['amplify', 'job-log'], with_fake_aws=False)


@then('every step of the job is listed with its status')
def step_steps_listed(context):
    for line in ('PROVISION    SUCCEED', 'BUILD        FAILED', 'DEPLOY       CANCELLED'):
        assert line in context.result.stdout, context.result.stdout


@then('the tail of the build log is printed')
def step_tail_printed(context):
    assert 'BUILD log, last 200 lines:' in context.result.stdout, context.result.stdout


@then('the cause names the out of memory line and its line number')
def step_cause_heap(context):
    assert 'Cause: BUILD log line 8: FATAL ERROR: Reached heap limit' in context.result.stdout, context.result.stdout
    assert 'JavaScript heap out of memory' in context.result.stdout


@then('the cause names the failed custom resource and its message')
def step_cause_plugin(context):
    assert "Cause: ReprojectOnDeploy CREATE_FAILED" in context.result.stdout, context.result.stdout
    assert "Unknown plugin 'home-page'" in context.result.stdout


@then('the first error of the build log is still shown')
def step_first_error_shown(context):
    assert 'First error in the BUILD log (line 7)' in context.result.stdout, context.result.stdout


@then('failures from before the job started are not reported')
def step_stale_not_reported(context):
    assert 'stale failure from a previous job' not in context.result.stdout


@then('the cause names the missing module')
def step_cause_module(context):
    assert "No module named 'cli_login'" in context.result.stdout.split('Cause:')[1], context.result.stdout


@then('the command fails and says the application id is required')
def step_requires_app_id(context):
    assert context.result.returncode != 0
    assert '--app-id is required' in context.result.stderr, context.result.stderr
