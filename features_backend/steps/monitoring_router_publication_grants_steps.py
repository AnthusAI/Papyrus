"""The router's per-publication AppSync grants (features_backend/monitoring-router-publication-grants.feature). Reads the template; no AWS."""
from pathlib import Path
import subprocess
import sys

from behave import given, then, when

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "infra" / "monitoring" / "papyrus-monitoring.yaml"


def pytest(file, keyword):
    return subprocess.run([sys.executable, "-m", "pytest", "-q", f"procedures/newsroom/tests/{file}", "-k", keyword],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)


def passed(result):
    assert result.returncode == 0, result.stdout + result.stderr


@given("the monitoring stack template with its publication API parameters")
def template(context):
    assert TEMPLATE.is_file()


@when("the grants on the router role are listed per API")
def listed(context):
    context.grant_result = pytest("test_monitoring_router.py", "every_configured_publication_api or auto_accept_grant or router_role_is_least_privilege")
    context.size_result = pytest("test_monitoring_stories.py", "6144")


@then("every publication API has the intake, decision relation, automatic acceptance and enrichment read-back fields")
def every_api(context):
    passed(context.grant_result)


@then("Machines on Machines is granted alongside the Papyrus product-site backend it replaces")
def both(context):
    passed(context.grant_result)
    text = TEMPLATE.read_text()
    assert "${MachinesOnMachinesApiId}" in text and "${PapyrusApiId}" in text


@then("no managed policy was added to the router role and none exceeds its size limit")
def limits(context):
    assert TEMPLATE.read_text().count("Roles: [!Ref RouterRole]") <= 20
    passed(context.size_result)
