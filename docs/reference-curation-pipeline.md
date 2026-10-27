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
| 1 | Delivery of a routed item | `monitoring_router.deliver_reference` -> `monitoring_intake.ReferenceIntake` | Each router sweep, per publication that got a positive decision | Router Lambda (`papyrus-monitoring`) | A `Reference` with `curationStatus = pending`, a provenance `Message`, the relevance decision relations. **No text, no summary, no GROBID.** |
| 2 | Procedure triggers | `Router.start_procedures` -> `procedure_runner.handler` | Right after step 1, once per new Reference (never for a reused one) | Procedure-runner Lambda (`papyrus-procedure-runner`, container, 15 min) | A `ProcedureRun` in the site's newsroom and a `TRIGGER#` row. **No publication of the `hn` router has `procedureTriggers` today**, so nothing is started. |
| 3 | Preview card | `reference_images.references_enrich_images` (link exploration) | By hand: `papyrus references enrich-images` | A developer machine or any CLI host | `ReferenceAttachment` role `preview`, sort key `002-preview`: image URL, description, site name. |
| 4 | Find the source | `references find-fetch-url-text` (`reference_url_text`, `source_site_plugins`) | By hand (utility worker or CLI; refuses Lambda) | Machine with Biblicus | A `source` `ReferenceAttachment` (the PDF) in corpus storage. |
| 5 | Extract text | `references process-fetch-url-text` -> Biblicus `url-text` extractor; PDFs through GROBID; an LLM article filter (default `gpt-5.4-mini`) for HTML | By hand, usually after a Reference is accepted or for a batch an operator picks | Machine with Biblicus and a **local GROBID container** (`grobid/grobid:0.9.1-crf`, `127.0.0.1:8070`, started by `biblicus.grobid_runtime`) | `ReferenceAttachment` roles `extracted_text_raw` and `extracted_text` in corpus storage (`corpora/...`), then the citation graph: authors, cited-Reference stubs, `cites` relations. |
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

## 7. Not done here

* Whether a capture is complete: a Cyclotron classifier trained on `card.labels`.
* Biblicus-quality extraction (`extracted_text` in corpus storage) for pending References: the curated text
  lives on `ModelAttachment`s, so the topic runs that read `extracted_text` attachments do not see it. Accepted
  References still get that text through `process-fetch-url-text`.
* Publication doctrine in the summary prompt; the citation graph from GROBID references (stored as fields,
  not yet linked as References).
