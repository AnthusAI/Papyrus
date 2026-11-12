# Fallback and workaround audit

Standing rule (Ryan, 2026-11-12): no workarounds, no fallbacks, no compatibility shims. Fix causes properly; one correct path that fails
clearly. Related issue: PPY-99738c (the four shims named there are rows 1-5 below).

Method: a keyword sweep of `src/`, `amplify/`, `lib/`, `components/`, `infra/` and `scripts/` for fallback, workaround, shim, legacy,
compat, "for now", temporary, hack and deprecated (1,311 matching lines outside tests), a second sweep for `??`/`||` environment
defaults and for catch blocks that return a default, then a read of every cluster that was not obviously benign. Lines are grouped into
clusters; each row is one cluster. Most raw hits are class d (`tempfile`, the `deprecated` category status, layout `fallbackPenalty`,
font stacks, the Alexa `AMAZON.FallbackIntent`, retry/backoff, one-shot migration commands that name "legacy" as the thing they migrate).
Line numbers are for develop at `bc3de5a2`.

Classes: **a** dead or unreachable; **b** a silent substitute for something that should be required (should fail clearly); **c** a
compatibility alias or old-shape reader with live callers or live data; **d** legitimate, not a fallback.

"Status" says what happens to the row: PR names the removal PR; **Ryan** means a released site or live data still depends on it and the
decision is his; blank means left alone (class d).

| # | file:line | what it does | class | proposed removal | risk | who depends on it | status |
|---|---|---|---|---|---|---|---|
| 1 | lib/console-chat-client.ts (old :60-124, :411-462, :748-834) | `__type` introspection of Query, Message and CreateMessageInput picks fields and queries at run time; three `*_LEGACY` reduced field sets and queries | b | Delete; one fixed typed query per operation | low: the fields and indexes are in `amplify/data/schema.ts` | components/papyrus-console-shell.tsx only | PR 1 |
| 2 | lib/console-chat-client.ts (old :291-317, :1097-1131) | Every read retried under `apiKey` after a `userPool` failure | b | userPool only (Message and MessageThread grant no public key) | low | console shell | PR 1 |
| 3 | lib/console-chat-client.ts (old :486-504, :523-571, :904-1005) | A failed thread list derives threads from messages; failed `createMessageThread` returns the input as if saved; failed `updateMessageThread` invents a thread; `isUnavailableQueryError` treats "unauthorized" as "schema missing" | b | Raise the backend error | low | console shell | PR 1 |
| 4 | lib/console-chat-client.ts (old :510-521) | If no message has a thread id, every message is shown in every thread | b | Query `listMessagesByThreadAndSequence` for the thread | low | console shell | PR 1 |
| 5 | lib/console-chat-client.ts (old :659-670), components/topic-steering-workspace.tsx:1502,1507,1582-1587 | `typeof model.onCreate !== "function"` returns a no-op subscription / "model unavailable". In the steering workspace the probe is not harmless: `SemanticRelation` is `modelWithoutSubscriptions`, so the probe always trips and References realtime never starts on any site | b | Console: delete the probe. Steering: delete the whole realtime effect, or make SemanticRelation realtime (against the avoid-AppSync-realtime rule); removing only the probe would loop reconnects | low for the console; the steering workspace is different, see below | topic steering workspace, console shell | PR 1 (console); steering is Ryan's decision |
| 6 | lib/graphql-content-repository.ts:564 | `typeof editionModel.listPublishedEditionsByStatusAndPublishedAt === "function"` else the editionDate index | b | Use the deployed index (schema.ts); the drafts source maps the same query to its edition-date index explicitly | low | every reader | PR 2 |
| 7 | lib/graphql-content-repository.ts:460-492 | `pruneLayoutPlanUnavailableItems` drops plan blocks whose items did not load and only warns | b | Throw: a missing plan item is a publishing error (AGENTS.md) | medium: a plan that points at an unpublished item now fails the build instead of rendering without it | every publication build | PR 2 |
| 8 | lib/graphql-content-repository.ts:1174 | `getFallbackImage` ("Fallback editorial image.", credit "Fallback image"), no callers | a | Delete | none | none | PR 2 |
| 9 | src/papyrus_newsroom/reference_curation_signals.py:2749-2759 | Catches `FieldUndefined` for `listReferencesByNewsroomFeedAndImportedAt`, falls back to `list_references_by_corpus` | b | Call the index; let a mismatch raise; an empty feed is an empty list, not a corpus scan | low: new References carry `newsroomFeedKey: references` | newsroom CLI | PR 2 |
| 10 | components/news-desk-taxonomy-client.ts:2285-2345, :319-330, :2360-2420 | Reference page loader: imported-feed query, on failure or empty a "legacy feed" query, then a table-scan `listReferences` fallback with client-side sort; empty indexed result silently triggers the next | b | Keep the indexed loaders (imported feed, status index, merged status page); delete the legacy-feed and table-scan loaders | medium: a Reference lacking `newsroomFeedKey` or `importedAt` no longer appears under the imported order (every creation path in the repo sets both); also removes an O(N) read (indexes-over-scans rule) | news desk reference list in every site | PR 3 |
| 11 | components/news-desk-taxonomy-client.ts:1022 | `loadDashboardSlice` logs and substitutes an empty slice when a dashboard query fails | b | Fail the slice with a visible error | medium: the dashboard shows an error state instead of partial numbers | news desk dashboard | listed; PR 5 if time |
| 12 | lib/story-stage-query.ts:10-30 | Board column reads the `stage` index "for a site whose backend has no head stage index, or whose index is not filled yet" | b | Head index only | medium: needs the head backfill done on every site first | news board on every site | Ryan (confirm backfill) |
| 13 | components/topic-steering-workspace.tsx:392,646-654,842-1056,1371 | Section short-title fallback table; dashboard sections/proposals fall back to a second snapshot when the first is empty | b | One source of sections | medium | steering workspace | listed |
| 14 | components/reference-capture-client.ts:51-106 | Falls back to the older `extracted_text` attachment when a card has no curation text | c | Migrate old rows, then delete | medium: old References would show no text | released sites' data | Ryan (needs data migration) |
| 15 | lib/content-item-lifecycle.ts:53-89, src/papyrus_content/content_item_lifecycle.py:34,226 | Old stage names are read as their replacement (`LEGACY_CONTENT_ITEM_STAGE_ALIASES`, `legacyStageKeysToLoad`) | c | Migrate rows to new stage names, then delete | medium | stored Items on every site | Ryan |
| 16 | lib/amplify-server-runtime.ts:79-93 | Reads Cognito ids from the old snake_case `auth` block of amplify_outputs when `Auth.Cognito` lacks them | c | Require the current shape | low-medium: sites with old outputs files fail at build with a clear message | sites pinned to old Amplify outputs | Ryan (released sites) |
| 17 | lib/newsroom-section-routing.ts:6-10 | Old `?tab=categories` query reads as `topics` | c | Delete the alias | low | bookmarked URLs | PR 5 |
| 18 | components/news-desk-taxonomy-client.ts:3211-3227, amplify/functions/newsroom-summary/handler.ts:192-206 | Summary facets merge the old flat count fields into the new shape | c | Read the new shape only (both sides ship together) | low if the summary function is deployed with the client | newsroom summary | PR 5 |
| 19 | components/needs-me-feed.tsx:282,319,443 | `legacyAuto` list added to the auto count | c | Delete if no caller passes it | low | check callers | PR 5 |
| 20 | components/newsroom-assignment-detail.tsx:71 | Shows an "Old section" option for a desk value no longer offered | c | Keep: it shows data rather than hiding it | none | editors | d |
| 21 | amplify/functions/category-action/reference-links.ts:229-233 | Looks up the old `related_to` relation id before the `tagged_with` one | c | Delete after `papyrus relations migrate-concept-tags` has run on every site | medium | live relations | Ryan |
| 22 | src/papyrus_content/concept_tag_migration.py, concept_tags_commands.py, relations_commands.py, messages_commands.py (`migrate-insights`, `*-legacy-comments`), convert_bodies_commands.py | One-shot migration commands and their `legacy` readers | d | Remove each command after its migration has run everywhere | none now | operators | d (retire later) |
| 23 | amplify/functions/shared/email-mime-intake.ts:164-174, src/papyrus_newsroom/email_mime_intake.py:219 | Second MIME parser substitutes text/subject/links when the first yields none | b | One parser, fix its gaps | medium: messy real mail | inbound email on every site | listed |
| 24 | src/papyrus_newsroom/email_submission_replies.py:813-919 | `chat_fallback` reply mode when a filing reply cannot be built | b | Report the failure to the editor | medium | email intake | listed |
| 25 | src/papyrus_newsroom/slack_agent.py:22-40 | Reads `SLACK_SIGNING_SECRET`/`SLACK_BOT_TOKEN` when the `PAPYRUS_` names are unset; returns "" when none | b | One name each; raise naming the missing setting | low | Slack agent deploys | PR 6 |
| 26 | src/papyrus_content/assignments_workflow.py:64-75 | Run directory falls back to the system temp directory when the repo is not writable | b | Take the run directory from configuration; fail when unwritable | medium: Lambda must pass its writable dir | assignments workflow in Lambda | listed |
| 27 | src/papyrus_content/steering.py:216-235, corpus_storage_paths.py:17-63, renditions_commands.py:82 | Tries the old mixed-case and token corpus folder names when the configured path does not exist | c | Migrate folders, then delete | medium | local corpus checkouts | Ryan |
| 28 | src/papyrus_content/monitoring_router.py:87-94, :377 | Accepts the `cyclotron-publication/v1` contract and discoveries queued by "the earlier editor-gated path" | c | Delete once the queue has drained | low | in-flight jobs | listed |
| 29 | src/papyrus_content/monitoring_router.py:2936, infra/monitoring/seed_router_config.py:13 | Criteria fingerprint "fallback" when unknown | b | Raise on an unknown fingerprint | medium | monitors | listed |
| 30 | src/papyrus_content/monitoring_stories.py:234,271,308,343 | `ItemStore(..., legacy=legacy_story_drafts)` second read path for old drafts | c | Migrate drafts, delete | medium | monitors | Ryan |
| 31 | src/papyrus_content/email_quarantine.py:27 | `LEGACY_REJECTION_CODES` | c | Migrate quarantine rows, delete | low | quarantine list | listed |
| 32 | src/papyrus_content/reference_url_text.py (47 hits), references_commands.py, cli.py, priming_curation.py | When the article filter fails the raw text is stored with status `fallback_raw` and counted; DOI API fallback resolver | b/d | The filter failure is already reported as `ExtractionIncomplete` in priming; make the other callers fail the Reference instead of keeping raw text | medium: fewer References get text until the filter is fixed | reference intake | listed |
| 33 | src/papyrus_content/accession.py:332-340, reference_url_text.py:3287 | Second PDF URL tried when the first download fails | d | A different source is a documented step, not a silent substitute | none | | d |
| 34 | src/papyrus_content/reference_capture.py:549-560 | `_fallback_text` extracts text from HTML when the primary extractor yields none | b | One extractor | medium | capture | listed |
| 35 | src/papyrus_knowledge_query/tokens.py, engine.py:122 | Regex token counting when tiktoken is missing, with a warning | b | Require tiktoken | low: it is a declared dependency | knowledge queries | PR 6 |
| 36 | src/papyrus_knowledge_query/engine.py:2026 | `except Exception: message = {}` ("defensive runtime fallback") | b | Let it raise | low | knowledge graph | PR 6 |
| 37 | src/papyrus_knowledge_query/vector_index.py:577-625 | `_reference_summary_payload_for_indexing_legacy` and `_fallback_summary_payload` read old summary Messages | c | Migrate, delete | medium | vector index | Ryan |
| 38 | src/papyrus_newsroom/coverage_theme.py (50 hits), assignments_workflow.py:2909 | `--allow-fallback` lets a theme pick the rotating desk | d | An explicit opt-in flag, off by default | none | | d |
| 39 | src/papyrus_content/projection/standard/includes.py | `::include ... fallback="post"` | d | A documented author-facing option | none | | d |
| 40 | src/papyrus_content/web_structured_metadata.py:27, web_search_providers.py:4 | `use_llm_fallback` flag; `WEB_SEARCH_PROVIDERS` ordered chain plus the older `WEB_SEARCH_PROVIDER` | b/c | Drop the old single-provider name; keep an explicit ordered list if the site configures it | low | search config | listed |
| 41 | src/papyrus/__init__.py:9 | Source checkouts report a marked version when not installed | d | Dev convenience | none | | d |
| 42 | src/papyrus_content/tenant_adoption.py, markus_import.py:124-135,423,500 | Adopts legacy untenanted Items | c | Delete after every site is tenanted | medium | imports | Ryan |
| 43 | amplify/site-backend.ts:244-251,310,325, amplify/functions/ses-inbound-receive/handler.ts:38-39,339 | Inbound email domain `p.apyr.us`, corpus `AI-ML-research`, hosted-zone id and name default silently when the setting is unset | b | Require each setting; fail the synth naming it | medium: touches synth and defaults, which another agent is changing | every site's backend | Ryan; not touched (overlaps the optional-feature defaults work) |
| 44 | amplify/deploy-identifiers.ts:4, amplify/site-backend-names.ts (`isLegacyProduction*`) | A written value stays "a working fallback" when the env var is unset; p.apyr.us legacy pipeline naming | c | Require the env var once sites migrate | medium | released sites | Ryan |
| 45 | amplify/functions/console-chat-responder/resource.ts:33-37, amplify/functions/shared/console-chat-enqueue.ts:28 | Model, TTL, runner path, timeout and response target default via `\|\|` | d/b | Documented defaults for tunables are fine; the model name is configuration and should be required | low | responder deploy | listed |
| 46 | amplify/plugins/*/config.ts (`integer`, `number`, `text` with `fallback`) | Plugin config readers with documented per-field defaults | d | Documented defaults | none | | d |
| 47 | amplify/seed/seed.ts:277-278 | Local seed editor password/email default | d | Seed data for local sandboxes (test values) | none | | d |
| 48 | lib/site-brand.ts:247-266, lib/brand-fonts.ts:39, lib/chrome-text.ts:401, lib/themed-image.ts, components/use-feed-preferences.ts | Brand default, font stacks, em overrides, stored reader preferences | d | Documented user-facing defaults | none | | d |
| 49 | lib/front-mosaic.ts, lib/furniture.ts, lib/layout-types.ts, lib/article-frame-solver.ts | `fallbackPenalty` is a layout-solver cost term | d | Not a fallback | none | | d |
| 50 | amplify/plugins/alexa/intents/fallback.ts, lib/reference-links.ts:76 | Alexa `AMAZON.FallbackIntent`; user-facing "no suggestions" text | d | Required by Alexa / a message | none | | d |
| 51 | lib/reporting-story-budget.ts:129-226, lib/semantic-graph.ts:258-291 | Story budget reads linked messages when the packet has none; a relation endpoint that does not resolve is shown as a placeholder object | b | Raise on an unresolved endpoint | medium | reporting pages | listed |
| 52 | lib/prospectus-publication-access.ts:7, src/papyrus_content/prospectus_publication_access.py:4 | "For now every member gets their role's capabilities on all publications" | b | Real per-publication grants (Prospectus work, not a removal) | n/a | | Ryan |
| 53 | tempfile / TemporaryDirectory / `.queue-` temp files across src (about 30 lines) | Scratch files | d | | | | d |
| 54 | `deprecated` category status (categories_commands.py, news-desk-taxonomy-client.ts, topic-steering-workspace.tsx) | A category lifecycle state | d | | | | d |
| 55 | src/papyrus_content/records.py:31 | `FieldUndefined` for a model's list/get field is treated as "model not deployed" and answered with an empty result | b | Raise | medium: sites on an older backend | record readers | listed |
| 56 | src/papyrus_content/graphql_authoring.py:755,1240 | `NEWER_REFERENCE_FIELDS`: retries a Reference query without fields the backend lacks | b | One query; deploy the fields | medium: released sites on older backends | every CLI call on References | Ryan |
| 57 | src/papyrus_content/references_thumbnails.py:212, references_transcripts.py:290 | A `FieldUndefined` error means "skip this step" | b | Raise | low | thumbnail and transcript steps | listed |
| 58 | src/papyrus_content/story_reporting.py:492 | `setStoryReferenceRole` missing on the backend is answered with a client-side substitute | b | Raise | medium | story reporting | listed |

## Counts

Rows by class (a cluster counts once; rows 32 and 40 are split b/d and b/c and counted as b; row 45 is split d/b and counted as d):

| class | rows | which |
|---|---|---|
| a dead or unreachable | 1 | 8 |
| b silent substitute | 29 | 1-7, 9-13, 23-26, 29, 32, 34-36, 40, 43, 51, 52, 55-58 |
| c compatibility alias, live callers or data | 14 | 14-19, 21, 27, 28, 30, 31, 37, 42, 44 |
| d legitimate | 14 | 20, 22, 33, 38, 39, 41, 45-50, 53, 54 |

The 1,311 raw lines reduce to these 58 clusters; about 900 of them fall in class d clusters (temporary files, `deprecated` status,
layout penalties, font stacks, migration tooling, tests' own vocabulary).

## Removal order

1. PR 1: console chat client (rows 1-4, 5 console part), this audit, the Gherkin feature.
2. PR 2: lib/graphql-content-repository.ts shims and the dead image (rows 6-8), the Python `FieldUndefined` fallback (row 9).
3. PR 3: the Reference page loader chain (row 10).
4. PR 4: small aliases whose callers are all in this repo (rows 17-19) and Python substitutes (rows 25, 35, 36).

Needs Ryan (a released site, stored data or a design question depends on it, so it is listed, not removed): rows 5 (steering
realtime), 12, 14-16, 21, 27, 30, 37, 42-44, 52, 56. Rows 11, 13, 23, 24, 26, 29, 32, 34, 40, 51, 55, 57, 58 are removable but
each changes what an editor sees when something is broken; they are queued behind the four PRs above.
