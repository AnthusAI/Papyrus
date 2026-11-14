from pathlib import Path
import subprocess
import sys

from behave import given, when, then


@given('a cloud email infrastructure case named "{case}"')
def cloud_email_case(context, case):
    context.cloud_email_case = case


@when('its infrastructure is synthesized locally')
def synthesize_cloud_email(context):
    root = Path(__file__).resolve().parents[2]
    command = ([sys.executable, "-m", "pytest", "-q", "procedures/newsroom/tests/test_email_submission_infra.py"]
               if context.cloud_email_case == "receiver" else
               ["node", "--import", "tsx", "scripts/test-cloud-email-infra.ts", context.cloud_email_case])
    context.cloud_email_result = subprocess.run(
        command,
        cwd=root, capture_output=True, text=True, timeout=120,
    )


@then('its cloud email contract is satisfied')
def cloud_email_satisfied(context):
    result = context.cloud_email_result
    assert result.returncode == 0, result.stdout + result.stderr
