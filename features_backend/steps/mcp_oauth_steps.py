import copy
import importlib.util
from pathlib import Path

from behave import given, when, then

path = Path(__file__).resolve().parents[2] / "amplify/functions/mcp-oauth/grants.py"
spec = importlib.util.spec_from_file_location("mcp_grants", path)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class MemoryStore:
    def __init__(self): self.rows, self.spent = {}, set()
    def create(self, key, value):
        if key in self.rows: return False
        self.rows[key] = copy.deepcopy(value)
        return True
    def get(self, key): return copy.deepcopy(self.rows.get(key))
    def is_spent(self, key, spent): return (key, spent) in self.spent
    def rotate(self, key, version, value, spent):
        if self.rows[key]["version"] != version or (key, spent) in self.spent: return False
        self.rows[key] = copy.deepcopy(value)
        self.spent.add((key, spent))
        return True
    def replace(self, key, version, value):
        if self.rows[key]["version"] != version: return False
        self.rows[key] = copy.deepcopy(value)
        return True


def setup(context):
    context.now = 1000
    context.store = MemoryStore()
    context.grants = g.Grants(context.store, "https://cms.example", clock=lambda: context.now)
    context.verifier = "v" * 43
    context.args = dict(client="client", redirect="https://client.example/callback", resource="https://cms.example/api/mcp")
    context.person = dict(kind="staff", subject="staff-subject", accessToken="user-token", idToken="id-token")


def issue(context, expiry=4600):
    return context.grants.issue_code(**context.args, challenge=g.pkce(context.verifier), principal=context.person, upstream_expiry=expiry, transaction_id=g.token())


def exchange(context, code):
    return context.grants.exchange(code, **context.args, verifier=context.verifier)


def refused(fn):
    try: fn()
    except g.InvalidGrant: return
    raise AssertionError("Grant was accepted")


@given('a signed-in person authorizes a registered client for a publication')
def step(context):
    setup(context)
    context.code = issue(context)

@when('the client exchanges the code with a different redirect, resource or verifier')
def step(context):
    for change in ({"redirect": "https://other.example/callback"}, {"resource": "https://other.example/api/mcp"}, {"verifier": "x" * 43}):
        args = dict(context.args, verifier=context.verifier, **change) if "verifier" not in change else dict(context.args, **change)
        refused(lambda: context.grants.exchange(context.code, **args))

@then('the exchange is refused and the code remains unusable by that request')
def step(context):
    assert exchange(context, context.code)["access_token"]
    refused(lambda: exchange(context, context.code))

@given('a person has signed in through Prospectus')
def step(context):
    setup(context)
    context.person = dict(kind="reader")

@when('Prospectus has not returned a verified site subject')
def step(context):
    refused(lambda: issue(context))

@then('reader authorization is unavailable')
def step(context):
    assert not context.store.rows

@given('an authenticated newsroom staff member')
def step(context): setup(context)

@when('the member authorizes a client')
def step(context): context.tokens = exchange(context, issue(context))

@then("the grant carries that member's user-scoped credentials")
def step(context):
    assert context.grants.verify(context.tokens["access_token"], resource=context.args["resource"]) == context.person

@then('no operator credentials are substituted')
def step(context): assert context.person["accessToken"] == "user-token"

@given('a client holds a valid refresh token')
def step(context):
    setup(context)
    context.tokens = exchange(context, issue(context))

@when('it refreshes and then replays the old token')
def step(context):
    context.new = context.grants.refresh(context.tokens["refresh_token"], client="client", resource=context.args["resource"])
    refused(lambda: context.grants.refresh(context.tokens["refresh_token"], client="client", resource=context.args["resource"]))

@then('the replay is refused and the grant is revoked')
def step(context): assert context.grants.verify(context.new["access_token"], resource=context.args["resource"]) is None

@given('upstream authorization expires in one hour')
def step(context): setup(context)

@when('the person authorizes a client')
def step(context): context.code = issue(context)

@then('the grant expires no later than that upstream authorization')
def step(context):
    context.now = 4600
    refused(lambda: exchange(context, context.code))

@then('no grant lasts more than seven days')
def step(context):
    context.now = 1000
    code = issue(context, expiry=1000 + 10 * 86400)
    row = context.store.get(code.split('.')[0])
    assert row["expires"] == 1000 + 7 * 86400

@given('a client holds a grant for one publication')
def step(context):
    setup(context)
    context.tokens = exchange(context, issue(context))

@when('the grant is revoked or presented to another publication')
def step(context):
    assert context.grants.verify(context.tokens["access_token"], resource="https://other.example/api/mcp") is None
    context.grants.revoke(context.tokens["refresh_token"], client="client")

@then('the grant cannot authorize access')
def step(context): assert context.grants.verify(context.tokens["access_token"], resource=context.args["resource"]) is None

@when('malformed tokens are presented')
def step(context):
    context.store.rows.clear()
    context.lookups = []
    context.store.get = lambda key: context.lookups.append(key)
    refused(lambda: context.grants.refresh('unicode.☃', client='client', resource=context.args['resource']))
    assert context.grants.verify('bad.value', resource=context.args['resource']) is None
    context.grants.revoke('bad.value', client='client')

@then('they are refused without looking them up')
def step(context): assert not context.lookups

@given('a client holds a grant with a seven-day deadline')
def step(context):
    setup(context)
    context.deadline = context.now + 7 * 86400
    context.tokens = exchange(context, issue(context, expiry=context.deadline))
    context.old_access_invalid = True

@when('it refreshes every fifteen minutes until the deadline')
def step(context):
    while context.now + 900 < context.deadline:
        context.now += 900
        previous = context.tokens['access_token']
        context.tokens = context.grants.refresh(context.tokens['refresh_token'], client='client', resource=context.args['resource'])
        context.old_access_invalid &= context.grants.verify(previous, resource=context.args['resource']) is None
        assert context.store.get(context.tokens['access_token'].split('.')[0])['expires'] == context.deadline

@then('each previous access token fails immediately after rotation')
def step(context): assert context.old_access_invalid

@then('the deadline never moves and the grant fails at the deadline')
def step(context):
    context.now = context.deadline
    assert context.grants.verify(context.tokens['access_token'], resource=context.args['resource']) is None
    refused(lambda: context.grants.refresh(context.tokens['refresh_token'], client='client', resource=context.args['resource']))

@when('the token is rotated and an unrelated client or publication replays it')
def step(context):
    old = context.tokens['refresh_token']
    context.new = context.grants.refresh(old, client='client', resource=context.args['resource'])
    refused(lambda: context.grants.refresh(old, client='other', resource=context.args['resource']))
    refused(lambda: context.grants.refresh(old, client='client', resource='https://other.example/api/mcp'))
    context.old = old

@then('the successor remains usable until a real replay revokes it')
def step(context):
    assert context.grants.verify(context.new['access_token'], resource=context.args['resource']) == context.person
    refused(lambda: context.grants.refresh(context.old, client='client', resource=context.args['resource']))
    assert context.grants.verify(context.new['access_token'], resource=context.args['resource']) is None

@when("the member's ID credential is absent")
def step(context):
    context.person.pop("idToken")

@then("no staff grant is issued")
def step(context):
    refused(lambda: issue(context))
    assert not context.store.rows


@given("a client holds a grant backed by a one-hour browser session")
def step(context):
    setup(context)
    context.deadline = context.now + 3600
    context.tokens = exchange(context, issue(context, expiry=context.deadline))
    context.initial_access = context.tokens["access_token"]

@when("access expires and the client refreshes it until that session expires")
def step(context):
    context.now += 900
    assert context.grants.verify(context.initial_access, resource=context.args["resource"]) is None
    for now in (1900, 2800, 3700, 4599):
        context.now = now
        context.tokens = context.grants.refresh(context.tokens["refresh_token"], client=context.args["client"], resource=context.args["resource"])
        assert context.grants.verify(context.tokens["access_token"], resource=context.args["resource"]) == context.person

@then("access works after rotation but no refresh extends the original deadline")
def step(context):
    assert context.tokens["expires_in"] == 1
    context.now = context.deadline
    assert context.grants.verify(context.tokens["access_token"], resource=context.args["resource"]) is None
    refused(lambda: context.grants.refresh(context.tokens["refresh_token"], client=context.args["client"], resource=context.args["resource"]))
