import pytest

from papyrus_content import tenant_records as records
from papyrus_content.tenancy import TenantError
from papyrus_content.tenant_records import DomainAlreadyClaimed, TenantRecordError


class FakeTable:
    def __init__(self):
        self.rows = {}
        self.queries = []

    def create(self, model, row):
        key = (model, row["id"])
        if key in self.rows:
            raise KeyError(row["id"])
        self.rows[key] = row

    def query(self, query_field, variables):
        self.queries.append(query_field)
        return [r for (m, _), r in self.rows.items() if m == "TenantMembership" and r["userSub"] == variables["userSub"]]


def test_state_key_and_ids():
    assert records.tenant_state_key("past_due") == "state#past_due"
    assert records.membership_id("alpha", "sub-1") == "alpha#sub-1"
    assert records.domain_id(" Alpha.Apyr.US. ") == "alpha.apyr.us"
    for bad in ("", "a..b", "-a.b", "a b.c", "x" * 64 + ".com"):
        with pytest.raises(TenantRecordError):
            records.domain_id(bad)
    with pytest.raises(TenantRecordError):
        records.tenant_state_key("gone")
    with pytest.raises(TenantError):
        records.membership_id("Alpha", "s")
    with pytest.raises(TenantRecordError):
        records.membership_id("alpha", "a#b")


def test_records_carry_their_keys():
    tenant = records.tenant_record("alpha", "acct-1", "Alpha", "2026-11-10T00:00:00Z")
    assert tenant["stateKey"] == "state#active" and tenant["id"] == "alpha"
    member = records.membership_record("alpha", "s1", "editor", "ops", "2026-11-10T00:00:00Z", user_profile_id="p1")
    assert member["id"] == "alpha#s1" and member["userProfileId"] == "p1" and member["tenantId"] == "alpha"
    with pytest.raises(TenantRecordError):
        records.membership_record("alpha", "s1", "owner", "ops", "t")
    with pytest.raises(TenantRecordError):
        records.domain_record("alpha", "a.apyr.us", "wildcard")


def test_membership_lookup_is_one_query_on_the_user_sub_index():
    table = FakeTable()
    for tenant in ("alpha", "beta", "gamma"):
        for n in range(5):
            sub = "ada" if n == 0 else f"{tenant}-{n}"
            table.create("TenantMembership", records.membership_record(tenant, sub, "member", "ops", "t"))
    found = records.list_memberships_for_user(table.query, "ada")
    assert table.queries == ["listTenantMembershipsByUserSub"]
    assert sorted(r["tenantId"] for r in found) == ["alpha", "beta", "gamma"]
    with pytest.raises(TenantRecordError):
        records.list_memberships_for_user(table.query, " ")


def test_a_hostname_belongs_to_one_tenant():
    table = FakeTable()
    records.claim_domain(table.create, "alpha", "alpha.apyr.us", "subdomain")
    with pytest.raises(DomainAlreadyClaimed):
        records.claim_domain(table.create, "beta", "Alpha.apyr.us", "custom")
    assert table.rows[("TenantDomain", "alpha.apyr.us")]["tenantId"] == "alpha"
