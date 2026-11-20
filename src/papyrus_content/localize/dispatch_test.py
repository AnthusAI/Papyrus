"""The dispatcher's stream handling: decoding a stream record and the function that wraps ``handle_changes`` (the rules are in
features_backend/translation/story-localize-on-publish.feature)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from .dispatch import ENDED, decode_image

HANDLER = Path(__file__).resolve().parents[3] / "amplify" / "functions" / "localization-dispatch" / "handler.py"


def stream_record(old: dict | None, new: dict | None, event: str = "MODIFY") -> dict:
    def image(row):
        return None if row is None else {name: ({"BOOL": value} if isinstance(value, bool) else {"N": str(value)} if isinstance(value, int) else {"NULL": True} if value is None else {"S": value})
                                          for name, value in row.items()}
    return {"eventName": event, "dynamodb": {"SequenceNumber": "1", "OldImage": image(old), "NewImage": image(new)}}


def load_handler():
    spec = importlib.util.spec_from_file_location("localization_dispatch_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_stream_image_decodes_to_a_plain_row():
    row = decode_image(stream_record(None, {"id": "s#es", "state": "wanted", "sourceVersionNumber": 3, "publish": True, "reason": None})["dynamodb"]["NewImage"])
    assert row == {"id": "s#es", "state": "wanted", "sourceVersionNumber": 3, "publish": True, "reason": None}
    assert isinstance(row["sourceVersionNumber"], int) and row["publish"] is True
    assert decode_image(None) is None


def test_every_state_a_run_can_end_in_frees_a_place():
    assert set(ENDED) == {"saved", "held", "failed", "stopped", "unchanged", "waiting", "published"}


def test_a_deleted_record_changes_nothing_and_a_failed_batch_is_reported_for_retry(capsys):
    handler = load_handler()
    deleted = {"Records": [stream_record({"id": "x", "state": "wanted"}, None, "REMOVE")]}
    assert handler.handler(deleted) == {"batchItemFailures": []}

    class Client:
        def list_by_index(self, *args, **kwargs):
            raise RuntimeError("the API is down")

    batch = {"Records": [stream_record(None, {"id": "x#es", "state": "wanted", "requestedAt": "t"}, "INSERT")]}
    answer = handler.handler(batch, client=Client(), table=object(), runner=lambda request: None, publisher=lambda task: None)
    assert answer == {"batchItemFailures": [{"itemIdentifier": "1"}]}
    assert json.loads(capsys.readouterr().out)["event"] == "papyrus_localization_dispatch_failed"
