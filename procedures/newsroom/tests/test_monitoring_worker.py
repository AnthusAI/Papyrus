import json

import pytest

from papyrus_content.monitoring import Monitor, collect
from papyrus_content import monitoring_commands as commands


def test_two_due_worker_runs_use_checkpoint_and_do_not_poll_early(tmp_path, monkeypatch):
    m = Monitor("hn", "example", "knowledge-corpus-example", "https://example.org/graphql", tmp_path / "state")
    feed = b'<rss><channel><item><title>One</title><link>https://example.org/one</link><comments>https://news.ycombinator.com/item?id=1</comments></item></channel></rss>'
    now, fetches, registrations, emitted = [1000.0], [], [], []
    def fetch():
        fetches.append(now[0])
        return feed
    def intake(item, provenance):
        registrations.append(item.source_id)
        return {"referenceId": "r", "referenceLineageId": "l"}
    monkeypatch.setattr(commands, "collect", lambda monitor, sink, **kwargs: collect(monitor, sink, fetch=fetch, **kwargs))
    result = commands.run_worker(m, intake, watch=True, max_runs=2, clock=lambda: now[0],
                                  sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), emit=emitted.append)
    assert result == 0 and fetches == [1000, 1900] and registrations == ["1"]
    assert json.loads(emitted[-1])["unchanged"] == 1
    assert commands.status(m)["status"] == "complete"


def test_config_rejects_unknown_fields_and_bad_binding(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schemaVersion": 1, "typo": True}))
    with pytest.raises(ValueError, match="supported"):
        commands.load_monitor(str(path))
