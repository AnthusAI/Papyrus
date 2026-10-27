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
