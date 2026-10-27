from pathlib import Path
import subprocess
import sys
from behave import given, when, then

@given('synthetic editor-selected newsletter References')
def selected(context):
    context.handoff_root = Path(__file__).resolve().parents[2]

@when('their cloud handoff contracts are exercised')
def exercise(context):
    context.handoff_result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
        'procedures/newsroom/tests/test_email_reference_handoff.py'], cwd=context.handoff_root,
        capture_output=True, text=True, timeout=120)

@then('only those References are queued idempotently and negative predictions remain reviewable')
def satisfied(context):
    result = context.handoff_result
    assert result.returncode == 0, result.stdout + result.stderr

@given('the deployed AppSync Lambda resolver event shape')
def deployed_shape(context):
    context.handoff_root = Path(__file__).resolve().parents[2]

@when('an editor opens one exact receipt or queues its selected Reference')
def deployed_dispatch(context):
    context.handoff_result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
        'procedures/newsroom/tests/test_monitoring_view.py', '-k', 'appsync_dispatch'],
        cwd=context.handoff_root, capture_output=True, text=True, timeout=120)

@then('dispatch honors the named operation and malformed requests read no monitoring records')
def deployed_satisfied(context):
    result = context.handoff_result
    assert result.returncode == 0, result.stdout + result.stderr

@given('a stored newsletter with branded SendGrid article wrappers')
def branded_tracking(context):
    context.handoff_root = Path(__file__).resolve().parents[2]

@when('its exact receipt is opened and its tracking contracts are exercised')
def branded_contracts(context):
    context.handoff_result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
        'procedures/newsroom/tests/test_email_submission.py',
        'procedures/newsroom/tests/test_monitoring_view.py', '-k', 'branded or tracking'],
        cwd=context.handoff_root, capture_output=True, text=True, timeout=120)

@then('opaque tracking URLs are never offered as direct References and redirect protections remain enforced')
def branded_satisfied(context):
    result = context.handoff_result
    assert result.returncode == 0, result.stdout + result.stderr


@then("a resolved legacy candidate imports and queues once while its raw wrapper is rejected")
def legacy_tracking_import_contract(context):
    result = subprocess.run([sys.executable, "-m", "pytest", "-q",
        "procedures/newsroom/tests/test_email_reference_handoff.py", "-k", "legacy_branded"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
