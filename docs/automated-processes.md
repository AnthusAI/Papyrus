# Automated processes: the standard, and an honest inventory

Epic PPY-24fdf4, story PPY-07ca8a. An automated process is anything that acts without a person at the keyboard: a schedule, a trigger, a worker, an agent. Each one states the same things in the same order, so an editor, an operator or another agent can answer "what will it do, what can it never do, and how do I undo it" without reading the code.

This page has three parts: the [template](#the-template), the [inventory](#inventory) written with it from the code and the docs as they are on `develop` (2026-11-03), and the [Reference identity gate](#reference-identity-the-one-gate-for-every-path-that-creates-a-reference) with every path that creates a Reference.

The inventory records what the code and its docs say. Where nothing says, it says **no spec**. It does not describe intentions.

## The template

Every automated process states:

1. **Trigger.** What starts it: a schedule, an event, a person's action, a command.
2. **Inputs.** What it reads.
3. **The decision.** What it decides, by which rule or model, and what the possible outcomes are.
4. **May write.** The records and fields it is allowed to create or change.
5. **Must never.** What it must not do, stated so that a test can fail.
6. **Seen and reversed.** Where a person sees what it did and how they undo it.
7. **Records.** What it leaves behind about itself (receipts, logs, reasons, actors).
8. **Fails.** Whether it fails closed or open, and what is left behind when it does.
9. **Cost and bound.** What it spends and the real constraint that stops it (time, money, a lease), never an arbitrary count.
10. **Measured.** How anyone knows it works.
11. **Gherkin.** Where its behaviour is specified.

A process that cannot fill a line says so in that line.

## Inventory

### 1. Monitoring collection

- **Trigger.** The collector Lambda on its schedule (every 15 minutes for the Hacker News monitor, 6 hours for TTAB and Hugging Face), or a fixed time of day when the monitor's `runAt` is set. A pass stopped by its time budget is due at once.
- **Inputs.** One source per monitor: the Hacker News RSS feed, the TTAB decision search, the Hugging Face Hub model list, research paper feeds (arXiv RSS and Atom, Hugging Face daily papers), or approved web-search queries through a search provider.
- **Decision.** Which items are new: the pass reads newest first until it reaches an item it already collected (the high-water mark). Items are deduplicated per monitor by fingerprint and across monitors by canonical URL in the candidate record (`monitoring_candidates.py`, `CAND#<hash>`), which uses `monitoring.canonical_url`.
- **May write.** The monitoring table only: per-item records with `routing: collected`, candidates, the checkpoint (`STATE.resume`) and receipts. It writes nothing to any publication.
- **Must never.** Deliver to a publication, curate, or train.
- **Seen and reversed.** The Monitoring page in the newsroom. Nothing needs reversing: a collected item is not yet a Reference.
- **Records.** One receipt per run with `read.stoppedBy` (`time_budget`, `rate_limited`) and, for web monitors, how many searches were paid for and through which provider.
- **Fails.** Closed. A page's items are committed before the next page is asked for, so a stop loses nothing; a 429 is waited out for as long as `Retry-After` says, else the pass stops and resumes at the same page. A provider that refuses its key or has used up its plan raises an alarm.
- **Cost and bound.** No item, page or request limit. Bounded by the Lambda time (80 seconds of reading in a 120 second function), the source's rate limit, and for web monitors the account of paid searches: the same query for the same dates is never asked twice in a pass.
- **Measured.** The receipts. No quality measure of collection (how much of what matters is found) is specified: **no spec**.
- **Gherkin.** `monitoring-hacker-news`, `monitoring-huggingface`, `monitoring-paper-feeds`, `monitoring-web-search`, `monitoring-web-section-queries`, `monitoring-web-search-spend`, `monitoring-no-caps`, `monitoring-run-at`. Details: [monitoring-cloud.md](monitoring-cloud.md#reading-a-source-no-item-page-or-request-limits).

### 2. Routing and delivery

- **Trigger.** The router Lambda on `cron(7/15 * * * ? *)`, plus a `collect` run every 2 minutes for jobs still running when the route run ended.
- **Inputs.** Collected items; the router config for each publication; the Cyclotron's answers; the publication's References (to see what it already holds).
- **Decision.** For `decisions: cyclotron`, the item goes to every publication whose relevance output labels it `include`. For `direct` the monitor's own rule decides and every collected item is delivered. For `hold` nothing is decided. Then the delivery itself: create a pending Reference, or reuse the one the publication already holds.
- **May write.** Per publication, through IAM-signed AppSync: a `pending` Reference (create only, never an upsert), the monitor id and the source's details on it, the `relevance_decision_is` relation, a `KnowledgeImportRun`, and per-delivery rows in the monitoring table. It may start a procedure once per newly created Reference.
- **Must never.** Reset or change curation (status, actor, reason, stars) of an existing Reference; write a Message (Messages come only from people); decide for a publication whose output is not ready. Since PPY-07ca8a it also does not create a second Reference for a document the publication already holds ([the identity gate](#reference-identity-the-one-gate-for-every-path-that-creates-a-reference)).
- **Seen and reversed.** The References feed, with the machine decision in the rationale line and in the Cyclotron panel. An editor rejects or archives; nothing is deleted.
- **Records.** The decision relation on the Reference; delivered flags, attempts and errors per publication per item; a receipt per run.
- **Fails.** Per publication and per item. One failing backend never loses the others and a rerun skips what is delivered. A Cyclotron outage does not stop collection (separate schedules and roles). Several lineages matching one URL in a corpus is an error that needs an editor.
- **Cost and bound.** Lambda time and the lab's pacing and backoff. The router holds one lock and has reserved concurrency 1.
- **Measured.** Per-run counts in the receipt (delivered, reused, errors). A delivery-quality measure is the Cyclotron's (process 3).
- **Gherkin.** `monitoring-post-then-collect`, `monitoring-decision-contract`, `monitoring-combined-decisions`, `monitoring-router-hold-decisions`, `monitoring-router-publication-grants`, `monitoring-private-queue`, `monitor-delivery-on-reference`, `monitoring-enrich-before-decide`, `reference-identity`. Details: [monitoring-cloud.md](monitoring-cloud.md#the-router-step-4).

### 3. Relevance decisions (the Cyclotron)

- **Trigger.** The router posts each story for each publication to the shared Cyclotron and polls for the answer; editors' votes are sent back as feedback in the same invocation.
- **Inputs.** The item as enriched (title, text where read), the publication's binding, and, for feedback, the editor's vote and written reason.
- **Decision.** The Cyclotron returns a label per output (`include` or not) with a confidence. The labels are the Cyclotron's, not Papyrus's.
- **May write.** Papyrus writes the decision relation on a delivered Reference and sends feedback labels. It trains nothing itself.
- **Must never.** Send a machine actor's decision as a human vote (`auto:cyclotron`, `auto:rule`, `ai`, `system:*` are never votes); put an email address in the reviewer field.
- **Seen and reversed.** The Cyclotron panel on the newsroom home page (last change, latest evaluation, reviewed labels). A changed vote is a new label, never an edit.
- **Records.** Decision receipts with item revision, request id and output; feedback receipts `FB#<requestId>` (`sent`, `stale`, `refused`, `invalid`).
- **Fails.** Closed per story: an outage leaves the item collected and undecided; an old job after a Cyclotron run cutover is discarded and re-posted once; a story whose output is not ready waits.
- **Cost and bound.** The lab's pacing and backoff; Lambda time. The cost per decision is the Cyclotron's: **no spec** in this repository.
- **Measured.** The home-page status reads the Cyclotron's own evaluation number and what it was measured on. Retraining on evidence of mistakes: **no spec** in this repository.
- **Gherkin.** `monitoring-decision-contract`, `monitoring-combined-decisions`, `monitoring-lab-pacing`, `monitoring-lab-backoff`, `monitoring-no-pending-timeout`, `monitoring-router-feedback-actors`, `monitoring-cyclotron-status`, `cyclotron-relevance-config`, `cyclotron-relevance-records`, `cyclotron-relevance-recording`, `cyclotron-relevance-sweep`. Details: [monitoring-cloud.md](monitoring-cloud.md#the-decision-contract), [steering-and-relevance.md](steering-and-relevance.md).

### 4. Automatic acceptance

- **Trigger.** Hourly, one invocation per publication (`{"task":"auto-accept"}`), live mode only, for monitors whose decisions come from the Cyclotron; and on delivery for `direct` monitors (a rule acceptance).
- **Inputs.** Pending References nobody voted on, their Cyclotron confidence, and the publication's human votes.
- **Decision.** Accept a pending Reference whose confidence reaches a threshold learned per publication: the smallest confidence at which the Wilson 95 percent lower bound of the accept rate is at least `precision` (default 0.9), after a delay learned from the publication's human voting latency. No threshold qualifies means nothing is accepted.
- **May write.** On the Reference: `curationStatus=accepted`, the status keys, `curationStatusUpdatedBy` (`auto:cyclotron` or `auto:rule`), the reason with the numbers behind it, `curationActorKind`. Then a summary delta.
- **Must never.** Touch a Reference a person was the last actor on; count an automatic acceptance as a vote or let it teach the threshold; send it to the Cyclotron as feedback.
- **Seen and reversed.** "Accepted automatically" on the card, list row and detail; the **Accepted automatically** filter. A Reject records the editor as the actor with their reason and then does train; Accept confirms it as a human vote. Reversing leaves behind: the Reference joined the accepted evidence at once, so an idea may have been filed from it.
- **Records.** The reason on the Reference, one JSON log line per publication per run, the receipt.
- **Fails.** Closed: no confidence reaches the target, no votes, or no time means nothing is accepted. A failed summary delta never undoes an acceptance. Known gap in the docs: the router's IAM identity is not authorised for `updateNewsroomSummary`, so the pass logs `summary-failed` and the counts are repaired by the next summary rebuild.
- **Cost and bound.** One indexed query per voted Reference and per waiting Reference, bounded by the run's remaining time.
- **Measured.** The estimated precision and its lower bound are logged each run. Whether the acceptances were right in hindsight (how many were later rejected): **no spec**.
- **Gherkin.** `reference-automatic-acceptance`, `monitoring-auto-accept-task`. Details: [monitoring-cloud.md](monitoring-cloud.md#automatic-acceptance).

### 5. Capture and summary (curation before review)

- **Trigger.** A procedure the router starts once for each newly created Reference (`papyrus.reference.curate`), or `papyrus references curate`.
- **Inputs.** The Reference's address; the page or PDF; for research papers the PDF bytes for GROBID.
- **Decision.** Whether the text is captured, with completeness signals (facts, not a verdict); then a summary; then for research papers GROBID's title, authors, abstract and citations.
- **May write.** The curation card (`ReferenceAttachment`), the extracted text and summary bodies, the Reference's `captureState`; GROBID may create pending Reference rows for cited works.
- **Must never.** Change the curation status (the Reference stays pending and the editor decides); overwrite text an editor pasted or corrected; follow a non-public address; ask YouTube for a video's transcript (YouTube refuses cloud addresses: a video keeps its page's description and waits for `papyrus references capture-transcripts`, run by a person on a non-cloud connection, [4d](reference-curation-pipeline.md#4d-video-transcripts-the-worker-2026-11-04)).
- **Seen and reversed.** The card on the Reference with a status of `ready`, `degraded` or `capture_failed`. An editor corrects or pastes text; the machine capture stays as the original. `--force` redoes finished stages except over an edit.
- **Records.** The card with typed failure reasons; `change reason` on versions; the summary prompt version.
- **Fails.** Typed and mostly closed: `timeout`, `connection`, `http_5xx` and `dns` are transient and retried on the next run; the rest are final until `--force`. Without an OpenAI key the summary is a typed skip. A running card holds a 30 minute lease.
- **Cost and bound.** One model call for the summary per Reference. The reader's guards (400 KB of HTML, 8 MB of PDF), request timeouts and an overall deadline. No count limit.
- **Measured.** The card status and its signals. Whether summaries are right is not measured here; the independent claim check of [fact checking](fact-checking.md) does not yet cover Reference summaries.
- **Gherkin.** `reference-curation-before-review`, `reference-capture-state`, `reference-previews`, `reference-automatic-previews`, `reference-dates`. Details: [reference-curation-pipeline.md](reference-curation-pipeline.md).
- **Gap.** The citation step creates Reference rows by its own lookup; see [the identity gate](#reference-identity-the-one-gate-for-every-path-that-creates-a-reference).

### 6. Suggestions (related References and concepts)

- **Trigger.** The moment a Reference's summary vector is stored, new or rewritten because its text changed (the vector pass of the daily monitor-stories run queues one check). Never a schedule; never an accept, reject, vote or star.
- **Inputs.** The Reference's summary vector and the publication's vector index; the site's own decided suggestions for the cut-off.
- **Decision.** Which indexed References and concepts are close enough to suggest, cut where the site's decided suggestions say (`suggestion_calibration`).
- **May write.** Suggested links (`related_to`, with the close-match score), one check record per Reference in the router's table, and the index's vectors; the saved place of the vector pass.
- **Must never.** Repeat the check for text it already checked; walk the corpus to find work; decide a link (a suggestion is only a suggestion, and the card shows two of them); index rejected or archived References as live.
- **Seen and reversed.** Suggested links on the card and in the Related section, each with Accept and Reject; the decision is recorded and trained on.
- **Records.** One `{"suggestOnce": ...}` log line per check, the check record row, and the daily line's `suggestionsQueued`.
- **Fails.** A failed check is delivered again by the queue up to three times, then waits in a dead-letter queue with an alarm. A Reference with nothing to embed has no vector and so no check.
- **Cost and bound.** One check is a few S3 Vectors reads and queries and a handful of API requests, once per Reference text. Embedding cost in the daily pass counts against the run's cost meter.
- **Measured.** Checks queued per daily run, and the dead-letter queue depth. Whether suggestions are good is measured only by editors' later decisions: no report, **no spec**.
- **Gherkin.** `suggest-once`, `monitoring-vector-pass`, `pending-reference-vectors`, `reference-links`, `link-explanation-vectors`, `junk-concept-suggestions`. Details: [monitoring-cloud.md](monitoring-cloud.md#vector-index-and-suggestions).
- **Gap.** A suggestion is never a duplicate decision: nothing here distinguishes the same document from a related one (that is the epic's next step).

### 7. Idea generation (monitor stories, trends)

- **Trigger.** Daily at 07:30 UTC per publication (`monitor-stories`), the weekly knowledge run's trend step, or `papyrus ideas ...`.
- **Inputs.** Accepted References (human, `auto:cyclotron` or `auto:rule`) with no idea or story yet, their context (an editor's reason, comments, related References), and the Cyclotron's scores.
- **Decision.** Whether the item is worth a story, and whether a draft passes the citation rules and the point check (process 8).
- **May write.** Content Items at the `idea` stage marked Generated, one soft review request per pass, and the based-on links.
- **Must never.** Publish; draft one Reference twice; file an idea that only summarises its source; read pending References for drafting.
- **Seen and reversed.** The Idea column of the Stories board. An editor moves an idea forward or spikes it with a reason.
- **Records.** One JSON log line per publication for the plan, one per step (`monitorStoriesStep`), one when the plan finishes, and the receipt.
- **Fails.** Closed, and nothing is thrown away: the daily run only plans, and a queue drafts one candidate per message; a step that fails is delivered again up to three times, then waits in a dead-letter queue with an alarm, and the plan finishes without it. What was filed stays filed, and the next plan offers only what is not drafted.
- **Reads.** The plan reads the existing ideas once (the stage indexes, then those stories by id) and stores them in its head row with the context and the duplicate cut. A step reads its own row and head, the Reference it cites and the few records it files and links, by id or index: never a whole table, and the worker's role has no `listItems` or `listReviewRequests`.
- **Cost and bound.** One plan a day per publication; one step is bounded by the Lambda's 300 seconds and a 0.50 dollar guard on one oversized request. No fixed number of ideas and no time stop on the plan.
- **Measured.** The log counts. Whether editors keep or spike the ideas is visible on the board but not reported: **no spec**.
- **Gherkin.** `monitoring-daily-stories`, `monitoring-stories-queue`, `idea-pipeline`, `idea-monitor-stories`, `idea-trend-stories`, `idea-context-packs`, `idea-items`, `idea-duplicate-cut`, `idea-excluded-source-hosts`, `idea-run-large-site`, `idea-standard-replay`. Details: [idea-pipeline.md](idea-pipeline.md), [monitoring-cloud.md](monitoring-cloud.md#monitor-stories-daily).

### 8. Point check ("so what")

- **Trigger.** Every draft idea that passed the citation rules.
- **Inputs.** The draft and the source and other material it cites; the judge is told nothing of how the draft was written.
- **Decision.** One question: what does this draft claim that the reader could not get from the source alone? The answer is `adds`, `restates` or `unsupported`.
- **May write.** Nothing by itself; the idea is filed or not.
- **Must never.** File an idea on an unclear answer.
- **Seen and reversed.** A rejected draft is skipped as `already_rejected` until new evidence arrives. Whether an editor can see the rejected drafts and their reasons: not described, **no spec**.
- **Records.** The log counts `failedTheCheck`; reasons such as `no_point_beyond_source`.
- **Fails.** Closed: no clear answer, no idea.
- **Cost and bound.** One more model call per draft inside the run's cost meter.
- **Measured.** A replay of 2026-11-02 found drafts that repeated the editors' reason; the standard replay is specified. A running accuracy figure for the judge: **no spec**.
- **Gherkin.** `idea-more-than-summary`, `idea-more-than-summary-packs`, `idea-standard-replay`. Details: [idea-context-packs.md](idea-context-packs.md).

### 9. Fact check

- **Trigger.** Each claim of a research packet and of the Story context pack; the check is a pure function over claims and the cited source texts (`check_claims`).
- **Inputs.** Claims with their cited source ids and the texts of those sources.
- **Decision.** A verdict per claim: `verified`, `needs_check`, `rejected` or `unchecked`, from a literal check of names, numbers and quotations (code), then an independent judge asked more than once (a claim is `verified` only if all passes agree).
- **May write.** Verdicts on the packet. A claim that is not verified is held with its reasons, never silently deleted and never passed on as fact.
- **Must never.** Let the judge override a literal failure; count `unchecked` as verified.
- **Seen and reversed.** Not shown to editors yet: the console does not display claim status and there is no publishing gate (layer 7 of the table in [fact-checking.md](fact-checking.md)). **No spec** for either.
- **Records.** Counts, reasons and source strength on the packet.
- **Fails.** Closed: a judge that fails leaves the claim `unchecked`.
- **Cost and bound.** A repeated judge call per claim, reserved against the run's time.
- **Measured.** 4 of 28 real claims changed verdict across three replays on 2026-11-03, which is why the judge is asked repeatedly. Not run live in CI; the specs use a fake judge.
- **Gherkin.** `fact-check`. Only research packets are covered; Reference summaries, idea drafts, Story drafts and agent conversations are not: **no spec**.

### 10. Research assignments

- **Trigger.** Every 5 minutes, per publication that turned `researchAssignments` on; an editor creates the assignment on a Story.
- **Inputs.** Open `research.multi` assignments naming a Story, oldest first; the search and model keys; the public pages and PDFs the run opens.
- **Decision.** None beyond running: the assignment is claimed with a lease, `research_multi` runs, and it is completed or failed with the reason.
- **May write.** The assignment's status and events, the research packet Message, and, through research intake, proposed References (pending). Since PPY-07ca8a a source the publication already holds is reported, not registered again, and its status is never reset.
- **Must never.** Retry a failed assignment on its own (a run spends search and model calls); start a run with less than 420 seconds left.
- **Seen and reversed.** The assignment on the Story; an editor reopens a failed one.
- **Records.** Assignment events and one `{"researchAssignments": ...}` log line per publication.
- **Fails.** Closed: an expired lease fails the assignment with its reason so nothing hangs.
- **Cost and bound.** Search and model calls per run, bounded by the run's time; an idle tick costs one config read, one list query and a lock. No count limit.
- **Measured.** `ran`, `failed`, `expired` and `leftOpen` in the log. Whether the proposed sources are useful: **no spec**.
- **Gherkin.** `monitoring-research-assignments`, `assignment-multi-search`, `browser-assign-research`, `reference-identity`. Details: [monitoring-cloud.md](monitoring-cloud.md#research-assignments).

### 11. Knowledge runs

- **Trigger.** A weekly EventBridge schedule starting a Step Functions state machine (cloud), or `papyrus knowledge ...` on a workstation.
- **Inputs.** The publication's accepted References, extracted text, the previous run's topic identity.
- **Decision.** Topic model, typed entity extraction, an AI review of the extractor's output, the snapshot and archive, the wiki pages to create, update, revise or retire, then the projection. A later run proceeds unless its output differs sharply from the site's own history.
- **May write.** Semantic nodes, relations and cluster proposals (not public), the snapshot and archive, wiki pages and the projection of the site.
- **Must never.** Reach the projection after a failed stage; delete a wiki page under a known plugin's prefix; run from a checkout whose `origin/main` is stale.
- **Seen and reversed.** The run record and preview; entity writes are undone with `knowledge entities` commands; the projection takes the lease.
- **Records.** The run record, the snapshot and its archive, stage logs.
- **Fails.** Closed: any stage failure ends the run before projection.
- **Cost and bound.** Fargate time and the AI review's call cap (`KNOWLEDGE_REVIEW_MAX_CALLS`, default 150 per run, shared fairly between entities, clusters and relations: see [knowledge cloud run](knowledge-cloud-run.md#the-ai-review)).
- **Measured.** The run's own counts against the site's history. A quality measure of the topics themselves: **no spec**.
- **Gherkin.** `knowledge-cloud-run`, `knowledge-run-any-site`, `knowledge-run-cost`, `knowledge-run-preview`, `knowledge-run-undo`, `knowledge-archive`, `knowledge-polish`, `knowledge-run-monitor-stories`. Details: [knowledge-cloud-run.md](knowledge-cloud-run.md), [knowledge-workstation-run.md](knowledge-workstation-run.md).

### 12. Concept writes (get or create)

- **Trigger.** Any automated writer of a concept (`SemanticNode`): a knowledge run, a graph import, ontology authority recomputation, the monitor import, an author concept made from a Reference's text.
- **Inputs.** The concept the writer wants and the concepts that exist.
- **Decision.** Match by kind and a case and white-space insensitive name or alias. Missing: create it. Present: leave it alone and write only the associations. Rejected: do not revive or link it.
- **May write.** New concepts (create-only); a partial update of the derived numbers (`authorityScore`, `authorityRank`, `acceptedReferenceMentionCount`, `distinctSourceKindCount`, `relationCount`, `updatedAt`); the three named exceptions: `generated` to `accepted` on a published Story's front matter or a monitor record, and the acceptance mark on a concept the front-matter path created.
- **Must never.** Change a name, description, alias, kind, key or status of an existing concept; supersede a concept; revive a rejected one.
- **Seen and reversed.** In the wiki and the entity review; a person's edit is never undone by a run.
- **Records.** The import run id and change reason on a created concept.
- **Fails.** Closed: a create that conflicts with an existing concept is a no-op, never an update.
- **Cost and bound.** One read of the concepts per run.
- **Measured.** A guard test fails when a module outside the allowed list writes a concept that is not create-only.
- **Gherkin.** `knowledge-run-concepts`. Code: `src/papyrus_content/semantic_node_writes.py`.

## Restoring newsroom data

Every Amplify Data table (references, messages, votes, curation decisions and the rest) has DynamoDB point-in-time recovery on, for every site, with no site setting (PPY-39a16b). It is set in `amplify/site-backend.ts` and reaches a site with that site's next deploy.

- **What it covers.** Any second in the last 35 days, per table.
- **What a restore does.** It creates a new table beside the old one; it never overwrites. An operator compares the two, copies the wanted records back, and deletes the restored table. The site keeps using the original table until then.
- **What it does not cover.** Attachments and other files in S3 (S3 versioning is the separate safeguard, see [site hosting](site-hosting.md#rollback)); the newsletter subscriber table, which keeps recovery off so that erasing a subscriber is real erasure; rate-limit, throttle, lease and ledger tables, which hold no editorial data.
- **Cost.** About 5 cents a month across the seven sites at the current size.

## Reference identity: the one gate for every path that creates a Reference

The same document arrives repeatedly because the same searches rerun and because different paths each had their own idea of "the same". `src/papyrus_content/reference_identity.py` is now the one definition. `identity_keys(reference)` returns the keys a row answers to, pure and standard-library only (it loads in the router zip):

| Key | From |
| --- | --- |
| `url:<host>/<path>[?<query>]` | the source address, through `monitoring.canonical_url` and then the rules below |
| `arxiv:<id>` | arXiv `abs`, `pdf`, `html` and `format` addresses (also `export.arxiv.org`, `ar5iv`), with any `vN` and `.pdf` removed, and the `10.48550/arXiv.<id>` DOI |
| `doi:<doi>` | `doi.org` and `dx.doi.org` addresses, `doi:` strings, a `doi` field, and a `/doi/` path on a publisher address; lower-cased |
| `text:<sha256>` | `capturedTextSha256`, only when `captureState` is `full` (a thin or paywalled capture is not identity) |

**Two URL canonicalisers existed.** `monitoring.canonical_url` lower-cases the scheme and host, drops the fragment and `utm_*`, `fbclid` and `gclid`, and keeps everything else, including a default port and a Unicode host. `reference_intake_validation.canonical_source_url` keeps the query as given, drops default ports, converts the host to punycode, and rejects whitespace and over-long addresses. Neither is wrong for its job (the second is a validator that decides what may be stored); they disagreed on ports, hosts and tracking parameters, so the same page could be two Reference rows. The identity key starts from the first and adds the second's port and punycode rules, and additionally treats http and https, a leading `www.`, a trailing slash and query parameter order as the same address. Tracking parameters now have one list, in `monitoring.py`, which `link_exploration.canonical_url` reads too; before that the gate saw `?trk=` as a different page. References created before this change keep their own rows until they are grouped. The stored `sourceUri` is not rewritten.

The same title is **not** identity. `title_candidate_key` exists only for the report, which counts same-title groups as candidates.

**On a hit** a path returns or reports the existing Reference (the one in the caller's corpus first, then accepted, then pending, then the oldest) and writes nothing to it. A held Reference keeps the curation status an editor gave it, and an accepted Reference is never reset to pending.

### Every path that creates a Reference

| Path | Code | What it checked before | What it does now |
| --- | --- | --- | --- |
| Monitor delivery (router, `papyrus monitoring`) | `monitoring_intake.ReferenceIntake` | `canonical_url` of the source address and its aliases against Reference rows of the monitor's corpus; several lineages matching was an error | The gate at publication scope when nothing in the corpus matched. A hit in another corpus or under another form is reused (`identityMatched`); only the discovery fields are written, and only for a hit in the monitor's own corpus |
| Editor paste (`intakePendingReferences`) | `reference_intake.find_or_create_source_reference` | `canonical_source_url` equality inside the corpus | The gate at publication scope; a hit returns `reusedExisting` and `matchedBy` and creates nothing, no provenance and no preview |
| Email submission | `intake_email_submission_references`, which calls the editor path | The same as the editor path (email duplicate receipts dedupe the emails, not the Reference) | The same as the editor path |
| Story source registration (Tactus `papyrus_find_or_register_source`) | `find_or_create_source_reference` | The same as the editor path | The same as the editor path |
| Research intake (`assignments process-proposals`, the research worker) | `assignments_workflow.intake_research_packet_proposals` | Only with `--cited-only`: `held_reference_urls`, by normalised URL, in the corpus. Otherwise nothing, and the item id was a hash of the URL, so a rerun updated the same lineage with `pending` and reset an accepted Reference | The gate always, at publication scope. A hit is listed in `references` (action `existing`) and the item is not registered; a repeat inside one batch is `duplicate-in-batch` |
| Chat `Reference.create` | `papyrus_newsroom.newsroom.papyrus_reference_create` | The external item id (a hash of the normalised URL) in the corpus when `skipExisting` (the default); with `skipExisting: false` it wrote over | The gate always; `skipExisting: false` no longer bypasses it and the result carries `matchedBy` |
| CLI catalog (`references create-from-catalog`, imports) | `cli.plan_reference_catalog_registration` | The external item id in the corpus when `--skip-existing` (the default); otherwise it updated | The gate at publication scope; with `--skip-existing false` an item may still update its own lineage but never turns a decided Reference back to pending. The matches are printed as `identity-existing` lines |
| Citation graph (GROBID cited works) | `reference_url_text._resolve_or_build_cited_reference_record` | The external item id (`doi:`, `arxiv:`, `isbn:`) and the identifiers in the metadata, among References of the corpus that the caller supplies | The same, plus the gate over the same supplied rows. **The scope is what the caller passes**: the research intake passes only the rows it just registered, so there it is not publication scope |
| Accession (replacement or next version) | `accession.py` | Not an arrival: it replaces or versions an existing Reference | Unchanged. **No spec** for what it does when the replacement's address is already another row's |
| Move to another corpus | `amplify/functions/category-action` `moveReferenceCorpus` | Not an arrival: a new version of the same lineage in the target corpus | Unchanged |
| Public submissions | `amplify/plugins/reader-steering` | They file Proposals, not References; the filing view only reports whether the link is already a Reference | Unchanged |
| Generic `createReference` mutation | allow-listed in `amplify/functions/assignment-action/data-access.ts` | I found no caller in the repository that creates a Reference arrival with it | Unchanged. **No spec** |

### The report

`papyrus references duplicates [--format text|json] [--groups] [--skip-text-hashes]` is read-only. It lists the References, and the attachments unless `--skip-text-hashes` (captured-text hashes come from the `extracted_text` attachment of fully captured References), joins rows that share any key into groups, and prints: counts by key kind, groups across corpora, groups with differing curation statuses, groups holding an accepted row, rows with no key at all, and the same-title groups as **candidates**, with how many of those are not already one identity group. With `--groups` (text) or always (JSON) it lists the members. It writes nothing, and changes no relation, status or row. The reach of the text key is limited: most captured text lives in model attachments, not in `ReferenceAttachment`, so the text key sees only the older attachments.

### Gaps this inventory found

- The citation graph step checks only the References its caller supplies.
- Accession replacement and the generic `createReference` mutation have no identity rule and no spec.
- Existing duplicate rows are not cleaned up; the gate stops new ones.
- Grouping the same story across different sources, and an agent that suggests duplicates, are not built; they are the epic's next stories.
- Several processes above have no outcome measure (collection, suggestions, idea quality, topics, relevance retraining).
