import datetime as dt

import boto3
import pytest
from moto import mock_aws

from .ledger import FAILED, RUNNING, SUCCEEDED, RunLedger
from .state import StateStore


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for name, value in {"AWS_ACCESS_KEY_ID": "t", "AWS_SECRET_ACCESS_KEY": "t", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        yield


def store():
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="state")
    return StateStore(client, "state", "publications/shipped/")


def test_upload_then_download_round_trips_and_skips_unchanged_files(tmp_path):
    state = store()
    source = tmp_path / "a"
    (source / "raw").mkdir(parents=True)
    (source / "raw" / "one.md").write_text("one")
    (source / "knowledge-run.json").write_text("{}")
    assert state.upload("corpus/", source) == 2
    assert state.upload("corpus/", source) == 0
    target = tmp_path / "b"
    assert state.download("corpus/", target) == 2
    assert (target / "raw" / "one.md").read_text() == "one"
    assert state.download("corpus/", target) == 0


def test_prune_makes_the_prefix_mirror_the_directory(tmp_path):
    state = store()
    state.write_text("corpus/raw/gone.md", "x")
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "kept.md").write_text("k")
    state.upload("corpus/", tmp_path, prune=True)
    assert state.read_text("corpus/raw/gone.md") is None
    assert state.read_text("corpus/raw/kept.md") == "k"


def test_a_missing_object_reads_as_none():
    assert store().read_text("config/nothing.txt") is None


def ledger(execution="e1"):
    table = boto3.resource("dynamodb", region_name="us-east-1")
    if "ledger" not in [t.name for t in table.tables.all()]:
        table.create_table(
            TableName="ledger",
            KeySchema=[{"AttributeName": "publication", "KeyType": "HASH"}, {"AttributeName": "runKey", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "publication", "AttributeType": "S"}, {"AttributeName": "runKey", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
    return RunLedger(table.Table("ledger"), "shipped", "2026-W44", execution, clock=lambda: dt.datetime(2026, 10, 26, 5, tzinfo=dt.timezone.utc))


def test_ledger_rows_are_keyed_by_publication_week_execution_and_stage():
    book = ledger()
    assert book.status("snapshot") is None
    assert book.begin("snapshot") == 1
    assert book.status("snapshot") == RUNNING
    assert book.begin("snapshot") == 2
    book.finish("snapshot", {"entities": 3})
    assert book.status("snapshot") == SUCCEEDED
    item = book.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#e1#snapshot"})["Item"]
    assert item["details"] == {"entities": 3} and item["attempts"] == 2 and item["expiresAt"] > 0


def test_a_failure_is_recorded_with_its_error_and_a_retry_clears_it():
    book = ledger()
    book.begin("archive")
    book.fail("archive", "boom")
    assert book.status("archive") == FAILED
    book.begin("archive")
    item = book.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#e1#archive"})["Item"]
    assert "error" not in item and item["status"] == RUNNING


def test_executions_do_not_share_stage_rows():
    assert ledger("e1").status("snapshot") is None
    first = ledger("e1")
    first.begin("snapshot")
    first.finish("snapshot")
    assert ledger("e2").status("snapshot") is None
