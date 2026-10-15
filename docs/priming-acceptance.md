# Optional example priming: acceptance to first operation

Product story: `PPY-7227acea-e3f5-4bc2-b3c5-17f62568d49d`.
Core initiative: `decision-flywheel-da886c09-7acb-45d3-acf8-c81585f26d8a`.

The reviewable local flow uses actual shared `PrimingPanel` controls and the
existing Papyrus research and web curation paths:

1. Deliberately choose a representative source. Select research-paper extraction
   or web extraction plus the existing metadata/summary generator. The configured
   transformer owns source access and provider budgets.
2. Review the complete candidate item and exact values supplied to the model.
   Reject/revise extraction using transformation feedback. This feedback is not
   a classification rationale. No item is imported yet.
3. Choose every configured label and supply its own human explanation. Accept
   explicitly. The existing local transaction saves the item and labels together.
   Cancellation and invalid/stale drafts cannot be accepted. Acceptance retry is
   idempotent. The panel's `onAccepted(draft)` supplies the acknowledged list and
   classifier revision pins to the host; it does not start a Cyclotron.
4. When deliberately creating a new Cyclotron, capture its accepted example list:

   ```python
   from papyrus_content.priming_bootstrap import AcceptedPrimingSnapshot

   selected = AcceptedPrimingSnapshot.capture(
       priming_service,
       list_id=accepted_draft["contract"]["list_id"],
       classifiers=[{"id":row["id"],"revision":row["revision"]}
                    for row in accepted_draft["contract"]["classifiers"]],
       definition=relevance_plan.definition,
   )
   ```

5. Supply `priming_snapshot=selected` to `run_decide_relevance(...)`, or pass
   `selected.for_definition(definition)` to the existing native
   `Cyclotron.open(..., priming_examples=...)`. Labels, question and input fields
   must match the destination definition. No implicit label/question translation
   occurs. Existing stores refuse changed/retrofitted priming; use a deliberate
   new store/version. Later catalog acceptance never changes a captured snapshot.
6. The first operational decision sees the captured examples and human rationales
   as training context. Priming identities must be disjoint from pending reference
   identities; the sweep checks overlap before claims or writes. Priming creates
   no operational predictions/review counts, development set or held-out score.

Omit `priming_snapshot` for normal operation. An empty/unaccepted selected list
fails visibly, but selecting priming is never required to start operation.

Structured CSV, JSON, JSONL and XLSX imports follow the same preview/acceptance
transaction and bootstrap. CSV/XLSX templates are empty and derive fields and
label choices from the configured schema and classifier revisions. They contain
no invented example content or judgments.

## Evidence and limitations

New focused tests exercise actual GraphQL acceptance, the HTTP transformation job
service, existing distinct research/web planners, correction/cancel/retry, all
four structured formats/templates, frozen bootstrap, reopen, retrofit refusal,
and the actual relevance sweep with and without priming. Source extraction and
model boundaries are explicitly synthetic/offline; no paid call proves editorial
quality. These tests are not real Threat Intelligence acceptance.

The read-only verifier can also consume examples previously accepted through the
actual local PrimingPanel UI. It backs up the catalog read-only, opens a new SDK
store in a temporary directory, checks explicit labels/rationales and zero
operational labels, and never dispatches a provider:

```sh
PYTHONPATH=src:/path/to/cyclotron/src python scripts/priming-preview/verify-bootstrap.py \
  --database /path/to/examples.sqlite3 --list-id papyrus-examples \
  --classifiers '[{"id":"editorial","revision":1},{"id":"scope","revision":1}]'
```

The preserved LAN synthetic catalog verifies 19 examples per classifier, all with
rationales, zero operational labels and zero provider/source calls. Its report
explicitly says `realThreatIntelligenceAcceptance: false`. The source catalog is
not modified. This does not start/restart the preview server.

Human URLs, labels and explanations are entered in the UI. Nothing needs to be
supplied in chat, and an empty catalog is a valid ready state. Real acceptance
follows the operator's use; scripted test inputs are never presented as their
judgments. See the human-input UI below.

The unified preview/release owner owns newsroom navigation and production route
configuration. Shared storage conversion must merge the existing core priming
API, catalog drafts/feedback and root-store context before cloud activation; its
storage owner's `df7dc8b10af4b9ae62496b8663e7151f226c3366` exposes the ported APIs and passes the 10 bootstrap checks; hosted composition and authoritative cloud storage remain separate work. No production
transport, provider, IAM, resource, migration or cloud authority is activated here.

## Reachable human-input UI

The dedicated local page is `http://127.0.0.1:8901/priming` while the temporary
process is running. It uses actual shared PrimingPanel source and a separate,
initially empty `.papyrus-runs/human-priming/examples.sqlite3` catalog. The old
synthetic fixture catalog is never imported. The page can be used on this Mac;
it is deliberately not an anonymous LAN endpoint.

Choose **From reference / URL** and enter only the URL. `PapyrusPrimingCuration`
uses the existing registration planner, source resolver, Biblicus extraction and
item projection. Type is inferred from actual extraction metadata, including
`urlExtraction.sourceKind`; title/type/summary are not required input fields.
The real arXiv source `https://arxiv.org/abs/2503.15739` resolves through the
existing arXiv plugin to its PDF. Its preview title is **ECLAIR: Enhanced
Clarification for Interactive Responses**, with a complete source abstract.
The live extraction ran with the OpenAI key removed and created no human labels.

Preview shows the extracted values. Optional corrections follow extraction and
are recorded as transformation feedback. Choose publish/not publish and enter
the explanation, then accept explicitly. No label is preselected. Rejection,
revision and cancellation remain available; file imports use the same explicit
acceptance contract. A missing human judgment never blocks opening the UI or
preparing a preview.

The current local source policy enables arXiv paper URLs only. Other source
URLs fail visibly before extraction or paid calls because the expected web
worker commands are absent from the inspected Biblicus source. This is an
explicit dependency limitation, not a manual-entry substitute. No new scraper or
summarizer is provided. The server removes its OpenAI key and disables Biblicus
model fallback and automatic service startup.

Reproduce the small UI asset build and temporary process:

```sh
node scripts/priming-preview/build.mjs /path/to/cyclotron --human
PYTHONPATH=src:/path/to/cyclotron/src python scripts/priming-preview/serve-human.py
```

`verify-human.cjs` targets a separate disposable server/catalog on 8903/8904.
It now checks URL-only extraction of the real paper, disabled acceptance without
human labels/rationales, and cancellation with no accepted item. It must never
run against the human workspace. Offline tests separately verify web pipeline
wiring, correction, job retry/cancellation, stored provenance and atomic human
acceptance. That initial verification did not claim a live web-worker run; pinned real CLI offline verification is recorded below.

Automatic approval review rejected installing persistent KeepAlive service
`com.anthus.papyrus.human-priming` because auto-start persistence was not explicitly
authorized. The permitted alternative is a temporary loopback process, with no
service installed. No persistent auto-start or public/production activation is
claimed. The release owner has the endpoint and component integration contract.

## Automated URL runtime and setup review (2026-10-15)

The source inspection checkout is `../Biblicus`, pinned at
`7cb4e8b835e4880d463146bd12bfb29cc553fae1`. It remains unmodified. The actual
`biblicus.url_text.extract_url_text` Python callable provides source-aware PDF
extraction, but its CLI does not register `extract url-text`. Papyrus now calls
that existing callable through its configured interpreter and stdin JSON,
without implicit `uv` installation. Metadata and extraction both honor
`papyrus_content.env.BIBLICUS_ROOT` / `BIBLICUS_WORKDIR`; fresh-process tests cover
an explicit path containing spaces and the configured publication's sibling
path, including worker cwd/interpreter/PYTHONPATH.

Existing setup references:

- [README Python setup](../README.md#python-newsroom-package) recommends Poetry
  and `scripts/install-biblicus-local.sh`.
- [The installer](../scripts/install-biblicus-local.sh) accepts
  `BIBLICUS_WORKDIR` and defaults to extras `web,ner,markitdown`. It has not been
  run; PDF extraction works using the existing Python environment plus worker
  source. No global environment was changed.
- [pyproject.toml](../pyproject.toml) declares `markitdown[all]` in the newsroom
  extra; MarkItDown is unnecessary for the verified GROBID PDF path, but is
  required by the worker's generic web conversion.
- [Worker bootstrap](newsroom-worker-bootstrap.md) covers cloud corpus workers.
  Its S3 sync/GraphQL registration steps are unnecessary for this local,
  non-applying priming preview and were not run.
- Existing `references_commands.py` and Biblicus `grobid_runtime.py` define
  localhost port 8070 and image `lfoppiano/grobid:0.8.0`. Their automatic Docker
  launch publishes on all interfaces, so it is disabled here. The temporary
  `papyrus-priming-grobid` container instead binds **127.0.0.1:8070**, uses 2 CPUs
  and a 5 GiB limit, and is removed when stopped. No KeepAlive/restart policy is
  installed. The image is Intel and runs under emulation on this M1.

Live verification found and fixed an existing arXiv bug: generic meta
`description` described the abstract page rather than containing the paper's
abstract. The existing source plugin now reads scholarly `citation_abstract` or
arXiv's abstract block and decodes entities. Generic page descriptions cannot
silently qualify as complete paper abstracts.

The inspected main/develop and published branch CLI definitions lack both
`extract article-text` and `summarize map-reduce`, which Papyrus's web processor
expects. That baseline dependency is resolved by the assigned owner source pin
`e4001ea1c2378a66d2b58bae4ee793c7e5a2fe38`; no competing worker was implemented here. The opt-in bounded provider gateway
is implemented, but remains inactive without a trusted host grant and worker pin.

## Proposed bounded live acceptance runs

| Run | Paid-model budget | Data destinations | Acceptance |
| --- | --- | --- | --- |
| Supplied arXiv paper | **$0, zero model requests**. Existing PDF pass-through skips the article filter. OpenAI key removed; local GROBID retry count fixed at one attempt per extraction. | Public abstract/PDF requests to `arxiv.org`; PDF bytes to loopback GROBID. Its existing header/citation consolidation may consult CrossRef/bibliographic services. Full source artifacts remain private local working data. | URL alone produces preview. Human chooses the publication label/rationale in UI; no scripted real judgment. |
| One selected public web reference | **Proposed ceiling $0.50 total, at most 7 requests**, no automatic provider retries. All stages use pinned `gpt-5.4-mini-2026-03-17`; each request admits at most 12,000 input and 2,000 output tokens. Standard rates checked 2026-10-15 are $0.75/$4.50 per million input/output tokens: full reservations total at most **$0.126**. | Test URL: `https://www.cisa.gov/news-events/alerts/2021/01/07/supply-chain-compromise`. Source requests go to `www.cisa.gov`; OpenAI `https://api.openai.com/v1/responses` receives public extracted text, URL/title and existing transformation prompts. Human classification labels/rationales are excluded. | Worker source pin and offline gateway integration are verified below; source/converter destination review and explicit spending authorization remain required before execution. No paid request or live grant exists. |

The $0 paper path is independently usable. Web execution and its budget approval
remain pending; worker compatibility is verified below, while the live host remains unconfigured.
Neither run enables cloud authoring, publication, deployment or anonymous LAN.


## Durable provider admission (inactive)

`PrimingProviderBudget` is an optional trusted-host dependency of `CurationJobs`.
The human preview does not configure it. A host grant binds one exact job and
HTTPS URL to unique approval evidence for one hour; HTTP cannot create grants.
Workers receive an ephemeral loopback gateway capability, never the real provider
key. The scoped subprocess environment removes provider/AWS credentials and
forbids the existing automatic `uv` dependency fallback.

The gateway pins the Responses endpoint/model, rejects tools, non-text inputs,
pricing overrides and oversized requests, sets `store=false`, default service tier
and no reasoning effort, and disables transport retries/redirects. It counts the
serialized request with the pinned model tokenizer plus a 1,024-token framing
allowance; unavailable tokenizer data fails closed. SQLite reserves the full
per-request cost before dispatch. Duplicate requests, grant resets, cancellation,
expiry and the eighth call fail closed. Uncertain delivery and restart with an
unfinished reservation seal the grant without refunding its allowance.
Cancellation denies later admission; already dispatched provider work may finish,
while the job discards a late candidate. This is not cross-store atomic rollback.

Offline tests cover concurrent admission, restart/crash, cancellation, duplicate
requests, request bounds, scoped credentials and HTTP transport failures. The separate opt-in real CLI suite below establishes compatibility with the pinned worker commands.
`scripts/priming-preview/web-readiness.py` probes CLI help without credentials,
provider calls, grants or catalog writes. With the existing Poetry worker runtime, MarkItDown is present. The original baseline
probes returned exit code 2; both pass against the assigned owner pin below.

The selected CISA URL was extracted through the existing Papyrus/Biblicus
`extract_url_text` callable and installed MarkItDown with the OpenAI key removed
and optional HTML model fallback disabled: 16,111 characters (16,143 UTF-8 bytes),
`source_kind=web`, `method=html-heuristics`. This verifies raw extraction only;
article filtering and title/subtitle/summary generation now pass offline against the
assigned worker pin; actual paid generation remains unapproved. Pricing reference: https://developers.openai.com/api/docs/models/gpt-5.4-mini.

The restored local preview is `http://127.0.0.1:8901/priming`. Its temporary
foreground process has no autostart policy. The restored screenshot was saved to
Library as `libfile_e9a11a1c8100819191088c997964002e`; the actual paper candidate
preview is `libfile_e84040f93d588191ba2b38da14c36333`. The human catalog was not used
for scripted acceptance tests.


## Assigned Biblicus handoff and current cross-owner proof

The parent assigned Biblicus thread `01a1411f-2c1e-70b2-bf5a-9a7ee2d5c0c2`.
The owner acknowledged the exact Papyrus callers and bounded gateway contract;
implementation source pin `e4001ea1c2378a66d2b58bae4ee793c7e5a2fe38` and
offline worker proof are delivered. Owner tracking head `a4e8902` has the same source/docs tree. Biblicus epic
`blbs-dde6aeaf-5e9a-4b49-9d35-57a1308f9792` and BDD story
`blbs-e50f1705-0421-4234-aefb-50e11e9ada59` hold the contract, with tracking-only
checkpoint `d3ba6cb`. No integration-owned Biblicus source edits were made.

Against shared core `100284b100649210c3bb9c60e2ab79be992a31ca`, the 51 focused
priming/bootstrap/API/provider checks and actual 83-test publication execution
harness pass using temporary stores and offline providers. The new regression
first reproduced rejection of title/abstract-only feedback under a valid source
grant. Admission now retains the original URL when checking correction fields;
an explicitly supplied replacement URL still fails before worker execution.
This does not enable the gateway on the human preview or grant paid execution.


## Real worker integration (no paid calls)

The opt-in `procedures/newsroom/tests/test_priming_biblicus_contract.py` suite uses
real Papyrus extraction/metadata planners, real subprocess CLI commands from the
assigned worker checkout, and our actual FastAPI gateway on disposable loopback
ports. Only source IO and upstream provider responses are fixtures; all stores
are temporary. No human catalog, preview server, source origin or paid endpoint
is used. Run with `BIBLICUS_CONTRACT_CHECKOUT` pointing to the pinned worker and
`BIBLICUS_CONTRACT_PYTHON` pointing to the existing Poetry interpreter. Without
both explicit paths, this external-contract suite skips instead of guessing.

The complete URL-only pipeline produces an unclassified candidate in seven
requests with $0.126 reserved. Failure tests verify malformed article output
stops before metadata, provider outage/cancellation yields no candidate, actual
gateway token rejection dispatches no provider call, and malformed/failed/map-time
cancelled metadata cannot dispatch reduce. Real CLI integration exposed a generic
planner's `filterFallbacks` behavior. Priming now explicitly rejects that fallback
before metadata, preserving the generic planner and preventing silent raw-text
acceptance after a failed filter.

The final combined suite passes **60 tests**, including eight real CLI-to-gateway cases and the priming-only fallback regression. Both CLI readiness probes pass in the existing Poetry runtime with MarkItDown.
This confirms commands and local integration, not paid result quality or human
acceptance. The current human preview still has no configured provider budget;
its original PID 19198 and HTTP 200 were checked after the tests.
