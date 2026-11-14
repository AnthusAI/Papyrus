import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_ID_ENVIRONMENT_VARIABLE } from "../lib/tenant-keys";
import { TenantContextRefusal, buildTenantContext } from "../amplify/functions/shared/tenant-context";

type Vector = {
  name: string;
  mode: string;
  tenantEnv: string | null;
  identity: Record<string, unknown> | null;
  explicitTenant: string | null;
  expect: { refusal: string } | { tenantId: string | null; roles: string[]; mode: string; operator: boolean };
};

const vectors: Vector[] = JSON.parse(readFileSync("features_backend/fixtures/tenant-context/vectors.json", "utf8")).cases;

for (const vector of vectors) {
  test(vector.name, () => {
    const environment: Record<string, string> = { [TENANCY_MODE_ENVIRONMENT_VARIABLE]: vector.mode };
    if (vector.tenantEnv) environment[TENANT_ID_ENVIRONMENT_VARIABLE] = vector.tenantEnv;
    const build = () => buildTenantContext(vector.identity, { explicitTenant: vector.explicitTenant, environment });
    if ("refusal" in vector.expect) {
      const expected = vector.expect.refusal;
      assert.throws(build, (error) => error instanceof TenantContextRefusal && error.reason === expected);
    } else {
      assert.deepEqual(build(), vector.expect);
    }
  });
}
