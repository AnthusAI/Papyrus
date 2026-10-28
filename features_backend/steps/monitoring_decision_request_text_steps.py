from copy import deepcopy
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402
from papyrus_content.monitoring_router import build_decide_request, validate_request, validate_router_config  # noqa: E402

SUMMARY = "A short summary of the article."
ARTICLE = "A long captured article sentence. " * 5000


def values_of(context):
    return context.request["payload"]["item"]["values"]


@given("a collected story with a long captured article and a summary")
def step_story(context):
    context.table_ = tr.FakeTable()
    context.table_.put_item(tr.COLLECTOR_CONFIG)
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.FEED, now=1000)
    context.router_cfg = validate_router_config(tr.router_config())


@when("the router builds the decision request for the enriched story")
def step_build(context):
    discovery = context.table_.items[("MONITOR#hn", "DISC#101#000001")]
    context.request = deepcopy(build_decide_request(context.router_cfg, context.router_cfg["publications"][0], discovery,
                                                    enrichment={"summary": SUMMARY, "body": ARTICLE})["body"])


@when("a separate body is added to the request values")
def step_add_body(context):
    values_of(context)["body"] = ARTICLE


@when("the request text is replaced by the article alone")
def step_replace_text(context):
    values_of(context)["text"] = ARTICLE


@then("the request values hold the summary but no separate body")
def step_values(context):
    assert values_of(context)["summary"] == SUMMARY and "body" not in values_of(context)


@then("the request text holds the title, the address, the summary and the whole article")
def step_text(context):
    v = values_of(context)
    assert v["text"] == f"{v['title']}\n{v['url']}\n\n{SUMMARY}\n\n{ARTICLE}"
    assert v["text"].count(ARTICLE) == 1


@then("the enriched request is valid")
def step_valid(context):
    validate_request(context.request)


@then("the enriched request is refused")
def step_refused(context):
    try:
        validate_request(context.request)
    except ValueError:
        return
    raise AssertionError("the request was accepted")
