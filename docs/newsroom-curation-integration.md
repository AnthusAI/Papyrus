# Optional References curation integration

PPY-58f107 adds an opt-in References seam. `NewsroomCurationProvider` supplies one
account/publication/binding-pinned controller to the existing References view.
Without the provider the released CMS performs no new curation reads. This branch
does not activate a hosted service or alter the released site configuration.

## Trusted host composition

`papyrus_content.curation_host.create_curation_host(resolve_context)` accepts a
host resolver returning `CurationContext`. Resolve the original verified session,
selected account, explicit publication grants, current binding and selected lab
on the server. `authorize(capability)` must freshly return that same complete
`PublicationSelection` (including person), or refuse. Never derive authority from
browser scope headers or infer publication grants from a console role.

The context endpoint returns browser-safe bootstrap data. POSTs require JSON,
same-origin requests and three expected pins: `X-Cyclotron-Account`,
`X-Papyrus-Publication`, `X-Papyrus-Binding`. These are expectations, not identity.
Requests are bounded to 4 MB. Responses are not cached. Only the limited priming
schema is exposed; the core's unrelated administrative GraphQL API is absent.

For embedded publication commands, use `EmbeddedPublicationTransport` with the
existing `PublicationBFF`; its fresh guard reaches `lab.command` after owner lock
acquisition. The legacy direct embedded client does not provide this guarantee.
For remote commands use a configured server-to-server HTTP client to the guarded
publication host. No browser-selected remote endpoint is accepted.

`GuardedPrimingService` takes a service plus the selected owner's execution
factory. Its original-session guard runs after acquiring ownership. The local
review composes the actual SQLite PrimingService. **Hosted composition must inject
the account-scoped S3 authority adapter and original-session execution guard; it
must fail closed until available.** S3 text/state/coordination is canonical;
DynamoDB is a rebuildable card index. This branch creates no cloud SQLite server,
central grant, credential, enrollment, S3 resource or hosted worker.

Both browser modes use the same shared monitoring, review and priming components.
Account/binding changes invalidate pending results and remount local form state.
Operational reviews need explicit labels and explanations. Priming example acceptance needs an explicit label; its classification explanation is optional. Steering
needs an explicit evaluation before a separate promotion; retries retain request
identity when content is unchanged. There is no automatic mutation retry.

Corrections to extracted content are operator-supplied title and abstract/summary.
The note is saved separately; it does not automatically rerun extraction or a
model. Priming classification rationale is separate and optional. Revised previews need
labels again. Accepted examples cannot use the draft correction route.

## One entry point: Add a reference

References has a single "Add a reference" area. "Paste a URL" is the live URL form
and works as before. "Import a file" is the shared Cyclotron panel and renders only
when a curation session supplies example support and the person may review
(`useReferenceImport` in `components/reference-curation-controls.tsx`); with no
provider, only "Paste a URL" renders. Editor-facing copy describes adding
references, never the engine behind it. Leaving an import preview (cancel or
reject) saves nothing; `features_backend/newsroom_curation.feature` covers that
and the full preview details and source provenance for a web page.

## Reproducible local review and dependency boundary

The local review is `scripts/curation-review/serve.py`, temporary loopback only.
Its fixture identity/grants, source extraction, provider and evaluation result are
explicitly synthetic. Native Cyclotron classification/ownership, catalog and
priming persistence, Papyrus preparation orchestration, HTTP/BFF serialization,
review provenance and shared controls execute. Remote mode uses an in-process
ASGI HTTP peer against disposable local stores; it is **not hosted S3 proof**.
Only `https://example.invalid/` inputs are accepted, before any fetch. Real
sources, paid models, cloud identity and production writes are disconnected.

Pinned local composition:

- Papyrus imported runtime: `95bd70a4d18c546d62b81fe0653a51c8599d83c8`.
- Core execution/storage: `c677adc6a9d4db3747ae1a26338e45553ff2ae19`.
- Publication modules/shared UI overlay: `9911b4e8640e20b86ceab82bd830d98b403786bc`.
- Optional-explanation shared UI: `0123708a3ccb52e89bac5821a383b2643e530dcb`.
- UI archive SHA-256: `403e8d24d2e69f666159518c567f49c1484001eacf181d7f3c939a732cfcb3b7`.
- Matching storage-owner optional-explanation delta: `8f24975d77544f4db1179d8c45398ed7f0ad66cf` (only three priming files over the existing core pin).

The optional-explanation delta preserves configured labels and supplied text,
normalizes missing/null rationale to an empty string and omits invented human
feedback from frozen context. It does not change operational ReviewControl. The
full newer hosted worker checkpoint is not adopted by this local composition.

The core pin alone does not contain the publication modules/shared PrimingPanel.
`.papyrus-runs/dependencies/manifest.json` records the exact local composition.
The vetted artifact is installed only in this review checkout's node_modules.
The public package dependency/lock is deliberately unchanged: the released
`ui-v0.2.1` does not export these new controls. **Publishing/pinning the reviewed
shared dependency is a release gate; a clean public install cannot yet build this
opt-in addition.** Do not substitute an invented public package version.

With that composition, Python dependencies and Cyclotron's existing Vite tooling:

```sh
node scripts/curation-review/build.mjs /path/to/cyclotron-tooling
PYTHONPATH=src:.papyrus-runs/dependencies/core/src:/path/to/priming-deps \
  python scripts/curation-review/serve.py --port 8930 \
  --state .papyrus-runs/curation-review-state
```

The review URL is `http://127.0.0.1:8930/newsroom/references`. Each account has one
explicit synthetic operational prediction, initially zero human labels and zero
accepted examples. Run browser mutations on a **separate** temporary test state
and port 8931: `node scripts/curation-review/verify.cjs`. This retains the review
catalog for the operator. Physical iPad/Safari and hosted activation are not
verified. The foreground process is temporary; no startup service is installed.

Offline checks: owner-composed publication SDK/ASGI harness, new host and actual
flow pytest modules, shared-control and controller TS checks, isolated Vite build,
typecheck with a type-only missing-output declaration, focused ESLint and browser
screenshots. The declaration provides no runtime Amplify outputs or credentials.

## Production routes (PPY-58f107 phase A)

`app/api/newsroom/curation/{context,publication,priming}` are Node route handlers
(`lib/curation-routes.ts`) that sit between the References tab and a curation
upstream, the central Cyclotron lab. They run no Python and hold no storage. Per
request, in order: the upstream is configured (`PAPYRUS_CURATION_UPSTREAM_URL`,
https, else 503 `curation_not_configured`); Origin matches and the body is JSON
under 4 MB; the sealed Prospectus session has a selected account; Prospectus
re-authorizes that account now; the three pins match the session account and the
site publication (`PAPYRUS_CURATION_PUBLICATION_ID`, default the site brand id);
the role grants the capability (priming imports and other mutations need
`review`). The request is forwarded with the person's current access token (read
from the cookie on that call), no redirects, a 15 s timeout and an 8 MB response
cap. Before anything is returned the person is re-authorized again and the echoed
pins and publication envelope must equal the request. Any failure is a refusal or
a generic 503; the token is never returned or logged.

`components/newsroom-curation-bootstrap.tsx` mounts `NewsroomCurationProvider`
around the References view. It reads the Prospectus session, and only for a
signed-in person with a selected account asks for `context`. Everything else
leaves the provider empty, so the released CMS is unchanged.

### Site environment variables

| Variable | Meaning |
| --- | --- |
| `PAPYRUS_CURATION_UPSTREAM_URL` | Base URL of the curation upstream (the central Cyclotron lab API). It must be an **origin with no path**: `https://host`, with no trailing path, query or credentials. The routes call `/api/newsroom/curation/<route>` on it, so a path you add is discarded rather than honored. It must be `https`; `http` is accepted only for loopback (local review). |
| `PAPYRUS_CURATION_PUBLICATION_ID` | The publication id the pins must match and that the upstream sees. Optional: defaults to the site brand id. |

**Unset means off (fail closed).** With `PAPYRUS_CURATION_UPSTREAM_URL` unset,
blank, not `https` (non-loopback), or carrying credentials, every curation route
answers 503 `curation_not_configured`. The References bootstrap treats any
non-OK `context` response as no provider, so "Import a file" stays hidden and
only "Paste a URL" renders. There is no fallback upstream.

Expected value for the shared lab: `PAPYRUS_CURATION_UPSTREAM_URL=https://o01d28uizl.execute-api.us-east-1.amazonaws.com`.
This is the value to set when the site is activated; it is **not** set anywhere
yet. These are Amplify branch variables on the SSR app (set per branch, outside
this repository). `amplify.yml` copies `^PAPYRUS_CURATION_` into `.env.production`
at build time (checked by `npm run test:amplify-env-export`) so both reach the
server at runtime. Sites whose generated build spec (the app shell) or own
`amplify.yml` already exports every `^PAPYRUS_` variable need no change.

Nothing is activated by this code. Phase B needs separate approval: the upstream
(lab priming routes, S3 priming storage authority, extraction worker and provider
budget), `PAPYRUS_CURATION_UPSTREAM_URL` and `PAPYRUS_CURATION_PUBLICATION_ID` on
the site, `cms.prospectusAccountsApiStageArn` (PPY-0c5242), and the site's
Prospectus registration.
