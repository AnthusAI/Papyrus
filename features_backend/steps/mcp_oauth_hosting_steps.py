import subprocess
from pathlib import Path

from behave import given, when, then


@given('a publication opts into hosted MCP with its HTTPS console origin and compute role')
def configured(context):
    context.mcp_root = Path(__file__).resolve().parents[2]


@when('its backend configuration is evaluated')
@when('the grant function cannot be reached')
def evaluate(context):
    context.mcp_result = subprocess.run(
        [str(context.mcp_root / 'node_modules/.bin/tsx'), str(context.mcp_root / 'scripts/test-mcp-oauth-runtime.ts')],
        cwd=context.mcp_root, text=True, capture_output=True, check=False,
    )


@then('it has a private grant function with its own encrypted store')
@then('only the configured compute role is granted invocation')
@then('the invocation reports a service failure separately from an invalid token')
def verified(context):
    assert context.mcp_result.returncode == 0, context.mcp_result.stdout + context.mcp_result.stderr
