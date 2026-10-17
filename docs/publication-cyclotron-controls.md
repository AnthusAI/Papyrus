# Publication-bound Cyclotron controls

`components/publication-cyclotron-panel.tsx` is the same data-only operator view
for embedded deployment-owned state and a shared remote lab. It uses the actual
Cyclotron `ReviewControl` and `CyclotronStatusView`; there is no synthetic model,
mode-specific UI fork, network client or automatic production activation inside
this component. The host chooses its authenticated transport and persistence
owner. Add this panel to the existing newsroom surface through the UI/release
owner; this branch intentionally does not edit that owner's routes or shell.

## Host props and transport

Pass `mode: 'embedded' | 'remote'`, matching `status` and `history` responses from
`cyclotron-publication/v1`, and optionally:

- `onReview(payload)`: await the verified backend acknowledgement, then refresh
  status/history. The shared control requires an explicit label and explanation.
  Payloads preserve prediction version/fingerprint, binding revision and a stable
  retry identity. Same unchanged review drafts reuse the same request ID after an
  error; a correction has new explicit content and identity. Do not blindly retry
  paid or uncertain engine operations.
- `onSteer(classifier)`: open the application's authorized, output-scoped steering
  interface. Leave absent until supported. Do not wire the existing global SDK
  review-rate override as a publication-specific change: that would affect sibling
  outputs. No new steering engine is supplied in this slice.

`lib/publication-cyclotron.ts` exports the response/payload types,
`publicationReviewPayload`, scope validation and `createPublicationClient`.
The latter accepts the host's `(operation, payload) => response` function; use an
existing authenticated same-origin BFF. It verifies the response's publication
and contract version and has no automatic retry. A `PublicationLab` and either
`EmbeddedPublicationClient` or `HTTPPublicationClient` on the Python side execute
the same command contract. Never accept actor/account claims from browser JSON;
those come from the host's verified authority. See Cyclotron
`docs/publication-deployment-contract.md` for API fields and limitations.

Snapshot output definitions and classifier identity must agree. Mismatched
publication/binding snapshots or out-of-scope classifier data fail before render.
Review controls use output-specific DOM IDs but always send the original common
item identity to the backend. Recorded reviews remain visible with their actual
explanation and an explicit correction action. Source URI and prediction/binding
versions are inspectable; source text is escaped React content.

Human review requires a configured label; its explanation is optional.
The panel uses the shared `ReviewControl` default optional-explanation behavior. Consume
its matching Cyclotron source/package checkpoint; the old public `ui-v0.2.1` pin
must not be assumed to provide the new contract. This worktree tests against the
local core source pack only. Package/source-pin updates and live route activation
are coordinated with the release owner, not performed by editing another tree.

## Evidence and dependencies

`node --import tsx scripts/test-publication-cyclotron-ui.ts` renders the actual
shared components for both mode labels and verifies optional explanations and required labels,
publication scope, prediction pins, and unchanged payload identity on manual
retry. These are SSR/payload contract checks, not a browser interaction or live
classification claim. The core's ReviewControl test verifies required explanation
blocks submit until nonblank, with optional behavior preserved by default.

`publication_modes_test.py` sends the existing Papyrus research-paper/web curation
candidate into actual deterministic Cyclotron execution through both direct
embedded and in-process HTTP boundaries. Existing curation orchestration runs;
source/provider/tokenizer boundaries are synthetic and outbound sockets are
forbidden. This test does not install a synthetic production classifier.

The source curation/optional priming implementation is unchanged. Publication
acceptance does not implicitly label sibling publications. Cloud storage/runtime,
service-role authorization, output-scoped steering, immutable historical source
revision integration and production deployment composition remain dependencies.
No persistent EC2 SQLite service, cloud resource, IAM/OAuth expansion, secret
transmission or paid provider test is added.

## Frozen context and scoped steering follow-on

History rows may carry `context`, `historicalContext`, `provenanceUnavailable` and
`feedbackReconciliationRequired`. The panel inspects immutable source/binding
references and sends `contextId` with current reviews. Older source/binding views
are read-only. A canonical SDK change outside the composed provenance path is
identified for reconciliation; a historical label is not represented as current
truth. Output/context-specific DOM IDs prevent shared-item controls from sharing
textarea IDs. Original item IDs still go to the backend.

`publicationSteeringPayload(status, classifier, bindingRef, command)` builds an
explicit incumbent-pinned native command. Command is either
`{action:'evaluate', proposal, requestId, explanation}` or
`{action:'promote', trialFingerprint, requestId, explanation}`. The typed client
exposes `.steer(payload)` and `.replayRecords()`; the latter only exports verified
source/binding/prediction/feedback records and does not execute learning.

`onSteer(classifier)` now opens the host's proposal workflow through a distinct
**Evaluate classifier proposal** button. It does not misuse the monitoring card's
**Change review rate** control. Native evaluation/promotion is implemented in
Cyclotron's injected single-owner gateway; the host still owns the reviewed
proposal UI, transport, writer lock and execution authorization. No production
callback/route or global review-rate mutation is automatically wired here.

The backend refuses superseded-source reviews, changed source values for existing
labeled targets and unsafe historical-output reassignment until the appropriate
runtime/storage migration is supported. It never rewrites classification inputs
to fabricate historical parity. Consume the matching follow-on Cyclotron source
checkpoint and its `docs/publication-deployment-contract.md`; coordinator/auth and
cloud activation dependencies remain separate.

### Account selection and guarded BFF composition

All publication envelopes now require host-derived `accountId`. Construct the
TypeScript client with `createPublicationClient(scope, request, currentScope)`;
`scope` pins `{accountId, publicationId, bindingRevision}`, and `currentScope()`
returns the currently selected scope or null after sign-out. The client copies and
freezes its pins, checks selection before dispatch and after response, and refuses
mismatched response accounts/bindings. `request(operation, payload, pinnedScope)`
must forward the expected account to the same-origin BFF; the BFF must verify it
against trusted selection. No automatic mutation retry or cache is introduced.
Use `client.cacheKey` / `publicationScopeKey(scope)` for query caches; the key
encodes the complete tuple without delimiter collisions.

`PublicationCyclotronPanel` remounts its internal review drafts, retry identities,
messages and busy state on that same key. Status/history and frozen contexts must
agree on account. The host must replace snapshots as a pair when selection changes
and must stop rendering the old panel while loading the new scope.

The Python `papyrus_content.publication_bff.PublicationBFF` is a real composition
resolver for Cyclotron's `create_publication_host`. The deployment injects
`resolve_selection(connection)` returning a server-verified `PublicationSelection`
and `resolve_access(connection, publication, capability)` returning
`PublicationAccess` only after fresh account AND explicit publication checks.
Do not infer publication review/steer grants from console roles. The resolver
checks pinned account/person/binding and execution-owner identity again inside the
core's public `execution_guard`, after ownership acquisition. It owns no auth or
storage database and creates no credentials or service endpoint.

This composition requires core execution-owner revision
`0b903779222fdab842caa077fd8bc645e96e23e4` plus the publication integration changes.
It uses public native guard keywords for decide/review and `engine.execution(...)`
for synchronous reads, steering and post-core provenance settlement. It never nests
an async lock-owning engine method inside that scope. Post-core authorization loss
can leave a completed native result without its provenance receipt; this returns
`reconciliation_required`, not success or a claim that the native result rolled
back. No cross-store transaction or distributed cloud authority is claimed.

Focused verification: shared-control SSR/client tests and lint; Python
`scripts/verify_publication_execution_contract.py <owner-core> <papyrus-checkout>`
in the integration Cyclotron checkout runs actual SDK/ASGI tests against the pinned
owner engine without copying source or editing its checkout. Deployment still
requires release-owner route/session/grant composition and the chosen supported
storage authority. These modules do not activate production Papyrus.
