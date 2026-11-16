from behave import given, when, then
from papyrus_content import procedure_runner as pr
from test_localize_worker_tenant import TENANT, launched_request, source_eligibility

@given("a localization worker launched for a tenant publication")
def launched(context):
    context.worker_tenant = pr.child_environment(pr.validate_request(launched_request()), None).get("PAPYRUS_TENANT_ID")

@when("the worker checks that publication's original story")
def checks_original(context):
    context.source_eligible = source_eligibility(context.worker_tenant, f"{TENANT}#story-1")

@then("the original is eligible for localization")
def eligible_original(context):
    assert context.source_eligible

@given('a localization worker with tenant "{tenant}"')
def tenant_worker(context, tenant):
    context.worker_tenant = None if tenant == "missing" else tenant

@when('it checks lineage "{lineage}" in language group "{group}"')
def check_source(context, lineage, group):
    context.source_eligible = source_eligibility(context.worker_tenant, group, lineage)

@then('source eligibility is "{eligible}"')
def eligible_source(context, eligible):
    assert context.source_eligible is (eligible == "yes")
