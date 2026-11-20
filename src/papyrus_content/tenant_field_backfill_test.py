"""``content backfill-tenant-id`` (PPY-8f9462): the plan, the writes, and which models it can reach. The rules are in automation-tenant-id.feature."""
from __future__ import annotations

import pytest

from papyrus_content.graphql_authoring import LIST_DEFINITIONS, MUTATIONS
from papyrus_content.tenancy import TENANT_FIELD_MODELS
from papyrus_content.tenant_field_backfill import (
    apply_tenant_id_backfill, plan_model, plan_tenant_id_backfill, reachable_models, unreachable_models)


class Owners:
    """Rows by model; ``list_row_owners`` and ``update_record_unscoped`` as the authoring client offers them."""

    def __init__(self, rows):
        self.rows, self.writes = rows, []

    def list_row_owners(self, model):
        return [dict(row) for row in self.rows.get(model, [])]

    def update_record_unscoped(self, model, payload):
        self.writes.append((model, payload))


def test_every_model_is_reached_or_named_as_not_reached():
    assert set(reachable_models()) | set(unreachable_models()) == TENANT_FIELD_MODELS
    assert all(model in LIST_DEFINITIONS and model in MUTATIONS for model in reachable_models())
    assert "Automation" in reachable_models()


def test_a_row_is_stamped_left_or_listed_by_its_owner():
    plan = plan_model("Automation", "alpha", [{"id": "b"}, {"id": "a", "tenantId": None}, {"id": "c", "tenantId": "alpha"}, {"id": "d", "tenantId": "beta"}])
    assert (plan.stamp, plan.already, plan.other_tenant) == (["a", "b"], 1, ["d"])
    assert plan.counts() == {"rows": 4, "stamp": 2, "alreadyStamped": 1, "otherTenant": 1}


def test_apply_writes_the_tenant_and_the_id_only_and_names_nothing_else():
    client = Owners({"Automation": [{"id": "rate"}, {"id": "mine", "tenantId": "alpha"}], "Message": [{"id": "m1"}]})
    plan = plan_tenant_id_backfill(client, "alpha")
    assert plan.pending_writes == 2 and client.writes == []   # planning writes nothing
    assert apply_tenant_id_backfill(client, plan) == {"Automation": 1, "Message": 1}
    assert sorted(client.writes, key=lambda write: write[0]) == [("Automation", {"id": "rate", "tenantId": "alpha"}), ("Message", {"id": "m1", "tenantId": "alpha"})]


def test_a_model_the_command_cannot_reach_is_refused_by_name():
    with pytest.raises(ValueError, match="ReaderVote"):
        plan_tenant_id_backfill(Owners({}), "alpha", ["ReaderVote"])


def test_the_tenant_id_is_validated():
    with pytest.raises(Exception, match="Tenant id"):
        plan_tenant_id_backfill(Owners({}), "Not A Tenant")
