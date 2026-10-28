import json
import sys
from pathlib import Path

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import priming_export_fixture as fx  # noqa: E402
from papyrus_content import priming_export as pe  # noqa: E402


def site(context):
    if not hasattr(context, "site"):
        fx.FakeCards.bodies = {}
        pe.AttachmentStore = fx.FakeCards
        context.site = fx.FakeSite()
    return context.site


@given('a Reference "{name}" an editor accepted with the reason "{reason}"')
def accepted(context, name, reason):
    site(context).tables["Reference"].append(fx.reference(name, "accepted", by="user:ryan", reason=reason))


@given('a Reference "{name}" an editor rejected with the reason "{reason}"')
def rejected(context, name, reason):
    site(context).tables["Reference"].append(fx.reference(name, "rejected", by="user:ryan", reason=reason))


@given('a Reference "{name}" the monitoring worker accepted')
def worker_accepted(context, name):
    site(context).tables["Reference"].append(fx.reference(name, "accepted", by="papyrus-monitoring-worker"))


@given('a Reference "{name}" that is still pending')
def pending(context, name):
    site(context).tables["Reference"].append(fx.reference(name, "pending"))


@given('a Reference "{name}" an editor accepted with a summary "{summary}" and the body "{body}"')
def with_content(context, name, summary, body):
    s = site(context)
    s.tables["Reference"].append(fx.reference(name, "accepted", by="user:ryan"))
    s.cards[name] = {"summary": {"text": summary}, "current": {"textSortKey": "curation-text"}}
    fx.FakeCards.bodies[name] = body


@given('a TTAB draft for proceeding "{proceeding}" that an editor moved to "{stage}"')
def ttab_draft(context, proceeding, stage):
    s = site(context)
    story = "content-item-draft"
    s.tables["Automation"].append(fx.automation())
    s.tables["ProcedureRun"].append(fx.run(story, proceeding))
    s.tables["Item"] += [fx.version(story, 1, "reporting", "TTAB ruling analyst (Tactus)"),
                         fx.version(story, 2, stage, "papyrus-cli", state="current", at="2026-10-26T09:00:00Z")]


@when("the priming export runs for the publication")
def run_export(context):
    context.rows, _ = pe.export_priming(site(context), fx.PUBLICATION, fx.CORPUS)


@when("the priming export runs for the publication including unlabeled rows")
def run_export_unlabeled(context):
    context.rows, _ = pe.export_priming(site(context), fx.PUBLICATION, fx.CORPUS, include_unlabeled=True)


def found(context, row_id):
    rows = [row for row in context.rows if row["id"] == row_id]
    assert rows, f"no row {row_id}: {[row['id'] for row in context.rows]}"
    return rows[0]


@then("the export has {count:d} rows")
def count_rows(context, count):
    assert len(context.rows) == count, [row["id"] for row in context.rows]


@then('the row "{row_id}" is labeled "{classifier}" "{label}" by {who}, {made}')
def labeled(context, row_id, classifier, label, who, made):
    row = found(context, row_id)
    assert row["labels"][classifier]["label"] == label, row["labels"]
    role = "editor" if "editor" in who else "automation"
    assert row["provenance"]["labeledBy"] == role, row["provenance"]
    assert row["provenance"]["modelMade"] is (not made.startswith("not")), row["provenance"]


@then('the row "{row_id}" has no labels')
def no_labels(context, row_id):
    assert found(context, row_id)["labels"] == {}


@then('the row "{row_id}" has no "{classifier}" label')
def lacks_label(context, row_id, classifier):
    assert classifier not in found(context, row_id)["labels"]


@then('the row "{row_id}" has the text "{text}"')
def has_text(context, row_id, text):
    assert found(context, row_id)["values"]["text"] == text.replace("\\n", "\n")


@then('the export text contains no "{needle}"')
def no_needle(context, needle):
    assert needle not in pe.encode_lines(context.rows)
