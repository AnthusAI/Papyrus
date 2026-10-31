# Home page: public data files

> Status: Beta, phase 1 of the `homePage` epic (PPY-1b83d3). This page covers the data files, the fields, the task and the CLI. The Reference grids are described under "The references include"; the freshness trigger is described under "Freshness"; the Message threads are described under "Message threads".

A Papyrus site can show part of its curation to visitors. The first piece is a public JSON file of the site's accepted References and of the pending ones the Cyclotron expects an editor to accept. It is served next to the pages, for example `https://anth.us/_data/home-page/references.json`.

## Data files

| File | Holds |
| --- | --- |
| `_data/home-page/references.json` | `generatedAt`, `corpus`, `fields` (the published field names) and `references`, accepted ones newest-accepted first, then recommended ones newest arrival first |
| `_data/home-page/threads.json` | With `homePage.threads.enabled`: `generatedAt` and `threads`, most recently active first (see "Message threads") |
| `_data/home-page/threads/<key>.json` | With `homePage.threads.enabled`: one file per public thread with its Messages in sequence |

The file lives under the site's URL policy, so `urls.basePath` is honoured (`<basePath>/_data/home-page/references.json`). Reconcile never calls it an orphan.

## Which References

- **accepted**: `curationStatus` accepted and `versionState` current.
- **recommended**: pending (`<corpusId>#unrated`) and current, whose live P(accept) is at least `homePage.references.recommendedThreshold` (default 0.5, the threshold the console already uses to skip predicted rejects). P(accept) is the console's `acceptProbability`: the confidence of the current `relevance_decision_is` decision when it chose the positive label, one minus it otherwise, 0.6 when no confidence was recorded and 0.5 with no decision.
- Rejected, archived and superseded References are never exported.

## Public fields

`key` (the first 12 hex characters of the SHA-256 of the lineage id, so no id appears), `status` (`accepted` or `recommended`), `title`, `authors`, `url`, `host`, `mediaType`, `sourceDate`, `sourceUpdatedAt`, `retrievedAt`, `importedAt`, `arrivedAt`, `acceptedAt` (accepted only), `decidedAt`, `section` (the section's title), `reasonCode`, `actor` (`human`, `cyclotron`, `rule`, `agent` or `catalog`; never who), `shareable`, `confidence` (live P(accept), two decimals), `predictedAcceptProbability` (the original prediction), `predictionDecidedAt`, `inboundCitationCount`, `outboundCitationCount`, `versionNumber`, and from the preview attachment `image`, `summary` and `siteName`.

The allowlist is `PUBLIC_REFERENCE_FIELDS` in `src/papyrus_content/home_page/export.py`. `homePage.references.fields` is `"all"` (every field above, the default) or a list of those names that includes `key` and `status`; any other name is a build error.

Never published, each with its reason in `EXCLUDED_REFERENCE_FIELDS`: identity (who decided, who relayed, an editor's private note, intake provenance), the captured text of the source and its storage details, and internal ids and keys. A unit test proves every field of the Reference model is either published or excluded, exactly once, and the Gherkin scenarios scan an export with the reader-privacy scanner. `summary` is the preview's description clipped at `publicData.summaryCharacters` (default 240) on a sentence boundary. Text is also scrubbed of anything shaped like an email address, a UUID or a site subject, and a Reference whose address would carry one in its path is left out.

## Settings

The `homePage` key of `projection.json`; a site without it has no home-page behaviour. Unknown keys are a build error that names the key.

```json
{"homePage": {"layout": "latest", "perSection": 4,
  "references": {"corpus": "knowledge-corpus-example", "fields": "all", "defaultCount": 6, "recommendedThreshold": 0.5},
  "threads": {"enabled": false, "authors": "handle", "anonymousLabel": "Editor"},
  "freshness": {"debounceSeconds": 300, "intervalHours": null, "purge": false}}}
```

`layout: "sections"` (with `perSection`, `homeLead` and `homeSections`) and the `urls.sections.<name>.index` setting are described in [Section index pages and a home of sections](building-a-papyrus-static-site.md#section-index-pages-and-a-home-of-sections); a site that does not set them is unchanged.

`references.corpus` defaults to the corpus of the site's publication key (`PAPYRUS_PUBLICATION_CORPUS_KEY` in the Lambda, `--site KEY` on the CLI).

## The task

`home-page-snapshot` runs in the content-actions function (`{"projectionTask": {"task": "home-page-snapshot"}}`). Under the projection lease it builds the document, writes the file only when its content changed (the `generatedAt` stamp alone is not a change), then re-renders only the listing pages whose inputs changed and, with `freshness.purge`, purges the file on the edge. A site without a `homePage` setting ignores the task. The report is `{written, unchanged, references, pagesRewritten, purged}`.

## The CLI

```bash
papyrus home-page snapshot --site KEY --site-bucket BUCKET --static-dir SITE/web --auth iam --amplify-outputs FILE
papyrus home-page snapshot --site KEY --out DIR          # a local directory
papyrus home-page snapshot --site KEY --dry-run          # counts and file size; writes nothing
```

Mutation commands write by default; `--dry-run` prints the report and the size of the file only. `--static-dir` points at the site checkout so its `projection.json` (including `urls.basePath`) applies; without it the defaults are used.

## The references include

`::include{kind="references" select="recent|confident|recommended" count="6" [section="Tools"] [card="tile|row"] [heading="..."] [more="/path/"] [empty="..."]}` places Reference cards on an authored page, rendered at projection time from `_data/home-page/references.json`. A site needs the `homePage` setting; without it the include is a build error that names the page file.

- `recent`: accepted, newest accepted first. `confident`: accepted, highest Cyclotron confidence first (none recorded counts as 0.5). `recommended`: not yet accepted, highest confidence first. Ties go to the newest arrival, then the key.
- `count` defaults to `homePage.references.defaultCount` (6). `section` keeps References whose section label (or a configured section name's label) matches.
- Each page has one ledger. The first component to place a Reference keeps it; a later component skips it and refills up to its `count` from its own ordering. Nothing is shared between pages.
- A card shows confidence as "93% confidence" with a Lucide `gauge` icon and a five-segment meter drawn by shape (filled or outlined). A recommended card says "Recommended by Cyclotron, not yet accepted" with a `sparkles` icon. Cards use flat tones and rounded corners, with no borders. A component with nothing left draws the `empty` text, or nothing.
- The Markdown twin keeps the include line as written. A page's digest folds in the snapshot digest, so a changed snapshot rewrites only the pages that place a references include.
- `pages[].path`, a section `base` or a collection `base` equal to `_data`, `_plugins`, `_papyrus`, `_next` or `api` is a build error. `newsroom` is also reserved on sites whose edge routes the CMS.

## Message threads

With `homePage.threads.enabled` the same task also writes `_data/home-page/threads.json` and one `_data/home-page/threads/<key>.json` per thread, and `::include{kind="threads" select="recent" count="8" layout="list|grid" [heading="..."] [empty="..."]}` places them on an authored page, rendered at projection time. Today only `select="recent"` (most recently active first) exists. `count` defaults to `homePage.references.defaultCount`. The task owns `_data/home-page/threads/`: it deletes the file of a thread that is no longer public. Nothing reads the per-thread files yet; they are the seam for the later forum pages.

- **Public threads**: `threadKind` is `reference_conversation` or `story_conversation`, `status` is `active`, and the anchor is public: `reference#<lineageId>` whose public key is in the current `references.json`, or `item#<lineageId>` of a published Story that has a page. Unanchored and other-kind threads, and threads on rejected or archived References, are never exported. A thread with no public Message is left out.
- **Public Messages**: `status` active, `messageKind` comment, never deleted. A deleted or moderated Message is omitted entirely and the count excludes it, because its text stays in the database after a soft delete.
- **Message fields**: `key` (first 12 hex characters of the SHA-256 of the id), `at`, `edited`, `text` (the Message as written, with raw HTML removed and anything shaped like an email address, a UUID or a site subject scrubbed) and `author`. Thread entries carry `key` (hashed the same way), `title`, `anchor` (`{kind: "reference", key, title}` or `{kind: "story", url, title}`), `messages` (the count), `lastAt` and `latest` (the latest Message). The author is `{"handle": "ryan"}` when the person set a public handle in their profile settings and `homePage.threads.authors` is `handle` (the default), otherwise `{"label": "Editor"}` (`homePage.threads.anonymousLabel`) or `{"label": "AI"}` for a Message that was not written by a person. `authors: "none"` always uses the label and reads no profile. Never written: `authorSub`, `authorUserProfileId`, `authorLabel`, `deletedBySub`, `createdBySub`, `createdByLabel`, `metadata`, `responseOwner` or any record id.
- **The card** names what the thread is on in words and a Lucide icon (`link` for a Reference, `file-text` for a Story, whose title links to its page), the title, "N messages" beside a `message-square` icon, the date of the last activity, the latest Message as plain text clipped at a sentence boundary (`publicData.summaryCharacters`, default 240) and "by" the author. Flat tones, rounded corners, no borders.
- **De-duplication**: threads claim `thread:<key>` in the page ledger, so two threads includes on one page never repeat a thread, and they do not interfere with the Reference cards.
- **Freshness**: with `threads.enabled`, the `home-page` plugin also reads the Message table's stream into the same trigger. A new comment, or a change of its `status`, `content`, `editedAt` or `deletedAt`, opens the same debounce window. A Message stream that another feature already switched on is reused, not replaced.

## Freshness

Curation changes reach the pages without anyone running a command. The backend plugin `home-page` (`backend.plugins: ["home-page"]` in `papyrus.config.ts`) wires four things, and only for a site that lists it: every other site synthesizes exactly what it did before.

1. The DynamoDB stream on the Reference table (old and new images). Reference is a realtime model, so the table already streams old and new images; the plugin only asks for the same specification and consumes the stream, so the table itself is not updated.
2. A small trigger function, `homePageTrigger` (Python 3.12, arm64, 256 MB, 30 s). It reads batches of up to 100 records (waiting at most 10 seconds to fill one) and ignores a record unless `curationStatus`, `feedStateKey`, `predictionSortKey`, `versionState`, `title` or `curationSectionId` differs between the old and new image. An insert or a removal counts as a change.
3. A trailing-edge debounce. The first change in a quiet period claims a slot with a conditional write in the shared projection lock table (partition key `publication`, value `home-page-debounce#<site scope>`, expiring by TTL) and creates a one-off EventBridge Scheduler schedule `papyrus-home-page-snapshot-<site scope>-<epoch>` at the end of the window. It invokes content-actions with `{"projectionTask": {"task": "home-page-snapshot"}}`, runs once and deletes itself. Changes inside the window find the slot taken and schedule nothing, because the run reads them all. If creating the schedule fails the slot is released and the batch is retried by the stream. The site scope is a short hash of the site's content-actions function name, so sites that share an account never share a slot or a schedule name.
4. The run itself: the snapshot is written only when it changed, and `project_stale_listings` re-renders only the pages whose digest includes the changed selection. A burst of ten accepts costs one run.

| Setting | Default | Meaning |
| --- | --- | --- |
| `homePage.freshness.debounceSeconds` | 300 | Quiet time between the first change and the run. The default equals the HTML `s-maxage` the writers set (`PAPYRUS_HTML_S_MAXAGE_SECONDS`, 300): with purge off a page can never be fresher than its edge lifetime, so a shorter window buys nothing. Lower it together with `publication.cache.htmlSMaxAgeSeconds`. |
| `homePage.freshness.intervalHours` | none | Adds an EventBridge rule that runs the snapshot at this interval even without changes, as a safety net. Off by default. |
| `homePage.freshness.purge` | false | The task invalidates the snapshot file on the edge after writing it. Invalidation paths are free for the first 1000 a month, then billed per path. |

The plugin reads `debounceSeconds` and `intervalHours` from the site's `projection.json` when the backend is synthesized (and the task reads the whole block at run time), so there is one place to set them. A plugin request may override the first two: `plugins: [{ name: "home-page", debounceSeconds: 120 }]`. The plugin refuses to synthesize when the site has no publication or its `projection.json` has no `homePage` setting, because the stream would schedule runs that the task ignores.

To turn it on for a site: add `homePage` to `projection.json`, add `"home-page"` to `backend.plugins`, and deploy the backend. The plugin needs no other setting. The trigger has no dead-letter queue: a batch that still fails after two retries is dropped, and the next change (or the interval rule, when set) catches up, because every run reads the whole table state.
