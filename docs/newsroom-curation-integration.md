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
Reviews and example acceptance need explicit labels and explanations. Steering
needs an explicit evaluation before a separate promotion; retries retain request
identity when content is unchanged. There is no automatic mutation retry.

Corrections to extracted content are operator-supplied title and abstract/summary.
The note is saved separately; it does not automatically rerun extraction or a
model. Publication classification rationale is separate. Revised previews need
labels again. Accepted examples cannot use the draft correction route.

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
- UI archive SHA-256: `0506c9fddbc446f537226519a537e2a903e7a0458cd4e505378fe8e685afc0cb`.

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
