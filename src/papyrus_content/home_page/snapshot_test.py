import json
from datetime import datetime, timedelta, timezone

from papyrus_content.home_page.snapshot import (
    HOME_PAGE_DATA_DIRECTORY,
    REFERENCES_FILE,
    build_snapshot,
    changed_without_generated_at,
    snapshot_bytes,
)

NOW = datetime(2026, 10, 31, 12, 0, 5, 123000, tzinfo=timezone.utc)


def record(key, status="accepted", accepted_at=None, arrived_at="2026-10-01T00:00:00.000Z"):
    return {"key": key, "status": status, "acceptedAt": accepted_at, "arrivedAt": arrived_at}


def test_the_file_lives_under_the_home_page_data_directory():
    assert HOME_PAGE_DATA_DIRECTORY == "_data/home-page"
    assert REFERENCES_FILE == "_data/home-page/references.json"


def test_the_document_has_its_stamp_corpus_fields_and_references():
    document = build_snapshot([record("a")], NOW, corpus="knowledge-corpus-example", fields=["key", "status"])
    assert document["generatedAt"] == "2026-10-31T12:00:05.123Z"
    assert (document["corpus"], document["fields"]) == ("knowledge-corpus-example", ["key", "status"])
    assert [entry["key"] for entry in document["references"]] == ["a"]


def test_references_are_newest_accepted_first_then_recommended_by_arrival():
    records = [
        record("old", accepted_at="2026-10-01T09:00:00.000Z"),
        record("recommended-late", "recommended", arrived_at="2026-10-30T00:00:00.000Z"),
        record("new", accepted_at="2026-10-20T09:00:00.000Z"),
        record("recommended-early", "recommended", arrived_at="2026-10-02T00:00:00.000Z"),
    ]
    keys = [entry["key"] for entry in build_snapshot(records, NOW)["references"]]
    assert keys == ["new", "old", "recommended-late", "recommended-early"]


def test_only_the_stamp_changing_is_not_a_change():
    first = snapshot_bytes(build_snapshot([record("a")], NOW))
    later = snapshot_bytes(build_snapshot([record("a")], NOW + timedelta(hours=1)))
    assert first != later
    assert not changed_without_generated_at(first, later)


def test_a_different_record_is_a_change():
    first = snapshot_bytes(build_snapshot([record("a")], NOW))
    assert changed_without_generated_at(first, snapshot_bytes(build_snapshot([record("a"), record("b")], NOW)))


def test_no_old_file_or_an_unreadable_one_is_a_change():
    new = snapshot_bytes(build_snapshot([], NOW))
    assert changed_without_generated_at(None, new)
    assert changed_without_generated_at(b"not json", new)


def test_the_bytes_are_compact_json_with_a_newline_and_keep_non_ascii_text():
    body = snapshot_bytes({"title": "Café"})
    assert body.endswith(b"\n") and "Café".encode() in body
    assert json.loads(body) == {"title": "Café"}


def thread_record(key, last_at, count=1):
    messages = [{"key": f"{key}{number}", "at": last_at if number == count else "2026-01-01T00:00:00.000Z", "edited": False, "text": "Hi", "author": {"label": "Editor"}} for number in range(1, count + 1)]
    return {"key": key, "title": f"Thread {key}", "anchor": {"kind": "reference", "key": "k", "title": "R"}, "messages": messages}


def test_the_threads_document_lists_the_most_recently_active_first_with_counts_and_latest():
    from papyrus_content.home_page.snapshot import THREADS_DIRECTORY, THREADS_FILE, build_threads_snapshot, thread_file

    index, documents = build_threads_snapshot([thread_record("a", "2026-10-01T00:00:00.000Z"), thread_record("b", "2026-10-02T00:00:00.000Z", count=3)], NOW)
    assert THREADS_FILE == "_data/home-page/threads.json" and THREADS_DIRECTORY == "_data/home-page/threads"
    assert thread_file("b") == "_data/home-page/threads/b.json"
    assert index["generatedAt"] == "2026-10-31T12:00:05.123Z"
    assert [(entry["key"], entry["messages"], entry["lastAt"]) for entry in index["threads"]] == [("b", 3, "2026-10-02T00:00:00.000Z"), ("a", 1, "2026-10-01T00:00:00.000Z")]
    assert index["threads"][0]["latest"] == documents["b"]["messages"][-1]
    assert list(documents["b"]) == ["key", "title", "anchor", "messages"]
