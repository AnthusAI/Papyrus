"""Private public-source review staging; no cloud intake, routing or learning.

The queue is local operator state, never a publication content repository.
Human replies remain separate received feedback until explicitly reconciled.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from .monitoring import HN_FEED, _iso, fetch_hn_feed, parse_hn_feed


def _write_private(path: Path, text: str):
    if path.is_symlink():
        raise ValueError('Private queue output must not be a symlink')
    fd, temporary = tempfile.mkstemp(prefix='.queue-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _export(directory, db, shown_records):
    groups = {}
    for (payload,) in db.execute('SELECT payload FROM discoveries ORDER BY sequence'):
        discovery = json.loads(payload)
        url = discovery['canonicalUrl']
        item = groups.setdefault(url, {'itemId': 'source-' + hashlib.sha256(url.encode()).hexdigest(),
                                     'canonicalUrl': url, 'discoveries': []})
        item['title'] = discovery['title']
        item['lastObservedAt'] = discovery['observedAt']
        item['discoveries'].append(discovery)
    last = db.execute("SELECT value FROM metadata WHERE key='last_collection'").fetchone()
    data = {'schemaVersion': 1, 'kind': 'private-monitor-review', 'sourceUrl': HN_FEED,
            'lastCollection': json.loads(last[0]) if last else None,
            'presentedSources': shown_records,
            'items': sorted(groups.values(), key=lambda row: (row['lastObservedAt'], row['itemId']), reverse=True)}
    lines = ['# HN discoveries to review', '',
             'Private collection only: no predictions, no applied labels, no publication routing.',
             'Reply with the source ID, publication (Papyrus, Threat Intelligence, Anth.us or Pilobolus), yes/no, and optional reason. Unspecified choices stay undecided.',
             'Earlier received human decisions remain separate and unchanged; collection never applies them.', '',
             'Last collection: ' + json.dumps(data['lastCollection'], sort_keys=True), '']
    shown_ids = {row['sourceId'] for row in shown_records}
    shown_urls = {row['canonicalUrl'] for row in shown_records}
    if shown_records:
        lines.extend(['Already presented; replies tracked separately: ' + ', '.join('HN ' + row['sourceId'] for row in shown_records), ''])
    for item in data['items']:
        if item['canonicalUrl'] in shown_urls or any(d['sourceId'] in shown_ids for d in item['discoveries']):
            continue
        latest = item['discoveries'][-1]
        title = item['title'].replace('\n', ' ').replace('\r', ' ')
        lines.extend([f"## HN {latest['sourceId']}: {title}", '',
                      f"Source: <{item['canonicalUrl']}>",
                      f"HN: <{latest['sourceItemUrl']}>",
                      f"Observed: {latest['observedAt']} · revision {latest['revision']} · {len(item['discoveries'])} discovery records", ''])
    _write_private(directory / 'review.json', json.dumps(data, indent=2) + '\n')
    _write_private(directory / 'review.md', '\n'.join(lines))
    return len(data['items'])


def collect_queue(directory, *, interval_seconds=900, limit=30, fetch=fetch_hn_feed, now=None, shown_records=()):
    """One due public RSS fetch; atomically persist revisions and export review.

    Canonical URLs group sources, while separate HN IDs/revisions retain all
    discovery provenance. A source failure leaves the saved review items intact.
    """
    if type(interval_seconds) is not int or interval_seconds < 60:
        raise ValueError('Queue interval must be at least 60 seconds')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Queue limit must be between 1 and 100')
    shown_records = list(shown_records)
    for row in shown_records:
        if (not isinstance(row, dict) or set(row) != {'sourceId', 'canonicalUrl', 'sourceMessageId', 'shownAt'}
                or not all(isinstance(value, str) and value for value in row.values())
                or not row['sourceId'].isdigit()):
            raise ValueError('Shown records require source identity, URL, message provenance and timestamp, without labels')
    now = time.time() if now is None else now
    directory = Path(directory).absolute()
    if directory.is_symlink():
        raise ValueError('Private queue directory must not be a symlink')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    for name in ['queue.sqlite3', 'queue.lock', 'review.json', 'review.md']:
        if (directory / name).is_symlink():
            raise ValueError('Private queue files must not be symlinks')
    fd = os.open(directory / 'queue.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('This private queue is already collecting') from error
        # SQLite journals inherit the database's private mode from creation.
        db_fd = os.open(directory / 'queue.sqlite3', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.fchmod(db_fd, 0o600)
        os.close(db_fd)
        with sqlite3.connect(directory / 'queue.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS discoveries (sequence INTEGER PRIMARY KEY, source_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(source_id, revision))')
            due = db.execute("SELECT value FROM metadata WHERE key='next_due'").fetchone()
            result = {'status': 'complete', 'observedAt': _iso(now), 'sourceUrl': HN_FEED,
                      'newDiscoveries': 0, 'unchanged': 0, 'nextDueAt': _iso(now + interval_seconds)}
            if due and float(due[0]) > now:
                count = _export(directory, db, shown_records)
                return {**result, 'status': 'not_due', 'nextDueAt': _iso(float(due[0])),
                        'queuedSources': count, 'reviewPath': str(directory / 'review.md')}
            try:
                items = parse_hn_feed(fetch())[:limit]
            except Exception as error:
                # Exception text may include remote response URLs or headers.
                result.update(status='failed', error=type(error).__name__)
                items = []
            for item in items:
                old = db.execute('SELECT revision, fingerprint FROM discoveries WHERE source_id=? ORDER BY revision DESC LIMIT 1', (item.source_id,)).fetchone()
                if old and old[1] == item.fingerprint:
                    result['unchanged'] += 1
                    continue
                revision = old[0] + 1 if old else 1
                discovery = {'monitorId': 'hn-public-review', 'sourceUrl': HN_FEED,
                             'sourceId': item.source_id, 'sourceItemUrl': item.source_item_url,
                             'canonicalUrl': item.canonical_url, 'title': item.title,
                             'sourcePublishedAt': item.published_at, 'observedAt': _iso(now),
                             'fingerprint': item.fingerprint, 'revision': revision}
                db.execute('INSERT INTO discoveries (source_id, revision, fingerprint, payload) VALUES (?, ?, ?, ?)',
                           (item.source_id, revision, item.fingerprint, json.dumps(discovery)))
                result['newDiscoveries'] += 1
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('next_due', ?)", (str(now + interval_seconds),))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_collection', ?)", (json.dumps(result),))
            db.commit()
            count = _export(directory, db, shown_records)
            return {**result, 'queuedSources': count, 'reviewPath': str(directory / 'review.md')}
