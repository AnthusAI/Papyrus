import re
from pathlib import Path

from behave import then, when

ROOT = Path(__file__).resolve().parents[2]


@when("the editorial-checks store's GraphQL operations are compared with the function's role")
def compare_store_with_role(context):
    store = (ROOT / "src/papyrus_content/editorial_checks.py").read_text()
    wire = (ROOT / "amplify/functions/editorial-checks/wire.ts").read_text()
    store_class = store[store.index("class GraphQLEditorialStore"):]
    operations = dict(re.findall(r"^([A-Z_]+) = .*?(?:query|mutation) \w+[^{]*\{\s*(\w+)\(", store, re.M | re.S))
    context.called = {field for constant, field in operations.items() if constant in store_class}
    context.granted = set(re.findall(r'"(?:Query|Mutation)/fields/(\w+)"', wire))


@then("every field the store calls is granted to the role")
def every_field_granted(context):
    missing = sorted(context.called - context.granted)
    assert context.called, "found the store's operations"
    assert not missing, f"not granted to the editorial-checks role: {missing}"
