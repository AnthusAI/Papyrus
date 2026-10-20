import json
from pathlib import Path
import tempfile

from behave import given, when, then
from papyrus_content.monitoring_queue import collect_queue

FEED = b'<rss><channel><item><title>First</title><link>https://example.org/a</link><comments>https://news.ycombinator.com/item?id=123</comments></item><item><title>Again</title><link>https://example.org/a</link><comments>https://news.ycombinator.com/item?id=124</comments></item></channel></rss>'

@given('a private HN review queue and a feed with two discoveries of one source')
def setup_queue(context):
    directory = tempfile.mkdtemp(prefix='papyrus-private-hn-')
    context.tmp_dirs.append(directory)
    context.private_queue = Path(directory) / 'queue'
    collect_queue(context.private_queue, fetch=lambda: FEED, now=1000)

@when('the private collector repeats and one source title changes')
def revise_queue(context):
    collect_queue(context.private_queue, fetch=lambda: FEED, now=2000)
    collect_queue(context.private_queue, fetch=lambda: FEED.replace(b'First', b'Revised'), now=3000)

@then('one review source retains all three discovery revisions')
def queue_revisions(context):
    data = json.loads((context.private_queue / 'review.json').read_text())
    assert len(data['items']) == 1 and len(data['items'][0]['discoveries']) == 3

@then('the private review batch contains no predictions or applied labels')
def no_queue_learning(context):
    text = (context.private_queue / 'review.md').read_text()
    assert 'no predictions' in text and 'no applied labels' in text

@when('the next due private collection fails')
def fail_queue(context):
    def unavailable():
        raise OSError('source unavailable')
    collect_queue(context.private_queue, fetch=unavailable, now=2000)

@then('the prior review source remains available with a visible collection failure')
def queue_failure(context):
    data = json.loads((context.private_queue / 'review.json').read_text())
    assert len(data['items']) == 1 and data['lastCollection']['status'] == 'failed'
