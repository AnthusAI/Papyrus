import copy
import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

spec = importlib.util.spec_from_file_location('grants', Path(__file__).with_name('grants.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class Store:
    def __init__(self):
        self.items, self.spent, self.lock, self.barrier = {}, set(), threading.Lock(), None
    def create(self, key, value):
        with self.lock:
            if key in self.items: return False
            self.items[key] = copy.deepcopy(value)
        return True
    def get(self, key):
        with self.lock:
            value = copy.deepcopy(self.items.get(key))
            barrier = self.barrier
        if barrier:
            try: barrier.wait(timeout=2)
            except threading.BrokenBarrierError: pass
        return value
    def is_spent(self, key, spent):
        with self.lock: return (key, spent) in self.spent
    def rotate(self, key, version, value, spent):
        with self.lock:
            if self.items[key]['version'] != version or (key, spent) in self.spent: return False
            self.items[key] = copy.deepcopy(value)
            self.spent.add((key, spent))
            return True
    def replace(self, key, version, value):
        with self.lock:
            if self.items[key]['version'] != version: return False
            self.items[key] = copy.deepcopy(value)
            return True


def test_simultaneous_exchange_and_refresh():
    store = Store()
    grants = g.Grants(store, 'https://cms.example', clock=lambda: 1000)
    verifier = 'v' * 43
    args = {'client': 'client', 'redirect': 'https://client.example/cb', 'resource': 'https://cms.example/api/mcp'}
    code = grants.issue_code(**args, challenge=g.pkce(verifier), principal={'kind': 'staff', 'subject': 's', 'accessToken': 't', 'idToken': 'id'}, upstream_expiry=4600, transaction_id=g.token())
    def exchange():
        try: return grants.exchange(code, **args, verifier=verifier)
        except g.InvalidGrant: return None
    store.barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool: answers = list(pool.map(lambda _: exchange(), range(2)))
    assert sum(answer is not None for answer in answers) == 1
    refresh = next(answer for answer in answers if answer)['refresh_token']
    store.barrier = threading.Barrier(2)
    def rotate():
        try: return grants.refresh(refresh, client='client', resource=args['resource'])
        except g.InvalidGrant: return None
    with ThreadPoolExecutor(max_workers=2) as pool: answers = list(pool.map(lambda _: rotate(), range(2)))
    assert sum(answer is not None for answer in answers) == 1
    store.barrier = None
    assert grants.verify(next(answer for answer in answers if answer)['access_token'], resource=args['resource']) is None


def test_staff_grants_require_both_tokens():
    grants = g.Grants(Store(), 'https://cms.example', clock=lambda: 1000)
    try:
        grants.issue_code(client='client', redirect='https://client.example/cb', resource='https://cms.example/api/mcp', challenge=g.pkce('v' * 43), principal={'kind': 'staff', 'subject': 's', 'accessToken': 't'}, upstream_expiry=4600, transaction_id=g.token())
    except g.InvalidGrant:
        return
    assert False, 'staff grant without an ID token was accepted'


def test_consent_transaction_is_single_use_and_retained():
    store = Store()
    grants = g.Grants(store, 'https://cms.example', clock=lambda: 1000)
    args = dict(client='client', redirect='https://client.example/cb', resource='https://cms.example/api/mcp', challenge=g.pkce('v' * 43), principal={'kind': 'staff', 'subject': 's', 'accessToken': 't', 'idToken': 'i'}, upstream_expiry=1010, transaction_id='a' * 43)
    grants.issue_code(**args)
    assert store.items['a' * 43]['storage_expiry'] >= 1300
    try:
        grants.issue_code(**args)
    except g.InvalidGrant:
        return
    assert False, 'transaction replay issued another code'


def test_access_rotates_until_original_upstream_expiry():
    now = [1000]
    grants = g.Grants(Store(), 'https://cms.example', clock=lambda: now[0])
    args = dict(client='client', redirect='https://client.example/cb', resource='https://cms.example/api/mcp')
    person = {'kind': 'staff', 'subject': 's', 'accessToken': 't', 'idToken': 'i'}
    code = grants.issue_code(**args, challenge=g.pkce('v' * 43), principal=person, upstream_expiry=4600, transaction_id=g.token())
    tokens = grants.exchange(code, **args, verifier='v' * 43)
    first = tokens['access_token']
    assert tokens['expires_in'] == 900
    for moment in (1900, 2800, 3700, 4599):
        now[0] = moment
        if moment == 1900: assert grants.verify(first, resource=args['resource']) is None
        tokens = grants.refresh(tokens['refresh_token'], client=args['client'], resource=args['resource'])
        assert grants.verify(tokens['access_token'], resource=args['resource']) == person
    assert tokens['expires_in'] == 1
    now[0] = 4600
    assert grants.verify(tokens['access_token'], resource=args['resource']) is None
    try:
        grants.refresh(tokens['refresh_token'], client=args['client'], resource=args['resource'])
    except g.InvalidGrant:
        return
    assert False, 'refresh extended the upstream deadline'


def test_revoke_serializes_with_refresh():
    store = Store()
    grants = g.Grants(store, 'https://cms.example', clock=lambda: 1000)
    args = {'client': 'client', 'redirect': 'https://client.example/cb', 'resource': 'https://cms.example/api/mcp'}
    code = grants.issue_code(**args, challenge=g.pkce('v' * 43), principal={'kind': 'staff', 'subject': 's', 'accessToken': 't', 'idToken': 'i'}, upstream_expiry=4600, transaction_id=g.token())
    tokens = grants.exchange(code, **args, verifier='v' * 43)
    store.barrier = threading.Barrier(2)
    def rotate():
        try: return grants.refresh(tokens['refresh_token'], client='client', resource=args['resource'])
        except g.InvalidGrant: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        refresh = pool.submit(rotate)
        revoke = pool.submit(grants.revoke, tokens['refresh_token'], client='client')
        successor = refresh.result()
        revoke.result()
    store.barrier = None
    assert grants.verify(tokens['access_token'], resource=args['resource']) is None
    if successor: assert grants.verify(successor['access_token'], resource=args['resource']) is None


def test_contention_and_store_outages_fail_closed():
    import pytest
    store = Store()
    grants = g.Grants(store, 'https://cms.example', clock=lambda: 1000)
    args = {'client': 'client', 'redirect': 'https://client.example/cb', 'resource': 'https://cms.example/api/mcp'}
    code = grants.issue_code(**args, challenge=g.pkce('v' * 43), principal={'kind': 'staff', 'subject': 's', 'accessToken': 't', 'idToken': 'i'}, upstream_expiry=4600, transaction_id=g.token())
    tokens = grants.exchange(code, **args, verifier='v' * 43)
    old_replace, old_rotate = store.replace, store.rotate
    store.replace = lambda *args: False
    store.rotate = lambda *args: False
    with pytest.raises(g.GrantUnavailable): grants.refresh(tokens['refresh_token'], client='client', resource=args['resource'])
    with pytest.raises(g.GrantUnavailable): grants.revoke(tokens['refresh_token'], client='client')
    store.replace, store.rotate = old_replace, old_rotate
    def unavailable(*args): raise ValueError('storage unavailable')
    store.get = unavailable
    with pytest.raises(ValueError): grants.verify(tokens['access_token'], resource=args['resource'])
    with pytest.raises(ValueError): grants.revoke(tokens['refresh_token'], client='client')


def test_rotation_invalidates_unexpired_access_and_preserves_legacy_deadline():
    import pytest
    now = [1000]
    store = Store()
    grants = g.Grants(store, 'https://cms.example', clock=lambda: now[0])
    args = {'client': 'client', 'redirect': 'https://client.example/cb', 'resource': 'https://cms.example/api/mcp'}
    person = {'kind': 'staff', 'subject': 's', 'accessToken': 't', 'idToken': 'i'}
    code = grants.issue_code(**args, challenge=g.pkce('v' * 43), principal=person, upstream_expiry=2000, transaction_id=g.token())
    original = grants.exchange(code, **args, verifier='v' * 43)
    key = code.split('.')[0]
    legacy_digest = g.digest(g.token())
    store.items[key]['used_refresh'] = [legacy_digest]
    now[0] += 1
    rotated = grants.refresh(original['refresh_token'], client='client', resource=args['resource'])
    assert grants.verify(original['access_token'], resource=args['resource']) is None
    assert grants.verify(rotated['access_token'], resource=args['resource']) == person
    assert store.items[key]['expires'] == 2000
    assert store.items[key]['used_refresh'] == [legacy_digest]
    now[0] = 2000
    with pytest.raises(g.InvalidGrant): grants.refresh(rotated['refresh_token'], client='client', resource=args['resource'])


def test_access_revoke_remains_authorized_after_rotation_wins_cas():
    store = Store()
    grants = g.Grants(store, 'https://cms.example', clock=lambda: 1000)
    args = {'client': 'client', 'redirect': 'https://client.example/cb', 'resource': 'https://cms.example/api/mcp'}
    code = grants.issue_code(**args, challenge=g.pkce('v' * 43), principal={'kind': 'staff', 'subject': 's', 'accessToken': 't', 'idToken': 'i'}, upstream_expiry=4600, transaction_id=g.token())
    original = grants.exchange(code, **args, verifier='v' * 43)
    replace = store.replace
    successor = []
    def race(key, version, value):
        if not successor:
            successor.append(grants.refresh(original['refresh_token'], client='client', resource=args['resource']))
        return replace(key, version, value)
    store.replace = race
    grants.revoke(original['access_token'], client='client')
    assert successor
    assert grants.verify(successor[0]['access_token'], resource=args['resource']) is None


def test_other_site_cannot_exchange_refresh_or_revoke_shared_store():
    import pytest
    store = Store()
    site = g.Grants(store, 'https://cms.example', clock=lambda: 1000)
    other = g.Grants(store, 'https://other.example', clock=lambda: 1000)
    args = {'client': 'client', 'redirect': 'https://client.example/cb', 'resource': 'https://cms.example/api/mcp'}
    code = site.issue_code(**args, challenge=g.pkce('v' * 43), principal={'kind': 'staff', 'subject': 's', 'accessToken': 't', 'idToken': 'i'}, upstream_expiry=4600, transaction_id=g.token())
    with pytest.raises(g.InvalidGrant): other.exchange(code, **args, verifier='v' * 43)
    tokens = site.exchange(code, **args, verifier='v' * 43)
    with pytest.raises(g.InvalidGrant): other.refresh(tokens['refresh_token'], client='client', resource=args['resource'])
    other.revoke(tokens['refresh_token'], client='client')
    assert site.verify(tokens['access_token'], resource=args['resource']) is not None
