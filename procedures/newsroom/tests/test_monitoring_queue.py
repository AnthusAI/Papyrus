import json
import stat

from papyrus_content.monitoring_queue import collect_queue


FEED = b'''<rss><channel>
<item><title>First</title><link>https://example.org/a?utm_source=hn</link><comments>https://news.ycombinator.com/item?id=123</comments></item>
<item><title>Second discovery</title><link>https://example.org/a</link><comments>https://news.ycombinator.com/item?id=124</comments></item>
</channel></rss>'''


def test_private_queue_deduplicates_sources_and_preserves_discovery_revisions(tmp_path):
    queue = tmp_path / 'private'
    first = collect_queue(queue, fetch=lambda: FEED, now=1000)
    again = collect_queue(queue, fetch=lambda: FEED, now=2000)
    revised = collect_queue(queue, fetch=lambda: FEED.replace(b'First', b'Revised'), now=3000)
    assert first['newDiscoveries'] == 2
    assert again['newDiscoveries'] == 0 and again['unchanged'] == 2
    assert revised['newDiscoveries'] == 1 and revised['unchanged'] == 1
    saved = json.loads((queue / 'review.json').read_text())
    assert len(saved['items']) == 1
    item = saved['items'][0]
    assert item['canonicalUrl'] == 'https://example.org/a'
    assert len(item['discoveries']) == 3
    assert {d['sourceId'] for d in item['discoveries']} == {'123', '124'}
    assert [d['revision'] for d in item['discoveries'] if d['sourceId'] == '123'] == [1, 2]
    assert all(d['fingerprint'] and d['observedAt'] and d['sourceUrl'] for d in item['discoveries'])
    assert 'humanDecisions' not in item and 'referenceId' not in item
    assert 'no predictions' in (queue / 'review.md').read_text()
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in queue.iterdir() if p.is_file())
    assert stat.S_IMODE(queue.stat().st_mode) == 0o700


def test_queue_skips_early_fetch_and_keeps_prior_items_on_failure(tmp_path):
    queue = tmp_path / 'private'
    collect_queue(queue, fetch=lambda: FEED, now=1000)
    def forbidden():
        raise AssertionError('must not fetch early')
    assert collect_queue(queue, fetch=forbidden, now=1100)['status'] == 'not_due'
    def failed():
        raise OSError('source unavailable')
    result = collect_queue(queue, fetch=failed, now=2000)
    assert result['status'] == 'failed' and result['error'] == 'OSError'
    saved = json.loads((queue / 'review.json').read_text())
    assert len(saved['items']) == 1 and saved['lastCollection']['status'] == 'failed'


def test_private_queue_refuses_symlink_and_does_not_touch_feedback(tmp_path):
    import pytest
    feedback = tmp_path / 'received.json'
    feedback.write_text('{"decisionsReceived":18,"applied":0}')
    before = feedback.read_bytes()
    queue = tmp_path / 'private'
    collect_queue(queue, fetch=lambda: FEED, now=1000)
    assert feedback.read_bytes() == before
    (queue / 'review.md').unlink()
    (queue / 'review.md').symlink_to(feedback)
    with pytest.raises(ValueError, match='symlink'):
        collect_queue(queue, fetch=lambda: FEED, now=2000)
    assert feedback.read_bytes() == before


def test_already_presented_sources_remain_unlabelled_without_representing(tmp_path):
    shown = [{'sourceId': '123', 'canonicalUrl': 'https://example.org/a',
              'sourceMessageId': 'human-thread-message', 'shownAt': '2026-10-20T11:02:58Z'}]
    queue = tmp_path / 'private'
    collect_queue(queue, fetch=lambda: FEED, now=1000, shown_records=shown)
    saved = json.loads((queue / 'review.json').read_text())
    assert len(saved['items']) == 1 and saved['shownUnlabelled'] == shown
    text = (queue / 'review.md').read_text()
    assert 'Already presented; awaiting replies: HN 123' in text
    assert '## HN' not in text


def test_local_command_needs_no_cloud_authoring_or_authentication(tmp_path, monkeypatch, capsys):
    import sys
    from papyrus_content import monitoring_commands, monitoring_queue
    monkeypatch.setitem(sys.modules, 'papyrus_content.graphql_authoring', None)
    monkeypatch.setattr(monitoring_queue, 'collect_queue',
                        lambda directory, **kwargs: collect_queue(directory, fetch=lambda: FEED, now=1000, **kwargs))
    assert monitoring_commands.command(['collect-local', '--directory', str(tmp_path / 'private')]) == 0
    assert json.loads(capsys.readouterr().out)['newDiscoveries'] == 2
