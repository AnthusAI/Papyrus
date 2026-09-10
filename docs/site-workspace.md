# Site workspaces (local filesystem convention)

A Papyrus publication with a split reader + CMS needs **one local folder that
assembles the whole site**: the static reader repo, the Papyrus CMS checkout
(as a dependency), and a local data volume for analysis that posts back to the
cloud. This file defines that layout so it is the same for every site.

Kanbus: PPY-43704a. First instance: Pilobolus. Related:
[site-hosting.md](site-hosting.md), [site-stacks.md](site-stacks.md),
[new-publication-from-corpus.md](new-publication-from-corpus.md).

## Why a workspace

A site is not one repo. It is three things bound together:

1. **Reader** — a static site repo (Markus HTML) deployed on its own Amplify
   `WEB` app. Example: `AnthusAI/Pilobol.us` on `pilobol.us`.
2. **CMS** — a Papyrus checkout configured for one brand
   (`PAPYRUS_SITE_BRAND=<id>`), deployed on its own Amplify `WEB_COMPUTE` app
   with its own AppSync + S3 bucket. Papyrus is a **dependency pulled in**,
   not forked per site.
3. **Data** — corpus accession files and analysis run output that are too large
   or too churny for git. They live locally, feed local analysis (Biblicus topic
   modeling, extraction, graph), and **post back to the cloud** (AppSync +
   the CMS S3 bucket) after.

Without a workspace convention these three scatter across `~/Projects` and the
binding between them lives in someone's head. This file makes the binding
inspectable.

## Canonical layout

```text
<Projects>/<Site>/                       # e.g. Pilobolus/  (workspace root)
  site.yml                                # manifest: declares the bindings
  reader/                                 # static reader repo (clone or worktree)
  cms/                                    # Papyrus checkout/worktree (the dependency)
  data/                                   # local data volume (gitignored, posted to cloud)
    corpora/<corpus-key>/                 # corpus accession working copy
    runs/                                 # analysis run output (.papyrus-runs)
```

`reader/` and `cms/` are git worktrees (or clones) of their respective repos.
`data/` is a plain local volume — **never** committed to git.

### Binding data into the CMS worktree

Papyrus resolves corpus paths relative to its own root
(`path: corpora/<corpus-key>` in steering configs, and `.papyrus-runs/` for
run output). Both are already gitignored in Papyrus, so they are *data*, not
code — even though they physically sit inside the worktree.

The workspace makes that explicit by relocating data into `data/` and symlinking
back so Papyrus runs unchanged:

```bash
# from <Site>/cms/
ln -s ../data/corpora/<corpus-key> corpora/<corpus-key>
ln -s ../data/runs .papyrus-runs
```

Now `cms/corpora/<corpus-key>` and `cms/.papyrus-runs` resolve to the volume,
Papyrus's relative steering paths keep working, and the data lives outside any
git repo. This mirrors the existing convention in `AGENTS.md`: treat S3 as the
durable corpus source of truth and local `corpora/` as working copies.

### Reader build dependency

The reader build already expects a Papyrus checkout. Point it at the workspace
CMS:

```bash
cd <Site>/reader/web
PAPYRUS_ROOT=$(pwd)/../cms python3 build_via_papyrus.py
```

No `PAPYRUS_ROOT` guessing, no separate Papyrus clone to keep in sync.

## `site.yml` manifest

One file declares the site so a new agent or operator can assemble it without
folklore:

```yaml
schemaVersion: 1
site: pilobolus
brandId: pilobol-us            # PAPYRUS_SITE_BRAND
corpusKey: pilobol-us
reader:
  repo: https://github.com/AnthusAI/Pilobol.us
  path: reader                 # workspace-relative
  domain: pilobol.us
  amplifyAppId: d1od6t7lzbwanr
  platform: WEB
cms:
  repo: https://github.com/AnthusAI/Papyrus
  path: cms                    # workspace-relative
  branch: cursor/pilobol-us-cms-backend-6799   # or main once merged
  domain: newsroom.pilobol.us
  amplifyAppId: null           # fill after `pilobol-us-cms` app is created
  platform: WEB_COMPUTE
  env:
    PAPYRUS_SITE_BRAND: pilobol-us
    NEXT_PUBLIC_PAPYRUS_SITE_BRAND: pilobol-us
    PAPYRUS_CONTENT_SOURCE: graphql
data:
  path: data
  corpora:
    - corpusKey: pilobol-us
      s3Prefix: s3://<pilobol-us-cms-media-bucket>/corpora/pilobol-us/
    - corpusKey: pilobol-us-source
      s3Prefix: s3://<pilobol-us-cms-media-bucket>/corpora/pilobol-us-source/
cloudSync:
  postAnalysisTo: appsync       # analysis results post back via CLI / GraphQL
  postCorpusTo: s3              # corpus accession syncs to the CMS bucket
```

`amplifyAppId: null` for the CMS is intentional until the app exists; fill it
on first deploy.

## Local analysis → cloud round trip

This is the reason `data/` exists. Some work only runs locally (Biblicus topic
modeling, extraction, graph builds) and the results must land in the cloud CMS:

1. **Pull corpus** from the CMS bucket into the local volume:
   ```bash
   cd <Site>/cms
   PYTHONPATH=src python -m papyrus.cli ops corpora sync-from-cloud \
     --config <steering.yml> --corpus-key <corpus-key>
   ```
2. **Run local analysis** (Biblicus) against `data/corpora/<key>/`. Output
   lands in `data/runs/`.
3. **Post results back** to the cloud CMS:
   - Corpus accession: `ops corpora sync-to-cloud` → CMS S3 bucket.
   - Taxonomy / graph / reference state: `ops categories import-config`,
     `knowledge concepts import-types`, `references ...` → CMS AppSync.
   - Analysis artifacts: `analysis execute-assignment` records the snapshot
     path in GraphQL; the artifact stays in S3.

The local volume is a scratchpad; the deployed CMS app (AppSync + its S3
bucket) is the durable source of truth. Re-running analysis rebuilds the
local volume from S3 + GraphQL.

## General pattern (any site)

The same shape works for every split publication:

| Site | reader repo | cms brand | reader domain | cms domain |
| --- | --- | --- | --- | --- |
| Pilobolus | `AnthusAI/Pilobol.us` | `pilobol-us` | `pilobol.us` | `newsroom.pilobol.us` |
| *(future)* | `AnthusAI/<Site>.us` | `<site-id>` | `<site>.us` | `newsroom.<site>.us` |

For a **single-app** publication (Threat Intelligence style), the workspace
collapses: `reader/` and `cms/` are the same Papyrus checkout, and there is one
domain. Keep the `data/` volume regardless — local analysis still needs it.

## Bootstrapping a new workspace

```bash
mkdir -p <Projects>/<Site>/{reader,cms,data/corpora,data/runs}
cd <Projects>/<Site>

# reader (clone or worktree of the reader repo)
git clone <reader-repo> reader          # or: git worktree add reader <branch>

# cms (worktree of Papyrus on the site branch)
git -C <Projects>/Papyrus worktree add cms <site-branch>
cd cms && ln -s ../data/runs .papyrus-runs
ln -s ../data/corpora/<corpus-key> corpora/<corpus-key>

# manifest
$EDITOR site.yml     # copy the template above, fill in ids/domains
```

## Anti-patterns

| Anti-pattern | Why it fails |
| --- | --- |
| Fork Papyrus per site | Loses framework updates; site drifts. Pull Papyrus in as a worktree instead. |
| Commit `data/` to git | Large/churny analysis output pollutes history and breaks clones. |
| Store corpus data only in the Papyrus worktree (no volume) | Ties data to one checkout; worktree switches lose it. |
| Point `PAPYRUS_ROOT` at a random Papyrus clone | Drift between reader build and the CMS config. Use `<Site>/cms`. |
| Share one CMS app across sites | Couples unrelated corpora; forbidden (see site-hosting.md). |

## Related

- [`publications/pilobol_us/docs/bootstrap.md`](../publications/pilobol_us/docs/bootstrap.md)
  — Pilobolus CMS Amplify app setup.
- [`docs/new-publication-from-corpus.md`](new-publication-from-corpus.md) —
  corpus accession and reference registration.
- [`skills/publication-bootstrap/SKILL.md`](../skills/publication-bootstrap/SKILL.md)
  — end-to-end bootstrap skill.
