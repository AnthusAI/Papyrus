import json
from pathlib import Path

import pytest

from papyrus_content.tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_ID_ENVIRONMENT_VARIABLE
from papyrus_content.tenant_context import TenantContextRefusal, build_tenant_context

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "features_backend/fixtures/tenant-context/vectors.json").read_text())["cases"]


@pytest.mark.parametrize("case", VECTORS, ids=[case["name"] for case in VECTORS])
def test_vector(case, monkeypatch):
    monkeypatch.setenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, case["mode"])
    monkeypatch.delenv(TENANT_ID_ENVIRONMENT_VARIABLE, raising=False)
    if case["tenantEnv"]:
        monkeypatch.setenv(TENANT_ID_ENVIRONMENT_VARIABLE, case["tenantEnv"])
    expected = case["expect"]
    if "refusal" in expected:
        with pytest.raises(TenantContextRefusal) as refused:
            build_tenant_context(case["identity"], case["explicitTenant"])
        assert refused.value.reason == expected["refusal"]
        return
    context = build_tenant_context(case["identity"], case["explicitTenant"])
    assert (context.tenant_id, list(context.roles), context.mode, context.operator) == (
        expected["tenantId"], expected["roles"], expected["mode"], expected["operator"])
