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
them). The writer is the `setReferenceStars` mutation (`amplify/functions/category-action`, editor groups, like `reviewReferenceCuration`); Python reads with
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
* **YouTube**: a video link (`watch`, `youtu.be`, `shorts`, `live` or an embed, on `youtube.com`, `m.youtube.com` or
  `youtube-nocookie.com`) is captured from its transcript (`youtube-transcript-api`, English when offered). `capture.textVia`
  is `youtube_transcript`. YouTube often refuses cloud addresses; then the page's own text (its description, or its title when
  there is nothing else) is kept, `capture.textVia` is `youtube_description` and `capture.textReason` says why: `blocked`,
  `no_transcript`, `unavailable`, `unreadable` or `library_missing`. Every attempt prints one JSON line
  (`{"youtubeTranscript": "captured" | "fallback", "videoId", "reason", "characters"}`) so CloudWatch can count the blocks.
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

Owner `reference` / `Reference.id`, role `metadata`, so list them with
`modelAttachmentsByOwnerRoleAndSortKey(ownerId = Reference.id)` or read one by id
(`model-attachment-reference-<safe_id(Reference.id)>-metadata-<sort key>`, `createModelAttachmentDownload`):

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
 "note": "optional, at most 4000 characters"}
```

The editor is the signed-in caller; the request cannot name one. Result: `{ok: true, referenceId, status,
edits: [...], label, summaryStale}`, or `{ok: false, errors: [{code: "correction-rejected", message}]}`.
At least one of `text`, `grobid`, `assessment` is required. Replacing text marks the summary `stale`; the next
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
  References still get that text through `process-fetch-url-text`.
* Publication doctrine in the summary prompt; the citation graph from GROBID references (stored as fields,
  not yet linked as References).
