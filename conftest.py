"""Pytest configuration for Papyrus Python packages under src/."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))



import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _checklist_gate_off():
    """Publishing refuses while a required checklist step is open (docs/story-procedure.md). Tests about something else publish Stories freely, so the gate is
    off for the whole session (module fixtures publish too); a test module that exercises the rule asks for ``real_checklist_gate``."""
    from papyrus_content import story_checklist

    real = story_checklist.require_checklist_closed
    story_checklist.require_checklist_closed = lambda client, item: None
    yield real
    story_checklist.require_checklist_closed = real


@pytest.fixture
def real_checklist_gate(_checklist_gate_off, monkeypatch):
    from papyrus_content import story_checklist

    monkeypatch.setattr(story_checklist, "require_checklist_closed", _checklist_gate_off)


# Variables that choose a GraphQL lane or a signed-in site. A developer's machine often has a real `papyrus login` session in
# ~/.config/papyrus and a lane in the shell; CI has neither. Every test starts like CI: signed out, in an empty sign-in directory,
# with no lane named (the signed-in lane is the default). A test that wants a lane or a session sets it (PPY-5f119a).
SIGN_IN_ENVIRONMENT = ("PAPYRUS_GRAPHQL_AUTH", "PAPYRUS_CLI_AUTH_CONFIG", "PAPYRUS_SITE")


@pytest.fixture(autouse=True)
def _signed_out_by_default(monkeypatch, tmp_path_factory):
    for name in SIGN_IN_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path_factory.mktemp("papyrus-state")))


@pytest.fixture(autouse=True)
def _a_person_at_a_terminal_by_default(monkeypatch):
    """Commands are run as an agent unless a person's terminal is evidence (actor_identity.py). Tests start as a person at a terminal, in an environment with no
    agent runtime in it; a test about the fail-closed rule sets what it needs."""
    from papyrus_content import actor_identity

    monkeypatch.setattr(actor_identity, "terminal_is_interactive", lambda: True)
    for name in (actor_identity.ACTOR_KIND_VARIABLE, *actor_identity.AGENT_RUNTIME_MARKERS):
        monkeypatch.delenv(name, raising=False)


def shard_that_runs(test_file_path: str, shard_count: int) -> int:
    """CI runs the unit tests as several jobs. A test file's path alone decides its job, so the jobs together run every file exactly once."""
    import zlib

    return zlib.crc32(test_file_path.encode("utf-8")) % shard_count


def pytest_addoption(parser):
    parser.addoption("--shard", default=None, help="N/M: run only the test files that fall to shard N of M (N from 0).")


def pytest_collection_modifyitems(config, items):
    requested_shard = config.getoption("--shard")
    if not requested_shard:
        return
    shard_text, _, shard_count_text = requested_shard.partition("/")
    shard, shard_count = int(shard_text), int(shard_count_text)
    if not 0 <= shard < shard_count:
        raise pytest.UsageError(f"--shard {requested_shard}: the shard must be from 0 to {shard_count - 1}")
    kept, left_to_other_shards = [], []
    for item in items:
        test_file_path = Path(str(item.fspath)).resolve().relative_to(ROOT).as_posix()
        (kept if shard_that_runs(test_file_path, shard_count) == shard else left_to_other_shards).append(item)
    if left_to_other_shards:
        config.hook.pytest_deselected(items=left_to_other_shards)
        items[:] = kept
