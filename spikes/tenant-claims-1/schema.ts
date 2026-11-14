// Throwaway spike (PPY-867f76): two tenant models, claims-only rules, no group rules.
// Item and Reference carry the rules the epic proposes. ItemLocked is the same model with a field-level rule on
// tenantId (create and read only), to test whether tenantId can be made immutable.
import { a, defineData, type ClientSchema } from "@aws-amplify/backend";

export const roles = {
  admin: "papyrus_tenant_admin",
  editor: "papyrus_tenant_editor",
  curator: "papyrus_tenant_curator",
  member: "papyrus_tenant_member",
} as const;

const tenantRules = (allow: any) => [
  allow.ownerDefinedIn("tenantId").identityClaim(roles.admin),
  allow.ownerDefinedIn("tenantId").identityClaim(roles.editor).to(["create", "read", "update", "delete"]),
  allow.ownerDefinedIn("tenantId").identityClaim(roles.member).to(["read"]),
];

export const schema = a.schema({
  Item: a
    .model({
      tenantId: a.string().required(),
      title: a.string(),
      key: a.string(), // index partition key, written "<tenant>#..." in the spike
    })
    .secondaryIndexes((i) => [i("key")])
    .authorization(tenantRules),
  Reference: a
    .model({
      tenantId: a.string().required(),
      url: a.string(),
      tkey: a.string(),
    })
    .secondaryIndexes((i) => [i("tkey")])
    .authorization(tenantRules),
  ItemLocked: a
    .model({
      tenantId: a
        .string()
        .required()
        .authorization((allow) => [
          allow.ownerDefinedIn("tenantId").identityClaim(roles.admin).to(["create", "read"]),
          allow.ownerDefinedIn("tenantId").identityClaim(roles.editor).to(["create", "read"]),
          allow.ownerDefinedIn("tenantId").identityClaim(roles.member).to(["read"]),
        ]),
      title: a.string(),
    })
    .authorization(tenantRules),
});

export type Schema = ClientSchema<typeof schema>;
export const data = defineData({ schema, authorizationModes: { defaultAuthorizationMode: "userPool" } });
