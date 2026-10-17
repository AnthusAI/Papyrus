# Schema and API alignment (no compatibility shims)

Local code and the deployed GraphQL API must describe the same contract. Fix drift by deploying, not by adapting in code.

Local application code and the deployed GraphQL API must describe the same contract.
When CLI or Lambda code fails because a field, model, or input type is missing on
AppSync, that is a **deployment error** — not a signal to add adaptation logic in
Python or TypeScript.

**Do not fix schema drift in code. Fix the deployment.**

### Forbidden (unless the user explicitly approves a temporary emergency repair)

- Runtime schema introspection that **filters** queries or mutations to match
  whatever the remote API currently exposes (for example: dropping undeployed
  fields from `listReferences`, or stripping keys from `CreateReferenceInput`
  before send).
- Fallback read queries with reduced field sets for "older" APIs.
- Dual-shape normalizers that accept both old and new schema shapes.
- Silent `try/except` branches that continue with partial or degraded behavior
  when the API contract does not match code.
- Any logic whose purpose is "make the CLI work against a sandbox that hasn't
  caught up yet." That sandbox will catch up once; the shim stays forever.

These patterns look small at first. They become permanent branches every agent
and every future feature must reason about. **One hour of deployment lag is not
worth years of compatibility debt.**

### Required response when code and deployed schema disagree

1. Confirm local schema in [`amplify/data/resource.ts`](../amplify/data/resource.ts)
   (or the relevant Amplify resource) is what code expects.
2. Deploy it to the target environment:
   - **Sandbox:** `npx ampx sandbox` (wait for deploy to finish), then
     `npm run outputs:sandbox` if needed.
   - **Production:** use the normal pipeline; do not patch around prod drift
     from local agents.
3. Re-run the failing CLI command. It should succeed against the updated API or
   fail with a real data/logic error — not a field-undefined validation error.

Do **not** weaken the CLI client, GraphQL authoring layer, or newsroom tools to
paper over an outdated AppSync schema.

### Temporary emergency repairs

Only when the user **explicitly approves** restoring production immediately:

- Keep the repair as narrow as possible (one command, one model, one migration).
- Document exactly why it exists and when it must be removed.
- Remove it from normal read, authoring, repository, and solver paths as soon
  as deployment or data is corrected.

Default is **clean breaks**: fail loudly, deploy schema, move on.

### Concrete anti-pattern (do not repeat)

During Threat Intelligence bootstrap, sandbox AppSync was missing
`Reference.inboundCitationCount`, `Reference.reviewedFeedKey`, and related
fields that already existed in local schema. The wrong fix was adding
`_resolved_fields()` and runtime mutation input filtering in
`src/papyrus_content/graphql_authoring.py`. The right fix was deploying sandbox
schema, then re-running `references create-from-catalog`.
