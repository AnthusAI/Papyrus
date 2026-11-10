# One row per story in the stage indexes (PPY-94729f)

> Status: design, for Ryan to decide before anything is built. Nothing on this page is implemented, no schema has changed and no production data has been written. The board tasks are under epic PPY-94729f.

## The short version

A story is stored as one `Item` row per version. Each saved version keeps the `stage` it was written in, and the stage index (`stage` + `updatedAt`, query field `listItemsByStageAndUpdatedAt`) indexes every row that has a stage. So a story that went through Copywriting and was then published has rows in the Copywriting partition and in the Published partition, and a story published twelve times has twelve rows in Published.

On Machines on Machines, 456 of the 580 rows in the Published partition are superseded versions, and 26 board cards showed a version that was not the newest (10 published stories sat in Copywriting). The board reads 25 rows per column, newest `updatedAt` first, and keeps the highest `versionNumber` it has seen per lineage. When the newest version is not on a loaded page, an old one wins.

PR #1361 hides superseded rows with a query filter. That fixes what editors see, but DynamoDB still reads the superseded rows before the filter drops them (about 4.7 times as many rows in Published), the cost grows with every version ever saved, and every other reader of the stage index (the CLI's `stories list`, ideas, the section context pack, the checklist backfill, the monitors built on them) still reads every version and filters in memory.

**Recommendation: a sparse key.** Add one attribute, `headStageKey`, that only the head row of a lineage carries, and one new index on it (`headStageKey` + `updatedAt`, query field `listItemsByHeadStageAndUpdatedAt`). The head is set and cleared in the writes that already flip `versionState`, so a save, a stage move or a publish costs exactly the writes it costs today. Every board, list and projection then reads exactly the rows it shows. Version rows stay as history and are in no stage index.

- It costs one backend deploy per site (the one GSI change in that deploy), one write per lineage to backfill, and no extra write per change.
- The same pattern already runs on `Reference`: `feedStateKey`, `mediumFeedKey`, `contentNeededKey` and `publicFeedKey` are sparse keys removed from a version when it is superseded (`src/papyrus_content/records.py`).
- Keep #1361 as the stop-gap until the console reads the new index, then remove its filter.

## What the code does today

### The model

`Item` in `amplify/data/schema.ts` (mirrored in `amplify/data/resource.ts`) has `lineageId`, `versionNumber`, `previousVersionId`, `versionState` (`current` or `superseded`), `stage`, `status`, `typeStatus`, `sectionStatus` and the content. Its indexes include:

| Index | Partition | Sort | Holds |
| --- | --- | --- | --- |
| `listItemsByLineageAndVersion` | `lineageId` | `versionNumber` | every version of one story (the history) |
| `listItemsByStageAndUpdatedAt` | `stage` | `updatedAt` | **every version that has a stage**, current or not |
| `listItemsByVersionStateAndUpdatedAt` | `versionState` | `updatedAt` | every row, split into current and superseded |
| `listItemsByTypeStatusAndPublishedAt` | `typeStatus` | `publishedAt` | every row, including superseded versions that were published |
| `listItemsBySectionStatusAndPublishedAt` | `sectionStatus` | `publishedAt` | the same, by section |

`stage` is not tenant-scoped today (`TENANT_SCOPED_INDEX_FIELDS` in `src/papyrus_content/tenancy.py` is `typeStatus` and `sectionStatus`), so on a backend that serves several tenants the stage partitions are shared.

### Where versions are written and superseded

| Writer | What it writes | Supersede |
| --- | --- | --- |
| `publishing.save_item` (console save in place, Markus import) | creates v1 with `stage: copywriting`, or updates a row in place | none |
| `story_reporting.save_story_version` (console "new version", CLI `stories save`, copywriting, story writing) | reads every version of the lineage (`itemsByLineageAndVersion`), creates `v(n+1)` as `current` | one update per row that is `current` or is the latest: normally **one** |
| `publishing.publish_item` | updates the published row in place: `stage: published`, `versionState: current` | reads the lineage, one update per other `current` row: normally **zero** (the save already superseded it) |
| `publishing.unpublish_item` | updates the row in place to `stage: copywriting` | none |
| `story_reporting.move_story_stage` (board card move, story triggers) | updates `stage` on the current row in place | none |
| `story_reporting.repair_story_versions` | renumbers a muddled lineage, leaves exactly one `current` | one update per row that changes |
| `story_checklist` (sub-task steps) | creates the next version of a step | updates `-v(n-1)` by id; sub-tasks have no `stage` |
| others that set `stage`: `content_item_lifecycle`, `assignments_workflow`, `copywriting`, `story_triggers`, `editor_review`, `story_selection`, `story_commands`, `seed_edition`, `markus_import` | | |

So supersede is already **one write per save**, not one per old version: only the row that was current is touched. What is O(versions) is the read in `save_story_version` and `publish_item`, which list the whole lineage to find the current row. That is a per-lineage query, not a table read, and it is out of scope here (noted under follow-ups).

Two smaller findings:

- **Two definitions of "the head".** Python takes the row marked `current` (`story_reporting._current_of`, used by stage moves, `stories show` and the checklist). The console takes the highest `versionNumber` among loaded rows (`lib/content-item-lifecycle.ts latestVersionPerContentItem`). They differ when an older version is published (`publish_item` makes it current and supersedes the newer draft). This design picks one: **the head is the row marked `current`**, and `headStageKey` is present exactly when `versionState` is `current` and the row has a stage.
- **Superseding probably moves the old row to the top of its column.** The supersede update does not pass `updatedAt`, so AppSync stamps it with the time of the save, and the stage index sorts by `updatedAt`. A superseded row therefore looks freshly changed in its old stage. The Gherkin specs check this; either way the new index does not contain the row.

### Who reads the stage index

| Reader | Where | What it does with superseded rows |
| --- | --- | --- |
| Board columns | `components/news-desk-taxonomy-client.ts loadNewsroomContentItemStagePage` | 25 per page, newest first, story types filtered in the query; keeps the highest version per lineage: **the visible bug** |
| Board refresh | `loadNewsroomContentItemsChangedSince`, merged by `lib/board-refresh.ts applyChangedVersions` | reads changed rows since the newest shown; superseded rows with a fresh `updatedAt` come back as "changed" |
| `papyrus stories list` | `story_signals.list_stories` | reads every row of every stage partition, filters `versionState == current` in memory |
| Ideas pipeline | `ideas/items.idea_rows` | reads every row of the pre-publish stages, filters in memory |
| Section context pack (agents) | `newsroom_context_pack.section_stories` | reads every row of the given stages, filters in memory |
| Checklist backfill | `story_checklist.backfill` | iterates every row, dedupes by lineage |
| Story monitors | through the functions above | same |

The public site and the projector do not read `Item` by stage: they read `PublishedItem` (one row per lineage already). `typeStatus` and `sectionStatus` on `Item` have the same problem for published versions, and `itemsBySectionStatus` is defined in the authoring client; nothing user-facing reads it today, so it is listed as a follow-up rather than fixed here.

## The options

### (a) A sparse head key on the version row (recommended)

Add `headStageKey: a.string()` to `Item` and one index `index("headStageKey").sortKeys(["updatedAt"]).queryField("listItemsByHeadStageAndUpdatedAt")`.

- The head row carries `headStageKey = stage` (tenant-prefixed on a tenant backend: `headStageKey` joins `TENANT_SCOPED_INDEX_FIELDS`, so `tenant_stamped_payload` prefixes it like `typeStatus`). Every other row has no `headStageKey`, so DynamoDB never puts it in the index.
- Writers set it in the create or update they already make and set it to `null` in the supersede update they already make. Amplify's update resolver removes an attribute set to `null`, which is exactly how `feedStateKey` leaves the Reference feed index today.
- One helper in `content_item_lifecycle` (`head_stage_fields(row, head=True|False)`) is the only place the rule lives; every writer in the table above calls it. A test-only invariant on the fake client checks after every backend scenario that each lineage has at most one row with `headStageKey` and that it equals that row's `stage`.
- Readers query the new index by stage. A board column then reads exactly its 25 heads, a changed-since refresh returns only heads, and `stories list --stage copywriting` reads only the stories in Copywriting.
- Projection `ALL` is fine: the index holds one row per lineage. (Amplify now supports `INCLUDE` projections, but an AppSync query on a GSI returns null for unprojected fields and errors on required ones, so `INCLUDE` would have to list every required `Item` field; not worth it at this size.)

### (b) A separate Story head record

A new model (say `Story`, one row per lineage) carrying `headVersionId`, `stage`, `section`, `type`, `title`, stars and the board fields, with its own stage index. Version rows become history only.

- It is the cleaner model in the long run: stars already "belong to the Story, not to one version" (`item_stars.carry_item_stars` copies them onto every version), stage moves are already recorded per lineage, and `PublishedItem` is a per-lineage record of the same shape for the live text.
- A new table can be created with all its indexes in one deploy (the one-GSI-per-deploy limit applies to changing an existing table), so it is also one deploy per site.
- But every save, stage move, publish, unpublish and star becomes **two writes** that the generic AppSync client cannot make atomically, so the two records can drift; every reader changes shape and needs a second read for anything only the version has; the model needs auth rules, tenant handling, local-preview fakes and CLI support in seven backends. That is a large change for a bug that (a) fixes with no extra writes.
- Verdict: not now. If later work (stars, checklist state, story variations) wants a per-lineage record, (a) does not stand in its way: the backfill and the readers would move to it.

### (c) Rewrite `stage` on superseded rows to a terminal value

Set `stage = "superseded"` whenever a row is superseded.

- No schema change and no deploy, and no extra write per save (it rides on the supersede update).
- But it **destroys history**: the version would no longer say which stage it was written in, which `editor_review` (version `stage`), the reporting trail and the lens evidence show. Publishing an older version or repairing a lineage could not restore its stage.
- `superseded` becomes a fake stage that `require_content_item_stage`, `CONTENT_ITEM_STAGES` and every stage enumeration must special-case, and its partition grows forever.
- The backfill rewrites almost every story row (every superseded version: hundreds on MoM), not one per lineage.
- `stage` would mean two things (where a story is, and whether a row is history). Verdict: rejected.

### (d) Keep the query filter from #1361

`filter: { versionState: { ne: "superseded" } }` on the board's two queries.

- Front-end only, no backend deploy, fixes the 26 cards now.
- DynamoDB reads before it filters: the Published column reads about 580 rows to return 124, and the ratio worsens with every save. It is the "read many to show a few" pattern the indexes-over-scans rule forbids, and the other readers stay exposed.
- Verdict: ship it as the stop-gap, remove it when the console reads the new index.

(One more was considered: query the existing `versionState = current` partition with a stage filter. That partition holds the current row of every `Item` of every type and stage, sub-tasks included, so each column would read all of them. Rejected.)

### Trade-offs

| | (a) sparse head key | (b) Story head record | (c) `stage = superseded` | (d) #1361 filter |
| --- | --- | --- | --- | --- |
| Rows per lineage in the stage index | 1 | 1 (new table) | 1 (+ one `superseded` partition growing forever) | all versions, filtered after the read |
| Extra writes per save / move / publish | 0 | +1 each, not atomic | 0 | 0 |
| Extra reads per board column | 0 | 0, but a second read for version fields | 0 | about 4.7x on Published today, growing |
| Backend deploys per site | 1 (+1 optional to drop the old index) | 1 (new table) | 0 | 0 |
| Backfill writes, MoM | 1 per lineage with a stage | 1 create per lineage | 1 per superseded row (most rows) | none |
| History kept | yes | yes | **no** | yes |
| Other readers fixed | yes, after switching | yes, after rewriting | yes | no |
| Main risk | a writer forgets the key (mitigated by one helper, an invariant test and the verify command) | two records drift | breaks history and stage semantics | cost grows, rule broken |

## The migration

The order respects three constraints: one GSI change per deploy per table, each of the seven sites has its own backend deploy, and every backend or schema deploy needs Ryan's approval. Old readers keep working at every step, because the old `stage` attribute and index are untouched until the last one.

| Step | Board | What ships | Deploys | Writes |
| --- | --- | --- | --- | --- |
| 0. Stop-gap | PPY-2f3d94 | #1361 filter in the console | front-end bump only | none |
| 1. Specs | PPY-e7da00 | Gherkin scenarios first, failing | none | none |
| 2. Schema + 3. dual-write | PPY-ad0997, PPY-fe0b16 | `headStageKey` field, the one new GSI, the helper in every writer, the capability check in the client | **1 backend deploy per site** (approval); MoM first, the other six in one batch | none extra per change |
| 4. Backfill | PPY-35a385 | `papyrus stories head-index`, dry run then apply, per site | none | 1 per lineage; MoM reads about 830 rows once |
| 5. Console reads | PPY-52f3da | board columns and refresh on the new index | front-end bump | none |
| 6. Python reads | PPY-9281e4 | CLI, ideas, context pack, checklist, monitors on the new index | CLI release / front-end bump | none |
| 7. Cleanup | PPY-3504bf | drop fallbacks and the #1361 filter; then drop the old `stage` index | **1 backend deploy per site** (approval), optional | none |
| 8. Docs | PPY-f78fec | data model and operations docs | none | none |

Steps 2 and 3 go in one release: the field must exist before anything writes it, and the deploy that adds the field is the one that adds the index. Steps 5 and 6 can share a release, after the backfill has run on the site. If Ryan prefers fewer bumps, 5 and 6 can ride in the release after 2–3 as long as the backfill runs before that release reaches each site.

### Transition: old and new readers side by side

- **During step 2–3 on a site**: new rows and every supersede already maintain `headStageKey`; old readers ignore it. The new index is partially filled (only lineages touched since the deploy), so nothing reads it yet.
- **The CLI runs against all seven sites from one install.** A CLI built after step 3 would send `headStageKey` to a site whose schema does not have it, and AppSync rejects unknown input fields. The authoring client therefore asks once per process whether the site's `Item` type has `headStageKey` (`graphql_type_field_names`, already in `graphql_authoring.py`) and leaves the field out when it does not. Step 6 uses the same check to fall back to the old index plus the `versionState` filter, with one line on stderr, until step 7 removes the fallback.
- **The console** ships with its site's backend, so it never meets a schema it was not built for; it only has to wait for the backfill (step 5 after step 4).
- **The board refresh** changes one rule: a changed row replaces every loaded row of the same lineage, in any column (a lineage has one head). Today it replaces by row id, which leaves a card in its old column when a new version is created.

### The backfill and verify command

`papyrus stories head-index [--dry-run] [--stage S] [--rate N]`, per site, through the signed-in `papyrus` CLI (never the AWS CLI). Like every `papyrus` mutation it writes unless `--dry-run`; the procedure is to run the dry run first.

1. Read the old stage index partition by partition (`CONTENT_ITEM_STAGES`). This is the migration's one full read of story rows, run inside a named `request_meter` sweep so it is counted as intended. On MoM it is about 830 rows.
2. Group rows by lineage and pick the head with the existing rule (`_current_of`: the row marked `current`; if a muddled lineage has several, the most recently created). Report muddled lineages by id so `stories repair-versions` can fix them; do not repair here.
3. For each lineage: set `headStageKey` on the head when it is missing or wrong, and remove it from any other row that has it. Rows already right are not written, so a second run writes nothing (idempotent).
4. Pass each row's own `updatedAt` in the update, so no card jumps to the top of its column.
5. Write at a capped rate (default 5 per second; about a minute for MoM) and in pages, printing one line per change and a summary: lineages, heads set, keys removed, muddled lineages, already right.
6. With `--dry-run` and nothing to change, it is the health check: run it before the reader switch and before the cleanup on every site.

Superseded rows have no `headStageKey` to begin with, so the backfill only writes one row per lineage. Tenant prefixes come from the client's existing `tenant_stamped_payload`.

## Failure modes

| What goes wrong | Effect | Guard |
| --- | --- | --- |
| A writer sets `stage` or `versionState` without the helper | a lineage with no head (missing from the board) or two heads | one helper; the fake-client invariant runs after every backend scenario; the verify dry run reports drift; readers still dedupe by lineage |
| A writer creates the new version but cannot update the old one (a role without update rights, as `story_checklist` allows) | two heads | readers keep the highest `versionNumber` per lineage among heads; verify reports it |
| Crash between creating `v(n+1)` and superseding `v(n)` | two heads until the next save or the verify run | the same dedupe; the backfill repairs it |
| The backfill bumps `updatedAt` | every card looks freshly changed | it passes each row's own `updatedAt`; a scenario checks the order is unchanged |
| A new CLI against a site not yet deployed | writes rejected | capability check drops the field; readers fall back |
| The console switches before the backfill | columns show only stories touched since the deploy | step 5 is ordered after step 4; the verify dry run is the gate |
| Tenant backends | stage partitions shared across tenants | `headStageKey` is tenant-prefixed from day one |
| Deploy of the index fails | the release does not reach the site; nothing reads the index yet | MoM first, then the batch |

## Tests (Gherkin first)

Scenarios before code, in `features_backend/` for writers and the backfill and `features/` for the board:

- A new story has one row in its stage's head index; saving a new version moves the head to the new row and the old row leaves the index, in the same writes as today (the request meter counts them).
- Moving a card, publishing, unpublishing and starring keep exactly one head, in the right stage.
- Publishing an older version makes it the head; the newer draft leaves the index.
- A muddled lineage with two current rows: the backfill picks the newest, reports the lineage and writes nothing else.
- The backfill dry run lists what it would change and writes nothing; apply writes one row per lineage; a second run changes nothing; card order is unchanged.
- On a tenant backend the key is tenant-prefixed and a column never shows another tenant's stories.
- The board: a published story that was once in Copywriting shows only in Published; a refresh after a new version replaces the card wherever it was.
- The CLI against a site without the field falls back and says so once.
- After cleanup, a repository test fails if anything still names `listItemsByStageAndUpdatedAt` or `itemsByStage`.

## What fixes the visible bug first

1. **Now: #1361 (PPY-2f3d94).** Front end only, no backend approval needed beyond the site bump. It hides the 26 wrong cards immediately.
2. **For good: steps 2–4 on MoM, then step 5.** One approved backend deploy on MoM, one backfill run (about a minute), one front-end bump. From then on the board reads one row per story and the filter can go. The other six sites follow in one batch for each step.

## Follow-ups (not in this epic)

- `save_story_version` and `publish_item` list the whole lineage to find the current row. With a head key the writer could read the head directly; worth doing when the lineage reads show up in the request meter.
- `typeStatus` and `sectionStatus` on `Item` also index superseded published versions. Nothing user-facing reads them by those keys today; if something starts to, the same sparse pattern applies (a `headSectionKey`), one GSI per deploy.
- `Item` still stores `bodyMarkus` and `body` in DynamoDB, against the rule that text lives in S3. Out of scope here; dropping the old stage index (step 7) at least stops a second copy of every version's text in that index.
