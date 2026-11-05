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
        self.items, self.lock, self.barrier = {}, threading.Lock(), None
    def create(self, key, value):
        with self.lock:
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
    code = grants.issue_code(**args, challenge=g.pkce(verifier), principal={'kind': 'staff', 'subject': 's', 'accessToken': 't'}, upstream_expiry=4600)
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
