# Pilobol.us migration plan (Phase 3), v2

Status: **PLAN for Ryan's approval. Nothing here has been executed.** Kanbus PPY-3367d3
under epic PPY-1f1489. Design reference: [standard-site.md](../standard-site.md) 3.3.

Ryan's correction (2026-10-06): Pilobol.us is **pre-production**, Git history is the
rollback. So: **hard cutover**, no soak, no Git freeze, no dual Git/CMS build path, no
parity gate, brief downtime accepted. Earlier drafts of this plan (v1, risk-controlled
for a live site) were replaced.

Marks: **FACT** (verified 2026-10-06, read-only AWS, public GETs, scratch builds) or
**ASSUMPTION** (named step proves it).

## 1. Facts that drive the plan

* **CMS backend is empty.** Old CMS app `d11eu9hbs2mipk` (`newsroom.pilobol.us`): all 39 DynamoDB
  tables 0 rows, media bucket 0 objects, Cognito 0 users. FACT.
* **Old apps.** CMS app is `WEB_COMPUTE` in CloudFormation stack `amplify-app-shell-pilobol-us`,
  connected with a PAT, building Papyrus `main`; reader `d1od6t7lzbwanr` is `WEB`, hand-made, domains
  `pilobol.us` and `www`, repo-file `amplify.yml`, no service role. FACT.
* **Content.** `AnthusAI/Pilobol.us` (public) tracks **21 `.md`** under `web/content` (10 articles,
  `a-fungus-among-us`, 3 drafts, 7 `effects/` pages) plus 65 asset files. The "23" in PR #115 counted two
  build-generated, gitignored listing pages; never import them. FACT.
* **Fidelity.** A scratch build of `Pilobol.us@main` = 94 files, identical to the live site and identical with
  the old pinned renderer and Papyrus `develop`. An offline import/export of the 21 files: created 21
  (18 published, 3 drafts), 13 images (3.1 MB), 56 reader-owned assets not imported, 0 aliases and redirects;
  rebuilt site = the same 94 files. FACT.
* **Packages.** npm `@anthusai/papyrus` `next` = `1.0.0-next.8` (`latest` is a `0.0.0` placeholder); PyPI
  `papyrus-newsroom` `1.0.0.dev8`, Python `>=3.12`. FACT.
* **Template gaps** (`infra/amplify-app-shell`): always creates domains and a staging branch, and for `markus-static`
  a reader app with a domain; generated reader/staging specs install `papyrus-newsroom[markus]`, but S3 media needs
  `boto3` (extra `newsroom`). Console connect of a repo-less app works (PPY-a91e9c). FACT.
* **Reader auth.** `export-published` has no guest mode today (JWT lane or default AWS creds). Published items and
  `media/*` are guest-readable. FACT.
* **Brand.** The CMS app serves no Pretext article route for this brand, so the `bodyIr`/`convert-bodies` release gate
  does not apply; brand ids are exact (`pilobol-us`). The current brand puts the newsroom at the site root, which loops the
  staging gate (code reading, unproven). The migrated brand uses `/newsroom`. FACT / ASSUMPTION.
* **Auritus.** The embed is origin-locked to the site key's origin; the origin stays `pilobol.us`, so nothing changes.
  Bodies are stored verbatim, so article text (and narration hashes) are unchanged. Narration will not play on
  temporary `amplifyapp.com` URLs: expected.

## 2. Decision: new apps, not adoption

| | Adopt the old apps (v1) | **Create new apps from the template (chosen)** |
| --- | --- | --- |
| CMS app | Re-point a PAT-connected, CFN-owned app to a new repo in the console (unverified), change-set review of a stack with a different shape | Repo-less app + GitHub App connect (proven 2026-10-06) |
| Backend | In-place schema deploy, possible resource replacement | Fresh backend, nothing to lose or migrate |
| Template work | Adopt mode (`reader.amplifyAppId`, change-set helper) | Only what PPY-a91e9c already wants (optional domains) plus `boto3` |
| Cost | Downtime-free but risky, more steps | Brief downtime at the domain move (accepted) |

New apps win: fewer steps, no unverified console behavior on a legacy app. The old apps stay untouched until the final step.
The old stack name would collide, so `site.json` gets an optional `stackName` and the new stack starts **without domains**;
the domains move last (a domain belongs to one app).

## 3. End state

One repo `AnthusAI/Pilobol.us` (agreed D1) depends on the published packages (exact prerelease pins, D3) and feeds
two new apps: CMS (`WEB_COMPUTE`: `main` = `newsroom.pilobol.us`, `staging` = `staging.pilobol.us`) and reader (`WEB`: `pilobol.us`,
`www`). The reader builds from `papyrus ops content export-published --auth guest` (D2: unauthenticated Cognito identity,
public values as env vars, no role or token). Staging is the standard Cognito-gated drafts preview. Publish triggers a reader
build through `amplify:StartJob`. The brand is registered from the repo (`pilobol-us`, newsroom at `/newsroom`, D5); humans publish in
`/newsroom` (D6). The Git content path is deleted; Git history (tag `pre-cms-cutover`) is the rollback. The 22 PILO stories stay in
the pod. Old apps, stack, empty backend and the PAT secret are deleted.

## 4. Steps (tickets, execution order)

Sub-tasks of PPY-3367d3, label `phase-3`. Estimates are agent-days.

| Ticket | Id | What | Est. | Blocked by |
| --- | --- | --- | --- | --- |
| P3-00 | PPY-54b7e3 | Guest-read `export-published`; boto3 in reader install (D2) | 1.5 | none |
| P3-01 | PPY-4287e7 | One-time byte-diff sanity script (not a gate) | 0.25 | none |
| P3-02 | PPY-7835f2 | Template for new repo-less apps: optional domains/staging/reader domain, `stackName`, boto3 in specs (with PPY-a91e9c) | 1.5 | none |
| P3-03 | PPY-af5c03 | Repo scaffold on the packages (brand moved, `/newsroom`, `infra/site.json`, `reader/build.py`, delete `amplify.yml`) | 2.5 | P3-02 |
| P3-04 | PPY-97f03c | Create the new CMS and reader apps, GitHub App connect, first CMS build, release-gate checks | 1.5 | P3-03 |
| P3-05 | PPY-d9194c | Import the 21 items (dry run, apply) and byte-diff export fidelity | 0.5 | P3-04, P3-01 |
| P3-06 | PPY-bd249d | Hard switch: reader builds from the CMS export; delete the Git content path | 1.5 | P3-05, P3-00 |
| P3-07 | PPY-d0c5ad | Staging site and staging gate checks | 1.5 | P3-06 |
| P3-08 | PPY-8b0f91 | Rebuild-on-publish live proof | 1 | P3-06 |
| P3-09 | PPY-11c365 | Move domains, retire old apps/stack/backend/PAT, docs and procedures | 1.5 | P3-05, P3-06, P3-07, P3-08 |

**Parallel:** P3-00, P3-01, P3-02 start together. P3-07 and P3-08 run together after P3-06.
**Total about 13.25 agent-days. Critical path:** P3-02 (1.5), P3-03 (2.5), P3-04 (1.5), P3-05 (0.5), P3-06 (1.5), P3-07 (1.5), P3-09 (1.5) = **10.5 agent-days**.
Add about 1 day if Python 3.12 provisioning on Amplify needs a workaround.

### Removed from v1 and why

| v1 ticket | Why removed |
| --- | --- |
| PPY-0a84e5 P3-06 proof-backend rehearsal | Risk control for a live site; its useful part (dry run, apply, byte diff) is in P3-05 |
| PPY-eb1b18 P3-08 production CMS move and schema deploy | Replaced by fresh apps and a fresh backend (P3-04) |
| PPY-b17cbe P3-07 reader spec move | Existed only for the dual Git/CMS path; the new reader app has a generated spec |
| PPY-4a3c07 P3-14 Git retirement | Merged into P3-09; no soak means no separate step |
| P3-01 harness/gate, in-build parity gate, `PILOBOL_SOURCE`, soak, snapshot export | Live-site machinery; P3-01 is now a one-time script |

### What each step must show

* **P3-04 (release gates).** SCH: the fresh backend has `bodyMarkus` etc. on `Item` and `PublishedItem`. `convert-bodies`: not applicable
  (no rows). BRD: unknown brand id fails a scratch build, `PAPYRUS_SITE_BRAND` and `NEXT_PUBLIC_PAPYRUS_SITE_BRAND` equal `pilobol-us`.
  PRV: nodejs middleware works on WEB_COMPUTE (pages, `/newsroom`, `robots.txt`). First admin created and signs in. New Cognito domain prefix
  must differ from the old pool's `papyrus-pilobol-us` until the old backend is deleted.
* **P3-05.** `import-markus --draft-dirs drafts=articles --dry-run`, review with Ryan (expect created 21, published 18, drafts 3, media 13, errors 0),
  then `--apply`; re-run is a no-op; export and rebuild differ from Git by zero bytes. Source is `git archive origin/main web/content`.
* **P3-06.** Reader job succeeds from the export on the new reader's default URL; scratch Git build vs new site byte diff clean; wrong endpoint fails the build.
* **P3-07.** Anonymous staging visitor is redirected to sign-in without a loop, editor sees a draft, non-editor 403, noindex/robots, bucket private,
  `PAPYRUS_STAGING_PREVIEW` absent from `main`; the 6,047,745-byte image (`gowy-fall-of-icarus.jpg`) is measured against the 6 MB limit.
* **P3-08.** Publish and Unpublish in `/newsroom` start reader jobs; IAM resource ARN form (unverified in #125) works.
* **P3-09.** `pilobol.us`, `www`, `newsroom.`, `staging.` answer from the new apps; Auritus works on `pilobol.us`; old resources gone.

## 5. Risks (live-site risks dropped)

| Risk | Mitigation |
| --- | --- |
| Console connect flips platform to `WEB` or replaces the service role (seen in the connect test) | Check after connect; `aws amplify update-app --platform WEB_COMPUTE` (P3-04) |
| Python 3.12 via `uv` on the Amplify image, and Lambda bundling from `papyrus-newsroom==<pin>`, unproven | First exercised in P3-04 and P3-06; +1 day budget |
| Prerelease pins move or vanish | Exact pins and a from-scratch lockfile; bump by reviewed PR; move to `1.0.0` after Ryan promotes `develop` |
| Secrets in app env vars and SSM | Names only everywhere; JWT minted only with Ryan's yes, scratch `.env` deleted; guest read removes the reader's need; public repo holds none |
| Domain move: a domain is on one app only; certificate wait | Delete old domain associations first, then add via stack update; downtime accepted |
| Staging gate loop with a root-level newsroom | Brand uses `/newsroom`; probed in P3-07 |
| 6 MB response limit for the largest asset on staging | Measured in P3-07; exclude files over 5 MB from the staging upload if needed |
| Template change (PPY-a91e9c) not merged when needed | P3-02 includes it |

## 6. Decisions

Agreed 2026-10-06: D1 one repo, D2 guest read, D3 exact prerelease pins, D5 newsroom at `/newsroom`, D6 humans publish; D4 changed to hard cutover.
**Open: none.** (Optional: whether to enable Google sign-in on the new backend; default off, email sign-in.)

## 7. Moments Ryan is needed (four)

| # | When | What |
| --- | --- | --- |
| M1 | P3-04 | `aws sso login --profile legacy`; yes to the new stack deploy |
| M2 | P3-04 (one console sitting) | Install the AWS Amplify GitHub App on `AnthusAI/Pilobol.us`; connect the new CMS app and the new reader app (and the `staging` branch in P3-07); set backend secrets (`PAPYRUS_JWT_SECRET`, `OPENAI_API_KEY`); browser check of `/newsroom`; create the first admin |
| M3 | P3-05 to P3-08 | Yes to the JWT mint and the import apply; yes to env vars and merges; sign in as editor and non-editor for the staging probes; click Publish/Unpublish for the rebuild proof |
| M4 | P3-09 | Yes to deleting the old domains, apps, stack, empty backend and the PAT secret (Ryan or on his explicit yes); yes to the domain stack update |
