# Removing the fallbacks that stored data or released sites depend on: migrations

Companion to [remove-fallbacks-audit.md](remove-fallbacks-audit.md). Design only: nothing here has been run, and no command below writes to a live
site until Ryan says so. Each fallback in this file can only go after the data it reads has been moved to the one correct shape, so each has a
migration. Every migration is a `papyrus` CLI command that is a **dry run unless `--apply`**, **idempotent** (a second run writes nothing, and its dry
run is the health check), prints counts and a sample, and writes a report under `.papyrus-runs/`. Where a command already exists it is named; where it
does not, it is marked **new**.

The seven live sites: Anth.us, Machines on Machines (MoM), Shipped, Pilobolus (Pilobol.us), Threat Intelligence (TI), Distinctive, and p.apyr.us.
"Every site" below means all seven. The order for each fallback is: ship the migration command in a release, run its dry run on every site, apply on
every site (one batch rule: test on the site under test first, then the rest), re-run the dry run until it reports nothing left, then ship the
release that deletes the fallback.

## Rows that look removable but are not (found while doing the removable list)

| Audit row | Finding | What to do |
|---|---|---|
| 16 `lib/amplify-server-runtime.ts` reads Cognito ids from the `auth` block | The snake_case `auth` block (`user_pool_id`, `identity_pool_id`, `user_pool_client_id`) is the format `ampx generate outputs` writes for every Gen 2 site; `Auth.Cognito` is what the client library builds from it. This is the main path, not an old shape. Removing it would break every site's server reads. | Reclassify as class d. Nothing to migrate. (The code could say so in a comment; that is the only change.) |
| 57 `references_thumbnails.py`, `references_transcripts.py` | The `FieldUndefined` branch prints "this site's data API does not have the field yet; deploy the site first" and exits 2. That is a clear failure, not a substitute. | Reclassify as class d. |
| 58 `story_reporting.py` `setStoryReferenceRole` | A backend without the route raises a `RuntimeError` that names the missing route and the remedy. Clear failure. | Reclassify as class d. |
| 51 `lib/semantic-graph.ts` placeholder for an unresolved relation endpoint | The graph is built from the pages of records the screen loaded, so an endpoint that is not in memory is normal, not an error. Raising would break pages. | Not removable as written. The fix is to load or look up the endpoint on demand (a design question for the graph screen), not a migration. |
| 51 `lib/reporting-story-budget.ts` messages found by `metadata.assignmentId` | A second lookup for packets that have no link relation to their assignment: stored data. | Migration 10 below. |
| 29 `monitoring_router.py` criteria fingerprint fallback | Votes stored before fingerprints existed carry no `criteriaFingerprint`; the router falls back to `criteriaSince`. | Migration 11 below. |

## 1. Story board stage query (audit row 12: `lib/story-stage-query.ts`, `lib/story-stage-mode.ts`)

- **State.** The head stage index (`listItemsByHeadStageAndUpdatedAt`, key `headStageKey`) is read only when `SiteBrand.storyHeadStageIndex === true`;
  otherwise the board reads the `stage` index and filters superseded rows after the read, and a missing index flips the whole session back to `stage`.
  No site repository sets `storyHeadStageIndex` in `papyrus.config.ts` today. The backfill was applied on Anth.us on 2026-11-12.
- **Migration.** `papyrus stories head-index` (exists, `src/papyrus_content/story_head_index.py`): dry run by default, `--apply` fills `headStageKey` on
  each lineage's head row, removes it from non-heads, never writes a superseded row, writes only rows that differ, capped rate. Run
  `papyrus stories head-index` (dry run) on every site first; it must report 0 rows left to write.
- **Sites.** Every site except Anth.us still needs `--apply`: MoM, Shipped, Pilobolus, TI, Distinctive, p.apyr.us. Anth.us needs only the dry run
  to confirm 0.
- **Order.** (1) Apply on the six remaining sites, one at a time, MoM first (largest Published column, the case the fallback was written for).
  (2) Dry run on all seven reports 0. (3) Release R: the board always reads the head index, `storyHeadStageIndex` and `readWithStoryStageIndex` are
  deleted. (4) Every site is on R's backend before its front end deploys (the head index must exist), so the backend bump goes first within the
  site's single deploy.
- **Deleted afterwards.** `lib/story-stage-mode.ts`, the `stage` entry of `STAGE_INDEX`, `StageIndexMode`'s `"stage"` value,
  `boardStoryFilter()`'s use for the board, `isMissingHeadStageIndexError`, `markHeadStageIndexMissing`, `SiteBrand.storyHeadStageIndex`, and the
  matching tests in `scripts/test-board-head-index.ts` and `scripts/test-board-refresh.ts`. The CLI's `_HEAD_STAGE_KEY_SUPPORT` probe in
  `graphql_authoring.py` goes with migration 6.

## 2. Old stage names (audit row 15: `LEGACY_CONTENT_ITEM_STAGE_ALIASES`, `legacyStageKeysToLoad`, Python `LEGACY_CONTENT_ITEM_STAGE_REPLACEMENTS`)

- **State.** Items whose `stage` is `research`, `report` or `editor_select` are read as `reporting`; the board loads those partitions too.
- **Migration (new).** `papyrus stories rename-stage --from research,report,editor_select --to reporting [--site KEY] [--apply]`. For every Item
  row (all versions, because every saved version keeps its stage) whose stage is in `--from`, set `stage` to `--to` and recompute the stage-derived
  index fields (`headStageKey` on the head row, and the tenant-prefixed form on a shared stack), passing the row's own `updatedAt` so no card jumps
  in its column. Dry run prints counts per old stage and per version state. Idempotent: rows already on `reporting` are skipped.
- **Sites.** Unknown until the dry run counts them; expected on the older sites (MoM, Shipped, TI). The dry run decides, so it is run on all seven.
- **Order.** After migration 1 (the head key is computed from the stage, so the head index must already be filled, or the rename would write wrong
  keys). Apply, dry run to 0 on all seven, then release.
- **Deleted afterwards.** `LEGACY_CONTENT_ITEM_STAGE_ALIASES`, `canonicalContentItemStage`'s alias branch, `legacyStageKeysToLoad` and its callers in
  the board loader, `LEGACY_CONTENT_ITEM_STAGE_REPLACEMENTS` and `legacy_stage_keys_to_load` in `content_item_lifecycle.py`, and their tests.

## 3. Concept tags under the old relation name (audit row 21: `amplify/functions/category-action/reference-links.ts`, the `related_to` lookup)

- **Migration.** `papyrus relations migrate-concept-tags` (exists): moves concept tags from `related_to` to `tagged_with`, retires the old row
  (`superseded`, never deleted), keeps rejected tags rejected, dry run by default, operator lane (IAM). `--site KEY` limits the References.
- **Sites.** Run the dry run on all seven; apply wherever it reports rows (any site that had concept tagging before `tagged_with`).
- **Order.** Independent of the others. Apply, dry run to 0, then release.
- **Deleted afterwards.** The "same pair under the old name" branch and the `RELATED_TO` input acceptance in `category-action/reference-links.ts`
  (a client that still sends `related_to` then gets "A concept is linked with the tagged_with predicate"), `concept_tag_migration.py` and the
  command, per the audit's row 22 retirement rule.

## 4. Old corpus folder names (audit row 27: `steering.py`, `corpus_storage_paths.py`, `renditions_commands.py`)

- **State.** Two stores of corpus files: stored `ReferenceAttachment.storagePath` values under `corpora/<Mixed-Case-Key>/...` in S3, and local
  checkouts under old folder names. `corpus_storage_path_read_candidates` tries the canonical lowercase segment, then the mixed-case form, then the
  token form.
- **Migration.** `papyrus references backfill-corpus-storage-paths --mirror-s3` (exists, operator lane): rewrites each attachment's `storagePath` to the
  canonical segment and copies the S3 object. Dry run first. Add (new) `--verify` that reads every rewritten path and reports any that do not
  resolve, so "0 left" is provable. Local checkouts need no command: they are scratch space, and the code that resolves a missing configured path
  should say "path does not exist, run `papyrus ... pull`" rather than guess.
- **Sites.** Every site that has corpus attachments: Anth.us, MoM, Shipped, Pilobolus, TI, Distinctive, p.apyr.us (dry run on all; the key shapes
  differ per site, for example `AI-ML-research` on p.apyr.us).
- **Order.** Apply with `--mirror-s3` (copy, never move). Verify to 0 unresolved. Release the code that reads only canonical paths. Only after that
  release has been live for a full retention window, delete the old S3 objects (a separate, explicit cleanup the owner decides; permanent deletion is
  not part of this migration).
- **Deleted afterwards.** `legacy_mixed_case_corpus_segment`, `legacy_corpus_storage_segment`, `corpus_storage_path_read_candidates`'s extra
  candidates, the fallback loop in `steering.py`, and the legacy-folder use in `renditions_commands.py`.

## 5. Reference fields a backend may lack (audit row 56: `NEWER_REFERENCE_FIELDS`, `_UNDEFINED_MEDIUM_INPUT`, the head-stage-key support probe in `graphql_authoring.py`)

- **State.** Not stored data: a schema-version difference. One CLI install and one monitoring router serve sites on different backend versions, so a
  query that names a field the backend lacks is retried without it, and a write naming a missing field is resent without it.
- **Migration (new, read only).** `papyrus content schema-check` exists (`--type Reference --fields starRating,...`). Add `papyrus sites schema-report`
  that runs it for every field in `NEWER_REFERENCE_FIELDS`, `MEDIUM_REFERENCE_FIELDS` and the Item `headStageKey` against all seven sites and prints
  a site-by-field table. The "migration" is deploying each site's backend to a release that has every field; the report proves it.
- **Sites.** The report decides. Backends are deployed per site by the normal release batch.
- **Order.** After the next batch release reaches all seven backends and the report shows no missing field. Then release the CLI and router without
  the retry paths. A site whose backend is older than that release must be upgraded before the new CLI is used against it.
- **Deleted afterwards.** `NEWER_REFERENCE_FIELDS` retry, `_UNDEFINED_NEWER_FIELD`, `_NEWER_FIELD_SELECTION`, `MEDIUM_REFERENCE_FIELDS` resend,
  `_HEAD_STAGE_KEY_SUPPORT` and `_UNDEFINED_HEAD_STAGE_KEY_INPUT`.

## 6. Legacy story drafts read path (audit row 30: `monitoring_stories.py` `ItemStore(..., legacy=legacy_story_drafts)`)

- **State.** Ideas used to be `story_draft` Proposals; they are now Items at the `idea` stage. The idea store also reads the old Proposals so the
  daily plan can dedupe against them.
- **Migration.** `src/papyrus_content/ideas/migrate.py` already converts open `story_draft` Proposals to Items (dry run by default, `write=True` to
  file; skips decided Proposals, already-covered and duplicate ones; leaves the Proposals untouched; editor lane because an IAM operator cannot read
  Proposals). Expose it as `papyrus ideas migrate-drafts [--apply]` if it is not already a command (**new** wrapper), and add a verification line
  "open `story_draft` Proposals not represented as Items: N" so 0 is provable.
- **Sites.** The sites whose monitors ran before the idea-as-Item change: MoM, TI, Anth.us, p.apyr.us are the likely ones; the dry run decides.
- **Order.** Apply as a signed-in editor on each site, verify 0, release the router without the `legacy` argument.
- **Deleted afterwards.** `legacy_story_drafts`, `operator_story_drafts`, the `legacy=` parameter of `ItemStore`, and `ideas/migrate.py`.

## 7. Older `extracted_text` attachments for Reference text (audit row 14: `components/reference-capture-client.ts`)

- **State.** A Reference shows the text of its curation card (`curation-text` body). A Reference captured before cards has only the
  `extracted_text` attachment; the page falls back to it.
- **Migration (new).** `papyrus references backfill-curation-cards --site KEY [--limit N] [--apply]`. For each current Reference with an `extracted_text`
  attachment and no curation card, build the card from the stored text exactly as capture does (same code path, `reference_capture_state`), without
  re-fetching the web. Dry run prints counts and the number that have no usable text (those are listed for re-capture, not guessed). Idempotent.
  Operator lane.
- **Sites.** All seven (p.apyr.us and the older sites hold the most pre-card References).
- **Order.** After the stored attachments are canonical (migration 4), because the card is built from the stored text. Apply, dry run to 0 "cardless
  with text", release.
- **Deleted afterwards.** The fallback state and effect in `useReferenceCapture`, `primaryTextAttachment` if unused elsewhere, and `previewText`.

## 8. Untenanted Items (audit row 42: `tenant_adoption.py`, `markus_import.py:124-135,423,500`)

- **Migration.** `papyrus content adopt-tenant-data --tenant ID [--apply] [--json]` (exists): dry run by default, stamps `tenantId` and the
  tenant-prefixed index fields on Items, PublishedItems, MediaAssets, PublishedMediaAssets and NewsroomSections, leaves record ids and storage paths
  untouched.
- **Sites.** Every site that is moving to the shared (tenanted) stack: dedicated stacks keep `tenancy.mode = dedicated` and carry no `tenantId`, so
  they need nothing and the import code must keep working for them. The dry run is run only for tenants being adopted; there is no "every site" run.
- **Order.** The adoption is part of each site's move to a shared stack, not a standalone cleanup. The code in `markus_import.py` that adopts a legacy
  Item id can be deleted only when no site remains whose Items predate tenant scoping, which depends on the tenancy rollout (PPY-31c45c), so this
  row waits for that decision.
- **Deleted afterwards.** `adopt_legacy_item_family`, `_adopt_legacy_item_id`, `legacy_row_needs_adoption`, and `tenant_adoption.py` with its command.

## 9. Messages found only by `metadata.assignmentId` (audit row 51 second half: `lib/reporting-story-budget.ts:129-140`)

- **Migration (new).** `papyrus assignments backfill-message-links [--site KEY] [--apply]`: for each Message whose `metadata.assignmentId` names an
  Assignment and that has no `SemanticRelation` linking it to that Assignment, write the link relation the writers write today (same predicate and id
  scheme), through the operator lane. Dry run prints the count per site. Idempotent (the relation id is deterministic).
- **Sites.** Every site with reporting packets: MoM, TI, Anth.us, p.apyr.us likely; the dry run decides.
- **Order.** Apply, dry run to 0, then release the budget builder that reads linked messages only.
- **Deleted afterwards.** The `fallbackMessages` branch and `metadataAssignmentId` in `reporting-story-budget.ts`.

## 10. Votes stored without a criteria fingerprint (audit row 29: `monitoring_router.py` feedback path, `criteriaSince`)

- **State.** Editor feedback decides "stale or current" by comparing the vote's `criteriaFingerprint` with the latest `CRIT#` fingerprint; when
  either is unknown it uses the publication's `criteriaSince` binding revision.
- **Migration (new).** `papyrus monitors backfill-criteria-fingerprint --monitor ID [--apply]` (operator lane): for each stored vote row with no
  `criteriaFingerprint`, set it when the binding revision it was cast under still has recorded criteria (compute the fingerprint from those); mark
  the rest `criteriaFingerprint = "unknown"` explicitly and list them, because their criteria are gone. Dry run first; idempotent.
- **Decision for Ryan.** What a vote with unknown criteria should do once the fallback is gone: be dropped as stale (safe, loses old training signal)
  or be sent (current behavior when `criteriaSince` is satisfied). The code cannot choose silently.
- **Sites.** The monitoring account's monitors (one table); the router config lists the publications (Anth.us, MoM, Shipped, Pilobolus, TI,
  Distinctive, p.apyr.us).
- **Order.** Decision, then apply, then release the router that raises on an unknown fingerprint unless the vote is explicitly marked `unknown`.
- **Deleted afterwards.** The `criteriaSince` fallback, the `criteria_unchanged` basis, and the `criteriaSince` publication field.

## Order across migrations

1. Migration 1 (head index) on the six sites, then release R1 (board reads the head index only).
2. Migration 2 (stage names), then R2.
3. Migration 3 (concept tags), independent, can run in the same window as 2.
4. Migration 5's report, then the deploy batch that brings every backend to the same release, then R3 (CLI and router without field retries).
5. Migration 4 (corpus storage paths), then 7 (curation cards, which read the canonical paths), then R4.
6. Migrations 6, 9 and 10 in any order once Ryan has decided the vote question; each ships with its own release.
7. Migration 8 waits for the tenancy rollout.

Everything above follows the standing rules: dry run first, no live write until Ryan says go, the batch-bump rule (one site under test, then all
seven), and one deploy per site change.
