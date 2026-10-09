from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.relevance_cyclotron import build_relevance_cyclotron  # noqa: E402
from papyrus_content.relevance_recording import (build_recording, price_basis, references_export_relevance_recording,  # noqa: E402
                                                 shareable_reviews)
from papyrus_content.relevance_sweep import _owner_metadata  # noqa: E402

DOCTRINE = [{"kind": "mission", "body": ["Publish practical AI security analysis."]},
            {"kind": "policy", "body": ["Prefer primary evidence over vendor marketing."]}]


def export(context, *, explanations=True):
    from decision_flywheel import Cyclotron
    plan = build_relevance_cyclotron(context.steering, DOCTRINE)
    prices = price_basis(plan, None)
    sdk_prices = {name: {k: v for k, v in prices[name].items() if k.endswith("_mtok")} for name in ("decision_model", "optimizer")}
    with Cyclotron.open(plan.local_path, plan.definition, context.model, review_program=plan.review_program) as cyclotron:
        log = cyclotron.decision_log()
        usage = cyclotron.usage(sdk_prices)
        events = cyclotron.subscribe(limit=1000)["events"]
    review_ids = [review["reviewId"] for row in log for review in row["reviews"].values() if review.get("reviewId")]
    with mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer", side_effect=lambda c, a: None):
        shared = shareable_reviews(context.client, review_ids, _owner_metadata)
    context.recording = build_recording(plan=plan, publication="Example", log=log, usage=usage, events=events,
                                        shareable=shared, prices=prices, include_explanations=explanations)
    context.recording_text = json.dumps(context.recording)
    context.log = log


@when("the relevance recording is exported")
def step_export(context):
    export(context)


@when("the relevance recording is exported without explanations")
def step_export_without(context):
    export(context, explanations=False)


@then('the recording is schema version 2 from source "{source}"')
def step_schema(context, source):
    assert context.recording["schema_version"] == 2 and context.recording["source"] == source
    assert set(context.recording["scenarios"]) == {"live"}
    assert context.recording["attribution"]["price_basis"]["decision_model"]["source"] == "TypeSafe's published price"


@then("it has one cycle per decision in the order they were made")
def step_cycles(context):
    cycles = context.recording["scenarios"]["live"]["cycles"]
    assert [cycle["n"] for cycle in cycles] == [row["n"] for row in context.log] == [1, 2]
    assert [cycle["article"]["title"] for cycle in cycles] == [item["title"] for item in context.pending]


@then("each reviewed cycle shows the decision before the review, the editor's label and its reason code")
def step_reviewed(context):
    first, second = context.recording["scenarios"]["live"]["cycles"]
    assert (first["predicted"], first["actual"], first["reason_code"]) == ("include", "exclude", "out_of_scope")
    assert (second["predicted"], second["actual"]) == ("exclude", "include")
    assert first["confidence"] == first["probabilities"]["include"] and first["feedback_revealed"]


@then("the first window counts {decisions:d} decisions and {reviewed:d} reviewed")
def step_window(context, decisions, reviewed):
    window = context.recording["scenarios"]["live"]["windows"][0]
    assert (window["decisions"], window["feedback_revealed"]) == (decisions, reviewed)
    assert window["cyclotron"]["count"] == reviewed and window["cyclotron"]["accuracy"] == 0.0


@then("the first window and the total carry decision-model usage and cost at the Jev list price")
def step_usage(context):
    live = context.recording["scenarios"]["live"]
    window, total = live["windows"][0]["usage"], live["usage_total"]
    assert window["decision_model"]["requests"] == total["decision_model"]["requests"] == 2
    assert total["decision_model"]["input_tokens"] == 2000
    assert abs(total["usd"] - 2000 * 0.042 / 1e6) < 1e-12


@then('the explanation "{text}" is in the recording')
def step_explanation_in(context, text):
    assert context.recording["scenarios"]["live"]["cycles"][0]["editor_explanation"] == text


@then('the text "{text}" is not in the recording')
def step_text_absent(context, text):
    assert text not in context.recording_text


@when("a recording with optimizer calls is exported without an optimizer price")
def step_optimizer_without_price(context):
    plan = build_relevance_cyclotron(context.steering, DOCTRINE)
    usage = {"windows": [], "total": {"decision_model": {"requests": 0}, "optimizer": {"requests": 3}, "usd": 0}}
    context.error = None
    try:
        build_recording(plan=plan, publication="Example", log=[], usage=usage, events=[], shareable={},
                        prices=price_basis(plan, None))
    except ValueError as error:
        context.error = error


@then("the export asks for the optimizer's list price and its source")
def step_asks_price(context):
    assert context.error is not None and "optimizer's list price and its source" in str(context.error)


@when("the export command writes the recording from the private bucket")
def step_command(context):
    output = Path(tempfile.mkdtemp()) / "papyrus-relevance-run.json"
    with mock.patch("papyrus_content.steering.require_steering_config", return_value=context.steering), \
            mock.patch("papyrus_content.newsroom_doctrine.load_publication_doctrine_seed", return_value={"doctrine": DOCTRINE}), \
            mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(context.client, {})), \
            mock.patch("papyrus_content.relevance_sweep.S3SnapshotStore", return_value=context.bucket), \
            mock.patch("papyrus_content.relevance_cyclotron.decision_model_identity", return_value=context.model.model_identity), \
            mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer", side_effect=lambda c, a: None):
        calls = context.model.calls
        references_export_relevance_recording(["--output", str(output)])
    assert context.model.calls == calls
    context.output = output


@then("the recording file has {count:d} cycles")
def step_file(context, count):
    recording = json.loads(context.output.read_text())
    assert len(recording["scenarios"]["live"]["cycles"]) == count
