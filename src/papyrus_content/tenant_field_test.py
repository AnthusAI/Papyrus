"""PPY-94d609: every tenant-owned model carries an optional tenantId, and a tenant client stamps it."""

from __future__ import annotations

import pytest

from papyrus_content.tenancy import TENANT_FIELD_MODELS, TENANT_MODELS, tenant_field_stamped_payload
from procedures.newsroom.tests.test_tenancy import InMemoryGraphQLBackend, tenant_client


class IntrospectableBackend(InMemoryGraphQLBackend):
    """A site whose schema has tenantId; any schema query fails, as it does for the workers' role."""

    def _read(self, field, variables):
        if field == "__type":
            raise AssertionError("no schema query is allowed")
        return super()._read(field, variables)


def test_the_field_models_exclude_global_identity_and_the_fully_tenant_models():
    assert len(TENANT_FIELD_MODELS) == 56
    assert not TENANT_FIELD_MODELS & {"UserProfile", "UserIdentity", "PublicHandleClaim"}
    assert not TENANT_FIELD_MODELS & TENANT_MODELS


def test_stamping_only_adds_the_field_and_respects_a_value_already_set():
    assert tenant_field_stamped_payload("Message", "alpha", {"id": "m1"}) == {"id": "m1", "tenantId": "alpha"}
    assert tenant_field_stamped_payload("Message", None, {"id": "m1"}) == {"id": "m1"}
    assert tenant_field_stamped_payload("UserProfile", "alpha", {"id": "u1"}) == {"id": "u1"}
    assert tenant_field_stamped_payload("Message", "alpha", {"id": "m1", "tenantId": "beta"})["tenantId"] == "beta"


@pytest.mark.parametrize("model", ["Message", "Assignment", "Reference"])
def test_a_tenant_client_stamps_its_tenant_on_every_write(model):
    backend = IntrospectableBackend()
    tenant_client(backend, "alpha").create_record(model, {"id": "row-1"})
    row = backend.tables[model]["row-1"]
    assert row["tenantId"] == "alpha" and row["id"] == "row-1"


def test_a_client_without_a_tenant_writes_exactly_as_before():
    backend = IntrospectableBackend()
    tenant_client(backend, None).create_record("Message", {"id": "row-1"})
    assert "tenantId" not in backend.tables["Message"]["row-1"]
