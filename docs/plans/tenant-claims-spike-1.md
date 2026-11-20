# Tenant claims spike, part 1 (PPY-867f76, parent PPY-9f3de0)

Status: offline result only. **No sandbox was deployed** (this session was told not to deploy to AWS), so the two Google test
users, the real Cognito token and AppSync itself are untested. What was done instead is stronger than reading docs and weaker
than the ticket: Amplify's own transformer generated the resolvers for the spike schema, and the generated authorization
templates were executed with the simulator's VTL engine against an in-memory table.

## Answer to the ticket's question

**Can Amplify model rules require both the caller's tenant and the caller's role? Yes, in the generated rules, with one hole
that needs a field-level rule.** One rule per role, each `allow.ownerDefinedIn("tenantId").identityClaim("<claim>")`,
generates a check that the row's `tenantId` equals that claim, and a role that is not listed for an operation grants nothing
for it. With claims-only rules (no group rules), every cross-tenant, no-claim and wrong-role calls were denied or returned
nothing on both models, and the matching same-tenant calls worked. Open: the live run (below).

## Exact rule syntax that works

```ts
const tenantRules = (allow) => [
  allow.ownerDefinedIn("tenantId").identityClaim("papyrus_tenant_admin"),
  allow.ownerDefinedIn("tenantId").identityClaim("papyrus_tenant_editor").to(["create", "read", "update", "delete"]),
  allow.ownerDefinedIn("tenantId").identityClaim("papyrus_tenant_member").to(["read"]),
];
Item: a.model({
  tenantId: a.string().required()
    .authorization((allow) => [   // field rule: tenantId can be set on create, never changed
      allow.ownerDefinedIn("tenantId").identityClaim("papyrus_tenant_admin").to(["create", "read"]),
      allow.ownerDefinedIn("tenantId").identityClaim("papyrus_tenant_editor").to(["create", "read"]),
      allow.ownerDefinedIn("tenantId").identityClaim("papyrus_tenant_member").to(["read"]),
    ]),
  ...
}).authorization(tenantRules)
```

It compiles to `@auth(rules: [{allow: owner, ownerField: "tenantId", identityClaim: "papyrus_tenant_editor", operations: [...]}])`.
The claim is read from `$ctx.identity.claims`, compared as a string. One session carries one tenant, so a token holds claims
for one tenant only; if several role claims were present the rules combine as OR.

## Evidence (`spikes/tenant-claims-1/run-scenarios.cjs`, 39 checks, all as expected)

| Operation by an alpha editor on beta's row | Result |
| --- | --- |
| get | denied (auth filter removes the row; the response template raises Unauthorized) |
| list, with and without `filter: {tenantId: {eq: "beta"}}` | zero beta rows |
| list through the `key` / `tkey` index at a `beta#...` key | zero rows |
| create with `tenantId: "beta"` | denied |
| update, delete | denied (the existing row's tenantId is read and compared first); beta's row unchanged |

Controls: the same calls on alpha's own row work. A token with no tenant claim is denied on get, list and create. An alpha
**member** can read but cannot create or update (role matters, not only tenant). Item and Reference behave identically.

## Findings that change the design

1. **`tenantId` is NOT immutable with model-level rules.** An alpha editor's `updateItem(id, tenantId: "beta")` succeeds: the
   rule only checks the stored row's tenantId, the data resolver then writes whatever the input says, and there is no condition
   on the field. Amplify warns about this at synth ("owners may reassign ownership"). It is a cross-tenant write: alpha can
   push rows into beta. The field-level rule above (create and read only) closes it: the same update is denied, other
   fields still update. Cost: **a client must never re-send `tenantId` on update**, even unchanged (that is denied too);
   check generated clients and every writer. Parent sub-question 5: yes, via this field rule (offline).
2. **Base `list` is a DynamoDB Scan with a filter.** The tenant filter is applied after each page is read, so one tenant's
   page can come back short or empty when other tenants' rows fill the page. Lists on the shared stack must go through an
   index whose partition key is the tenant prefix. A Query on that key reads only that tenant's rows, so pages are full
   (scannedCount equals returned rows in the run), and a foreign key returns nothing. Measured page sizes on real DynamoDB: not done.
3. **Claims must be on the access token, and Amplify's trigger helper cannot do that.** The Amplify v6 data client sends
   the access token for `userPool` auth (`api-graphql/.../graphqlAuth.js` reads `tokens.accessToken`). A V1 pre-token trigger
   only customizes the ID token. A V2_0 event customizes both. `defineAuth({triggers: {preTokenGeneration}})` has no version
   option; the CDK call `userPool.addTrigger(UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG, fn, LambdaVersion.V2_0)` synthesizes
   `PreTokenGenerationConfig.LambdaVersion: V2_0` (see `synth.ts`); in Amplify that means an escape hatch on the pool's
   `cfnResources`, and it must not also set the legacy V1 field.
4. **Cognito plan (sub-question 4, partly).** Per the Cognito documentation, event versions two and three are available in the
   Essentials and Plus feature plans (the Lite plan only for pools that had advanced security on before 2024-11-22). So the
   access-token claims need Essentials or Plus. The per-MAU price was not looked up; the pool's current plan is not known from here.
5. **Choosing the tenant at sign-in.** `clientMetadata` reaches the trigger only via RespondToAuthChallenge, not InitiateAuth,
   and the Google (hosted UI) flow gives the Lambda no caller-chosen tenant. The pre-token Lambda must derive the tenant from
   something it can trust (the person's membership plus a server-side "current site" record), which PPY-0bb0fd designs. The
   spike Lambda's `clientMetadata` branch is a placeholder for that.
6. **Subscriptions (sub-question 3), read not run.** Every subscription's generated auth step builds a per-claim runtime filter
   (`tenantId eq <claim>`) and applies it with `setSubscriptionFilter`, or authorizes by a `tenantId` argument equal to the claim
   and raises Unauthorized for any other value. So they look filtered per tenant. Not executed: the simulator cannot run
   `$extensions.setSubscriptionFilter`. Needs the sandbox. The repo's rule is to avoid AppSync realtime anyway.

## Not done (needs the sandbox; blocked by "do not deploy")

- The scenario as written ("sandbox users acting for alpha and beta") with two Google-federated test users, a real access token
  and AppSync evaluating the real resolvers. The generated templates are what AppSync runs, but the simulator's utility
  functions and my in-memory expression evaluator are approximations (for example for DynamoDB filter/condition syntax).
- Page sizes on real DynamoDB, subscriptions, and the pool's Cognito plan.
- Fallback (custom resolvers reading claims) is **not** triggered by anything found: the rule form works. The one issue (immutability) has an in-model fix.

## Next step for whoever has sandbox access

`docs/aws-sandbox-personal.md`; deploy `spikes/tenant-claims-1/schema.ts` with the V2 trigger wired as in `synth.ts`, sign in two
Google test users (their addresses in the Lambda's table via env, never committed), run `features_backend/tenant-claims-spike.feature`
(@sandbox) by hand, then destroy the sandbox.
