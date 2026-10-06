# Pilobol.us migration plan (Phase 3)

Status: **PLAN for Ryan's approval. Nothing in this document has been executed.**
Kanbus: PPY-3367d3 (Phase 3) under epic PPY-1f1489. Design reference:
[standard-site.md](../standard-site.md) (section 3.3 is the original estimate). Phase 2
tools are on `develop` (PRs #98 to #127); `main` has none of them.

Every statement is marked **FACT** (verified on 2026-10-06 and how) or
**ASSUMPTION** (reasoned, not yet proven; the step that proves it is named).
Live resources were read only (list/get/describe, DynamoDB count scans,
public HTTP GETs). Builds were done in scratch copies.

## 0. Summary

1. The Pilobol.us CMS backend is **empty**: no content, no users, no media (section 1).
   That removes the usual data risks of "deploy a new schema to production" and makes the
   `convert-bodies` gate moot for this site. It also fixes the order: **move the CMS build
   and deploy the schema first, while it is empty, then import.**
2. The live Git-built site is reproducible byte for byte: 94 files built in scratch from
   `AnthusAI/Pilobol.us@main` equal the live site, built with either the pinned old renderer or
   Papyrus `develop`. A CMS import/export round trip of the real Git content rebuilds the same
   94 files (offline, in memory). So "not one byte changes" is testable at every step.
3. Recommended end state: **one repo** (`AnthusAI/Pilobol.us`) that depends on the published
   packages, feeds **two existing apps** (CMS `d11eu9hbs2mipk` in place, reader
   `d1od6t7lzbwanr` in place), with the reader reading the CMS through **guest (identity pool)
   access, no credentials in the build**.
4. Fourteen tickets (P3-01 to P3-14), about 21.5 agent-days, critical path about 15.5 agent-days
   plus a 7-day soak. Ryan is needed at 9 moments (section 8), two are GitHub App moments.
5. Four things the design did not anticipate (found by this research, each has a ticket):
   the template cannot adopt existing apps; the reader build spec lives in a repo file that
   would override the CMS app's spec; the pilobol-us brand's root-level newsroom would loop the
   staging gate; the generated reader spec lacks boto3.

## 1. Facts (verified 2026-10-06)

### 1.1 Repos and content

| Fact | Evidence |
| --- | --- |
| `AnthusAI/Pilobol.us` is **public**, default branch `main` (`7f30fa9`), no branch protection, 759 tracked files. It is the newsroom pod (22 PILO stories in `stories/`, wiki, corpora) plus the reader `web/` | `gh api`, `git ls-files` |
| Tracked reader content: **21 `.md`** under `web/content` (10 articles, `a-fungus-among-us`, 3 drafts in `drafts/`, 7 pages in `effects/`) and 65 asset files. The "23 files" of PR #115 included the two **gitignored, build-generated** listing pages (`index.md`, `articles/index.md`); they must not be imported | `git ls-files`, `.gitignore` |
| The reader build writes into the content dir (generated listings, default `author:` front matter) and hardcodes `POD_ROOT/content` and `POD_ROOT/dist-papyrus` | `web/build_via_papyrus.py` |
| The local checkout `/Users/home/Projects/Pilobol.us` is on a `wip` branch, not `main`: never use it as the source | `git branch` |
| Papyrus still holds the brand: `publications/pilobol_us/{brand.ts,theme.css,docs/bootstrap.md}`, `publications/pilobolus/*`, `corpora/pilobol-us-*.yml`, `PILOBOL_US_THEME_PACK_TOKENS` in `lib/site-stack.ts`, and a brand entry in the repo-root `papyrus.config.ts` | worktree of `origin/develop` |

### 1.2 Live AWS (account 335163751677, us-east-1, `AWS_PROFILE=legacy`)

| Item | Fact |
| --- | --- |
| Reader app `d1od6t7lzbwanr` (`pilobol-us`) | `WEB`, repo `github.com/anthusai/pilobol.us`, branch `main` autoBuild, domains `pilobol.us` and `www`, **no service role, no app-level build spec** (uses the repo's `amplify.yml`), `customRules` only `/<*>` to `/404.html` `404-200`, app env var **name** `ELEVENLABS_API_KEY` only (legacy; value never read), branch env empty. Last job 196 (`7f30fa9`) SUCCEED in 1.6 min |
| Reader build today | clones Papyrus at pin `d664fc7` and imports `papyrus_content` from that source tree; `pip install git+https://github.com/AnthusAI/Markus@v0.5.1`; `web/build_via_papyrus.py` |
| CMS app `d11eu9hbs2mipk` (`pilobol-us-cms`) | `WEB_COMPUTE`, repo `AnthusAI/Papyrus`, branch `main` autoBuild, domain `newsroom.pilobol.us`. Owned by CloudFormation stack `amplify-app-shell-pilobol-us` (2026-09-08, old shell: PAT-based repository; logical ids `App`, `Branch`, `Domain`, two roles, the same ids the new template uses). Legacy app spec (`npm install`, `ampx pipeline-deploy --debug`). Jobs 12 to 15 FAILED (2026-09-11 to 10-04); jobs 16 and 17 SUCCEED on 2026-10-05 from Papyrus `main` `d04b068` (12 min 39 s) |
| CMS `main` env (names) | `PAPYRUS_SITE_BRAND`, `NEXT_PUBLIC_PAPYRUS_SITE_BRAND` (both equal `pilobol-us`, checked by equality, not printed), `PAPYRUS_CONTENT_SOURCE` (value `graphql`, **invalid on develop**: only `published` or `drafts`), `PAPYRUS_EDITION_SLUG`, four `PAPYRUS_ENABLE_*`, `PAPYRUS_COGNITO_DOMAIN_PREFIX`, `PAPYRUS_OAUTH_REDIRECT_URLS`. No `SITE_ENV`, no `PAPYRUS_REVALIDATE_SECRET` |
| CMS backend (AppSync `daczqhhg25b2nfgrzpyc4vd7eq`) | all **39 DynamoDB tables scan-count 0** (Item, PublishedItem, MediaAsset, Edition, NewsroomSection, Reference, UserProfile all 0); media bucket has **0 objects**; Cognito user pool has **0 users** (groups `admin`, `curator`, `editor`; a Google IdP is defined); SSM secret names under `/amplify/d11eu9hbs2mipk/`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OPENAI_API_KEY`, `PAPYRUS_JWT_SECRET`. Data stack last updated 2026-10-05T13:54Z (job 17). So `bootstrap.md` sections 4 and 5 (sections, categories, corpus sync) were never run |
| Other | GitHub OIDC provider exists in the account; the only app-shell stack is `amplify-app-shell-pilobol-us`; secret `amplify/github-app-token` (the PAT) exists; hosted zone `pilobol.us` is in the account; `https://newsroom.pilobol.us/` answers 200 |

### 1.3 Papyrus packages and tools

| Item | Fact |
| --- | --- |
| Packages | npm `@anthusai/papyrus` tag `next` = `1.0.0-next.8`, `latest` = `0.0.0` (placeholder); PyPI `papyrus-newsroom` `1.0.0.dev8` (Python `>=3.12`). Prereleases only; a stable `1.0.0` needs a `develop` to `main` promotion, which is Ryan's (`main` is 80 commits behind `develop`) |
| Schema main to develop | `Item` and `PublishedItem` gain optional `bodyMarkus`, `bodyIr`, `aliases`, `metadata`; 5 new mutations on a new Python Lambda; storage rule `preview/*`; `defineSiteAuth`/`defineSiteBackend`. `schema.ts` diff adds **no secondary index** |
| `import-markus` (#115, #121) | verbatim front matter and body, idempotent, validates all before writing, never overwrites CMS edits, `--draft-dirs`, `--aliases-file`, `S3MediaStore` (private bucket, sha256 metadata) |
| `export-published` (#117) | published only unless `--drafts`; fail-closed on empty or any error; auth is **JWT lane or default AWS credentials, no guest mode** |
| `convert-bodies` (#109) | exists; nothing to convert here (0 rows) |
| Pretext reader gate (#109) | the CMS app does **not** serve Pretext article pages for this brand (`renderer: markus`; `getSiteRenderer` throws), so the `bodyIr` requirement never applies |
| Infra template (#112, #122) | always creates a reader app and domain for `markus-static`, two domains and a staging branch; no way to adopt existing apps (PPY-a91e9c covers only domains/staging). Generated reader and staging specs install `papyrus-newsroom[markus]`, but S3 media needs `boto3` (extra `newsroom`) |
| Staging (#119, #123) | middleware `runtime: "nodejs"` for all sites, unproven on WEB_COMPUTE; static staging proven only as a plan (sandbox proof was for Pretext drafts and content-actions, #127) |
| Rebuild-on-publish (#125) | IAM `amplify:StartJob` from the Lambda; the IAM resource ARN form is flagged unverified |

### 1.4 Measurements (scratch builds, no live writes)

* Scratch clone of `Pilobol.us@main` built with renderer pin `d664fc7` = **94 files**; built with
  Papyrus `develop` `4a423c3` = **identical** (`diff -rq` empty).
* Fetching all 94 paths from `https://pilobol.us`: **94/94 byte-identical** to the scratch build.
* Offline round trip with `develop` code (in-memory fake client, directory media store) on the
  21 tracked files: errors 0, created 21 (18 published, 3 drafts), 13 images (3,096,881 bytes; largest
  700 KB), 56 reader-owned assets not imported, 0 aliases, 0 redirects; export 18 items and 12 media;
  reader build from the export plus a no-clobber overlay of the Git `assets/` = **94 files identical to live**.
* 11 pages carry the Auritus embed (10 articles and `a-fungus-among-us`). Narration is generated in the
  reader's browser from the page text; with byte-identical HTML the narrated text is identical, so no job hash changes.
* Largest build file: `assets/he-said-he-could-see-it/gowy-fall-of-icarus.jpg`, 6,047,745 bytes (relevant to the 6 MB staging limit).

## 2. A. Target end state (recommended)

| Part | End state | Why |
| --- | --- | --- |
| Repo layout | **One repo, `AnthusAI/Pilobol.us`**, public as today. Adds `package.json` (exact-pinned `@anthusai/papyrus`), `papyrus.config.ts` (brand moved from Papyrus), `publication/theme.css`, `amplify/{backend,data/resource}.ts` one-liners, `corpora/*.yml`, `infra/` (own small app + `site.json`), `.github/workflows`. The reader stays in `web/` plus a `reader/build.py` entry. Pod (`stories/`, `project/`, wiki) unchanged | docs/standard-site.md 1.2 and 1.6 and the shipped `examples/pilobol-us.site.json` assume one repo feeding both apps. Alternative: a second `Pilobol.us-cms` repo (decision D1) |
| CMS app | `d11eu9hbs2mipk` **stays**, keeps backend and (zero) data; its build moves from Papyrus `main` to the Pilobol.us repo, spec generated by the template, packages pinned; GitHub App connection, no PAT | Backend is empty and the app is already owned by the shell stack. Fallback if the console cannot re-point it: replacement app on a fresh empty backend (section 4.2) |
| Backend | Same stack, schema updated in place by `ampx pipeline-deploy` on the Amplify build | additive; empty |
| Reader app | `d1od6t7lzbwanr` **stays** (DNS unchanged), build spec moves to the app, one spec with an env switch (`PILOBOL_SOURCE=cms`) between the Git path (default, unchanged) and the CMS path | instant rollback by env var |
| How the reader reads the CMS | `papyrus content export-published --auth guest` at build time (new, P3-02): unauthenticated Cognito identity pool credentials, public values as branch env vars, **no role, no token, no secret in the reader build** | published items and `media/*` are guest-readable; a JWT-lane build would hold a right to mint write tokens |
| Staging | CMS branch `staging` at `staging.pilobol.us`, drafts export with the editor/JWT lane, static preview in the private `preview/` prefix, Cognito `editor`/`admin` gate | standard 1.10 and decisions 6 and 14 |
| Rebuild-on-publish | content-actions Lambda calls `amplify:StartJob` for the reader (`d1od6t7lzbwanr`, `main`) | decision 7 (no webhook secret) |
| Brand | registered from the repo's `papyrus.config.ts`, id exactly `pilobol-us`; newsroom at `/newsroom` (changed from the root, see 4.4) | BRD gate; staging gate loop |
| Git content | frozen at cutover (tag `pre-cms-cutover`), the rollback until the soak ends, then removed from the tree | decision 4 of the epic: CMS is the source of truth |
| Out of scope (YAGNI) | the 22 PILO stories stay in the pod (they are board stories, not Items); Anth.us and TI are separate Phase 3 tickets | |

## 3. B. Steps (dependency order)

Tickets are `sub-task`, label `phase-3`, children of PPY-3367d3. "Ryan" = needed in person
(console, SSO, secrets) or for an explicit yes in chat for a LIVE step. Estimates are agent-days.

| # | Ticket | What | Live resources touched | Gate satisfied | Ryan | Est. | Blocked by |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P3-01 | PPY-4287e7 | Parity harness (byte diff, live diff, narration text hash) and baseline | none (HTTP GETs of the live site) | proof tool for "not one byte" | no | 0.5 | none |
| P3-02 | PPY-54b7e3 | `export-published --auth guest`; boto3 in the reader install | none (scratch sandbox only) | reader auth design (5) | SSO for sandbox | 1.5 | none |
| P3-03 | PPY-7835f2 | Template adopts live apps (reader by id, optional domains); reviewed non-replacing change set for the CMS stack | creates and deletes one change set object on the stack | INF limitation (PPY-a91e9c) | yes | 2 | none |
| P3-04 | PPY-af5c03 | Publication repo scaffold on packages, on a branch | none | brand registration (BRD), standard layout | D1, D3 | 3 | P3-03 |
| P3-05 | PPY-97f03c | Isolated proof backend on CMS branch `cms-proof`; stack update; GitHub App connect | CMS app config and stack; new branch + isolated backend | SCH on a real Amplify build, PRV (nodejs middleware), BRD, content-actions in package mode | **M1, M2** | 2 | P3-04 |
| P3-06 | PPY-0a84e5 | Rehearse import, export, byte parity on the proof backend | proof backend only | (4) offline-to-real data proof | yes (JWT, apply) | 1.5 | P3-05, P3-01 |
| P3-07 | PPY-b17cbe | Reader build spec from `amplify.yml` to the app, no behavior change | reader app spec, then a main merge | prerequisite for one repo feeding two apps | **M3** | 0.5 | P3-01 |
| P3-08 | PPY-eb1b18 | Production CMS: build off Papyrus `main`, deploy schema to the empty backend | CMS app `main`, production backend stack, first admin user | SCH, convert-bodies (n/a, 0 rows), browser verify, BRD, PRV | **M4** | 1.5 | P3-06, P3-07 |
| P3-09 | PPY-d9194c | Import 21 Git items into production CMS; offline export build == live | production tables and media bucket | (3), (4) | **M5** | 0.5 | P3-08 |
| P3-10 | PPY-bd249d | Reader reads the CMS export; `cms-reader` proof branch with in-build parity gate | reader app spec and a new non-production branch | (5), (7) | **M6** | 2 | P3-09, P3-02, P3-07 |
| P3-11 | PPY-d0c5ad | Staging site and the STG gate items | CMS stack (branch, domain), preview prefix | STG a, b, c, d | **M7** | 2 | P3-08, P3-10 |
| P3-12 | PPY-8b0f91 | Rebuild-on-publish proof on `cms-reader` | one test item in production backend (left unpublished) | RBP | yes | 1.5 | P3-10, P3-08 |
| P3-13 | PPY-11c365 | Cutover with parity gate; 7-day soak; instant rollback | reader `main` env and build | (8), narration (7) | **M8** | 1 + soak | P3-09, P3-10, P3-11, P3-12 |
| P3-14 | PPY-4a3c07 | Retire Git content; remove Pilobol.us from Papyrus; docs and procedures; delete PAT | Secrets Manager, reader env var | epic decision 4 | **M9** | 1.5 | P3-13 |

Parallel waves: **A** P3-01, P3-02, P3-03, P3-07 (P3-07 needs P3-01 for its proof); **B** P3-04, P3-05, P3-06;
**C** P3-08, P3-09; **D** P3-10, then P3-11 and P3-12 in parallel; **E** P3-13; **F** P3-14.

### 3.1 Deploying the Phase 2 schema to the existing production backend (item 1)

* **What changes (FACT):** four optional fields on two models, five mutations and one Lambda, one storage rule,
  auth and backend definition refactors. No new secondary index. Production data: none.
* **What Amplify does:** the CMS build runs `ampx pipeline-deploy` for branch `main` of app `d11eu9hbs2mipk`; the
  backend identity is app id plus branch name, not the repo, so changing the source repo updates the **same** stack
  in place (ASSUMPTION, standard Gen 2 behavior; proven by P3-05 on an equivalent isolated branch first). A failed
  deploy is a failed job with CloudFormation rollback and the previous deployment keeps serving (FACT: jobs 12 to 15
  failed this way and production stayed up).
* **Data migration:** none. **convert-bodies gate:** not applicable, because all tables are empty (re-checked with
  scan COUNT immediately before P3-08) and the CMS app serves no Pretext article route for this brand. If the
  counts are not 0 at that moment, **stop** and run `convert-bodies` as a dry run first.
* **Real risks:** construct-id changes in the refactor (`defineSiteBackend`) could cause **replacement** of the
  user pool, identity pool or tables; with an empty backend that loses nothing but can clash on the Cognito domain
  prefix `papyrus-pilobol-us` (which the Google OAuth setup depends on) and roll the job back. The proof branch uses a
  different prefix so it cannot clash. A synth-level diff against the deployed templates is not available through
  `ampx` (ASSUMPTION), so the proof is the isolated branch build, and the production build is the second run.
* **Rollback:** failure leaves production as is; a bad success is "redeploy job 17" (old frontend; the additive schema is
  harmless); full revert is possible because there is no data (reconnect to `AnthusAI/Papyrus`, previous stack template saved).

### 3.2 Moving the CMS app's build off Papyrus `main` (item 2)

* **What breaks:** (a) `PAPYRUS_CONTENT_SOURCE=graphql` is invalid on `develop` (`published|drafts`): must become `published`
  (done through the stack, P3-05); (b) `SITE_ENV` is unset, which the app treats as development (noindex headers, no
  staging guards): set `production` on `main`; (c) the build spec changes from `npm install` to `npm ci` plus `papyrus-app sync`;
  (d) brand ids are now **exact**: `PAPYRUS_SITE_BRAND` and `NEXT_PUBLIC_PAPYRUS_SITE_BRAND` must equal the registered id.
  FACT: both equal `pilobol-us` today (BRD gate satisfied for this site: no alias is involved); the repo's `papyrus.config.ts` registers
  exactly `pilobol-us`; unknown ids throw at startup (tested in scratch in P3-04); (e) the `?brand=` cookie override is gone; (f) middleware
  declares `runtime: "nodejs"` for all sites (PRV gate): proven first on the non-production `cms-proof` branch (pages, `/newsroom`
  redirect, `robots.txt`, production-mode behavior unchanged), then on `main`.
* **Order inside the CMS app (ordering hazard, ASSUMPTION):** apply the stack change set (spec, env, no PAT) **before** connecting the
  repository in the console, and verify `repository` afterwards, because a later stack update that omits `Repository` could disconnect it.
  Autobuild on `main` is switched off first so nothing rebuilds from a half-moved state; env values are baked at build time,
  so the running production deployment does not change.
* **Verification on a non-production branch first:** `cms-proof` (own backend, own Cognito prefix, Google off, `SITE_ENV=staging`) in P3-05.
* **Rollback:** reconnect `AnthusAI/Papyrus`, re-apply the saved stack template; keep the PAT secret until P3-14.

### 3.3 Importing the 21 Git items (item 3)

* Source is `git archive origin/main web/content` (tracked files only), never the local checkout.
* Dry run, reviewed with Ryan: `import-markus --content-dir <src> --draft-dirs drafts=articles --dry-run --json`
  expects created 21, published 18, drafts 3, media 13, readerOwnedAssets 56, errors 0 (FACT from the offline run; P3-06 repeats it
  on the proof backend, P3-09 on production with the same pinned package).
* Apply: `--apply --bucket <production media bucket>`; images upload to `media/assets/<slug>/...` through `S3MediaStore`
  (private bucket, guest-readable by the Storage rules, sha256 in object metadata); a second run must report created 0, updated 0,
  mediaUnchanged 13.
* Aliases and redirects: none. The live site has no redirect rules (only the catch-all `404-200`) and slugs and paths are preserved
  (`articles/<slug>.html`); the export's `redirects.json` is empty. Anth.us is the site that needs `aliases`.
* The three drafts are already public in Git; in the CMS they become private drafts (history is not rewritten).

### 3.4 Byte-identical proof against real stored data (item 4)

Three independent comparisons, all with the P3-01 harness: (1) scratch Git build == live (done today: 94/94); (2) CMS-export build
(from the proof backend in P3-06 and from production in P3-09) == the Git build, `diff -r` clean; (3) the first Amplify build of the CMS path
(P3-10, P3-13) carries the harness **inside the build** as a gate: the build fails, and therefore nothing deploys, if any byte differs
from the live site. Whether the renderer package (`develop`) differs from the old pin was measured: it does not for this content.

### 3.5 How the reader's Amplify build authenticates (item 5)

Per [standard-site.md](../standard-site.md) 1.8 and 1.10: published content is guest-readable, drafts need an editor lane only on staging.

| Option | How | Verdict |
| --- | --- | --- |
| **Guest read (recommended)** | New `export-published --auth guest`: `cognito-identity` `GetId` and `GetCredentialsForIdentity` unauthenticated, SigV4 to AppSync, the same credentials for `media/*` S3 reads. Public values (`PAPYRUS_GRAPHQL_ENDPOINT`, `PAPYRUS_IDENTITY_POOL_ID`, `PAPYRUS_MEDIA_BUCKET`, region) are plain branch env vars. Reader app needs no service role | 1.5 days (P3-02). Zero credentials; refuses `--drafts` and every write command |
| SSM-minted JWT (works today) | Reader service role with `ssm:GetParameter` on the CMS secret path, `papyrus auth refresh-jwt` per build | No code. The role can mint **write** tokens; not recommended for a public-content reader. Staging keeps this lane (drafts) |
| Long-lived token | | Forbidden (epic decision 3) |

### 3.6 Staging and rebuild-on-publish (item 6)

* **Staging (P3-11):** the stack adds branch `staging` and `staging.pilobol.us` (additions only, reviewed change set); build spec runs the drafts
  export, the reader entry, `upload-preview`, then the Next build; probes: anonymous redirected to a sign-in page **without a loop**, editor sees a
  draft with the STAGING banner and the draft is 404 on production, non-editor 403, `robots` disallow, noindex, bucket not public, `PAPYRUS_STAGING_PREVIEW` absent from `main`.
  The 6 MB limit is measured on the 6,047,745-byte image (fallbacks named in the ticket).
* **Rebuild-on-publish (P3-12):** proven on the `cms-reader` branch with a throwaway item published and unpublished **in the editor UI** (Lambda path),
  observing `StartJob` jobs, `pending-job-exists` suppression and the IAM resource ARN (the one unverified detail of #125). Production pages are not touched; the
  proof item stays an unpublished draft. At cutover (P3-13) the target is switched to `main` and one `papyrus content rebuild --reader` proves it.

### 3.7 Narration (item 7)

All 11 narrations are correct and live (per Ryan). The embed generates audio in the reader's browser; the job hash covers text, voice and backend, so **zero text drift = zero new jobs**.
Guards: the importer and exporter store and return the body verbatim (offline round trip: byte-identical files); the harness compares the narrated element's text hash
for the 11 pages at every step, and the in-build gate enforces it at cutover; do not press play on proof branches; no article is edited during the migration. Auritus v0.27.2 means a wrong
voice now fails loudly instead of silently substituting.

### 3.8 Cutover and rollback (item 8)

DNS does not change: `pilobol.us` and `www` stay on `d1od6t7lzbwanr`. One build spec serves both paths; `PILOBOL_SOURCE=cms` selects the CMS path, unset selects Git.
Cutover (P3-13): tag Git, point rebuild-on-publish at `main`, set the env on `main` with the parity gate on, start one job; the job either deploys identical bytes or fails with the live deployment untouched.
Rollback in seconds: clear the env map and start a job (Git path, frozen content). Because the Git copy goes stale once the CMS is the source of truth, **snapshot-export to Git first** if anything was published after cutover.
Soak: 7 days (decision D4), Git content kept; P3-14 removes it afterwards.

## 4. Gaps found and how the plan handles them

1. **Template cannot adopt the existing apps (P3-03).** `markus-static` requires a `reader` block that would create a new reader app owning `pilobol.us` (collision); domains and a staging branch are always created. Fix: `reader.amplifyAppId` adopt mode plus optional domains (with PPY-a91e9c).
2. **Replacement fallback for the CMS app.** If the console cannot re-point a PAT-connected, CFN-owned app (only repo-less to repo was tested) or the change set is not in-place: create a new CMS app from the template on a fresh empty backend (+1.5 days), move `newsroom.pilobol.us`, re-enter the four secrets (Google client id and secret, OpenAI key, JWT secret), delete the old stack with Ryan's approval. Nothing is lost because the backend is empty.
3. **Two apps, one repo, one `amplify.yml` (P3-07).** ASSUMPTION: a repo-level `amplify.yml` overrides app-level specs, so the reader's file would be run by the CMS app. Fix: the reader's spec moves to the app, byte-identical, proven by an identical rebuild, then the file is deleted; the proof branch carries its own file meanwhile.
4. **Staging gate loop (P3-04, P3-11).** With `newsroomBasePath: ""` and a newsroom root route, middleware redirects `/newsroom` to `/` while the gate redirects `/` to `/newsroom` (code reading, unproven live). The migrated brand uses `/newsroom` and a redirect root. Cost: the staff URL changes from `newsroom.pilobol.us/` to `.../newsroom` (root redirects).
5. **boto3 missing from the generated reader/staging spec install (P3-02).**
6. **Where the brand tokens live.** `PILOBOL_US_THEME_PACK_TOKENS` is core code in Papyrus; copied into the repo brand in P3-04, deleted from core in P3-14.

## 5. Release-gate matrix (epic comments 81291d, 492185, 19753b, c91ed6)

| Gate | Status for Pilobol.us | Where proven |
| --- | --- | --- |
| SCH deployed to the site's backend | pending | P3-05 (isolated), P3-08 (production) |
| convert-bodies run with `--apply` after a dry run | **not applicable**: 0 rows in every table, no Pretext article route on this app; re-checked by count immediately before P3-08 | P3-08 step 1 |
| Browser verification | pending | P3-05, P3-08 |
| BRD: exact brand id | **holds today** (both vars equal `pilobol-us`; the repo brand registers the same id) | P3-04, P3-08 |
| PRV: nodejs middleware on WEB_COMPUTE, non-production first | pending | P3-05 then P3-08 |
| STG a: `PAPYRUS_STAGING_PREVIEW` only on `staging` | pending | P3-11 |
| STG b: 6 MB response limit | pending (one file at 6,047,745 bytes) | P3-11 |
| STG c: static staging proof against a real backend | pending | P3-11 |
| LMB / staging auth against a real backend | sandbox-proven (#127); real backend pending | P3-05, P3-11 |
| RBP: StartJob IAM ARN form | pending | P3-12 |

## 6. C. Risk register

| # | Risk | Likelihood / impact | Mitigation | Owner step |
| --- | --- | --- | --- | --- |
| R1 | Production CMS data lost or corrupted | Low (backend is empty today) / High once content exists | Sequence: schema and build move **before** import; counts re-checked before each deploy; imports are idempotent and never delete | P3-08, P3-09 |
| R2 | Live site changes by one byte | Medium (many moving parts) / High | Parity harness at every step; scratch builds equal live today; in-build parity gate fails the build instead of deploying; rollback by env var | P3-01, P3-10, P3-13 |
| R3 | Narration hashes change, Batch jobs re-queue | Low / Medium | Byte identity implies identical text; text hash compared for 11 pages; no edits during migration | P3-01, P3-13 |
| R4 | GitHub App connection: a console flow behaves differently (platform flips to `WEB`, service role replaced, repo cannot be re-pointed, a later stack update disconnects it) | Medium / Medium | Save `get-app` before; verify platform, role and repository after each step; fix with `update-app --platform WEB_COMPUTE`; replacement fallback (4.2) | P3-05, P3-08 |
| R5 | Prerelease pins (`1.0.0-next.N` / `1.0.0.devN`) move or vanish; production runs on a prerelease while `latest` is a placeholder | Medium / Medium | Exact pins in both ecosystems and lockfiles; bump through a reviewed PR; upgrade to `1.0.0` after Ryan promotes `develop`; `npm ci --dry-run` in CI | P3-04 |
| R6 | Secrets in app env vars (`ELEVENLABS_API_KEY`) and SSM (JWT, Google, OpenAI) | Medium / High if leaked | Names only in every command and ticket; JWT minting only with Ryan's yes; scratch `.env` deleted; guest read removes the reader's need; repo is public: nothing secret in it | all |
| R7 | `ampx pipeline-deploy` replaces resources when the build source changes (backend code is now `defineSiteBackend`, ids may differ) | Low-Medium / Low (empty) | Same stack identity (app id + branch), isolated proof first, empty production backend, CloudFormation rollback, Cognito prefix kept; do it before import | P3-05, P3-08 |
| R8 | Python 3.12 provisioning via `uv` on the Amplify image is unproven; Lambda bundling in package mode unproven on Amplify | Medium / Medium (delay, not harm) | First exercised on `cms-proof` and `cms-reader`; +1 day budget; fallback custom build image or vendored wheel | P3-05, P3-10 |
| R9 | CMS outage during a reader build | Low / Medium | `export-published` fails closed (empty or error fails the build; old deployment keeps serving) | P3-10 |
| R10 | Proof branch page is publicly reachable (Amplify branch URL) | Low / Low | HTML canonical and `og:url` point to `https://pilobol.us`; short-lived; no narration played; delete after | P3-10 |
| R11 | Git rollback path goes stale after cutover | Medium / Medium | Snapshot export to Git before any rollback; 7-day soak with no Git edits | P3-13 |
| R12 | Static staging serves the 6,047,745-byte image through WEB_COMPUTE | Medium / Low (staging only) | Measure; fallback presigned redirect or size cut for staging | P3-11 |
| R13 | Desk workflow break: people or bots still commit to `web/content` | Medium / Medium | AGENTS.md and skills rewritten in P3-14; automation is board-only already; reader build no longer reads Git content after P3-14 | P3-14 |
| R14 | Auritus Batch, voice or key changes during the window | Low / Medium | Not touched by this plan; v0.27.2 fails loudly on a wrong voice | P3-13 |

## 7. D. Decisions needed from Ryan

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | One repo (`AnthusAI/Pilobol.us` holds pod, reader and the Next CMS app) or a second `Pilobol.us-cms` repo? | **One repo**, per standard-site 1.2 and 1.6 and the shipped example site file. Cost: the public pod repo gains a Next app and a dependency tree. Pick two repos if you want the pod to stay untouched; then P3-04 and P3-07 change shape (no spec conflict) |
| D2 | Reader build credentials: guest read (new 1.5-day change) or SSM JWT (no code)? | **Guest read** |
| D3 | Run production on prerelease pins (`1.0.0-next.N`) until you promote `develop` to `main`, or wait for stable `1.0.0`? | **Pin exact prereleases now** (this site's release gates are self-contained); move to `1.0.0` after your promotion |
| D4 | Soak length and rollback content: 7 days, Git frozen, snapshot-export before any rollback? | **Yes, 7 days** |
| D5 | Move the staff newsroom URL from `newsroom.pilobol.us/` to `newsroom.pilobol.us/newsroom` (needed for staging)? | **Yes** (0 users today) |
| D6 | After cutover, who publishes: humans via `/newsroom` (or `papyrus content publish` run by an agent at your explicit ask); automation stays board-only | **Yes** |

Not decisions (just for awareness): the 3 drafts become private CMS drafts; PAT secret and `ELEVENLABS_API_KEY` deletion in P3-14 is yours.

## 8. Moments Ryan is needed

| # | When | What |
| --- | --- | --- |
| M1 | P3-05 | **GitHub App (CMS app):** install the AWS Amplify GitHub App on `AnthusAI/Pilobol.us` (this repo only); connect `d11eu9hbs2mipk` to it in the console; check platform stays `WEB_COMPUTE` and the service role is unchanged. Set the proof branch secrets (`PAPYRUS_JWT_SECRET`, `OPENAI_API_KEY`) in the console; browser check |
| M2 | P3-05, P3-06 | AWS SSO login (`aws sso login --profile legacy`); yes to the change set execution, branch creation, JWT mint on the proof backend, import apply |
| M3 | P3-07 | Yes to the reader app spec update and the merge that removes `amplify.yml` |
| M4 | P3-08 | Yes to merge the scaffold to `main`, to starting the CMS job, to the first admin user; browser check of `newsroom.pilobol.us` |
| M5 | P3-09 | Yes to minting a JWT for the production backend and to the import apply |
| M6 | P3-10 | **GitHub App (reader app):** confirm `d1od6t7lzbwanr` is connected through the Amplify GitHub App (migrate it if it is still OAuth); yes to the app spec and the `cms-reader` branch |
| M7 | P3-11 | Yes to staging branch and domain; sign-in checks as editor and non-editor |
| M8 | P3-13 | Go/no-go; yes to tagging, the env change and the cutover job; browser check |
| M9 | P3-14 | Merge approvals; delete the PAT secret; decide the `ELEVENLABS_API_KEY` env var |

## 9. E. Estimates and critical path

Total about **21.5 agent-days**: P3-01 0.5, P3-02 1.5, P3-03 2, P3-04 3, P3-05 2, P3-06 1.5, P3-07 0.5, P3-08 1.5, P3-09 0.5,
P3-10 2, P3-11 2, P3-12 1.5, P3-13 1, P3-14 1.5.

**Critical path:** P3-03 (2) to P3-04 (3) to P3-05 (2) to P3-06 (1.5) to P3-08 (1.5) to P3-09 (0.5) to P3-10 (2) to P3-11 (2) to P3-13 (1)
= **15.5 agent-days to cutover**, then the 7-day soak and P3-14 (1.5). P3-12 runs beside P3-11; P3-01, P3-02, P3-07 run beside P3-03 to P3-05.
Add waits for Ryan's moments (calendar time, not effort) and budgets named in the risks (+1 day for Python 3.12, +1.5 for the replacement fallback).

## 10. Re-verifying the facts (read-only)

```bash
export AWS_PROFILE=legacy AWS_REGION=us-east-1          # read AGENTS.local.md first
aws amplify get-app --app-id d11eu9hbs2mipk              # never print environmentVariables values
aws amplify list-jobs --app-id d11eu9hbs2mipk --branch-name main --max-results 6
aws dynamodb scan --table-name Item-daczqhhg25b2nfgrzpyc4vd7eq-NONE --select COUNT   # also PublishedItem, MediaAsset
aws amplify list-domain-associations --app-id d1od6t7lzbwanr
aws cloudformation describe-stack-resources --stack-name amplify-app-shell-pilobol-us
git clone https://github.com/AnthusAI/Pilobol.us scratch/pilo      # build only in scratch copies
```
