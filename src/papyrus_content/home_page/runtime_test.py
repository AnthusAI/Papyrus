"""The Lambda finds the private state and the list of changed rows from the task the trigger scheduled."""

from __future__ import annotations

from papyrus_content.home_page.runtime import scope_of, stores_for
from papyrus_content.home_page.state_store import DirtyBatch, dirty_key
from papyrus_content.home_page.state_store_test import FakeTable


def test_a_scheduled_incremental_task_gets_the_state_and_what_changed():
    table = FakeTable()
    table.items[dirty_key("abc")] = {"publication": dirty_key("abc"), "ids": {"reference-1-v1"}}
    state, dirty, batch = stores_for({"task": "home-page-snapshot", "incremental": True, "scope": "abc"}, {}, table=table)
    assert state is not None and dirty is not None and batch == DirtyBatch(ids=frozenset({"reference-1-v1"}))


def test_a_manual_run_gets_the_state_store_so_it_leaves_a_state_but_reads_everything():
    environment = {"AWS_LAMBDA_FUNCTION_NAME": "content-actions-site-a"}
    state, dirty, batch = stores_for({"task": "home-page-snapshot"}, environment, table=FakeTable())
    assert state is not None and state.scope == scope_of("content-actions-site-a") and dirty is None and batch is None


def test_without_a_name_for_the_site_there_is_nothing_to_keep():
    assert stores_for({"task": "home-page-snapshot"}, {}, table=FakeTable()) == (None, None, None)
