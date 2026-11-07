# Reference curation pipeline

This page maps what happens to a Reference between its arrival and an editor's decision, and describes
**curation before review**: the stages Papyrus now runs on a monitored Reference *before* an editor is asked
to rate it. Terms follow `docs/reference-processing-terminology.md`.

An editor can only judge a Reference if Papyrus actually captured it. A thumbs-up on a card with no text
behind it teaches the system nothing. So the capture comes first, and the card says plainly whether there
is one.

## 1. The pipeline as it was (2026-10-27, read from code and from the deployed router config)

| # | Step | Code | When it runs | Where it runs | What it stores |
|---|------|------|--------------|---------------|----------------|
| 1 | Delivery of a routed item | `monitoring_router.deliver_reference` -> `monitoring_intake.ReferenceIntake` | Each router sweep, per publication that got a positive decision | Router Lambda (`papyrus-monitoring`) | A `Reference` with `curationStatus = pending` that records its monitor (`discoveredByMonitorId`, `discoveryDetails`), and the relevance decision relations. No `Message`. **No text, no summary, no GROBID.** |
| 2 | Procedure triggers | `Router.start_procedures` -> `procedure_runner.handler` | Right after step 1, once per new Reference (never for a reused one) | Procedure-runner Lambda (`papyrus-procedure-runner`, container, 15 min) | A `ProcedureRun` in the site's newsroom and a `TRIGGER#` row. **No publication of the `hn` router has `procedureTriggers` today**, so nothing is started. |
| 3 | Preview card | `reference_images.attach_preview` (link exploration; `references_enrich_images` is the batch form) | Automatically when a Reference is created: the monitoring router after delivering a new Reference (it reuses the page metadata item enrichment already read, else fetches once), the URL intake that registers a Reference, and email-submission registration. Never for a reused Reference, idempotent, and a failure is logged (`referencePreview` JSON line) and never blocks the Reference. By hand for the backfill and refresh: `papyrus references enrich-images` | The router Lambda, the intake hosts, or a developer machine / any CLI host for the backfill | `ReferenceAttachment` role `preview`, sort key `002-preview`: image URL, description, site name. |
| 4 | Find the source | `references find-fetch-url-text` (`reference_url_text`, `source_site_plugins`) | By hand (utility worker or CLI; refuses Lambda) | Machine with Biblicus | A `source` `ReferenceAttachment` (the PDF) in corpus storage. |
| 5 | Extract text | `references process-fetch-url-text` -> Biblicus `url-text` extractor; PDFs through GROBID; an LLM article filter (default `gpt-6-luna`) for HTML | By hand, usually after a Reference is accepted or for a batch an operator picks | Machine with Biblicus and a **local GROBID container** (`grobid/grobid:0.9.1-crf`, `127.0.0.1:8070`, started by `biblicus.grobid_runtime`) | `ReferenceAttachment` roles `extracted_text_raw` and `extracted_text` in corpus storage (`corpora/...`), then the citation graph: authors, cited-Reference stubs, `cites` relations. |
| 6 | Other text commands | `process-extract-text-now`, `process-attach-extracted-text`, `process-filter-text`, `process-generate-metadata` | By hand | Same | Same attachments; metadata generated from text. |
| 7 | Summary | `references summarize`, `title-subtitle resolve`, both through the cloud procedure `newsroom.reference.summarization` (`procedures/newsroom/reference_summarization.tac`, `gpt-6-luna`, prompt `reference-summary-v3-source-voice`) | By hand, or as a stage of step 8 | The site's newsroom procedure runtime | `ModelAttachment` (owner `reference`, role `metadata`, sort key `metadata`): `metadata.json` with `summary` and `summary_resolution`; `summarize` also writes `reference_summary_<n>_tokens` Message relations. |
| 8 | "Start curation" | UI action `startReferenceCuration` / `references curate-recent` -> Assignment -> `assignment_executors.execute_reference_curation_refresh_assignment` | On demand, per Reference; executed by an assignment worker | Worker | Stage statuses on the Assignment (`identifier`, `publicationDate`, `titleSubtitle`, `summary`, `topicPredictions`). |
| 9 | Email submissions | `email_submissions.process_email_submission_message` | Per inbound email | Email Lambdas | Create/find/process for explicit URLs and DOIs. |
| 10 | Registration procedure | `procedures/newsroom/ingestion_reference_register.tac` | Never in production | n/a | A dry-run envelope only; no I/O. |

Link exploration (`link_exploration.py`) and `pdf_text.py` existed, but only fed the digest excerpt (about
4,000 characters, the first 4 PDF pages), email intake, monitor stories and the preview card. Nothing
stored their text on a Reference.

**What that meant.** A Reference the router delivered sat as `pending` with a title and a URL. Text,
summary and GROBID fields appeared only when someone ran steps 5-8 by hand, typically after the editor had
already decided. The editor rated blind.

## A vote is recorded on the Reference

A vote (accept, reject, archive, reopen) used to write a `reference_curation` Message and a `comment` relation.
Messages come only from people, so the Reference holds it: `curationStatus`, `curationStatusUpdatedBy`,
`curationStatusUpdatedAt` and `curationStatusReason` (the note), plus the details of the vote in
`curationActorKind` (`human`, `agent`, `cyclotron`, `rule` or `catalog`), `curationReasonCode`, `curationSectionId`,
`curationShareable`, `curationDelegation` (JSON: `delegationId`, `relayedBy`, `instruction`) and
`curationDecisionRelationId`. The writers are the curation Lambda (`reviewReferenceCuration`, `recordDelegatedCuration`),
`reference_actions.review_reference_curation` (CLI and Tactus), the automatic accept and reject, and a catalog
registration that rejects. A Reference keeps only its latest vote; the history of earlier votes lives in the
Cyclotron's feedback. Every reader (the sweep, the proofs, the exports, the review screens) reads these fields; see
`src/papyrus_content/reference_vote.py`. `papyrus references backfill-vote-details [--dry-run]` copies the latest old
vote of each Reference from its `reference_curation` Message.

## A star rating is recorded on the Reference too (PPY-3247f1)

An editor can give any Reference one to five stars beside Accept and Reject, on every surface that decides a Reference (feed card, list, detail, Needs me,
Accepted automatically). The rating lives on the Reference in `starRating`, `starRatedAt` and `starRatedBy`, so it travels with every read of the row: the
feed, the Python readers and the idea pipeline need no extra query. It is **separate from the vote**: it never changes `curationStatus`, it needs no reason, it
can be set before or after a vote, and the newest rating wins (a tap on the same star clears it, which clears who and when too). It is **not relevance**: stars
are editorial interest, and nothing sends them to the Cyclotron as a label (`reference_vote.vote_fields` carries none; `reference_vote.latest_vote` ignores
them). The writer is the `setReferenceStars` mutation (`amplify/functions/category-action`, editor groups, like `reviewReferenceCuration`; an agent in a signed-in CLI session rates as that person with `papyrus references set-stars --reference <id> --stars 1-5|clear [--agent <name>]`, noted `<person> via cli (<agent>)`; optionally a delegation (`recordDelegatedStars`, `--delegation-file`) files `<person> via <agent> (delegation <id>)`, [story reporting](story-reporting.md#an-agent-on-the-signed-in-cli-no-aws-login)); Python reads with
`reference_stars.latest_stars` and writes with `reference_stars.star_fields` (which now also needs the Reference's `corpus_id`, for `starFeedKey`). The older `setReferenceQualityRating` mutation was not reused: it
turns three stars or more into an Accept and fewer into a Reject, which is the opposite of "stars do not change the vote", and it keeps the rating as a
`quality_rating_is` relation to a quality node, which costs a relation read per Reference. The idea pipeline reads stars as one of the strongest human signals
([ideas from context packs, "Editor interest"](idea-context-packs.md#editor-interest-stars-messages-and-accept-reasons)). A schema change: it needs the
backend deployed (a site release), and the `p.apyr.us` docs page for curation should gain a short "stars" section (follow-up PPY-3247f1).

### Finding the good ones again: Quality and Minimum stars

An editor curating with stars needs to go back for "the most recent, highest quality things". The References page has a third Sort, **Quality** (most stars first, newest first within a star level; only starred References), and a **Minimum stars** row (Any, 3+, 4+, 5), both in the feed and in search results ([reference search](reference-search.md)). They read a sparse index on `Reference`, `starFeedKey` (`<corpusId>#stars#<n>`, sorted by `feedArrivalAt`, query `listReferencesByStarFeedAndArrival`), one partition per star level, merged by the same reader as the feed ([reference feed indexes](reference-feed-indexes.md#the-star-index)). `setReferenceStars` writes `starFeedKey` with the rating (clearing the rating clears the key) and gives a Reference with no `feedArrivalAt` one, since the index sorts by it. Stars are still separate from the vote and from relevance, and still never reach the Cyclotron: this changes what an editor can look up, not what the Cyclotron learns. A new version of a Reference keeps its stars (`records._feed_keys_for_new_version`), and moving it to another corpus does too, in the new corpus's partition. Stories have the same three fields and the same rules, with their own mutation, `setItemStars`, and a carry-over for every Item version path ([content item lifecycle, star ratings](content-item-lifecycle.md#star-ratings-ppy-f1c1fd)). A Reference's rating also orders the public home page (an editor's rating first, then the Cyclotron's confidence), and is never printed there or published: only a position in the order is ([home page](home-page.md#ordering-human-ratings-then-cyclotron-confidence)).

## Suggested links on the card (PPY-3c11bd follow-up, Ryan 2026-11-02)

The Reference feed card and the Needs me Reference card show, under the stars and Accept and Reject, the two most likely suggested concepts and the two most
likely suggested References for that Reference (`components/card-suggestions.tsx`), each with Accept and Reject. One tap calls `ReferenceLinksStore.decide`, the
call the Related section makes, so the decision is recorded and trained on exactly as there; it is not a vote on the Reference. The order is the close match the
vector index recorded, most likely first (`lib/card-suggestions.ts`; the Needs me queue's `compareSuggestions` ranks the same way). Reads are lazy: a card asks
only once it is on screen, through one loader per store that reads at most two References at a time and never the same one twice
(`createSuggestionLoader`); the backend has no batch read, so a page of cards is throttled rather than batched. A card with no suggestions shows nothing and keeps
its height. The list rows are buttons, so suggestions stay in the detail pane's Related section. Beside them a small box takes `#name` and one button (`CreateConceptAction`, the Related section's own action) creates the concept if it is new and tags the Reference.

## 2. Curation before review

```
router delivers pending Reference
  -> (async) procedure runner starts  papyrus.reference.curate   [one trigger per publication]
       -> papyrus_curate_reference(reference_id)                 [papyrus_newsroom.tactus_tools]
            1. capture   resolve the address, read the whole article or PDF
                         + completeness SIGNALS (facts, never a verdict)
            2. summary   gpt-6-luna, source voice (mirror of reference_summarization.tac)
            3. GROBID    research papers only: title, authors, abstract, sections, references
                         (or a typed skip)
       -> curation card on the Reference  (status: ready | degraded | capture_failed)
the Reference stays pending; the editor sees the card and decides
```

Code: `src/papyrus_content/reference_capture.py` (stage 1), `reference_grobid.py` (stage 3),
`reference_curation.py` (orchestration, summary, backfill, CLI), `reference_curation_store.py` (storage,
status, editor corrections). Specs: `features_backend/reference-curation-before-review.feature`.

### Stage 1: capture

Link exploration does the network work (redirects, tracker wrappers, public addresses only, typed
URL-free failures). Capture adds:

* **HTML**: headings, paragraphs, list items, quotes and code blocks of the page, preferring `<article>`
  and `<main>`, without navigation, footer and forms (the whole article, not an excerpt).
* **PDF**: every page, with line wraps and hyphenation undone. The bytes are kept in memory for GROBID.
* **Following a PDF**: arXiv `abs` pages are read from `arxiv.org/pdf/<id>`; a page with
  `citation_pdf_url` is read from that PDF; a thin page that links one main PDF uses it when it is longer.
* **YouTube**: no transcript is fetched here. YouTube refuses cloud addresses (measured over 30 days: the router's transcript request was
  blocked 39 times and worked once; the same request from a home connection returned the transcript), so a video link (`watch`,
  `youtu.be`, `shorts`, `live` or an embed, on `youtube.com`, `m.youtube.com` or `youtube-nocookie.com`) is captured like any page and
  keeps the page's own text (its description, or its title when there is nothing else). `capture.textVia` is `youtube_description` and
  `capture.textReason` is `awaiting_transcript`, which makes the capture `thin` however long the description is, so the video is never
  taken for captured in full. The transcript is read later by a person's command on a non-cloud connection, and saved as the text the way
  a pasted text is: [video transcripts, below](#4d-video-transcripts-the-worker-2026-11-04). No Lambda carries the transcript library.
* **Bounds** are the real ones: the reader's response guards (400 KB of HTML, 8 MB of PDF; larger fails
  as `too_large`), per-request timeouts and the one overall deadline.

Typed failures (`capture.reason`): the link exploration reasons (`invalid_url`, `not_public`, `dns`,
`timeout`, `connection`, `tls`, `loop`, `http_4xx`, `http_5xx`, `blocked`, `too_large`, `unreadable`,
`unsafe_destination`) plus `no_text`, `unsupported_media`, `no_source_uri`. `timeout`, `connection`,
`http_5xx` and `dns` are `transient`: the next run retries them. The rest are final until `--force`.

### Completeness signals

Stored under `signals`. They are inputs for the future Cyclotron completeness classifier. **Nothing sets a
"complete" flag.**

| Field | Meaning |
|---|---|
| `wordCount`, `characterCount`, `paragraphCount`, `headingCount` | Size of the captured text |
| `metaDescriptionWordCount`, `wordsPerDescriptionWord`, `bodyNotLongerThanDescription` | The text against what the page says about itself (`og:description`) |
| `declaredWordCount`, `wordCountRatioToDeclared` | schema.org `wordCount` (JSON-LD) when the page declares one |
| `structuredArticleBodyWordCount` | schema.org `articleBody` length when present |
| `structuredAccessibleForFree` | schema.org `isAccessibleForFree` when present |
| `paywallMarkers` | `[{id, inTail}]` for phrases such as `subscribe_to_continue`, `sign_in_to_read`, `continue_reading`, `article_limit`; `inTail` is true when the phrase is in the last 600 characters |
| `endingPattern` | `sentence_end`, `ellipsis`, `truncation_marker`, `no_terminal_punctuation`, `empty` |
| `endsWithTerminalPunctuation`, `tail` | Whether it stops at a sentence end, and the last 120 characters |
| `responseTruncated` | The reader's size guard cut the response |
| `pdfPageCount`, `pdfEmptyPageCount`, `wordsPerPdfPage` | For PDFs: pages, pages with no text (scans), density |

### Stage 2: summary

One `gpt-6-luna` call (the Responses API; the model is a constant, not an option) with the source-voice
prompt of `reference_summarization.tac` (`reference-summary-v3-source-voice`; a test keeps the two in step).
Text longer than the model window keeps its head and tail (`inputTruncated`). The summary is stored on
the card and also written to the Reference's `metadata.json` (`summary`, `summary_resolution`), where every
earlier summary lives. An existing summary from elsewhere is kept unless `--force`. Without
`OPENAI_API_KEY` the stage is a typed skip (`openai_not_configured`) and a later run fills it in.
Not included yet: the publication doctrine block that `references summarize` adds to the prompt.

#### Directed summaries: why the newsroom is reading this source

A summary is one text shared by every reader of the Reference: the Cyclotron input, the suggestion vectors, the card and the reporter pack all read the same words. So it is written once, and when the Reference has a reason to be read, that reason is part of the prompt.

`reference_purpose_context(client, reference)` builds the reason as a block of text, or returns `None`:

* **The Assignment it came from**: its title and the editor's direction (the Assignment's metadata `direction`, read through `assignment_metadata` because it lives in an attachment, else its `instructions`). The Reference row keeps no pointer to the Assignment that proposed it (`Reference` has no metadata field), so a research run writes `assignmentId` into the `metadata` of the `uses_evidence` link it makes to the Story, beside the note, and the context reads it from the Reference's links. Links made before this change carry no `assignmentId` and are not migrated; a Reference with no Story link has no origin to read.
* **Every Story linked by `uses_evidence`** (`consulted`, `cited`, `based_on`), newest first: headline, deck, section title and role. Never the Story's body. There is no fixed count; the model's input window is the only bound.

With a block, the message starts with the rule *Why the newsroom is reading this source: ... It is not evidence. Every statement must still come from the source text*, and the rest of the prompt (source voice, grounding) is unchanged. With none, the prompt is byte-identical to the general one and the prompt version stays `reference-summary-v3-source-voice`; a directed summary is `reference-summary-v3-source-voice-directed`. Both paths use it: `references summarize` sends `purpose_context_text` to the procedure `newsroom.reference.summarization`, and curation (`_summary_stage`, `openai_summarizer`) sends `purposeContext`. A test keeps the rule and versions in step with the `.tac`.

A directed summary records `summary_purpose` in the Reference's `metadata.json` beside `summary_resolution`, and on the card's `summary.purpose`: `{assignmentId, storyLineageIds, contextHash}` (the hash is of the block). A general summary carries neither, so a reader can tell the two apart.

**When it is written.** The existing rule stands: a present summary is kept unless `--force` (`papyrus references curate`); `papyrus references summarize` replaces one with `--refresh`. A general summary is not rewritten when a Story is linked later, because the same text feeds the Cyclotron and the suggestion vectors. The router's enrichment runs before any link exists, so it stays general. A summary belongs to the Reference and is seen by every reader of it, whichever Story or Assignment asked for it first.

**Research runs.** `research.multi` registered its References with no text and no summary (`process-proposals` from a run passes `url-text` and `metadata-from-text` as false), so a reporter pack showed nothing for them. A cited-only run now runs the existing curation (`curate_found_references`: capture, then the summary with the Assignment as its purpose) on just the References it took in. The summary is keyed the way research runs are: `OPENAI_API_KEY`, else the SSM parameter named by `PAPYRUS_OPENAI_KEY_PARAMETER`; with neither the stage is the typed skip `openai_not_configured`. A failure on one Reference is recorded on its card and never fails the run; the result carries `curation: {curated, failed}`.

### Stage 3: GROBID (research papers)

`paper.isPaper` is decided from facts (`paper.basis`): `arxiv`, `doi` (a `doi.org` address),
`scholarly_host`, `citation_meta` (Highwire `citation_title` + `citation_author`) and `paper_structure`
(an abstract near the start and a references section later in a PDF). GROBID needs a PDF; a paper whose PDF
cannot be fetched is `pdf_unavailable`.

GROBID is a service, not a library. Papyrus uses one when `BIBLICUS_GROBID_URL` (or `--grobid-url`) names
it, or, on a developer machine with Biblicus and Docker, with `--start-grobid` (Biblicus starts its own
container). **The procedure runner Lambda has neither, so papers curated there end as the typed skip
`grobid_not_configured`**, and the rest of curation still completes. Reasons: `not_a_paper`,
`pdf_unavailable`, `capture_failed`, `grobid_not_configured`, `grobid_unreachable`, `grobid_busy` (503),
`grobid_timeout`, `grobid_request_failed`, `grobid_empty`, `grobid_parse_failed`. The retryable ones are
tried again by the next run (`grobid_not_configured` only once a service is configured).

### Citation stubs: archived, and brought back by a monitor

Reading a paper's bibliography creates a pending Reference for every work it cites (`reference_url_text.py`). Nobody chose those, and on a research
publication they run to thousands and bury the pending feed. They carry the citation graph's markers: `changeReason` `grobid-citation-graph`,
`curationStatusReason` "auto-created from GROBID citation graph" and `curationStatusUpdatedBy` `papyrus-reference-url-text`.

`papyrus references retire-citation-stubs --corpus-key KEY [--dry-run]` (`reference_citation_stubs.py`) archives, in place, each one that is still exactly
what the citation graph made: current, pending, those markers and that actor, no star rating (`starRating`, `starRatedAt`, `starRatedBy`, `starFeedKey`) and no
recorded vote (`curationActorKind`). Anything else is counted as skipped, with the rule that skipped it, and left alone. A Reference with a Cyclotron prediction is
still retired: a prediction is a guess, not a person's choice. It archives and never deletes. It writes the status, `curationStatusKey`, who, when and why, the reviewed-feed
key a person's archive writes, and clears `feedStateKey` (`predictionSortKey` and `feedArrivalAt` only sort inside that partition, so the Reference is in neither
feed). The record, its prediction, its link and every citation relation stay, and it records no vote, so nothing trains the Cyclotron. `--dry-run` prints the same
tab-separated counts (`scanned`, `eligible`, `withUrl`, `withoutUrl`, `withInboundCitations`, `withPrediction`, `skipped.<reason>`, `written`) and writes nothing; running it again
selects nothing. The archive is signed `papyrus-retire-citation-stubs`. It does not adjust the newsroom summary's status counters (nor does the automatic reject path).

A monitor that later finds one of these papers goes through `ReferenceIntake`, which reuses a matching Reference whatever its status. When the match was archived
by that actor, and only then, intake returns it to `pending` (status key, `feedStateKey`, reviewed-feed key; signed `papyrus-monitoring-worker`) before the router
records the Cyclotron's prediction on it. A rejected Reference, or one a person archived, stays exactly as it is. An archived stub still shows in the
citation lists of the papers that cite it (the lists read `cites` relations, which this does not touch); it is labelled with its title when the page holds
the Reference and with its lineage id otherwise, and the link opens it.

Spec: `features_backend/reference-citation-stubs.feature`.

### Idempotence, leases, retries

A card with status `ready` is left alone. A stage that finished is not repeated; one that failed for a
retryable reason is. A `running` card holds a 30-minute lease, so two runners do not curate the same
Reference. Text an editor has pasted is never recaptured over (the machine capture stays as the
original). `--force` redoes finished stages, except recapture over an edit.

## 2a. Enrich before decide (2026-10-27)

Curation now happens **before the Cyclotron decision and before human rating**, once per item, so the lab decides on enriched text
and editors rate exactly what was decided, with no second revision:

```
collector discovers (title, URL)
  -> router ENRICH, once per item  (capture -> signals -> summary -> GROBID if configured)   [ENRICH# row + S3]
  -> router DECIDE on item.values {title, url, source, sourceItemUrl, summary, text}
  -> router DELIVER: a pending Reference per included publication, with the item's curation COPIED onto it
  -> (async) papyrus.reference.curate  only fills per-site gaps (none expected)
```

* **Same stages, same shapes.** Item enrichment runs the stage code described below (`reference_capture`,
  `reference_curation.openai_summarizer`, `reference_grobid`); only the storage differs while there is no Reference yet
  (`monitoring_enrichment.py`; the `ENRICH#` row and S3 are described in `docs/monitoring-cloud.md`). Statuses and typed reasons
  are the card's (`ready`, `degraded`, `capture_failed`; `capture.reason`, `summary.reason`, `grobid.reason`).
* **Delivery copy.** `monitoring_enrichment.copy_curation` writes the card (`origin.kind = "item-enrichment"`) and the `curation-*`
  bodies on each delivered Reference version, so section 3 below describes what the newsroom panel shows, and
  `plan_stages` finds the Reference `already_curated`. A Reference whose item was captured transiently-failed, or a paper while
  GROBID was not configured, is exactly what the procedure may still fill in (typed skips stay skips unless a service appears).
* **Decide payload.** `summary` is the card's summary text; the full captured text goes only inside `text`, never as its own value; `text` is
  `title \n url \n\n summary \n\n body` (absent parts left out). The router sets no length limit of its own and always sends the whole body; the stored capture and the copy on the Reference stay whole too.
* **Never wait forever.** One attempt, transient failures retried on later runs (three attempts in all), then the decision
  proceeds with whatever exists. A capture failure is a typed status, not a stop.
* **Editor corrections** (section 4) remain a per-Reference new version. Sending a correction back as a new item revision, so the
  lab decides again on the corrected text, is intended later and deliberately not built.

## 2b. A Reference created by hand is enriched before it is predicted (PPY-d683da, PPY-47e246)

Until 2026-11-06 only a monitor's items and the References an editor selected from an email ran the stages above. A Reference created through
`papyrus references create-from-catalog` (signed in, or with AWS credentials), the Newsroom's Add dialog, chat, `papyrus references import` or a research
packet got a prediction request and nothing else: no captured text, no summary, no picture of its own, and nothing caught up later. Ten Machines on Machines
References had to be captured by hand for that reason. Now the request that asks for the prediction also asks for the enrichment (`predictFor.enrich`, one
row, keyed by `prediction_source_id`, so a retried creation adds nothing), and the router's five minute `email-references` task runs the existing stages first.

| Path | What creates it | What triggers the follow-up | What runs in the cloud | What is local only |
| --- | --- | --- | --- | --- |
| Monitor item | the router's delivery | the item's `ENRICH#` row, then `papyrus.reference.curate` fills gaps | capture, summary, GROBID, preview, prediction | video transcript and thumbnail |
| Email selection | `deliver` for an editor-selected candidate | the same, in the `email-references` lane | as above | as above |
| `create-from-catalog`, signed in | `intakePendingReferences` (Lambda) | `queue_after_intake` queues the one request | capture, summary, GROBID if configured, curation copied onto the existing Reference, then the prediction | video transcript and thumbnail |
| `create-from-catalog` and `import`, AWS credentials | the CLI writes the plan | `request_for_created` queues the one request; the CLI attaches the link preview | as above | as above |
| Add dialog | `intakePendingReferences` | as the signed-in CLI | as above | as above |
| Chat, research packet, email submission | `papyrus_reference_create`, `assignments_workflow`, `email_submissions` | `request_predictions` queues the one request | as above | as above |

What the router does for such a request (`Router.enrich_created_reference`): reads the Reference (missing, archived, superseded or a different address:
skipped, and the prediction request is refused with its own reason); skips it when `captureState` is already `full` (a person's or an earlier capture's text is
never replaced; a curation card that exists is kept by `copy_curation`); otherwise runs `enrichment_for` (capture, summary, GROBID where configured, with its
three-attempt retry) and copies the curation onto the **existing** Reference with `monitoring_enrichment.copy_curation`, labelled `origin.completenessChecked =
false` with a note that the extraction is automated and not checked for completeness (the way a `correctReferenceCapture` note labels an agent's text). The text
is stored where the curation pipeline stores it, a `curation-text.md` ModelAttachment and the card (the same family `correctReferenceCapture` writes), not a
`ReferenceAttachment` of role `extracted_text`; whether the knowledge query reads it is PPY-caa222, which this change does not touch. Then the prediction decides
on the enriched summary and text ("enrich before decide", 2a). The outcome is kept on the request's ROUTE row as `enrichment` with a distinct `state`:

| State | Meaning | Visible where | Retried |
| --- | --- | --- | --- |
| (no `enrichment`, request still in the lane) | queued but not run yet, or waiting for a transient retry | the `reference-predictions` lane, `enrichmentWaiting` in the receipt | on the next 5 minute run, three attempts in all |
| `enriched` | text, summary and card written | the card; `referencesEnriched` | no |
| `kept` / `already_captured` | a card or text a person supplied stands | ROUTE row | no |
| `oversized` | the source is over the reader's size limit (`capture.reason = too_large`) | the card (`capture_failed`), `enrichmentFailed`, the log line `referenceEnrichment` | no: final; paste the text in the newsroom |
| `blocked` | the source refused or is not text | the same | no: final |
| `capture_failed` | any other capture failure | the same | only a transient one, up to the attempt limit |
| `copy_failed` | the card could not be written | ROUTE row `curationCopy`, `curationCopyFailed` | the request is not retried; run the backfill |
| `stateRepaired` flag | the stored `captureState` or `contentNeededKey` disagreed with what the Reference holds and was corrected | ROUTE row | n/a |
| never queued | created before this change, or by a path that was not asking | `references queue-enrichment --dry-run` counts them | queue it by hand |

An enrichment failure never blocks the prediction and one Reference never stops the others. A video is enriched as far as the cloud can (YouTube refuses cloud
addresses for transcripts and thumbnails), `sync_capture_state` leaves it `thin` or `none` with its `contentNeededKey`, and the router counts it as
`videosNeedLocalRun`. The creating command says so: `N videos need a local run: papyrus references capture-thumbnails --write and papyrus references
capture-transcripts --write`. Requests queued before this change carry no `enrich` flag and are decided as they were.

**References created before this change need a one-time backfill.** `papyrus references queue-enrichment --site KEY` (or `--corpus-key KEY[,KEY...]`; add
`--dry-run` to see the counts) queues one enrich-only request (`enrichment_source_id`, `predictFor.enrichOnly`) for each current, unarchived Reference of the corpus
whose content is not captured in full. It reads the corpus's feed index (`referencesByFeedStateAndPrediction`, both partitions), writes only queue rows, and is
idempotent. It is a write to production data, so the owner approves it; this change does not run it.

## 3. Where the outputs are (for the UI)

All additive; no model, field or enum changed.

### The curation card: `ReferenceAttachment`

One row per Reference version. Lookup: `getReferenceAttachment(id)` with
`id = "reference-attachment-" + hash_short(["reference#<Reference.id>", "curation", "003-curation"])` (see
`reference_curation_store.card_id`), or find it among the attachments the newsroom already loads with the
References: `role == "curation"`, `sortKey == "003-curation"`. Its `metadata` is a JSON string:

```json
{
  "kind": "reference-curation", "schemaVersion": 1, "pipelineVersion": "reference-curation-v1",
  "referenceId": "...", "referenceLineageId": "...", "sourceUri": "...",
  "status": "ready | degraded | capture_failed | running",
  "startedAt": "...", "completedAt": "...", "updatedAt": "...",
  "capture": {"status": "completed | failed | not_run", "reason": "blocked", "transient": false,
              "sourceKind": "html | pdf", "contentType": "...", "via": "direct | arxiv_pdf | citation_pdf_url | linked_pdf",
              "destinationUrl": "...", "capturedAt": "...", "textSortKey": "curation-text",
              "textSha256": "...", "wordCount": 912},
  "signals": { "...see the table above..." },
  "page": {"title": "...", "description": "...", "siteName": "..."},
  "paper": {"isPaper": true, "basis": ["arxiv"], "arxivId": "2601.01234", "doi": "10.1234/x"},
  "summary": {"status": "completed | skipped | failed", "reason": "...", "text": "...", "model": "gpt-6-luna",
              "promptVersion": "reference-summary-v3-source-voice", "generatedAt": "...", "stale": false},
  "grobid": {"status": "completed | skipped | failed", "reason": "grobid_not_configured",
             "title": "...", "authorCount": 2, "hasAbstract": true, "sectionCount": 8, "referenceCount": 41,
             "fieldsSortKey": "curation-grobid", "teiSortKey": "curation-grobid-tei"},
  "current": {"textSortKey": "curation-edit-0001-text", "grobidSortKey": "curation-edit-0001-grobid"},
  "edits": [{"n": 1, "kind": "text | grobid", "sortKey": "...", "editedBy": "...", "editedAt": "...",
             "provenance": "edited by editor", "basedOn": "curation-text", "originalSortKey": "curation-text",
             "correctedFields": ["title"], "note": "..."}],
  "labels": [{"kind": "capture_completeness", "assessment": "complete | incomplete | incorrect",
              "labeledBy": "...", "labeledAt": "...", "textReplaced": true, "originalCaptureStatus": "completed",
              "originalTextSha256": "...", "originalSignals": {"...": "..."}, "originalPaper": false}],
  "editedSignals": {"wordCount": 1500, "...": "..."}
}
```

How to show it: **`status` is the "pending-ready" signal.** `ready` means there is text and a summary.
`capture_failed` means Papyrus holds no text: show that plainly (the reason is in `capture.reason`) and
offer paste-text. `degraded` means there is text but a stage is unfinished (usually the summary). No card
yet means curation has not run. `summary.stale` means an editor replaced the text and the summary awaits
the next run (show it, marked). A Reference with a `capture.reason` of `blocked` or a `signals.paywallMarkers`
entry with `inTail: true` is a likely paywall, but that is the editor's call (or the classifier's later).

### The bodies: `ModelAttachment`

Owner `reference` / `Reference.id`, role `metadata`. **Find one by listing**
`modelAttachmentsByOwnerRoleAndSortKey(ownerId = Reference.id)` and take the active row with the sort key, then download it with
`createModelAttachmentDownload`. Do not build the id: the upload function makes it (`model-attachment-<kind>-<owner>-<role>-<sort key>`, each part
lowercased, runs of other characters turned into `-`, a part over 80 characters cut to 67 plus `-` and 12 hex digits of its SHA-256), and the client's
formula disagreed with it for a Reference id over 80 characters (every real one: `reference-<corpus>-<64 hex>-v1`) until PPY-caa222.
`model_attachment_id` now matches, and `AttachmentStore` and the knowledge query use the list:

| Sort key | Media type | Content |
|---|---|---|
| `curation-text` | `text/markdown` | The machine capture (never overwritten after an edit) |
| `curation-grobid` | `application/json` | `{title, authors[{name, forenames, surname, affiliation?, email?}], abstract, doi, keywords[], sections[{heading, number?, text}], references[{title, venue, authors[], year, doi, arxivId, raw}]}` |
| `curation-grobid-tei` | `text/plain` | GROBID's TEI XML |
| `curation-edit-NNNN-text` | `text/markdown` | An editor's full text, version NNNN |
| `curation-edit-NNNN-grobid` | `application/json` | The fields with the editor's corrections applied (same shape as `curation-grobid`) |
| `metadata` | `application/json` | The Reference's `metadata.json`; curation adds `summary` and `summary_resolution` |

Show `card.current.textSortKey` / `card.current.grobidSortKey`; they point at the latest edit when there
is one, else at the machine capture.

## 4. Editor corrections

An editor can fix the captured text or paste the whole text, correct GROBID fields, and say whether the
machine capture was complete. Each correction is stored as a **new version** (`curation-edit-NNNN-*`) with
provenance `edited by editor`; the original stays. It also appends a **label** to `card.labels`: the
assessment, who and when, the original capture's status, failure, hash and **signals**. That is the
training data for the completeness classifier: it pairs the signals with the editor's verdict on the same
capture.

### AppSync action

`correctReferenceCapture` (content-actions Lambda; same groups as `intakePendingReferences`). Input
(`a.json`):

```json
{"referenceId": "<Reference.id>",
 "text": "<full corrected or pasted text>",        // optional
 "grobid": {"title": "...", "authors": [{"name": "..."}]},  // optional; any of title, authors, abstract, doi, keywords, sections, references
 "assessment": "complete | incomplete | incorrect",       // required with text; alone it is just a label
 "pdfAttachmentId": "<id of a PDF uploaded to this Reference>",   // optional, instead of text
 "captureReason": "no_transcript | unavailable | unsupported_platform",   // optional, a video only, never with text: nothing can be captured automatically
 "note": "optional, at most 4000 characters"}
```

The editor is the signed-in caller; the request cannot name one. Result: `{ok: true, referenceId, status,
edits: [...], label, summaryStale}`, or `{ok: false, errors: [{code: "correction-rejected", message}]}`.
At least one of `text`, `grobid`, `assessment`, `captureReason` is required (`captureReason` is the transcript worker's record of a video it cannot capture: [below](#4d-video-transcripts-the-worker-2026-11-04)). Replacing text marks the summary `stale`; the next
`papyrus references curate` (or router-started run) writes a new summary from the corrected text. Editing
does not change `curationStatus`. Concurrent corrections to one Reference are last-write-wins on the card
(editors do not edit the same Reference at once; the version bodies are never lost).

**Uploading a PDF.** When the source sits behind a bot wall, the editor downloads the PDF themselves and
uses "Upload a PDF" on the Reference. The browser stores it as a `ModelAttachment` of the Reference (owner
kind `reference`, role `curation-upload-pdf`, media type `application/pdf`) with the usual two-step upload,
then calls `correctReferenceCapture` with `pdfAttachmentId` (instead of `text`) and the `assessment`. The
Lambda checks the attachment belongs to that Reference, is a PDF (`%PDF`) and is at most 8 MB (the capture's
own PDF limit), reads it page by page with `pdf_text`/`pdf_to_text` (the one extractor the capture uses), and
refuses in words a scan with no text. The text is stored exactly like pasted text; the edit and
`card.current` record `via: "editor_pdf"` (`textVia`) so the panel says "Text from a PDF you uploaded". The
card's `paper` is re-detected from the text. GROBID does not run in the Lambda; `papyrus references curate`
decides it by `paper.isPaper`, but it has no access to an uploaded PDF's bytes yet (it skips with
`pdf_unavailable`).

`papyrus_content.reference_curation_store.apply_editor_correction(client, reference, editor=..., text=...,
grobid=..., assessment=..., note=...)` is the same operation for scripts.

## 4a. `Reference.captureState`: whether a person is still needed (2026-11-03)

Some accepted References are only a title and an address: the page was behind an I'm-not-a-robot gate or a paywall. It is worth human effort (upload a PDF, or select all and paste) to capture the highest-rated ones, so each Reference stores how much of its content we hold, on the Reference itself (`Reference.captureState`, no index): `full`, `thin`, `none` or `running`. **Empty means `none`**: a Reference a monitor discovered has only its address and nothing was captured. Only `full` counts as captured; `thin`, `none`, `running` and empty all read as "not captured". The newsroom's Captured filter, search's `captured` choice and the home page's list of accepted References that still need a capture read it.

**The rule decides today; no capture classifier exists yet.** It takes the same inputs as the card's capture badge (`captureStatus` in `lib/reference-capture.ts`: the curation card, else the older `extracted_text` attachments) and puts the editor's word on top:

1. Text a person pasted, corrected or uploaded (the card's current text is a `curation-edit-*` body) is `full`, whatever its length. The assessment that comes with a replacement is about the machine capture, not the new text.
2. Otherwise an editor's latest `capture_completeness` label wins: `complete` is `full`; `incomplete` and `incorrect` are `thin`, so it asks for a person again.
3. Otherwise text is `thin` when it has fewer words than the teaser line or when the card's completeness signals doubt it (a subscribe or sign-in phrase in the tail, an ellipsis or cut-off ending, text no longer than the page's own description, a page that says it is not free, far fewer words than the page declares, a truncated response, scanned PDF pages); a long text that only lacks a final full stop is `full`. Otherwise it is `full`.
4. No text is `none`. A card that is `running` with no text yet is `running`. An assessment cannot create text, so a label on a Reference with no text leaves it `none`.

**Videos.** A capture whose `capture.textReason` is `awaiting_transcript` (a video captured from its page alone), or a verdict the transcript worker recorded (`no_transcript`, `unavailable`, `unsupported_platform`), is `thin` until a person or the worker supplies text, whatever its length (`DESCRIPTION_ONLY_REASONS`; both twins, with vectors). The card's reason in To capture is then in words: `awaiting_transcript`, `no_transcript` ("YouTube has no transcript for this video"), and so on.

**The teaser line.** The browser's cards learn the line from the site's own corpus (a quarter of the median captured length, from ten captures). The stored state cannot see the corpus, so it always uses `DEFAULT_TEASER_WORDS` (250). A card can therefore differ from the stored state by a few words near the line; the filter and the home list use the stored state. The code is `storedCaptureState` / `captureStateOfAttachments` (`lib/reference-capture.ts`) and `capture_state` (`src/papyrus_content/reference_capture_state.py`), both tested against `scripts/fixtures/capture-state-vectors.json`.

**Who keeps it right.** One helper, `sync_capture_state(client, reference, card=None)`, recomputes the state from the card and, only when the card holds no text, from the Reference lineage's attachments, and writes the field only when it differs (never `none`: a stale value is cleared with null). It runs from:

| Path | Where |
| --- | --- |
| The curation run (`papyrus references curate`, the `papyrus.reference.curate` procedure), at its start (a Reference with no text yet becomes `running`; one that has text keeps its state) and at its end | `write_card` in `reference_curation_store.py` |
| An editor's paste, corrected text, uploaded PDF or assessment alone (`correctReferenceCapture`, `apply_editor_correction`) | `write_card` |
| The publication-date backfill, which rewrites the card | `write_card` |
| Older captured text: `papyrus references process-fetch-url-text`, `attach-extracted-text`, the text filter, assignment registration, citations (every `extracted_text` / `extracted_text_raw` ReferenceAttachment write) | `apply_record_changes` in `records.py` |
| A new version of a Reference | `_feed_keys_for_new_version` carries the state to the new version (the card and the text belong to the old version's id, and the newsroom reads attachments by lineage) |
| Existing References | `papyrus references backfill-feed-keys` (counts `captureStatesChanged`) |

**After a person captures it.** `correctReferenceCapture` stores the text as a new `curation-edit-NNNN-text` body, appends the label, marks the summary `stale` and sets `captureState` to `full` in the same call. **Nothing re-runs automatically**: the summary and, for a paper, GROBID wait for the next curation run (`papyrus references curate`, or the `papyrus.reference.curate` procedure where a publication's router triggers it; no publication's router has procedure triggers today). That run does not recapture over the person's text; it summarizes it.

## 4b. `Reference.medium`: what kind of thing the address is (2026-11-04)

A third attribute of a Reference, separate from its evidence level and its voice (PPY-f8ff49): the **medium**. It is set by rule from the address alone, by no model, and **only where the address is certain**. Today the one value is `video`; any other address has no medium (empty means "not known", never "not a video"). The code is `src/papyrus_content/reference_medium.py`, a pure function from address to `(medium, evidence level, playlist address)`, tested by exact shape in `reference_medium_test.py` and `features_backend/reference-medium.feature`.

**Exact shapes, never substrings.** The host and the whole path are matched; a channel page, a user page, a Vimeo category or `youtube.com/about` is not a video.

| Platform | A video | An aggregation (no medium) |
| --- | --- | --- |
| YouTube (`youtube.com`, `www.`, `m.`, `youtube-nocookie.com`, `youtu.be`) | `watch?v=<11 chars>`, `shorts/`, `live/`, `embed/`, `v/`, `youtu.be/<id>` (shapes read by `youtube_transcript.video_id`, the reader capture uses) | `playlist?list=`, `embed/videoseries?list=` |
| Vimeo | `vimeo.com/<digits>`, `vimeo.com/<digits>/<hash>`, `player.vimeo.com/video/<digits>`, `channels/<name>/<digits>`, `groups/<name>/videos/<digits>`, `showcase/<id>/video/<digits>` | `showcase/<id>`, `album/<id>`, `channels/<name>` |
| Dailymotion | `video/<id>`, `embed/video/<id>`, `dai.ly/<id>` | `playlist/<id>` |
| Loom | `share/<32 hex>`, `embed/<32 hex>` | |
| Wistia | `<account>.wistia.com/medias/<id>`, `fast.wistia.net/embed/iframe/<id>` | |
| TED | `ted.com/talks/<slug>` | `playlists/<id>/<slug>` |
| Twitch | `twitch.tv/videos/<digits>`, clips (`clips.twitch.tv/<slug>`, `<channel>/clip/<slug>`) | `collections/<id>` |

Not a video, on purpose: `music.youtube.com`, a Twitch channel page (live or not), `ted.com/talks` (the listing) and a talk's `/transcript` page, Vimeo `ondemand`, user and category pages.

**The fields** (all on `Reference`, set by the writers below, none required):

| Field | Meaning |
| --- | --- |
| `medium` | `video`, or empty. |
| `evidenceLevel` | The field PPY-f8ff49 proposes (`primary`, `secondary`, `aggregation`, `unknown`). The medium rule writes **only `aggregation`**, for a playlist, showcase, album or collection address, and **only when the field is empty**: a value an editor or the decision model (PPY-3dcc04) wrote is never replaced, and the model will write this same field. |
| `playlistUrl` | A YouTube watch or `youtu.be` address that carries a valid `list` parameter names both a video and a playlist. It is **the video** (`medium` video, no aggregation), and the playlist's own address (`https://www.youtube.com/playlist?list=...`) is recorded here for the follow story (PPY-566e82). |
| `mediumFeedKey` | The sparse index key, below. |

**What `canonical_url` does to these addresses** (read 2026-11-04, not changed here). `link_exploration.canonical_url` and `monitoring.canonical_url` remove tracking parameters and session junk from one shared list, and the first also removes the default port. Both keep every other parameter in order, so `v` and `list` both survive (as do `ab_channel`, `t`, `si` and `index`). `reference_identity.canonical_url_key` sorts the parameters and keeps both. So `watch?v=A` and `watch?v=A&list=L` are two addresses, and so are `youtu.be/A` and `youtube.com/watch?v=A`: the same video can be two References. The medium rule does not depend on this (it reads the video id out of the address); a video-id identity key is a follow-up.

**Who sets it.** Every creating writer goes through `catalog.reference_record` or sets it itself, and a vote or an archive keeps the key right:

| Source | How |
| --- | --- |
| `papyrus references import`, assignment registration, email submission, Slack and console chat `Reference.create`, named imports | `catalog.reference_record` sets `medium`, `playlistUrl`, `evidenceLevel` and the key |
| Monitor delivery (`ReferenceIntake`) and the console and email hand-off Lambda (`find_or_create_source_reference`) | through `catalog.reference_record` |
| GROBID citation stubs | `medium_fields` (a citation has a DOI, not an address, so it is empty in practice) |
| Accession (next version, replacement lineage), a new version of a Reference | the stored fields are carried and the key is recomputed (`feed_keys`) |
| A vote from the newsroom (`reviewReferenceCuration`, `rateReferenceQuality`), the agent chat vote (`review_reference_curation`), auto-accept, auto-reject, retiring and restoring citation stubs, a superseded version, a corpus move | `mediumFeedKey` moves with the status (`medium_key_patch`, `referenceMediumKeyPatch`); a Reference with no medium never gets the field named |
| Existing References | `papyrus references backfill-medium` (below) |

`src/papyrus_content/reference_creation_paths_test.py` runs every creating path offline with a video address, an ordinary address and a playlist address.

**The index.** `mediumFeedKey` is `<corpusId>#<medium>#<pending|accepted|rejected>` for a current, not archived Reference that has a medium, and absent otherwise. `listReferencesByMediumFeedAndArrival` reads it by `feedArrivalAt`, newest first. See [the medium index](reference-feed-indexes.md#the-medium-index).

**The reader.** A public videos page or block reads only the accepted partition: see [the standard site](standard-site.md#videos-on-a-public-page).

**Backfill** (one-off, idempotent, **safe by default**, unlike the other backfills):

```bash
papyrus references backfill-medium --site KEY                        # preview: one line per Reference it would change, then counts; writes nothing
papyrus references backfill-medium --corpus-key KEY1,KEY2 --write    # writes
papyrus references backfill-medium --all-corpora                     # preview of every corpus the backend lists
```

It reads each current Reference by curation status (no scan), writes only `medium`, `playlistUrl`, `evidenceLevel` and `mediumFeedKey`, never a vote or a curation field, and a second run writes nothing. `--dry-run` is accepted and means the same as leaving `--write` off; `--write --dry-run` writes nothing.

**Relation to `Reference.type` (PPY-0cd359, not built here).** `type` (paper, article, repository, model ...) would name what the source *is* and be set at intake from the monitor and the source site; `medium` says how the address *delivers* it, and only where an address proves it. They overlap only where a `type` value is itself a medium: if `type` ever gains `video`, it should be derived from `medium` (and `medium` kept as the certain, address-only fact), rather than set twice. They are independent of source kind (PPY-f8ff49): a YouTube lecture can be primary, a Vimeo reel an advocacy piece. A playlist is an *evidence level* (aggregation), not a medium, which is why `medium` has one value and the playlist rule writes the evidence-level field.

## 4c. Outbound links, recorded at capture (PPY-31821c, 2026-11-04)

When a page is captured (the curation run, `papyrus references curate`, and monitor enrichment before a decision), the capture also keeps **every outbound link of the page**, nothing followed. `reference_outbound_links.extract_links(html, base_url)` reads the same HTML and returns one record per address, in page order:

```json
{"url": "https://...", "label": "link text", "kind": "content | navigation | footer | credit | profile", "listed": true, "position": 3}
```

* **content**: in the page's main content (`<article>`, `<main>` or `role="main"`), and not one of the kinds below. **These are the only links a follower may use.**
* **navigation**: in `<nav>`, `<aside>`, `<header>` (including an article's byline header, where a category link sits), `role` navigation, banner, complementary or search, a block whose class or id says menu, sidebar, share, social, breadcrumb, comments, related, pager, newsletter and so on, marked `rel="tag"`, `category`, `author`, `next`, `prev`, or anywhere outside `<article>`/`<main>` on a page that has one.
* **footer**: in `<footer>` or `role="contentinfo"`.
* **credit**: in a thanks passage: a block that starts "Acknowledgements", "Thanks:" or "Special thanks", says "I would like to thank" or "we are grateful", or sits under an "Acknowledgements", "Thanks", "Credits" or "About the author" heading. A sentence that only begins "Thanks to this method ..." is content.
* **profile**: a link to a person's profile on LinkedIn, X/Twitter, Facebook, Instagram, Threads or TikTok, wherever it is. A post link is content.
* `listed` is true for a link inside a list item (a series, a reading list). The same address twice keeps its first position and the best kind (content over the rest). Fragments, `mailto:`, `tel:`, `javascript:` and the page's own address are not recorded. Addresses are kept as found (including tracking parameters).

**Where it is stored.** The body is a `ModelAttachment` (role `metadata`, sort key `curation-links`, `curation-links.json`: `{version, pageUrl, links}`), so the Reference row and the card stay small; the card gets `links: {total, content}` and `current.linksSortKey`. A page with no links writes no attachment. A capture that failed for lack of text (`no_text`) still stores the links of the page it read; a failed fetch and a PDF store none. Monitor enrichment stores the body beside the captured text (`linksKey` on the enrichment row) and `copy_curation` writes the attachment on delivery.

**Honest limits.** It is a rule on what the page declares, not a judgment. A page with no landmarks or theme classes is read as all content; a "related posts" list inside the article body is content; a thanks passage that does not use those words is content; a theme that marks article metadata with its own class names can slip through. On the acceptance page (a saved copy of a public blog hub page, `procedures/newsroom/tests/fixtures/kjam-memorization-hub.html`) it gets exactly the intended answer: the series' articles and the YouTube playlist are content links, and the category page, the sidebar and footer links and the three thanks links are not. The page has **18** series articles in its ordered list (23 links in all: 18 articles, the category page, the playlist, three thanks links), not 17 as the story counted, so 19 content links.

## 4d. Video transcripts: the worker (2026-11-04)

YouTube blocks the addresses cloud functions run on, so transcripts are captured by `papyrus references capture-transcripts` (`src/papyrus_content/references_transcripts.py`), run by anyone signed in on a connection YouTube answers. Nothing depends on a particular machine, and there is no paid service or proxy.

* **What it removed from the cloud**: the transcript attempt in `reference_capture._youtube_capture` (the router's monitor enrichment, `papyrus.reference.curate` and `papyrus references curate` all go through `capture_source`), the fetch in `youtube_transcript.py` (it keeps only `video_id`), the `youtube-transcript-api` package from the router and worker zips (`infra/monitoring/build.py` `VENDORED`, with `requests` and the packages only it needed), the procedure-runner image, and the content-actions Lambda. The dependency is the optional extra `transcripts` of the Python package.
* **Which videos**: the content-needed index ([reference feed indexes](reference-feed-indexes.md#the-content-needed-index)): `<corpus>#video#needs_content#<status>`, accepted and pending by default, merged newest first. Never a scan; a captured video and a settled one are not in it.
* **How it saves**: the `correctReferenceCapture` action, as the signed-in caller (the editor on the edit is you), the same path as the capture panel. The transcript goes in as `text` with the assessment `incomplete` (the cloud capture it replaces was) and a note naming the command, so it is stored as `curation-edit-NNNN-text`, the state becomes `full` and the video leaves the list. A video with no captions (or private, removed or restricted) is recorded with the new `captureReason` argument (`no_transcript`, `unavailable`; `unsupported_platform` for a video site with no reader): it goes on the card as `capture.textReason`, the Reference's `captureReason` is set, the key leaves the index so the next run does not ask again, and the video stays `thin` in the To capture queue for a person, with the reason in words. The action takes exactly these arguments and no more; the editor is never a field of the request.
* **Politeness and stopping**: `--pace` seconds between YouTube requests (default 3), each video asked once per run. If YouTube refuses the connection it waits 60 seconds, then 300, and stops with exit status 3 saying the command needs a non-cloud connection (and, when a cloud environment variable is set, that this looks like a cloud machine). A video it could not read for another reason is reported and left for the next run. A transcript above 900,000 bytes is reported and left (the data API's request limit).
* **After a transcript is saved**: the same as after a pasted text. The summary is marked `stale`; the next `papyrus references curate` run (or the `papyrus.reference.curate` procedure where a router triggers it) rewrites it from the transcript, and the knowledge snapshot and suggestion vectors read the summary and the text from there. The worker needs no model, so it only prints a reminder; **nothing schedules that curation run today** (the router's enrichment of a Reference created by hand, section 2b, is separate: it runs on creation, not after a transcript).
* **The text is a third party's.** It is stored as the Reference's text and read as data by every step that follows (summary, vectors, search, reporter packs). Nothing the worker does executes or interprets it.

## 4e. Video thumbnails (2026-11-04)

A video's card shows the video's own picture, not whatever its page declared as `og:image`. `papyrus references capture-thumbnails` (`src/papyrus_content/references_thumbnails.py`, the checks and address rules in `reference_thumbnails.py`) does it, from the same signed-in, non-cloud lane as the transcript worker. Until now capture read only the page's preview metadata (`link_exploration._IMAGE_KEYS`, stored as the `preview` attachment with the remote address as `sourceUri`), and a public card loaded that address straight from the source. For a YouTube watch page that read is unreliable from a cloud address, and any remote address meant a reader's browser contacted the platform.

* **The address, with no key and no page fetch**: YouTube is `https://img.youtube.com/vi/<id>/hqdefault.jpg`, built from the id `youtube_transcript.video_id` reads. Vimeo, Dailymotion, Loom, Wistia and TED are asked once through their oEmbed address for `thumbnail_url` (the answer must be an https address on a public host). Twitch has no oEmbed endpoint, so a Twitch video has none.
* **What is refused**: a missing YouTube video answers 404 with a grey 120 x 90 picture, so a picture under 320 px wide is never taken (200 px for the oEmbed platforms, whose pictures can be small), nor anything Pillow cannot read as JPEG, PNG or WebP, nor more than 3 MB. A 404 or 410 on the picture, or a 401, 403, 404 or 410 from an oEmbed answer, is a settled "no thumbnail". A 403, 429 or 5xx on the picture host, or a network error, is "could not ask": nothing is recorded and the next run tries again.
* **Our own copy**: the picture is put in the site's media bucket at `media/assets/reference-thumbnails/<hash of the Reference lineage>-<12 hex of the picture's sha256>.<ext>` with the signed-in editor's identity-pool credentials (the same lane `papyrus stories save-version --images` uses; no AWS profile). The renditions function the site already runs sees the object. The path is published through the Reference's existing image: `Reference.thumbnailPath` holds the site path (or `none`), and the home-page snapshot's `image` for a video is `/<path>`, drawn by the videos block under the site's `urls.basePath`. **A video never publishes a platform address**: no copy yet means no image, even when its page declared one. An ordinary page keeps its preview address as before.
* **Recording**: the `correctReferenceCapture` action takes a `thumbnail` object alone (`{state: "stored", path, sha256, width, height, mediaType, platform, sourceUrl}` or `{state: "none", reason}`) and `reference_thumbnails.record_thumbnail` writes `thumbnailPath` on the Reference. It refuses a Reference that is not a video and one whose `preview` attachment says `via: editor` (an image an editor chose is never replaced; the snapshot keeps that image too). The write changes a field the home-page trigger watches, so one debounced snapshot run publishes a batch of them.
* **Once**: the worker reads videos through the medium index (`<corpus>#video#<status>`, accepted and pending by default, newest first, never a scan) and skips every video whose `thumbnailPath` is set, `none` included. The first run is the backfill; each later run only has work for videos that arrived since. A new version of a Reference (a corpus move or a changed record) carries the value.
* **Previews by default**: without `--write` it lists what it would fetch and contacts nothing.
* **Where it runs**: only where the platforms answer. YouTube refuses cloud addresses for transcripts and nobody has measured whether `img.youtube.com` answers them, so no cloud function fetches a picture. If a measurement later shows it does, `reference_thumbnails.fetch_thumbnail` and `record_thumbnail` are what the router would call at creation.

## 4f. A Reference is titled with its page, not its address (2026-11-05)

A Reference whose title is its own web address (measured on one site: 1,376 of 4,649 current References, 1,373 of them found by web-search monitors) shows the address on its card. The cause was a missing write, not a missing read. A web search that cites a page without naming it (the OpenAI and Gemini providers in `web_search.py` fall back to `title or url`) hands the monitor an item titled with the address, and the monitor keeps it as the new Reference's title. Capture and the link preview then read the page's real title (`Capture.page["title"]`, the preview attachment's `title`, both stored) and nothing wrote it back. The user-intake path is not affected: the editor gives the title.

* **The rule** (`reference_titles.py`): a title is replaceable only while it is empty or is an address; anything else is an editor's or the source's and is never replaced. The replacement is the page's own title, whitespace-collapsed and at most 300 characters, never an address and never a bot wall's or error page's stock title (`Just a moment...`, `403 Forbidden`). The row is read again before the write, so a title set in the meantime wins.
* **Once, when the Reference is created or captured**: `reference_images.attach_preview` (called after every new Reference: the monitoring router, user intake, email submissions) writes the title its preview page declared; the curation capture (`reference_curation._title_stage`) writes `page.title`. No pass over a corpus is scheduled.
* **The page**: `title` is in the home-page trigger's `CHANGE_FIELDS`, so a title change on a Reference a page can show rebuilds the page. A pending Reference nobody has predicted is on no page, so its title change schedules nothing; its first prediction is the change that shows it (the unpredicted rule).
* **A Reference with no title to take** (the page is blocked, unreadable or declares none): the stored title stays the address, and the public card (`home_page/export.displayed_title`) shows the preview's title if there is one, else a readable name made from the site name (or host) and the words of the address, such as `Lab Space: csa research note ai coding assistant attack surface`. It is display only, never stored, and is not presented as a title anywhere.
* **Existing References**: `papyrus references repair-titles` ([operator CLI](operator-cli.md)) previews by default, which References already hold the page's title in the stored preview or capture card (no fetch) and which need a fetch, and with `--write` records them through `correctReferenceCapture` (`pageTitle`). The backend must carry that action before the command writes anything.

## 5. Running it

**After a delivery (asynchronous, config only per site).** The router already starts a registered procedure
for each new Reference without waiting for it (`docs/procedure-runner.md`). Register the procedure once per
site and add a trigger to the publication's router config:

```bash
papyrus procedures register --file procedures/newsroom/reference_curation.tac --key papyrus.reference.curate
```

```json
{"publicationId": "anth-us", "appsyncEndpoint": "...", "openaiKeyParameter": "/amplify/shared/<appId>/OPENAI_API_KEY",
 "procedureTriggers": [{"procedureKey": "papyrus.reference.curate", "input": {"reference_id": "{referenceId}"}}]}
```

The trigger fires once per source item, never for a Reference that already existed, and a failed start
never fails the delivery. An Automation record for the trigger (`docs/automations.md`) can pause it or
cap concurrency. References that arrive another way (editor-selected email candidates start no trigger;
anything created before the trigger existed) are covered by the backfill.

**Backfill.**

```bash
papyrus references curate --corpus knowledge-corpus-anth-us --status pending --dry-run   # what would run
papyrus references curate --corpus knowledge-corpus-anth-us --status pending             # run it
```

Options: `--status pending|accepted|rejected|archived|all`, `--limit N`, `--force`, `--start-grobid`,
`--grobid-url URL`, `--json`. It needs the site's endpoint and write access like the other operator
commands (`PAPYRUS_GRAPHQL_ENDPOINT`, `PAPYRUS_GRAPHQL_AUTH=iam` with a profile that may write
`ReferenceAttachment` and `ModelAttachment`), and `OPENAI_API_KEY` for summaries. Run it again and it
touches only Reference rows that still need a stage; `--dry-run` reads cards and prints counts without fetching or calling a model.

## 6. What a deploy needs

Nothing here changes a model or a stored shape. To turn it on for a site:

1. **Procedure-runner image**: rebuild and deploy `infra/procedures` (`build_image.sh`, then the
   `papyrus-procedure-runner` stack), so the runner has `papyrus_curate_reference`.
2. **Runner access**: the runner's role grants AppSync only for Distinctive's API
   (`PublicationNewsrooms` in `infra/procedures/papyrus-procedure-runner.yaml`). Add each site's AppSync API
   id (anth.us: `2m5fh2nqlnfxlfg2mxepp7tdbm`).
3. **Per site**: register the procedure (command above); add `openaiKeyParameter` and the trigger to the
   site's publication in the router config (`infra/monitoring/seed_router_config.py`).
4. **content-actions**: deploy the site backends with the `correctReferenceCapture` mutation (additive
   schema change in `amplify/data/schema.ts` and `resource.ts`, and the new branch in
   `amplify/functions/content-actions/handler.py`).
5. **GROBID** (optional): a reachable GROBID service and `BIBLICUS_GROBID_URL` on whatever runs the
   curation. No GROBID is deployed in `papyrus-production` today (no ECS service, Lambda or stack; the only
   ECS cluster runs the weekly knowledge-run jobs). The runner Lambda cannot host the container. Until one
   exists, papers get text, signals and a summary, and the typed skip `grobid_not_configured`; run the backfill from a
   machine with `--start-grobid` (Docker) to fill in papers.

### What the medium and the outbound links need per site

Nothing to turn on for the fields: they are written when the site's backend has them. **Order** (the same as the feed keys): 1. deploy the site's data API (the schema change below: four optional fields and one index); 2. deploy the engine that carries the writers (router, tools, chat); 3. `papyrus references backfill-medium --site KEY` (preview), then with `--write`; 4. (optional) turn on a videos page ([the standard site](standard-site.md#videos-on-a-public-page)). A router or chat that reaches a site before its schema is safe: a write for an ordinary address names no new field, a write that names the medium fields to a site without them is sent again without them (`MEDIUM_REFERENCE_FIELDS` in `graphql_authoring.py`; the backfill fills them in later), and reads drop the new fields on such a site (`NEWER_REFERENCE_FIELDS`). The chat's own GraphQL path (`review_reference_curation`) and the TypeScript Lambdas have no such retry, so deploy the data API first for a site where editors or agents vote on videos. The data API change adds **one** global secondary index to the `Reference` table (`mediumFeedKey`/`feedArrivalAt`); DynamoDB allows one index change per deploy per table, so it must not share a deploy with another index change on `Reference`. No IAM change: every worker that writes these fields already holds `createReference`, `updateReference`, `createReferenceAttachment` and the attachment upload pair (`procedures/newsroom/tests/test_reference_medium_iam.py` fails if one is lost), and no worker role reads the medium index.

## 6a. Stories based on a Reference (core rules)

A Reference is where a story can start. Whichever path makes a story from one, two rules hold. They are part of the automated
newsroom process, not a convention of one command. Executable specs: `features_backend/story-from-reference.feature` (the process),
`features/newsroom-story-references.feature` (the newsroom views); tests: `procedures/newsroom/tests/test_story_from_reference.py`.
Code: `src/papyrus_content/story_from_reference.py`.

1. **The story is linked to the Reference.** One `SemanticRelation`, predicate `uses_evidence` (relation type
   `semantic-relation-type-uses-evidence`), from the story's lineage to the Reference's lineage, with metadata role `based_on`. The
   link is by lineage ids, so it survives new versions of the story and of the Reference. A story can be based on several References.
   `consulted` and `cited` stay the roles for References read during reporting and cited in the text; a later link never weakens
   `based_on`. The newsroom story view (References) lists each Reference with its title, site, preview image, a link that opens it
   and a link to the original page, marked "Based on" in words and with an icon. The Reference view lists the stories based on it.
2. **The story has its own content.** The body is seeded from our words: the cited body of the generated idea (or of an older `story_draft` Proposal), or a brief for the
   copywriter. It is never the Reference's captured or extracted text, and it goes through the copywriting and copy-editing stages.
   **The copy guard** refuses to save a seeded body that shares `COPIED_RUN_WORDS` (12) or more consecutive words, ignoring case,
   punctuation and web addresses, with any captured text (`extracted_text` attachment) of a Reference it is based on
   (`StoryCopiedFromReference`; nothing is written). If the captured text cannot be read on the machine, the result says
   `copyCheck: unchecked` instead of passing silently. A short quotation is fine.

The image is the one thing a story may take. A `post` (`SEEDED_IMAGE_ITEM_TYPES`) gets the Reference's preview image (the
`preview` `ReferenceAttachment`, sort key `002-preview`) as a first line `::image{src="<preview address>" alt="<Reference title>"
credit="Image: <site>"}` in its `bodyMarkus`, and `seededImage: {hosted: false}` in its front matter. The address stays remote and
credited: we do not copy a third party's picture into our media (rights, and a stale copy) and we do not hide where it came from.
The illustration stage replaces it, or hosts a licensed copy as a `MediaAsset`. Other types get no image, and neither get a post
whose Reference declared none.

Paths that make a story from a Reference, and what each writes:

| Path | Body | Image | Link |
| --- | --- | --- | --- |
| `papyrus references promote` (monitor record to a draft article) | a stub of the record's own facts | none (article) | `based_on` |
| `story_from_story_draft` (an approved `story_draft` Proposal filed before ideas became Items; new ideas are Items that move through the stages) | the draft's own cited body | post only | `based_on` for each `reference:` target |
| `papyrus stories create --reference ID` and the Tactus `papyrus_create_story(based_on_references=...)` | the story's summary, as before | none | `based_on` |
| `papyrus assignments run-copywriting` (reporting packet to draft) | the packet's own facts, copy-checked | none | `based_on` for the packet's accepted References |
| The editor's **Create Story** (Reference card and detail; `createStoryFromReference`, `story_from_reference.create_story_from_reference`) | the Reference's generated summary, then `Source: [title](address), site.`; the source line alone when there is no summary | the preview, for any type (below) | `based_on` |

Stories made before this rule: `papyrus items link-references --site KEY [--role consulted|cited|based_on] [--dry-run]` finds each
story whose body (or front matter `sources`) links to the `sourceUri` of a Reference of the site, comparing addresses without
tracking parameters, fragment, `www.` and trailing slash. A story that matches one Reference is `based_on` it; one that matches
several cites them. Safe to repeat.

### Create Story (PPY-3c11bd)

Every Reference card and detail has one **Create Story** action (Lucide `FilePlus2`). One tap calls the `createStoryFromReference` mutation
(content-actions Lambda, content-write groups), which calls `create_story_from_reference`, which calls `create_story_from_references`, and the editor opens the Story.

* **The Story**: the site's default Story type (`storyTypes.default` in its `projection.json`, else `article`; the editor changes it in the Story, see [story types](content-item-lifecycle.md#story-types-and-sections)), stage `copywriting`, section only when the site has exactly one enabled section, title from the Reference.
* **The text**: the Reference's generated summary (the idea pipeline's summary chain: the `reference_summary_<N>_tokens` Message, the `curation` attachment, the
  preview description), then the source line. No summary: the source line only. Never invented text. This is a deliberate exception to "never seeded from the
  Reference's text": the summary is our generated words, and the copy guard still applies, so a summary that shares 12 or more words in a row with the captured
  text is left out (`seededFrom.summary: withheld`) and the Story starts from the source line.
* **The image**: the preview already found for the Reference, for any story type (the rule above is widened for this action only), as a remote credited address,
  recorded in the front matter (`seededImage`: `url`, `credit`, `page`, `hosted: false`). It is another site's picture: the editor shows a plain note that the
  rights must be checked before publishing (`components/seeded-from-reference-note.tsx`, shown while `seededFrom` is in the front matter).
* **The link**: `based_on`, so the Story appears under "Stories based on this Reference" and in the Story's References. A Reference that already has a Story is not
  given a second silently (`created: false, existing: [...]`); "Create another" sends `again`.
* **The vote**: creating a Story never changes the status by itself. The button, not the backend, records the editor's Accept for a *pending* Reference through the
  Accept path (a human vote, no reason, which trains the Cyclotron like any other vote; Ryan, 2026-11-02: "if I create the story myself from the reference, then
  yes, I accept the story"). A rejected Reference is not overturned and its button says so; an accepted one needs nothing.
* **The idea pipeline**: a Story `based_on` the Reference removes it from the single-item candidates (`hasStory`), so it is not also drafted as an idea.

The p.apyr.us documentation should gain a short "Create a Story from a Reference" page (follow-up PPY-3c11bd).

## 7. Not done here

* Whether a capture is complete: a Cyclotron classifier trained on `card.labels`.
* Biblicus-quality extraction (`extracted_text` in corpus storage) for pending References: the curated text
  lives on `ModelAttachment`s, so the topic runs that read `extracted_text` attachments do not see it. Accepted
  References still get that text through `process-fetch-url-text`. **The knowledge query does read it now**
  (PPY-caa222, [Where a query reads a Reference's text](internal-knowledge-research.md#where-a-query-reads-a-references-text)):
  a correction (`curation-edit-*`) beats an `extracted_text` attachment, which beats the machine `curation-text`.
  Still not done: the **vector index** (`knowledge-vector-index`) and the topic-model runs read only `extracted_text`, so a Reference whose text was
  only captured has a summary vector but no passage vectors until its text is also indexed (a follow-up; it needs a re-index, not a deploy).
* Publication doctrine in the summary prompt; the citation graph from GROBID references (stored as fields,
  not yet linked as References).
