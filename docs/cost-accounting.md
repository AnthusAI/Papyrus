# Cost accounting (Prospectus)

Prospectus keeps a private ledger of what each customer costs Anthus, and draws the weekly quota against it. The model is in Prospectus `docs/COST_ACCOUNTING.md`. Papyrus takes part in two ways, all in infrastructure code with no manual configuration:

1. It tags every AWS resource, so Prospectus can read each day's cost from Cost Explorer.
2. It reports the model tokens each site uses to that site's own Prospectus usage queue.

Board: PPY-25e0d7 (Prospectus kanbus-1f0c86). Specs: `infra/amplify-app-shell/features/cost-tags.feature` and `features_backend/cost-accounting-reports.feature`.

## Tags

Every costed resource carries four tags from the vendored Prospectus package `@anthus/cost-accounting` (`vendor/README.md`):

| Stack | `anthus:account` | `anthus:deployment` | Where |
| --- | --- | --- | --- |
| Site backend (Amplify Gen 2, every nested stack) | `owner` | site ID | `amplify/cost-attribution.ts`, applied in `amplify/site-backend.ts` |
| App shell, private chat | `owner` | site ID | `infra/amplify-app-shell/lib/cost-attribution.ts` |
| Knowledge run | `owner` | site ID (its publication) | `infra/scheduled-jobs/lib/knowledge-pipeline.ts` |
| Edge distributions, site newsletter sending | `owner` | `CostDeployment` / `SiteId` parameter | `infra/edge/*.yaml`, `infra/newsletter/` |
| Monitoring, procedure runner, email submissions, projection lease, GitHub OIDC provider, operator newsletter sending | `shared` | none | the templates and stacks themselves |

`anthus:app` is always `papyrus`, and `anthus:cost-key` is `<account>/papyrus/<deployment>`.

- **`owner`:** Prospectus charges whichever Account holds the active `papyrus-<site>` entitlement. When no Account holds it, the cost is overhead; Prospectus never guesses (Ryan, 2026-11-09). Papyrus configures no Account ID anywhere, and a change of owner needs no redeploy.
- **`shared`:** the resource serves every site, and Prospectus splits its cost by the usage the sites report.

The site backend learns its site ID from the Amplify branch variable `PAPYRUS_SITE_ID`, which the app-shell stack sets. A backend build without it fails rather than synthesizing untagged resources. For a sandbox, export it. The Anth.us edge templates are left unchanged.

**IAM roles** carry the tags too (`PAPYRUS_TAGGED_RESOURCE_TYPES` in `amplify/cost-attribution.ts`). A site's usage queue accepts any role in the account tagged `anthus:app=papyrus` and `anthus:deployment=<site>` (AnthusAI/Prospectus#150), so every role in a site's stacks may send to that site's queue. The `infra/pipeline` deploy roles are left out: they change only through their own approval flow and never send usage.

**CI:** `scripts/test-cost-tags.ts` synthesizes every CDK stack and reads every template under `infra/`, then runs the package's `assertCostTags`. An untagged costed resource fails the build, naming the resource. It also catches costed resources that CDK writes without tag support (the bucket auto-delete provider Lambda); `amplify/cost-attribution.ts` tags those directly.

**Activation:** Prospectus activates the tag keys as cost allocation tags in the management account once tagged resources have been billed. Until a stack is redeployed with the tags, its cost shows as untagged overhead.

## Usage

The functions that call models report token counts, never dollars, through `src/papyrus_cost_usage`. It is the Python twin of the package's TypeScript sender: the same message (version 1), the same per-product queue, the same validation. It tallies in memory, sends one message per Account, deployment and UTC day, and retries a failed send with the same operation ID.

| Function | Kind reported | Recorded in |
| --- | --- | --- |
| editorial-checks | `jev.tokens` (Humanus `usage.classifierInputTokens` from each check) | `src/papyrus_content/editorial_checks.py` (`Services.checked`) |
| knowledge-query | `openai.tokens.input` (embedding `usage.prompt_tokens`) | `src/papyrus_knowledge_query/services.py`, `vector_index.py` |

Each handler flushes before the invocation returns.

**Which Account is charged.** These functions are AppSync resolvers that the browser calls directly, so they never hold a verified customer Account. They report account `"owner"`, and Prospectus charges the one Account holding the active `papyrus-<site>` entitlement. With no such Account, or several, the message is refused into the dead-letter queue and an alarm fires.

- A runtime that does hold a verified Account passes its UUID: `SiteUsage.record(items, account_id=...)`. The Next.js server has one after Prospectus authorize; it makes no model calls today.
- Never pass an Account ID the browser supplied.

`amplify/cost-attribution.ts` (`wireSiteUsageSender`) sets each function's `PROSPECTUS_USAGE_QUEUE_URL` to `prospectus-usage-papyrus-<site>`, in the stack's own account (papyrus-production hosts Prospectus), and grants its role `sqs:SendMessage` on that one queue. The queue's own policy in Prospectus allows only the roles registered for the site in Prospectus `accounts/papyrus-sites.json`, so each function's role must be registered there before its sends are accepted. Prospectus creates no queue for a `public-reader` site.

A dedicated site sends as product `papyrus-<site>`. The shared multi-tenant tier will send to one `papyrus` queue (Prospectus kanbus-f45f7f). `site_usage_product` in `papyrus_cost_usage` is the seam for that, and it is not built.

Not reported yet:
- the console chat responder (Rust; there is no Rust sender);
- the reader-steering moderation call;
- the knowledge run and procedure runner containers (model tokens and container time);
- editorial calls made from the operator CLI on a workstation.
