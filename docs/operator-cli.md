# Operator CLI (dual backend)

> **Agents and anyone using the CLI for editing work:** start with the [agent CLI guide](agent-cli-guide.md) (or run `papyrus guide`): task-first recipes with exact syntax and what each prints, the two lanes (signed-in editor and IAM operator), which commands write by default, and a troubleshooting table. `papyrus <group> <command> --help` prints each command's usage, lane and write behaviour from `src/papyrus/operator/command_usage.py`. This page is the reference for operators.

One `papyrus` command against a local pod or the cloud newsroom. Executable spec: `features_backend/operator-cli.feature`.

Operators use **one** `papyrus` command on PATH (`[project.scripts] papyrus =
papyrus.cli:main`). It is a thin facade over `papyrus_content` and
`papyrus_newsroom` today; the operator surface is converging on the same argv for
**local pod** and **cloud** backends.

- **Same verbs, same flags.** Core operator commands include `papyrus references
  list`, `papyrus references show <id>`, and `papyrus assignments list`. Local pod and cloud must accept the same argv and
  return the same human-readable output shape (tabular list rows, detail blocks,
  exit codes). Executable specs live in `features_backend/operator-cli.feature`.
- **Backend is config, not a second command tree.** Select `local` or `cloud`
  from project config (`backend`, `local.podPath`, `cloud.graphqlEndpoint`) or
  with `--backend local|cloud`. Do not fork the noun vocabulary per backend.
- **Local pod backend** reads the Anth.us publication submodule
  (`pods/anthus-blog`, repo `AnthusAI/anthus-semantic-knowledge-base`): story
  artifacts, hooks, and pod reference rows. It does
  **not** revive a local Markdown content store (`content/articles/`) or emulate
  hosted corpus sync, editions, or the layout solver.
- **Cloud backend** uses the existing GraphQL/AppSync newsroom (`Reference`,
  `Assignment`, editions, knowledge-query). `references list` and `references show`
  without `--corpus-key` use, in order: the operator config's `defaultCorpusKey`, the
  canonical corpus of a steering file the site chose (`PAPYRUS_STEERING_CONFIG` or a
  `corpora/` file in a site's own checkout; the steering file inside the Papyrus source
  tree is the product's development default, not a site's choice), and, on a signed-in session, the backend's one
  canonical publication corpus (the same one `reporting create` uses). If the backend
  has none or several, the command fails and says to pass `--corpus-key`. Only the
  IAM lane and the local backend still fall back to the steering default shipped in
  the wheel (`threat-intelligence` today). Operators should not need `--corpus-key`
  or `PYTHONPATH=src` for the common path. A corpus key is the publication's key; the
  record id `knowledge-corpus-<key>` is accepted and means the same corpus. A list for a
  corpus that does not exist is an error that names the corpus the site serves, never an
  empty table (an existing corpus with no References still lists as empty).
  `references show <id> [--corpus-key KEY]` takes any id the other commands print: the
  record id (`...-v1`) from `references list`, or the lineage id that `stories show`
  prints. With `--corpus-key` a Reference from another corpus is an error that says which
  corpus it is in.
- **Reading one thing.** `papyrus stories list [--stage STAGE] [--section ID|SLUG|NAME] [--type article|post] [--stars N|--min-stars N|--max-stars N] [--sort updated|stars|rank] [--limit N]`
  prints one line per Story (lineage id, stage, section, title, then stars, source, votes, bucket, type, words, published; see docs/story-reporting.md; newest change first; spiked and
  held Stories only with `--stage`). `papyrus assignments show --assignment ID` prints one
  Assignment's status, type, queue, section, Story and holder, then its direction (what it asks for, read whole from the Assignment's
  metadata attachment), then its events. The direction prints as one `direction` row per line so a multi-line direction stays
  readable in the tab-separated output. Both are read only.
  `stories create --section` and `assignments create-research|create-reporting --section` take a
  section's id, slug or name, the same as `editorial context --section`, and store the id.
- **Object kinds are explicit.** Cloud `assignments list` rows are GraphQL
  `Assignment` work records (`kind: newsroom-assignment`). Local `assignments
  list` rows are Kanbus **pod stories** (`kind: pod-story`), not GraphQL
  Assignments. A pod story's `assignment` **stage** is Kanbus workflow state —
  use `kbs` for board columns and transitions. Cloud `references` rows are
  GraphQL `Reference` records (`kind: cloud-reference`); local rows are pod
  evidence/source artifacts (`kind: pod-reference`).
- **`kbs` stays the board.** Kanbus owns issues, columns, screenshots, and
  workflow transitions. `papyrus` owns newsroom objects (references, assignments,
  editions, knowledge). Do not merge `kbs` into `papyrus`.
- **Auth is operator UX.** Cloud authoring signs with the AWS credential chain
  (`AWS_PROFILE`); there is no `papyrus auth` group and no token to refresh.
  Missing AWS credentials must print recovery guidance, not a Python traceback.
- **Local pod references** live under `stories/<story-id>/references/*.json`.
  `papyrus references register --backend local` requires `--story <story-id>`
  or `local.defaultStory` in operator CLI config; never hard-code a story path.
  Same URL within the same corpus is an identity: re-register must refuse rather
  than overwrite accepted `status`/`why`/`title`. `accepted` and `pending` rows
  require a non-empty `--why`; `rejected` with empty why writes no row. List
  output includes `url`; show output includes `url` and `why`.
- **Kanbus `project_key` is stable.** Changing `.kanbus.yml` `project_key` does
  **not** remint existing issue ids or filenames under `project/issues/`. After a
  key change, legacy ids (for example `WIKI-*` rows when the key is `ANTH`) keep
  their old prefix; `papyrus` local-pod commands warn when legacy prefixes are
  detected. Pass `--story` explicitly; do not assume new work lands on a retired
  story id.

`lib/layout-plan.ts` owns the edition layout-plan contract:

- `EditionLayoutPlan` is stored with edition content as editorial intent, not
  solved geometry.
- Amplify stores this shape on `Edition.layoutPlan`.
- The plan is composable: `pages[]` contain `regions[]`, and regions contain
  typed `blocks[]`.
- Page presets currently include `front.mosaic`, `page.regionStack`,
  `page.railMain`, and `page.full`.
- Region types currently include `stack`, `split`, `railMain`, `strip`, and
  `fullPage`.
- Block types currently include `articleFrame`, `itemFrame`, `mediaCluster`,
  `itemStack`, `promoStrip`, `adBlock`, `rule`, and `masthead`.
- `articleFrame` presets currently include `front.teaser`,
  `article.standard`, `article.mediaInset`, and `article.mediaPrelude`.
- Media placement uses responsive intent: anchor, span range, vertical
  placement, collapse policy, crop policy, and wrap behavior.
- `articleFrame.typography.headlineScale` names the headline treatment with
  canonical newspaper terms: `banner`, `feature`, `standard`, `rail`, or
  `brief`. Do not infer headline scale from array position or patch it with CSS.
  When a user asks for a larger or smaller headline, map that request to one of
  these scale names and state the chosen name back in the implementation notes.
- `articleFrame.editorialPriority` names sequential importance with canonical
  terms: `primary`, `secondary`, `tertiary`, or `supporting`. This is separate
  from visual role and headline scale. In `front.mosaic`, one-column layouts
  use this priority so the `primary story` appears first even if it is centered
  or offset in a wide layout.
- `articleFrame.composition` can place label, headline, deck, byline, media,
  and pull quote slots on a local grid. Title slots reserve chrome above the
  body. Lead slots become solver-owned display obstacles inside the body and do
  not consume article cursors.
- Runtime validation uses Zod. A missing or invalid required plan is a
  publishing error; do not add a compatibility layer for previous plan shapes.
- Solved geometry, line positions, selected rectangles, and Pretext cursors must
  not be stored in the plan.

`lib/newspaper-layout.ts` owns layout and solver state:

- `ArticleFlow` tracks one article's current Pretext cursor and placed ranges.
- `PlacedTextRange` records `{ articleId, pageId, blockId, startCursor,
  endCursor, exhausted }`. Treat this as the source of truth for continuation
  correctness.
- `SolvedPage`, `SolvedRegion`, and `SolvedBlock` are the renderer contracts.
- `SolvedFurniture` includes image, pull quote, media cluster, and ad
  furniture with explicit solver-owned geometry.
- `buildNewspaperLayout(items, pageWidth, viewportHeight, layoutPlan)` receives
  generic publication items and the validated edition plan.
- The browser/client solver trusts the repository-normalized plan. Keep Zod
  validation in the content boundary and server/tooling path so Zod does not
  bloat the client newspaper bundle.

`components/newspaper.tsx` should remain mostly a renderer. It can map solved
objects to markup and CSS variables, but it should not decide text cutpoints,
page heights, section splits, or image variant scores.

`features/` owns executable BDD layout scenarios:

- `.feature` files are the durable behavior artifact. Keep them readable and
  product-level.
- Step definitions may use Playwright and geometry helpers to inspect DOM
  rectangles, but do not copy those details into scenario prose.
- Prefer adding a named fixture set in `lib/layout-scenarios.ts` when a bug
  depends on article length, viewport size, images, or pull quotes.
- Do not store test scenarios or edge-case fixtures in production edition
  records.
- The home page accepts `?scenario=<id>` as a content-source selector. It should
  go through `ContentRepository.loadEditionContent`, not bypass the content
  boundary in the renderer.
- The client exposes `window.__PAPYRUS_LAYOUT__` plus
  `window.__PAPYRUS_SCENARIO__` for test assertions.
- Scenarios should assert both rendered geometry and solver choices when a rule
  matters. For example, a blank-column repair should check that no continuation
  column is dead and that the intended image or furniture template won.

## Picking the site without a file

Signed in with `papyrus login`, an editor runs a newsroom command from any directory with no `amplify_outputs.json`,
`PAPYRUS_GRAPHQL_ENDPOINT`, `PAPYRUS_TENANT_ID` or AWS login. Name the site before the command,
`papyrus --site shipped.anth.us editorial context --backend cloud --format text`, or set `PAPYRUS_SITE`; otherwise the site the
working directory declares in `infra/site.json` is used, then an `amplify_outputs.json`, then the only signed-in site. Several
signed-in sites and no choice is an error that lists them. The flag is leading because several commands take their own `--site`
after the command name, and those keep their meaning. An operator on `PAPYRUS_GRAPHQL_AUTH=iam` is never sent to a signed-in site
by the directory or the only-site rules. Full order, the site file that carries the tenant, and the upgrade hint for an unknown
command: [CLI login](cli-login.md#picking-the-site-for-a-command). Executable spec: `features_backend/cli-site-selection.feature`.

`stories save-version` follows the same lane rule as `link-reference`: signed in, the version names the signed-in person and
`--author-label` is optional and ignored; on `PAPYRUS_GRAPHQL_AUTH=iam` it is required. `stories save-version --images` needs no outputs file
signed in: the site publishes its media bucket and identity pool ([CLI login](cli-login.md#the-site-file-tenant-and-version)).

Run from inside a Papyrus checkout, an installed `papyrus` stops at `papyrus-root-guard`, because it is a different install from that
checkout's. The message tells you to run it from another folder (any folder outside a Papyrus checkout) or to use the checkout's own
`poetry run papyrus`. `--allow-cross-root` (or `PAPYRUS_ALLOW_CROSS_ROOT=1`) is an explicit choice to run the install there anyway; the
check itself is unchanged.

## Creating stories and discovering commands

`papyrus stories link-story --story LINEAGE|SLUG --to LINEAGE|SLUG [--to ...] [--note TEXT] [--no-rerender] [--dry-run] [--json]` links a story to related stories for its See also block with the one official `see_also` relation (no relation can be chosen); a link in either direction counts as the same link, so repeating writes nothing, and a target that is not published yet is warned about. `--reference REFERENCE_ID` (repeatable) links the story to an accepted Reference instead (or as well): `papyrus stories link-story --story big --reference ref-123 --note "Primary filing"`; the Reference must exist and be accepted or nothing is written, and its title, host and status are printed. `stories show` lists a story's related stories and see-also References (and any item-to-item relation under a non-official name). It writes unless `--dry-run`. After a real write that created a link it re-renders the affected published story pages with no purge (`rerender  LINEAGE  no purge  ok`; visible within about five minutes; a failure is a warning, `--no-rerender` skips it; at most 20 stories, one after another, with a `rerendering LINEAGE (about a minute)...` line on stderr before each; the wait follows `PAPYRUS_GRAPHQL_TIMEOUT_SECONDS`). `stories link-concept` does the same for its story; `references link-concept` re-renders nothing. See [Linking stories to each other](story-reporting.md#linking-stories-to-each-other).

`papyrus stories link-concept --story LINEAGE|SLUG --concept NAME|#HASHTAG|NODEKEY [--concept ...] [--note TEXT] [--dry-run] [--json]` and `papyrus references link-concept --reference ID --concept ...` tag a story or a Reference with existing accepted concepts (`tagged_with`; exact matches only; a concept is never created; an existing or rejected tag is left alone; the public wiki page is checked). `papyrus stories check-links [--story ...]` and `papyrus references check-links (--reference ID | --corpus-id ID)` are read only audits of links and tags that are not the official shape. `papyrus relations migrate-concept-tags [--site KEY|--corpus-key KEY] [--limit N] [--apply]` (IAM lane; **dry run by default**) moves the legacy `related_to` concept tags of stories and References to `tagged_with` and retires the old rows (`superseded`, never deleted); `check-links --legacy-only` counts what is left. See [Tagging with concepts](story-reporting.md#tagging-with-concepts) and the [migration runbook](concept-tag-migration-runbook.md).

`papyrus stories suggest-links --story LINEAGE|SLUG [--kinds articles,posts,references] [--limit N] [--min-score S] [--include-linked] [--json]` (read only) ranks related articles, posts and accepted References from the story's concepts and the concepts near them, with the shared concepts, the path and the ready `link-story` command; `papyrus knowledge concepts related --concept NAME|#HASHTAG|NODEKEY [--limit N] [--json]` lists the concepts near a concept; `papyrus knowledge concepts search "free text" [--limit N] [--json]` (or `--list`) finds accepted concepts by meaning, exact names first, duplicates flagged. See [Suggesting related content](story-reporting.md#suggesting-related-content).

`papyrus stories suggest-associations (--story LINEAGE|SLUG | --reference ID) [--kinds articles,posts,references] [--limit N] [--json]` (read only, no embedding key needed) builds one query from the item's own title, summary and opening words, finds the accepted concepts that text names (name, alias or #hashtag as whole words, ranked by rarity and position; by meaning too when an embedding key and vector index exist), seeds `suggest-links` with them so an untagged item still gets related articles, posts and References, and prints the exact `link-concept` / `link-story` command for each. See [Suggesting related content](story-reporting.md).

`papyrus items link-references --site KEY [--role consulted|cited|based_on] [--json] [--dry-run]` links the stories whose text already links to a Reference's address to that Reference (see [Stories based on a Reference](reference-curation-pipeline.md#6a-stories-based-on-a-reference-core-rules)); it writes unless `--dry-run`.

`papyrus references duplicates [--format text|json] [--groups] [--skip-text-hashes]` is a read-only report of duplicate References in the publication the CLI is configured for. It groups current References that share an identity key (canonical URL, arXiv id, DOI, captured-text hash; [the identity gate](automated-processes.md#reference-identity-the-one-gate-for-every-path-that-creates-a-reference)) and counts same-title groups as candidates, never as duplicates. `--format json` prints the counts and every group's members; `--groups` adds them to the text output; `--skip-text-hashes` skips reading the attachments. It writes nothing. Spec: `features_backend/reference-identity.feature`.

`papyrus references backfill-publication-dates --corpus-id ID [--parallel N] [--dry-run] [--json]` fills in `Reference.sourcePublishedAt` for References curated before the publication-date stage existed. For every current http(s) Reference of the corpus whose curation card has no `publicationDate` it captures the HTML page the way curation does (same link exploration, so the same robots and timeout rules) and runs only the date stage (the date goes on `sourcePublishedAt`, the provenance on the curation card, which a Reference without one gets in minimal form): no summary, no GROBID, no model cost. A Reference that already has a date is recorded as source `monitor` without a fetch; a page that declares none stays null; PDFs are skipped (the PDF path resolves them). It writes unless `--dry-run`, which prints `would-set` lines (reference id, date, source, precision). `--parallel` sets the worker count (default 8). The summary line counts scanned, alreadyResolved, resolved (by source), keptMonitorDate, unknown, fetchFailures and skippedPdf. Re-running touches only what is still unresolved. The p.apyr.us corpus is `knowledge-corpus-ai-ml-research`; an empty corpus prints a message naming the id it looked for. See [idea context packs](idea-context-packs.md#23-two-dates-on-every-reference).

`papyrus references suggest-links --corpus-id ID --reference-id ID [--dry-run]` suggests related References and concepts for one Reference from the vector index (the Reference's stored summary vector is the query; no embedding call) and writes them as `suggested` links; it writes unless `--dry-run`. How many it keeps is the largest drop in similarity among the first half of the top results. The p.apyr.us corpus is `knowledge-corpus-ai-ml-research`; an empty corpus prints a message naming the id it looked for. See [idea context packs](idea-context-packs.md#32-suggesting-related-references-and-concepts).

`papyrus references search "agent memory" [--site HOST] [--show unrated|rated|accepted|rejected|all] [--limit N] [--cursor C] [--json]` finds References by words and by meaning together, rated or not, the way the newsroom References page search box does (see [reference search](reference-search.md)). It asks the site's `searchReferences` query with your `papyrus login` session, so it needs no AWS credentials, and it is read-only: one query, nothing written. Each line is the Reference's lineage id, its feed state, how it matched (`Matched: title, author`, `Matched: meaning`) and its title; `Next page: --cursor C` continues. Editors and admins only; one lane failing is said in a line and the other's results still print.

`papyrus references capture-transcripts [--site HOST] [--corpus-key KEY[,KEY...]] [--status accepted,pending] [--limit N] [--pace SECONDS] [--dry-run]` reads the transcripts of videos the newsroom holds no content for and saves them. **Run it on a non-cloud connection**: YouTube refuses cloud and data-centre addresses (no cloud function tries, see [the curation pipeline](reference-curation-pipeline.md#4d-video-transcripts-the-worker-2026-11-04)), and on one it stops after two waits with a message saying so. Anyone signed in with `papyrus login` can run it (editors and admins; no AWS credentials, no new permission): it saves each transcript with the same `correctReferenceCapture` action the newsroom's capture panel uses, as you. It finds the videos through the sparse content-needed index ([reference feed indexes](reference-feed-indexes.md#the-content-needed-index)), newest first, never by scanning. **Unlike the backfills it writes unless you pass `--dry-run`**, and `--help` is safe to run. `--status` takes `pending`, `accepted`, `rejected` or `all` (default `accepted,pending`); `--corpus-key` defaults to the site's one canonical publication corpus (read through its role index, the corpus `reporting create` uses; no table is listed); `--pace` is the wait between YouTube requests (default 3 seconds); `--limit` is the only cap and is off by default. Each video prints one flushed line (`captured`, `no_transcript`, `unavailable`, `unsupported_platform`, `failed`, `already_handled`, `too_large`); a failure never stops the run, and a second run continues where the first stopped. `--dry-run` lists what would be read and contacts neither YouTube nor the save action. It needs the optional package: `poetry install --extras transcripts` (or `pip install "papyrus-newsroom[transcripts]"`); without it the command says so before doing anything. Exit status: 0 done, 2 refused or not signed in, 3 YouTube blocked this connection.

`papyrus references capture-thumbnails [--site HOST] [--corpus-key KEY[,KEY...]] [--status accepted,pending] [--limit N] [--pace SECONDS] [--bucket NAME] [--identity-pool-id ID] [--write]` gives each video Reference its own thumbnail ([the curation pipeline](reference-curation-pipeline.md#4e-video-thumbnails-2026-11-04)): it fetches the picture from the platform (YouTube's address is built from the video id; Vimeo, Dailymotion, Loom, Wistia and TED are asked through oEmbed), checks it is a real picture, copies it to `media/assets/reference-thumbnails/` in the site's media bucket and records the path on the Reference with the `correctReferenceCapture` action. **Run it where the platforms answer, not on a cloud machine.** Signed in with `papyrus login` as an editor or admin; no AWS credentials. **It previews by default** (like `backfill-medium`, unlike `capture-transcripts`): it lists the videos that would be fetched and contacts nothing until you pass `--write`. The first `--write` run is the one-time backfill; it finds videos through the medium index and skips every video that already has a thumbnail or a recorded `none`, so a second run does nothing for them. `--pace` is the wait between videos (default 1 second); `--limit` is the only cap. Each video prints one line (`stored`, `none`, `failed`, `already_have`, `would_fetch`, `not_a_video`). Three platform refusals in a row stop the run with exit status 3; a storage fault stops it with 2. It needs a site whose data API has the `thumbnailPath` field.
`papyrus references create-from-catalog` queues, for each new Reference, one request that the router's five minute task answers by capturing the text, writing the summary and copying the curation onto the Reference before it predicts ([enrichment of a Reference created by hand](reference-curation-pipeline.md#2b-a-reference-created-by-hand-is-enriched-before-it-is-predicted-ppy-d683da-ppy-47e246)). With AWS credentials it also attaches the link preview. When the catalog holds videos it prints `N videos need a local run: papyrus references capture-thumbnails --write and papyrus references capture-transcripts`: the cloud cannot read a video platform's picture or transcript, so run those two where the platform answers (`capture-transcripts` writes by default, `capture-thumbnails` previews until `--write`).

`papyrus references queue-enrichment (--site KEY | --corpus-key KEY[,KEY...]) [--dry-run]` is the one-time backfill that queues the same enrichment for References created before that change and not captured in full. It writes queue rows in production, so run it with `--dry-run` first and only with the owner's approval; a second run adds nothing.

`papyrus references repair-titles [--site HOST] [--corpus-key KEY[,KEY...]] [--status accepted,pending] [--limit N] [--pace SECONDS] [--fetch] [--write]` is the one-time repair for References whose title is their own web address ([the curation pipeline](reference-curation-pipeline.md#4f-a-reference-is-titled-with-its-page-not-its-address-2026-11-05)). Signed in with `papyrus login` as an editor or admin; no AWS credentials. **It previews by default**: it reads the site's own records only and prints, per Reference, `would_set` (the page's title is already stored in the link preview or the capture card, so no fetch is needed) or `would_fetch` (nothing stored). `--write` records the stored titles with the `correctReferenceCapture` action (`pageTitle`), which the server accepts only for a title that is still an address; `--write --fetch` also reads the pages of the rest, one page per Reference, paced by `--pace` (default 1 second), and says `no_title` with the reason and the readable name the card will show for a page that is blocked, unreadable or declares no usable title. It finds the References through the feed-state index (never a scan), skips every title that is not an address, and a second run only meets what is left. The site's backend must carry the `pageTitle` action first: an older one answers with a one-line advice to deploy, and nothing is written. Exit status: 0 done, 2 refused or not signed in. Spec: `features_backend/reference-page-titles.feature`.



`papyrus references backfill-word-index (--site KEY | --corpus-key KEY[,KEY...] | --all-corpora) [--word-table NAME] [--outputs PATH] [--write]` fills the [word index](reference-search.md#word-index) the References search reads, for the References that existed before the table did. Run it once per site, right after the deploy that adds the table. It previews by default (one line per Reference it would index, then the counts) and writes nothing until `--write`. It reads References by curation status (never a scan), skips a Reference already indexed so a second run writes nothing, and changes no Reference. It needs AWS credentials for the word table (the operator lane); the table name is `--word-table`, `PAPYRUS_REFERENCE_WORD_TABLE`, or `custom.referenceWordIndex.tableName` in `amplify_outputs.json`.

`papyrus references backfill-public-fields (--site KEY | --corpus-key KEY[,KEY...] | --all-corpora) [--write]` sets the attributes a public block will read from an index ([the public-blocks attributes](reference-feed-indexes.md#the-public-blocks-attributes), PPY-7f1e54): `publicFeedKey` and `publicOrderKey` on every accepted Reference and on every pending one with a stored prediction of at least 0.5, and `cardImage`, `cardSummary`, `cardSiteName` and `cardPageTitle` copied from each such Reference's preview (a video's picture is its own thumbnail copy). It previews by default (like `backfill-medium`): one line per Reference it would change, then the counts, and nothing is written until `--write`. It is an operator command (AWS credentials, `PAPYRUS_GRAPHQL_AUTH=iam`). It reads the pending index only down to a prediction of 0.5 and each public row's preview once, changes no vote, and writes nothing on a second run. Run `backfill-feed-keys` first on a site whose pending rows have no prediction keys, and run this once per site before the release that adds the index.

`papyrus references retire-junk-suggestions [--execute]` lists the open vector-made concept suggestions whose concept is an author or a bookkeeping node (comment, rating, relevance, coverage, editorial form). It writes nothing without `--execute`; with it, each is marked rejected (by `auto:cleanup`, reason `not_a_concept`), so it leaves the queue and is not offered again. Nothing is deleted.

`papyrus stories create --title TEXT [--type article|post|...] [--section KEY] [--stage idea|assignment|reporting] [--summary TEXT] [--brief TEXT] [--reference ID ...] [--with-assignment]` mints a content item at the chosen stage (default `idea`) without opening an Assignment (each `--reference` is a Reference the story is based on, linked `based_on`); `--with-assignment` also opens the `reporting.candidate` Assignment on it (the same path as `papyrus reporting create`). `reporting create`, `research create` and the `run` commands resolve the corpus from the backend's canonical publication corpus when `--corpus-key` is omitted (`papyrus publication init` creates it on a fresh backend).

`papyrus stories set-type --story LINEAGE --type article|post|... [--dry-run]` changes the type of a story that is not published yet (a draft, idea or in review). `--type` on `create` and on `set-type` is a lowercase name that is not a system type and not `untyped`; when the site's own list is known (a `projection.json` in `PAPYRUS_SITE_STATIC_DIR`, or in `./web` of a site checkout) it must be one the site offers, and with no list the name is accepted with a note. A story created with no type and no site default is `untyped` and cannot be published until it has one; `create` warns when it made one. A published story is refused: the address of its page depends on its type. Spec: `features_backend/story-type-flag.feature`.

Every command group prints its own subcommands for `papyrus <group>` and `papyrus <group> --help`.

## Editorial policies

`papyrus editorial policies list | import-starter NAME | ensure-defaults | add | export` manages the site's `EditorialPolicy` records (what the newsroom's Editorial checks panel edits). They read and write the site's AppSync API with the same auth as the other operator commands, for example `PAPYRUS_GRAPHQL_AUTH=iam` with the site's `PAPYRUS_GRAPHQL_ENDPOINT` and an AWS profile whose role may write `EditorialPolicy`.

`papyrus editorial policies add --file PACK [--dry-run] [--publication KEY] [--actor NAME]`

- `PACK` is a Humanus `policy-pack-v1` file (JSON or YAML), validated before anything is read from the site. Every policy in it becomes a `publication`-scope policy, with its rule and classifier (judgment) detectors exactly as the file gives them: scope, `question`, `violation`, `threshold`, `reviewAt` and `message` (the text shown on each finding).
- A policy the site lacks is created as version 1. A policy whose title, guidance, severity, enabled flag, detectors, examples or rewrite guidance differ is saved as the stored version plus one, as the panel does. An identical policy is left alone, so re-running a file changes nothing. The pack's own `version` fields are not stored; `tags` have no field and are dropped.
- `--dry-run` prints one line per policy (`would create`, `would update ... version 2 -> 3`, `unchanged`) and writes nothing.
- `--publication KEY` refuses the run unless the site's canonical publication has that key.
- Each written policy's `source` is `operator-cli:<packId>:<actor>` (the actor defaults to `papyrus-cli`), which the panel shows in the policy list.

`papyrus editorial policies export --file PACK [--language TAG] [--pack-id ID] [--pack-version V]` writes the site's `publication` policies written for exactly one language (default the site's primary language; `*` for the language-neutral ones) as a pack (`.yml`/`.yaml` for YAML, otherwise JSON) that `add` loads back unchanged. Section policies and other languages' policies are left out and counted, since a pack has one language and no scope. `add` writes each policy for the pack's `language`.

## Site commands

`papyrus site <command>` runs from a site repository (the one with `infra/site.json`), not from the Papyrus checkout.

`papyrus site google-secrets set|check [--site PATH] [--profile NAME] [--account ID] [--region R] [--app-id ID] [--branch NAME]` manages the CMS app's Google OAuth client id and secret, the Amplify secrets that `amplify/auth/resource.ts` reads with `secret("GOOGLE_CLIENT_ID")` and `secret("GOOGLE_CLIENT_SECRET")`.

- `set` asserts the AWS account with STS (refusing on a mismatch, before any write), prompts for the client id (visible) and the secret (hidden), or takes `--client-id ID` plus `--secret-stdin` for automation. There is no `--secret` argument. It writes SSM SecureStrings at `/amplify/<appId>/<branch>-branch-<hash>/GOOGLE_CLIENT_ID` and `.../GOOGLE_CLIENT_SECRET`, confirms by fingerprint, and prints the Google Cloud Console origin and `/oauth2/idpresponse` redirect URI and the redeploy step.
- `check` reports whether both parameters exist (last modified, fingerprint), whether the deployed Cognito Google provider uses the same client id (fingerprint compare), the state of `PAPYRUS_DISABLE_GOOGLE_OAUTH` on the branch, and the URIs to register. It exits 1 when anything is missing or different. No value is ever printed.
- Account, profile and region come from the flags, then, for the account, `PAPYRUS_AWS_ACCOUNT_ID`, then the optional `aws` block of `infra/site.json` (`profile`, `accountId`, `region`), then `AWS_PROFILE` / `AWS_REGION`. An expected account is mandatory.
- It never enables or disables Google OAuth.

Walkthrough: [site-hosting.md](site-hosting.md#google-sign-in). Executable spec: `procedures/newsroom/tests/test_site_google_secrets.py`.
