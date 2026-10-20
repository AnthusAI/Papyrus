# Cyclotron: relevance decisions, priming and the proof number

One page for the whole Cyclotron integration. It replaces the former
`relevance-cyclotron`, `reference-priming`, `priming-acceptance`,
`priming-proof` and `publication-cyclotron-controls` pages. The 2026-10-15
verification log lives in
[archive/priming-acceptance-evidence-2026-10.md](archive/priming-acceptance-evidence-2026-10.md).

Engine guide: [Cyclotron docs/embedding.md](https://github.com/AnthusAI/Cyclotron/blob/main/docs/embedding.md).
Plan: `project/wiki/cyclotron-integration.md`, epic PPY-b0396fee. Priming
stories: PPY-7227acea (priming), PPY-200acd (proof, under epic PPY-7a0ac8).

## Status

| Piece | Where it lives | State |
| --- | --- | --- |
| Relevance sweep (`references decide-relevance`) | `papyrus_content.relevance_sweep` | Built. Needs the optional `cyclotron` Poetry group. |
| Status strip and review-rate control in References | Newsroom References tab | Built. |
| Recording export for the Cyclotron site | `references export-relevance-recording` | Built. Ryan approves a recording before it is copied out. |
| Paste a URL, preview, label, accept (`PrimingPanel`) | `NewsroomReferencesView` `priming` prop | Built, opt-in per host. No control shows without the prop. |
| Paper path (arXiv, GROBID) | `PapyrusPrimingCuration` | Works locally. |
| Web path (Biblicus worker pin) | `PapyrusPrimingCuration` | Offline-verified. Live run needs explicit spend approval. |
| Accepted examples to first operation | `papyrus_content.priming_bootstrap`, `run_decide_relevance` | Built. Applies to a new store only. |
| Prime a running cyclotron from a pasted URL | "Prime with a URL" in References; `papyrus_content.relevance_priming`, the sweep, the engine's `add_priming_examples` | Built. Uses the sweep worker's Biblicus and OpenAI, not the hosted `PrimingService` catalog. Needs Cyclotron v0.22.0. |
| Priming catalog | `PrimingService` | Local SQLite. The hosted S3 authority adapter is not built and fails closed. |
| Proof number (agreement at N = 0 and after N labels) | `papyrus_content.priming_proof`, `/cyclotron` page | Built. Needs its first real run on Ryan's Mac. |
| Publication panel (embedded or remote) | `components/publication-cyclotron-panel.tsx` | Built. The host owns transport, routes and grants. |
| Hosted newsroom | PPY-58f107 (Prospectus accounts) | Waiting. `resolve_context`, `authorize` and the account-scoped catalog come from Prospectus. |

Nothing here activates production IAM, DNS, deployment, public sources or paid
provider calls. Real Threat Intelligence acceptance has not happened; all
offline tests use synthetic sources and model boundaries.

## 1. Relevance cyclotron

A relevance cyclotron decides, for each pending `Reference` (a candidate source
found by research dispatch, research packets, citation-led discovery or inbound
email), whether it should become a reference for this publication. Editors
review its decisions in the Newsroom References tab and it aligns to their
labels and explanations.

### Configure it

One installation is one publication and has at most one relevance cyclotron.
Add a top-level `relevanceCyclotron` block to the publication's steering config
(`corpora/<publication>-steering.yml`). Every field has a default except where
shown; the values below are placeholders.

```yaml
relevanceCyclotron:
  cyclotronId: "papyrus-relevance"
  classifierId: "relevant"
  question: "Should this candidate source become a reference for this publication?"
  labels: ["include", "exclude"]
  positiveLabel: "include"
  decisionModel:            # must be a batched decision model
    provider: "jev"
    model: "jev-1.13.0"
  optimizer:                # null: decide and record only
    provider: "openai"
    model: "gpt-6-luna"
    maxCalls: 10
  store:
    localPath: "var/cyclotrons/papyrus-relevance"
    s3Prefix: "s3://<private media bucket>/cyclotrons/papyrus-relevance/"
  maxRequestsPerSweep: 200
  reviewProgram:            # placeholders until the engine's review-rate experiments
    rates: [1.0, 0.5, 0.25, 0.1]
    auditShare: 0.05
    confidenceThreshold: 0.7
    targetAccuracy: 0.85
    maxGapPoints: 5
    window: 100
    windowsRequired: 2
    minWindowLabels: 20
```

Rules the loader enforces:

- **Batched decision model.** A cyclotron asks its classifiers in one request,
  so the decision model must implement `classify_many`. Jev's adapter does.
- **Doctrine seeds the first rubric, never the question.** The question and
  labels are the cyclotron definition, which its store refuses to change. The
  publication doctrine (mission and policies) becomes the classifier's first
  rubric when the store is created; after that the LLM optimizer owns the
  rubric. Changing the question or labels later needs the engine's definition
  versions (decision-flywheel-ade3088c).
- **No keys in configuration.** Provider keys come from the environment (for
  example `TYPESAFE_API_KEY` for Jev and `OPENAI_API_KEY` for the optimizer) or
  SSM on a worker. A field whose name looks like a key, token, secret, password
  or credential is refused.
- **Snapshots stay private.** The store snapshot holds item values,
  explanations and transcripts; `store.s3Prefix` must point at the private
  media bucket.

### Install the engine

The engine is the optional `cyclotron` Poetry dependency group, pinned to one
Cyclotron main commit (9874b71). It is a group and not an extra so the git
requirement stays out of the published wheel. The default install and CI do not
include it; the Cyclotron scenarios are tagged `@requires-cyclotron` and are
skipped when `decision_flywheel` is not importable.

```bash
poetry install --extras "newsroom" --with cyclotron
poetry run behave features_backend --tags=@requires-cyclotron
```

### Run the sweep

```bash
poetry run papyrus references decide-relevance            # dry run: lists pending references, no model call
poetry run papyrus references decide-relevance --apply    # decide, send reviews, record status, save the store
```

Run it after research intake (`assignments research-intake-now --apply`) and on
a schedule. Each run:

1. Claims the `cyclotron.relevance` Assignment for this cyclotron; a second
   worker stops before any model call while the claim is held.
2. Restores the cyclotron store from `store.s3Prefix` when this worker has no
   local copy.
3. Applies editors' priming requests (see "Prime it with a URL"), then sends editors' reviews of decided references to the cyclotron. The label
   follows the existing scope-training rule: accepted is `include`; rejected as
   `out_of_scope` or `policy_exclusion` is `exclude`; other outcomes close the
   decision without a label. The editor's note is the explanation and the
   curation Message id is the review id, so a rerun records nothing twice.
4. Decides every current pending reference of the canonical corpus and records
   each new decision as a `relevance_decision_is` relation. An unchanged
   reference keeps its decision without a model call.
5. Records the `cyclotron-status/v1` snapshot
   (`knowledge-raw-payload-cyclotron-status-<cyclotronId>`), saves the store
   snapshot to the private bucket, and releases the claim.

The sweep never accepts, rejects or archives a reference. A reference an editor
reopens to pending is decided again only when a new version is promoted.

### What editors see

The References tab shows the cyclotron's status strip above the list (version,
agreement, calibration as "says N%, right M%", the review rate and its state),
read from the status snapshot the sweep records. "What the cyclotron is doing"
opens the detail card: recall, precision and accuracy with plain explanations,
the review rate's reason and next step, and the last change.

Editors who may change curation can set a manual review rate for confident
decisions (0% to 100%, for 1 to 30 days) or clear it. The Newsroom records the
request as a `KnowledgeRawPayload`
(`knowledge-raw-payload-cyclotron-review-rate-request-<cyclotronId>`); the next
sweep applies it once, and the status then shows who set it and when it expires.
Low-confidence decisions and the random audit share are always reviewed.

### Prime it with a URL

Above the status strip, editors who may change curation see "Prime with a
URL": an https URL, a label (the cyclotron's own labels, `include` and
`exclude` by default) and an optional explanation. Saving writes one
`KnowledgeRawPayload` per request
(`knowledge-raw-payload-cyclotron-priming-request-<cyclotronId>-<requestId>`,
kind `cyclotron-priming-request`, JSON in a `raw_payload` attachment), the same
channel as the manual review rate. There is no new store, Lambda or schema.

On the next sweep, after opening the store and before deciding anything, the
worker reads each request that has no outcome yet, extracts the page with the
existing `PapyrusPrimingCuration` (Biblicus, network and OpenAI, on the worker)
and calls the running cyclotron's `add_priming_examples`. The example is a
trusted, human-labeled item with id `priming:<sha256 of the URL, 16 hex>`, so it
cannot collide with a reference. The cyclotron appends it to the classifier's
example list as a new version; the sweep's own decisions then run on that
version, and the status shows `primedExamples` and the change "Added 1 primed
example to the example list."

The worker records the outcome as a `priming_outcome` attachment on the request:
`applied` with the version, or `failed` with a readable reason (an https-only
URL, a label the cyclotron does not have, a page that could not be read, or the
engine refusing a URL already primed with different content or already decided).
A request with an outcome is never processed again, and a failed request never
stops the sweep. The References tab lists the saved requests as waiting for the
next sweep, applied as version N, or failed with the reason.

The Newsroom does not read the steering config. Until a decision names the
cyclotron it assumes the defaults (`papyrus-relevance`, `include`/`exclude`), so
a publication that renames them must have decided at least once for the form to
use its names.

### Record a run for the Cyclotron site

```bash
poetry run papyrus references export-relevance-recording --output papyrus-relevance-run.json \
  --optimizer-price 0.40,0.10,1.60 --optimizer-price-source "<provider's published price page>, read <date>"
```

The export restores the latest store snapshot from the private bucket (or reads
`--store <dir>`), makes no model call and writes nothing to Papyrus. It follows
the Cyclotron editorial-run fixture's schema 2 with `source: "papyrus-live"`:
one cycle per decision in order (the source's title and public URL, the decision
shown before the review, the editor's label and reason code, the review
program's reason and propensity, and the cyclotron's changes), windows of 100
decisions with metrics on reviewed decisions, routing, and measured usage and
cost, and `usage_total` with the price basis.

- **Consent.** An editor's explanation is included only when the editor ticked
  "My explanation may be quoted publicly" on that review. `--no-explanations`
  leaves every explanation out. Reviewer names never appear.
- **Prices.** Jev is priced at TypeSafe's published list price. Any optimizer
  calls need `--optimizer-price IN,CACHED,OUT` (USD per million tokens) and
  `--optimizer-price-source`; the export refuses to guess.
- **Approval.** Ryan approves a recording before it is copied into
  Cyclotron-web.

## 2. Priming: examples before the first operation

Priming is optional. An editor pastes a source URL, reviews what Papyrus
extracted, labels it (an explanation is optional) and accepts. The accepted
examples can seed a new Cyclotron as initial context. They are not operational
decisions or evaluation results.

### Acceptance flow

The reviewable flow uses the shared `PrimingPanel` and the existing Papyrus
research and web curation paths:

1. Choose a representative source: research-paper extraction or web extraction
   plus the existing metadata and summary generator. The configured transformer
   owns source access and provider budgets.
2. Review the complete candidate item and the exact values supplied to the
   model. Reject or revise extraction with transformation feedback; that
   feedback is not a classification rationale. Nothing is imported yet.
3. Choose every configured label; its explanation is optional. Accept
   explicitly. The local transaction saves the item and labels together.
   Cancellation and invalid or stale drafts cannot be accepted, and retrying
   acceptance is idempotent. `onAccepted(draft)` hands the acknowledged list and
   classifier revision pins to the host; it does not start a Cyclotron.
4. When deliberately creating a new Cyclotron, capture the accepted list:

   ```python
   from papyrus_content.priming_bootstrap import AcceptedPrimingSnapshot

   selected = AcceptedPrimingSnapshot.capture(
       priming_service,
       list_id=accepted_draft["contract"]["list_id"],
       classifiers=[{"id": row["id"], "revision": row["revision"]}
                    for row in accepted_draft["contract"]["classifiers"]],
       definition=relevance_plan.definition,
   )
   ```

5. Pass `priming_snapshot=selected` to `run_decide_relevance(...)`, or pass
   `selected.for_definition(definition)` to the native
   `Cyclotron.open(..., priming_examples=...)`. Labels, question and input
   fields must match the destination definition; there is no implicit
   translation.
6. The first operational decision sees the captured examples and rationales as
   training context; blank explanations add none. Priming identities must be
   disjoint from pending reference identities, and the sweep checks overlap
   before claims or writes. Priming creates no operational predictions, review
   counts, development set or held-out score.

Omit `priming_snapshot` for normal operation. An empty or unaccepted selected
list fails visibly, but priming is never required to start operation. It does
not apply to an already-created production relevance store.

Structured CSV, JSON, JSONL and XLSX imports use the same preview and
acceptance transaction. CSV and XLSX templates are empty and derive fields and
label choices from the configured schema and classifier revisions; they contain
no invented content or judgments.

### Curation service

`papyrus_content.priming_curation` runs in the customer's external transformer
service. It uses the catalog registration planner and
`build_reference_url_text_attachment_plans` without applying records. The
research path returns an extracted source title and abstract. The web path also
calls `reference_generate_metadata_from_extracted_text(..., apply=False)` to
produce a title and summary, accepting explicit in-memory metadata so an
unregistered preview needs no GraphQL metadata lookup. No new scraper, article
filter, scholarly parser or summarizer exists; missing extraction or metadata
fails visibly, and a missing title or abstract asks for clarification.

`papyrus_content.priming_http` is a local or customer-hosted reference service
for the language-neutral `cyclotron-transform/v1` contract. The host supplies
its authorization function and owns TLS, source and network permissions,
tool and provider budgets, and one service owner per SQLite working store.
Request identities are retry-safe, cancellation is terminal and late results are
discarded. Raw source artifacts and registration plans stay in private working
state; public job responses carry only status, clarification fields or the
complete candidate projection. The service performs no Papyrus registration,
curation, GraphQL or S3 writes.

Final acceptance is Cyclotron's local atomic item-plus-label operation over the
host's authenticated application transport.

### Provider budget (inactive until a host grants it)

`PrimingProviderBudget` is an optional trusted-host dependency of
`CurationJobs`. A host grant binds one exact job and HTTPS URL to unique
approval evidence for one hour; HTTP cannot create grants. Workers get an
ephemeral loopback gateway capability, never the real provider key, and the
scoped subprocess environment strips provider and AWS credentials and forbids
the `uv` fallback. The gateway pins the Responses endpoint and model, rejects
tools, non-text input, pricing overrides and oversized requests, sets
`store=false`, and disables transport retries and redirects. SQLite reserves
each request's full cost before dispatch; duplicates, grant resets,
cancellation, expiry and the eighth call fail closed.

The proposed live web run ceiling is $0.50 total and at most 7 requests on the
pinned `gpt-5.4-mini-2026-03-17`; the arXiv paper path costs $0 and makes no
model request. No paid request or live grant exists. Spend needs Ryan's explicit
authorization.

### Local setup and previews

- Biblicus: the web worker commands come from the released `biblicus` package
  installed by the Poetry newsroom extra (`BiblicusRunner` runs its console script;
  `BIBLICUS_WORKDIR` names the directory holding the corpora). See [newsroom-worker-bootstrap.md](newsroom-worker-bootstrap.md)
  for cloud corpus workers.
- GROBID for PDFs: Biblicus 1.15.0 starts GROBID itself when `BIBLICUS_GROBID_URL` is unset or points at
  localhost. `BIBLICUS_GROBID_AUTO_START` defaults to on; set it to `0` to start nothing. The auto-started
  container is named `biblicus-grobid` (`BIBLICUS_GROBID_CONTAINER_NAME`), runs
  `grobid/grobid:0.9.1-crf` (`BIBLICUS_GROBID_DOCKER_IMAGE`), binds `127.0.0.1:8070` only, restarts
  `unless-stopped`, and is limited to `BIBLICUS_GROBID_MEMORY_LIMIT` (default `5g`). An existing container
  with that name is reused as-is, whatever its image or settings, so remove or rename a stale one to pick
  up new defaults. CrossRef consolidation is off unless `BIBLICUS_GROBID_CONSOLIDATE_HEADER` or
  `BIBLICUS_GROBID_CONSOLIDATE_CITATIONS` is set to a truthy value (`1`, `true`, `yes`, `on`).
- Human-input page (temporary loopback process, never a persistent service):

  ```sh
  node scripts/priming-preview/build.mjs /path/to/cyclotron --human
  PYTHONPATH=src:/path/to/cyclotron/src python scripts/priming-preview/serve-human.py
  ```

  It serves `http://127.0.0.1:8901/priming` with an initially empty
  `.papyrus-runs/human-priming/examples.sqlite3`. Enter only a URL; type is
  inferred from extraction metadata. Only arXiv paper URLs are enabled until the
  web worker pin is configured.
- Synthetic preview (refuses real URLs, makes no paid or cloud calls):

  ```sh
  PYTHONPATH=src:/path/to/Cyclotron/src python scripts/priming-preview/serve.py
  ```

  Open `http://127.0.0.1:8798/papyrus-preview`. Browser verification:
  `node scripts/priming-preview/verify.cjs` (set `PAPYRUS_BROWSER_EXECUTABLE`).
  `verify-human.cjs` targets a disposable server and catalog and must never run
  against the human workspace.
- Read-only bootstrap verifier for an existing examples catalog:
  `scripts/priming-preview/verify-bootstrap.py --database <examples.sqlite3> --list-id <id> --classifiers '[...]'`.
- Opt-in real worker suite: `procedures/newsroom/tests/test_priming_biblicus_contract.py`
  with `BIBLICUS_CONTRACT_CHECKOUT` and `BIBLICUS_CONTRACT_PYTHON`; it skips
  without both paths.

The pinned public Cyclotron `ui-v0.2.1` artifact does not expose the new panel.
Do not deploy this Papyrus change with that old UI artifact; updating the
source pin follows publication approval.

## 3. The proof number

"The classifier uses the editor's labels" is a claim until there is a number.

**Agreement with editors on a fixed held-out set, at N = 0 and after N priming
labels.** Agreement is the share of held-out sources where the relevance
classifier gives the same label the editor gave. Precision and recall of the
positive label (`include`, shown to editors as publish) are reported beside it.

- **Held-out set.** References that editors already reviewed, labeled by the
  scope-training rule (accepted is `include`; rejected as out of scope or a
  policy exclusion is `exclude`; anything else is left out). Balanced, half per
  label, so an always-one-answer classifier scores 50%. Selection is
  deterministic: ranked by `sha256(proofId, lineageId)`. The set is frozen once
  per proof id, carries a fingerprint over its items and labels, and is never
  regenerated; a new set needs a new proof id. Default size 40, at least 5 per
  label. Held-out items use the operational projection without the editor's
  review note, which would give the label away.
- **Labels (N).** `--teach-from` picks the source. `reviews` is the teaching
  pool frozen with the held-out set (every other labeled review, in review
  order, with the editor's note as explanation). `catalog` is the accepted
  priming examples in acceptance order. `both` uses reviews first, then the
  catalog. The catalog classifier must match `relevanceCyclotron` exactly (id,
  question, include/exclude labels). An example whose item id or source URL is in
  the held-out set is dropped and counted (`excludedBecauseInHeldOut`).
- **Conditions held fixed.** Every point opens a fresh Cyclotron store with only
  the first N examples as priming context, the configured decision model, the
  publication doctrine as the only rubric, no LLM optimizer and no review
  program. Only N changes between points.
- **Schedule.** N = 0, 5, 10, 20, 40 by default, capped at the number of usable
  examples. N = 0 is always included.

The report (`cyclotron-priming-proof/v1`) holds aggregate numbers, counts,
fingerprints, the decision model identity and dates. It holds no item text,
explanations or reviewer names.

### Produce it

The run calls the decision model, so it runs where the provider key is (Ryan's
Mac, by Remote Control), never from a cloud agent session.

```bash
# Once per proof id. Reads reviewed References; no model call; writes nothing to Papyrus.
poetry run papyrus references freeze-priming-held-out --proof-id ti-2026-10 \
  --output .papyrus-runs/proofs/ti-2026-10.held-out.json --size 40

# One decision-model call per held-out source per point.
poetry run papyrus references prove-priming --held-out .papyrus-runs/proofs/ti-2026-10.held-out.json \
  --teach-from reviews --output .papyrus-runs/proofs/ti-2026-10.reviews.report.json

# With pasted examples too (--teach-from catalog for pasted examples alone).
poetry run papyrus references prove-priming --held-out .papyrus-runs/proofs/ti-2026-10.held-out.json \
  --teach-from both --catalog <priming examples.sqlite3> --list-id <list id> \
  --classifiers '[{"id":"relevant","revision":1}]' \
  --output .papyrus-runs/proofs/ti-2026-10.report.json
```

Keep the held-out file private: it holds source titles, URLs and editor notes.
Cost is `held-out size x number of points` decision calls (200 for the defaults).

### When there are too few labels for a held-out set

A publication with a few dozen reviews (Threat Intelligence has 23) cannot spare
40 for a fixed held-out set. Use stratified cross-validation instead: every
labeled review is held out exactly once, taught only by reviews outside its own
fold, and the folds are pooled at each N.

```bash
poetry run papyrus references freeze-priming-cross-validation --proof-id ti-2026-10-cv \
  --output .papyrus-runs/proofs/ti-2026-10-cv.folds.json --folds 5

# One decision-model call per labeled review per point (23 x 4 = 92 for the defaults).
poetry run papyrus references prove-priming-cross-validated \
  --folds-file .papyrus-runs/proofs/ti-2026-10-cv.folds.json --schedule 0,5,10 \
  --output .papyrus-runs/proofs/ti-2026-10-cv.report.json
```

The schedule always also includes N = 0 and the largest N every fold can supply.
The classes are unbalanced, so the page shows precision and recall beside
agreement and states the design instead of claiming a 50% chance level.

### Where visitors see it

The publication's `/cyclotron` page shows the headline ("agreement went from X%
with no labels to Y% after N labels"), the before-and-after table and the
method. `/api/cyclotron/priming-proof` serves the same report as JSON. Until a
report is approved the page says no approved run has been published and still
explains the method.

A report becomes public only by a reviewed commit. Ryan approves a report, then
`npm run approve:priming-proof -- <site brand id> <report.json>` validates it,
saves it as `lib/approved-priming-proofs/<site brand id>.json` and regenerates
`lib/approved-priming-proof-reports.ts`. Brands whose newsroom owns the site root rewrite `/cyclotron` into the
newsroom; for those, link the API route.

## 4. Publication panel (embedded or remote)

`components/publication-cyclotron-panel.tsx` is the data-only operator view for
embedded deployment-owned state and a shared remote lab. It uses Cyclotron's
`ReviewControl` and `CyclotronStatusView`; it has no network client, mode fork
or automatic production activation. The host chooses its authenticated transport
and persistence owner and adds the panel to the newsroom surface through the
UI/release owner.

Pass `mode: 'embedded' | 'remote'`, matching `status` and `history` responses
from `cyclotron-publication/v1`, and optionally:

- `onReview(payload)`: await the verified backend acknowledgement, then refresh
  status and history. The shared control requires an explicit label; the
  explanation is optional. Payloads preserve prediction version and fingerprint,
  binding revision and a stable retry identity. An unchanged draft reuses its
  request ID after an error; a correction gets new content and identity. Do not
  blindly retry paid or uncertain engine operations.
- `onSteer(classifier)`: opens the host's classifier-proposal workflow through
  the **Evaluate classifier proposal** button. Leave absent until supported. Do
  not wire the global SDK review-rate override as a publication-specific change;
  it would affect sibling outputs.

`lib/publication-cyclotron.ts` exports the response and payload types,
`publicationReviewPayload`, `publicationSteeringPayload`, scope validation and
`createPublicationClient(scope, request, currentScope)`. The client accepts the
host's `(operation, payload, pinnedScope) => response` function (use an existing
authenticated same-origin BFF), pins `{accountId, publicationId, bindingRevision}`,
checks the selection before dispatch and after response, refuses mismatched
accounts or bindings, and does no automatic retry or caching. Use
`client.cacheKey` / `publicationScopeKey(scope)` for query caches. The panel
remounts its drafts, retry identities and busy state when that key changes; the
host replaces status and history as a pair on selection change. Never accept
actor or account claims from browser JSON.

History rows may carry `context`, `historicalContext`, `provenanceUnavailable`
and `feedbackReconciliationRequired`. Older source or binding views are
read-only, and a historical label is never presented as current truth. The
backend refuses superseded-source reviews, changed source values for labeled
targets and unsafe historical-output reassignment.

The Python `papyrus_content.publication_bff.PublicationBFF` composes
Cyclotron's `create_publication_host`. The deployment injects
`resolve_selection(connection)` (a server-verified `PublicationSelection`) and
`resolve_access(connection, publication, capability)` (a `PublicationAccess`
only after fresh account and explicit publication checks). Do not infer
publication review or steer grants from console roles. Post-core authorization
loss can leave a completed native result without its provenance receipt; that
returns `reconciliation_required`, never success and never a claim of rollback.
Composition requires Cyclotron execution-owner revision
`0b903779222fdab842caa077fd8bc645e96e23e4` plus the publication integration
changes. Verify with
`scripts/verify_publication_execution_contract.py <owner-core> <papyrus-checkout>`
from the integration Cyclotron checkout. See Cyclotron
`docs/publication-deployment-contract.md` for API fields and limits.

Deployment still needs the release owner's route, session and grant composition
and the chosen storage authority (PPY-58f107).

## Self-training from human decisions, in shadow mode

A cyclotron learns only from References a person explicitly accepted or
rejected. The Newsroom's curation Lambda records `actorKind: "human"` on the
curation Message only when AppSync supplied a user-pool subject claim for the
caller; request arguments cannot claim it, and IAM-signed service callers and
agents record `service`. A curation with no recorded actor kind, from before
this rule, never teaches.

Each decide-relevance sweep:

- sends the human review of every decided Reference to the cyclotron (a later
  opposite label corrects it);
- primes the cyclotron with every human-reviewed Reference it never decided,
  with the editor's note as human feedback and never inside the item;
- decides pending References. A decision is a suggestion: it never changes
  curation status. The relation records the labels and doctrine behind it
  (`provenance`: label set, doctrine fingerprint, teaching-label fingerprint and
  counts) next to the model version and fingerprint;
- records live agreement (`cyclotron-shadow-agreement/v1`, a KnowledgeRawPayload
  beside the status snapshot): suggestions compared with later human decisions,
  with precision and recall. Reviews made before the suggestion, or by anyone
  not provably human, are left out.

Controls in the steering config's `relevanceCyclotron` block: `enabled: false`
switches the publication off (the sweep decides nothing and says why), and
`maxDecisionsPerDay` caps new decisions per UTC day, on top of
`maxRequestsPerSweep`.

Which reviews reach the decision prompt: priming examples and training-role
labels do; development and audit-role labels do not. A review of a decision the
review program did not send is reviewer-selected and is always training. A
review of a decision the program sent is placed by hash: about a fifth are
protected audit evidence and about a quarter of the rest are held for
development, so they do not reach the prompt. That is deliberate, and it is why
the proof above teaches through priming, where every example reaches the prompt.

Section labels follow the same rule. A human or delegated accept can carry a
`sectionId` (an enabled `NewsroomSection`, validated when recorded and stored in
the curation Message metadata beside `actorKind`). `human_section_for_review(reference,
messages, section_ids)` in `relevance_decisions.py` returns that id only when the
latest curation is an explicit human accept carrying a section id in the given
set, and `None` otherwise. Agent or unknown actors, rejections and unrecognised
ids never produce a section label.

Historic curation has no `actorKind`. `papyrus references stamp-curation-actor-kind
--human-authors <label,label>` stamps `human` only on curation whose author label
a person names, and is a dry run (it also lists every other author label) until
`--apply`.

Not yet built: retiring a taught label when a human changes it to no label
(the engine corrects a flipped label, but cannot remove a primed example), and
gating automatic decisions on an approved fresh proof.

### The gate before any automatic decision

A cyclotron decision is only a suggestion. Nothing may change a Reference's
curation status automatically until a person has approved a fresh
cross-validated proof. `relevanceCyclotron.approvedProofPath` names the approved
report file (the one committed through `npm run approve:priming-proof`). Every
sweep stores the gate's verdict beside the live agreement as `autoDecision`:

- `allowed: false` with a `reason` when there is no approved proof, ten or more
  human labels have arrived since it was run, it is more than 30 days old, or
  its agreement at the largest label count is under 0.9.
- `allowed: true` with `scope: "reject-clear-misses"` otherwise. Accepting is
  never automatic. The sweep acts on the gate only through the opt-in auto-reject below.

`proof_is_due` gives the reason a fresh draft proof should be run (new labels or
age), for the scheduled proof that follows.

### Auto-reject of clear misses (opt in, off by default)

```yaml
relevanceCyclotron:
  autoReject:
    enabled: true                  # default false
    minimumRejectProbability: 0.95 # default 0.95
    maxRejectsPerSweep: 10         # default 10
```

With `--apply`, the sweep moves a pending Reference to rejected only when all of
these hold: `autoReject.enabled`; the gate says `allowed` with scope
`reject-clear-misses`; the decision is the negative label with probability at
least `minimumRejectProbability`; the Reference has no curation history at all
(a person who reviewed, or reopened, a Reference is never overruled); and the
sweep is under `maxRejectsPerSweep` and the daily decision cap. It never accepts.

Each rejection writes the usual `reference_curation` Message with
`actorKind: "cyclotron"`, reason code `out_of_scope`, and the cyclotron id,
probability, proof id and decision id in its metadata and reason, so the
Newsroom can show it was automatic and a person can reopen it. Because the actor
kind is not `human`, an auto-rejection is never a training label and never counts
toward the gate's human label count. The result and `--json` output list them as
`autoRejected` (`lineageId`, `probability`, `proofId`). A dry run lists what
would be rejected from decisions already recorded, and writes nothing. The Site
(Section) cyclotron stays shadow-only.

### Withdrawn labels

If a person sets a reviewed Reference back to pending, or a later curation is not
an explicit human label, the next sweep retracts the label the cyclotron learned
from it (`undo_review`, counted as `retiredLabels`). Priming examples added for
References no one decided have no retraction in the engine yet; that needs a
Cyclotron change.

Withdrawing a person's review of a Reference the cyclotron never decided now
retracts its priming example too (`retract_priming_examples`, Cyclotron PR 49).

## Site cyclotron: a classifier per Section

One shared cyclotron for the whole site (`siteCyclotron` in the steering config,
built by `papyrus_content.site_cyclotron`). Every enabled newsroom Section gets a
binary classifier (`section-fit-<id>`: does this Reference belong in that
Section?) and one multi-class `section-selector` chooses the Section. The
classifier set is derived from the Section list, so the Section curation that
Papyrus already has stays the only place Sections are maintained; each rubric is
seeded from the Section's mission, policy, assignment guidance and kill criteria.
The block holds only the cyclotron id, `enabled`, `maxDecisionsPerDay`,
`approvedProofPath` and `store`; the model, optimizer and review program come
from `relevanceCyclotron`. Training uses only the Section a person explicitly
chose (PPY-1b1788). Epic PPY-0a285b.

### The site sweep: `references decide-site-sections`

`papyrus_content.site_sweep` runs the site cyclotron the way the relevance sweep
runs the relevance cyclotron: one writer through the `cyclotron.site` Assignment
claim, the store restored from and saved to the private bucket, the same
`enabled` and `maxDecisionsPerDay` controls (a Reference counts once however
many classifiers answer) and the same `approvedProofPath` gate verdict.

```bash
poetry run papyrus references decide-site-sections            # dry run: lists pending references, no model call
poetry run papyrus references decide-site-sections --apply    # decide, teach, record agreement, save the store
```

`--sections-file` defaults to `corpora/<publication>-newsroom-sections.yml`, the
publication named by the `--config` file (`papyrus-steering.yml` gives
`papyrus-newsroom-sections.yml`).

### Per tenant

`--tenant <id>` (or `PAPYRUS_TENANT_ID`) makes the sweep and the proof per
tenant on a multi-tenant backend (see [multi-tenancy.md](multi-tenancy.md)). The
Section list is then that tenant's `NewsroomSection` rows, read through its
tenant-scoped client (`--sections-file` is ignored); the yml seed stays the
source for a single-tenant backend. The cyclotron id, local store path, S3
prefix, `cyclotron.site` Assignment and `site_decision_is` records are scoped by
appending `-<tenant>` to the configured cyclotron id, store path and prefix, so
two tenants with different Sections each have a cyclotron with only their own
classifiers and one tenant's sweep never supersedes the other's decisions. The
steering config, including the decision model and `approvedProofPath`, is
shared. A tenant with no Sections is refused with the command that seeds them:
`papyrus newsroom import-sections --tenant <id>`.

- One `decide` per pending Reference answers every classifier. Each answer is
  its own current `SemanticRelation` with predicate `site_decision_is` and
  `classifierId` `<cyclotronId>/<classifier>`, carrying the decision id, label,
  probabilities, version, fingerprint and provenance, and superseding that
  Reference's previous current relation for the same classifier. Every one is a
  suggestion; curation status is never changed.
- A delegated accept comes from a delegation a person approved: the agent requests it with `papyrus references request-delegation`, keeps the secret in a private file, and a person approves the short code in the Newsroom (see "Getting a delegation without pasting a secret" in `docs/story-reporting.md`). A pending, denied or unapproved delegation is refused.
- Teaching comes only from an explicit human or delegated accept that names a
  Section (`human_section_for_review`). For a Reference placed in Section S the
  selector learns S, `section-fit-S` learns `fits`, and every other
  `section-fit-*` learns `does-not-fit`. This assumes a Reference belongs to a
  single Section. Agents, unknown actors, rejections and accepts without a
  Section never teach. A Reference the cyclotron never decided teaches as a
  priming example for each classifier; a decided one teaches through one
  checklist review, with the curation Message id as the review id, so a repeat
  sweep changes nothing.
- The `cyclotron-shadow-agreement/v1` payload for the site cyclotron holds, per
  classifier under `classifiers`, the agreement metrics of suggestions against
  later explicit human Section decisions (selector: comparisons, correct,
  accuracy; fit classifiers: agreement, precision, recall, confusion), the
  overall `selectorAccuracy`, and the same `autoDecision` and `loop` entries as
  the relevance payload. A decision made after the human's review does not count.
- The classifier set follows the Section list (PPY-f579a2,
  `papyrus_content.site_classifier_set`). Before each sweep the stored
  cyclotron's active classifiers are compared with the ones the enabled Sections
  call for. A new Section gets a classifier (added through the engine's
  `add_classifiers`); a removed or disabled Section has its classifier retired
  (`retire_classifiers`), keeping its labels and history, and enabling it again
  brings it back with them. The dry run lists what would change under
  `classifierSet` and in warnings, and changes nothing. A classifier's labels can
  never change, so the selector's id names its Section set
  (`section-selector-<hash>`): when the set of Sections changes, the old selector
  is retired and a new one added. A fit classifier's question names the Section id
  and not its title, so renaming a Section never conflicts with the stored
  classifier. Each change is recorded in the store with who and when.
- A newly added classifier cannot review decisions made before it existed, so it
  learns from the Section choices people made earlier as priming examples, and
  from every decision made after it was added. Changing the set changes the
  shared decision request, so decisions nobody has reviewed yet are decided again
  and the other classifiers' ML heads refit on the next decision; their labels and
  rubrics are untouched. Withdrawn Section labels are not yet retracted.

### The Section proof: `references prove-site-sections`

`papyrus_content.section_proof` measures how often the site cyclotron's
classifiers agree with held-out human Section choices, the way the relevance
proof does for relevance. Labels come only from explicit human Section choices
(the same ones the sweep teaches from). Each classifier is cross-validated on its
own: every human-placed Reference is held out once, taught only by the placements
outside its own fold, and decided with and without that teaching, using the
relevance proof's folds, runner and agreement metrics. The selector reports
accuracy and per-Section recall; each Section's fit classifier reports
precision, recall and F1.

```bash
poetry run papyrus references prove-site-sections --proof-id sections-1                          # dry run: label counts, what is provable, no model call
poetry run papyrus references prove-site-sections --proof-id sections-1 --apply --output report.json
```

- The report schema is `cyclotron-section-proof/v1`: per-classifier results, label
  counts, and the caveats stated plainly. It holds aggregate numbers only.
- A classifier with too few labels is `not-yet-provable` with the reason and no
  number: a fit classifier needs at least 2 positive and 2 negative examples, the
  selector at least 10 human-placed References (and two enabled Sections), and a
  Section's recall is shown only with at least 2 placements.
- The fit classifiers' negatives are inferred from the single-Section assumption,
  and every number is agreement with editors, not independent truth. Each
  classifier lists its own sample-size caveat, such as how many percentage points
  one more correct answer moves recall; under 10 positives (or 30 placed
  References for the selector) the report calls the numbers a rough indication.
- `--apply` calls the configured decision model once per placed Reference per
  classifier, twice (without and with teaching). Tests use the scripted model.
