import { a, defineData, type ClientSchema } from "@aws-amplify/backend";

const EDITOR = "papyrus_tenant_editor";
const MEMBER = "papyrus_tenant_member";

// Rule shape under test: row.tenantId must equal the caller's role claim.
const tenantRules = (allow: any) => [
  allow.ownerDefinedIn("tenantId").identityClaim(EDITOR).to(["create", "read", "update", "delete"]),
  allow.ownerDefinedIn("tenantId").identityClaim(MEMBER).to(["read"]),
];

// tenantId is set on create and never again: field-level rules grant read and create, not update.
const tenantIdField = () =>
  a.string().required().authorization((allow: any) => [
    allow.ownerDefinedIn("tenantId").identityClaim(EDITOR).to(["create", "read"]),
    allow.ownerDefinedIn("tenantId").identityClaim(MEMBER).to(["read"]),
  ]);

// Same lock for the tenant index key: an editor must not move a row into another tenant's index partition.
const lockedOnceSet = () => tenantIdField();

const schema = a.schema({
  // Base shape, model-level rules only (what happens to tenantId on update without a field rule).
  Item: a.model({
    tenantId: a.string().required(),
    name: a.string().required(),
  }).authorization(tenantRules),

  // Index lists and the immutable field.
  Reference: a.model({
    tenantId: tenantIdField(),
    tenantKey: lockedOnceSet(), // "<tenant>#reference": the partition key of the tenant index
    status: a.string().required(), // "published" for every row: a partition shared by all tenants (the trap)
    seq: a.integer().required(),
    title: a.string().required(),
  })
    .secondaryIndexes((index: any) => [
      index("tenantKey").sortKeys(["seq"]).queryField("listReferenceByTenantKey"),
      index("status").sortKeys(["seq"]).queryField("listReferenceByStatus"),
    ])
    .authorization(tenantRules),
});

export type Schema = ClientSchema<typeof schema>;
export const data = defineData({ schema, authorizationModes: { defaultAuthorizationMode: "userPool" } });
