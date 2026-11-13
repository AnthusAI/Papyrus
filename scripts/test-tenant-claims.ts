import assert from "node:assert/strict";
import { test } from "node:test";
import { TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_ID_ENVIRONMENT_VARIABLE } from "../lib/tenant-keys";
import {
  TENANCY_MODELS_ENVIRONMENT_VARIABLE,
  buildTenantClaims,
  claimEnvironment,
  membershipRole,
  rolesFromGroups,
  type ItemReader,
  type Row,
  type TenancyModel,
} from "../amplify/functions/tenant-claims/claims";
import { createHandler, type PreTokenGenerationV2Event } from "../amplify/functions/tenant-claims/handler";

const ADA = "sub-ada";
const membership = (tenantId: string, userSub: string, role: string, status = "active"): Row => ({ id: `${tenantId}#${userSub}`, tenantId, userSub, role, status });
const selection = (userSub: string, selectedTenantId: string): Row => ({ id: userSub, selectedTenantId });

function store(rows: Partial<Record<TenancyModel, Row[]>>): ItemReader & { reads: string[] } {
  const reader = (async (model: TenancyModel, id: string) => {
    reader.reads.push(`${model}:${id}`);
    return rows[model]?.find((row) => row.id === id) ?? null;
  }) as ItemReader & { reads: string[] };
  reader.reads = [];
  return reader;
}

const shared = { [TENANCY_MODE_ENVIRONMENT_VARIABLE]: "shared", [TENANCY_MODELS_ENVIRONMENT_VARIABLE]: "true" };
const dedicated = (tenant?: string) => ({ ...(tenant ? { [TENANT_ID_ENVIRONMENT_VARIABLE]: tenant } : {}), [TENANCY_MODELS_ENVIRONMENT_VARIABLE]: "true" });
const claimsFor = (environment: Record<string, string>, read: ItemReader, groups: string[] = [], sub = ADA) =>
  buildTenantClaims(claimEnvironment(environment), { userSub: sub, groups }, read);

test("a shared stack gives the one role held on the selected tenant, and no claim for another", async () => {
  const read = store({ TenantMembership: [membership("alpha", ADA, "editor"), membership("beta", ADA, "member")], TenantSelection: [selection(ADA, "alpha")] });
  assert.deepEqual(await claimsFor(shared, read), { papyrus_tenant_editor: "alpha" });
  const switched = store({ TenantMembership: [membership("alpha", ADA, "editor"), membership("beta", ADA, "member")], TenantSelection: [selection(ADA, "beta")] });
  assert.deepEqual(await claimsFor(shared, switched), { papyrus_tenant_member: "beta" });
});

test("a lookup is two GetItems by key and never a scan", async () => {
  const read = store({ TenantMembership: [membership("alpha", ADA, "admin")], TenantSelection: [selection(ADA, "alpha")] });
  await claimsFor(shared, read);
  assert.deepEqual(read.reads, [`TenantSelection:${ADA}`, `TenantMembership:alpha#${ADA}`]);
});

test("no selection, no membership, an inactive membership or a mismatched row gives nothing", async () => {
  assert.deepEqual(await claimsFor(shared, store({ TenantMembership: [membership("alpha", ADA, "editor")] })), {});
  assert.deepEqual(await claimsFor(shared, store({ TenantSelection: [selection(ADA, "alpha")] })), {});
  for (const status of ["pending", "revoked", "removed"]) {
    assert.deepEqual(await claimsFor(shared, store({ TenantMembership: [membership("alpha", ADA, "editor", status)], TenantSelection: [selection(ADA, "alpha")] })), {});
  }
  const forged = { ...membership("alpha", ADA, "editor"), tenantId: "beta" };
  assert.deepEqual(await claimsFor(shared, store({ TenantMembership: [forged], TenantSelection: [selection(ADA, "alpha")] })), {});
  assert.deepEqual(await claimsFor(shared, store({ TenantMembership: [membership("alpha", ADA, "owner")], TenantSelection: [selection(ADA, "alpha")] })), {});
});

test("a stored selection that is not a tenant id selects nothing", async () => {
  const read = store({ TenantSelection: [selection(ADA, "Not A Tenant")] });
  assert.deepEqual(await claimsFor(shared, read), {});
  assert.deepEqual(read.reads, [`TenantSelection:${ADA}`]);
});

test("Cognito groups never give a tenant claim on a shared stack", async () => {
  assert.deepEqual(await claimsFor(shared, store({ TenantSelection: [selection(ADA, "alpha")] }), ["admin", "editor"]), {});
});

test("a dedicated stack emits its fixed tenant for matching groups, one claim per role", async () => {
  const read = store({});
  assert.deepEqual(await claimsFor(dedicated("alpha"), read, ["editor", "curator", "unrelated"]), { papyrus_tenant_editor: "alpha", papyrus_tenant_curator: "alpha" });
  assert.deepEqual(rolesFromGroups(["curator", "admin"]), ["admin", "curator"]);
});

test("a dedicated stack adds the membership role on its fixed tenant and ignores any selection", async () => {
  const read = store({ TenantMembership: [membership("alpha", ADA, "member"), membership("beta", ADA, "admin")], TenantSelection: [selection(ADA, "beta")] });
  assert.deepEqual(await claimsFor(dedicated("alpha"), read, ["editor"]), { papyrus_tenant_editor: "alpha", papyrus_tenant_member: "alpha" });
  assert.deepEqual(read.reads, [`TenantMembership:alpha#${ADA}`]);
});

test("a role held by group and membership gives one claim", async () => {
  const read = store({ TenantMembership: [membership("alpha", ADA, "editor")] });
  assert.deepEqual(await claimsFor(dedicated("alpha"), read, ["editor"]), { papyrus_tenant_editor: "alpha" });
});

test("a dedicated stack with no tenant emits nothing", async () => {
  assert.deepEqual(await claimsFor(dedicated(), store({}), ["admin"]), {});
});

test("without the tenancy models a dedicated stack emits group claims and a shared stack nothing, reading nothing", async () => {
  const read = store({});
  assert.deepEqual(await claimsFor({ [TENANT_ID_ENVIRONMENT_VARIABLE]: "alpha" }, read, ["admin"]), { papyrus_tenant_admin: "alpha" });
  assert.deepEqual(await claimsFor({ [TENANCY_MODE_ENVIRONMENT_VARIABLE]: "shared" }, read, ["admin"]), {});
  assert.deepEqual(read.reads, []);
});

test("membershipRole accepts only an active row for this person and tenant with a known role", () => {
  assert.equal(membershipRole(membership("alpha", ADA, "curator"), "alpha", ADA), "curator");
  assert.equal(membershipRole(membership("alpha", ADA, "curator"), "alpha", "sub-bo"), null);
  assert.equal(membershipRole(null, "alpha", ADA), null);
});

function event(groups: string[] = [], sub: string | null = ADA): PreTokenGenerationV2Event {
  return {
    request: { userAttributes: sub ? { sub, email: "ada@example.test" } : {}, groupConfiguration: { groupsToOverride: groups } },
    response: { claimsAndScopeOverrideDetails: {} },
  };
}

test("the handler writes the claims to both tokens and leaves groups alone", async () => {
  const read = store({ TenantMembership: [membership("alpha", ADA, "editor")], TenantSelection: [selection(ADA, "alpha")] });
  const result = await createHandler(read, () => shared)(event(["editor"]));
  assert.deepEqual(result.response.claimsAndScopeOverrideDetails, {
    idTokenGeneration: { claimsToAddOrOverride: { papyrus_tenant_editor: "alpha" } },
    accessTokenGeneration: { claimsToAddOrOverride: { papyrus_tenant_editor: "alpha" } },
  });
  assert.ok(!("groupOverrideDetails" in (result.response.claimsAndScopeOverrideDetails ?? {})));
});

test("the handler returns the event unchanged when there is no claim", async () => {
  const result = await createHandler(store({}), () => shared)(event());
  assert.deepEqual(result.response, { claimsAndScopeOverrideDetails: {} });
});

test("the handler refuses an event with no sub, and a failed read fails the token request", async () => {
  await assert.rejects(createHandler(store({}), () => shared)(event([], null)), /no sub/);
  const failing: ItemReader = async () => {
    throw new Error("data API unavailable");
  };
  await assert.rejects(createHandler(failing, () => shared)(event()), /data API unavailable/);
});
