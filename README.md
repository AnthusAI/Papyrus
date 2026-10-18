# Papyrus

You are focused on a topic. For us, it is AI/ML information systems. For you,
it might be golf club technology, oil markets, local
politics, or any other beat worth watching closely.

Papyrus turns that focus into a fully automated newsroom. Research agents
monitor the beat while you sleep, update a publication-specific knowledge base,
and surface surprising developments. Editor agents turn those signals into
assignments. Reporter agents prepare private reporting packets: the verified
facts, source trail, open questions, risks, angle, and copywriter brief an editor
needs before commissioning reader-facing copy. Copywriter agents turn selected
packets into draft Items for review. The next morning, you can open your
newsroom and see what it found, what it recommends, what needs copywriting, and
what is ready for review.

You steer it like an executive editor, as much or as little as you want:
choosing the canonical categories for topic coverage, configuring editorial
sections for the issue, setting editorial policy, selecting the strongest
packets for copywriting, commenting on drafts, and culling assignments before
publication. When you step back, Papyrus keeps operating from the momentum you
already gave it: accepted categories, current policy, section doctrine, open
assignments, prior decisions, and rejected proposal memory.

The beat is configuration, not code. The current AI/ML corpus is pilot content,
not an application assumption. A Papyrus publication changes subject by
changing publication configuration, corpus set, category/graph steering state,
edition plans, and worker instructions.

To start a new publication from a pile of files, follow
[`docs/new-publication-from-corpus.md`](docs/new-publication-from-corpus.md).
That workflow defines the corpus accession shape, reference-prospect intake,
accepted-only analysis manifests, authoritative labels, topic granularity
profiles, and `analysis.reindex` assignment path used to bootstrap a knowledge
base from scratch.

## What is in the box

- **A newsroom.** `/newsroom` is the operations workspace: topics, sections, doctrine, references, assignments, editions. Agents research and report in private; editors steer and decide. See [Newsroom operations](docs/newsroom-operations.md) and [How Papyrus works](docs/how-papyrus-works.md).
- **A knowledge base.** Accepted categories, references and a semantic graph give agents context beyond vector search. Search it with `knowledge-query` ([internal knowledge research](docs/internal-knowledge-research.md)).
- **A reader.** Either a newspaper-style Next.js reader laid out by a Pretext solver ([layout system](docs/layout-system.md)) or a static Markus site served from S3 and CloudFront ([site hosting](docs/site-hosting.md)).
- **A CLI.** `papyrus` signs every request with your AWS credentials (SigV4); there is no token to manage ([operator CLI](docs/operator-cli.md), [recipes](docs/python-cli-and-testing.md)).

## How a Papyrus Publication Fits Together

![How a Papyrus publication fits together: editors use the newsroom UI in the CMS app; Save calls the AppSync GraphQL API, and the content-actions Lambda renders only the affected pages into a versioned S3 site bucket served by CloudFront; a renditions Lambda makes images at upload; the Pretext kind is a Next.js server on Amplify that reads published models as a guest](docs/images/publication-architecture.svg)

Text version of the picture:

- **One CMS app per site.** Editors sign in with Google to the newsroom UI. Every change goes through the GraphQL API (AppSync), which stores items and published items in DynamoDB. Uploaded images go to the media bucket.
- **Save is live.** For a Markus site (publication kind `s3-projection`, the default for new sites), the `content-actions` Lambda behind the Save, Publish and Unpublish mutations saves the item and then renders only the pages that depend on it (the item page, the listings, tags, home, sitemap) into a versioned S3 site bucket. There is no build job and no Republish button; a change is visible within seconds. Writes happen in an order that never leaves a link to a missing page.
- **Images are made at upload.** An S3 event on the media bucket starts the `renditions` Lambda, which writes the responsive image files and a small size file into the site bucket. Page renders read the size file and never decode an image.
- **CloudFront serves the bucket.** The site's own CloudFront stack (with its own certificate) reads the private bucket and runs small edge functions for redirects and for `/x/` to `/x/index.html`. After each projection the Lambda invalidates exactly the changed paths, never a wildcard.
- **Pretext is the alternative kind.** A Pretext site is a Next.js server on Amplify that renders pages on request from the published models. A publish tells it to revalidate, and a page lives about a minute at most.
- **Guests are read-only.** The public (guest) GraphQL surface can read the published models and `media/*`, nothing else, and no model or mutation allows a guest to write.
- **Where Git fits.** Git holds code, theme and the site's projector, not articles. Content lives in DynamoDB; the site can always be re-projected from it with `papyrus ops content project --all`.

Details: [How a publish flows](docs/how-a-publish-flows.md) (for editors) and [Site hosting](docs/site-hosting.md) (for operators).

## Quick start

Requirements: Node and npm, Python 3.12 or 3.13, [Poetry](https://python-poetry.org/), and an AWS profile for anything that touches the cloud.

```bash
npm install
poetry install
cp .env.example .env     # app-level settings only; never credentials
npm run dev:127          # http://127.0.0.1:3001 (prefer 127.0.0.1 over localhost)
```

Settings you need for the features named:

| Variable | Used for |
| --- | --- |
| `PAPYRUS_GRAPHQL_ENDPOINT` | CLI and agents talking to a deployed AppSync API |
| `PAPYRUS_INBOUND_EMAIL_DOMAIN` | Addresses for inbound email submissions and replies |
| `PAPYRUS_PUBLIC_SITE_BASE_URL` | Absolute links in submission feedback (or `publicSite.baseUrl` in the Papyrus config) |

The shell environment wins over `.env`. See `.env.example` for the full list and [docs/inbound-email-submissions.md](docs/inbound-email-submissions.md) for the email flow.

For a cloud sandbox:

```bash
AWS_PROFILE=<profile> npm run sandbox          # provisions an Amplify sandbox
AWS_PROFILE=<profile> npm run seed:amplify     # users, sections, doctrine, procedures
poetry run papyrus ops content seed-edition    # fixture edition, articles and media
```

Production deploys run from `main` through the DevOps pipeline. Do not run `ampx pipeline-deploy` locally.

## Commands

## Commands

```bash
npm run dev
npm run dev:127
npm run lint
npm run typecheck
npm run build
poetry install
poetry run papyrus --help
poetry run papyrus procedures execute-tactus 'return api_list{}'
poetry run python procedures/newsroom/tests/test_newsroom_tools.py
npm run sandbox
npm run seed:amplify
poetry run papyrus ops content inspect
poetry run papyrus ops categories import-config --config corpora/papyrus-steering.yml
poetry run papyrus sections import --config corpora/papyrus-newsroom-sections.yml
poetry run papyrus ops categories import-steering --config corpora/papyrus-steering.yml --corpus-key <key>
poetry run papyrus ops categories import-steering --bundle <steering-export.json>
poetry run papyrus knowledge topics export-category-set --category-set <id> --output <accepted-category-set.json>
poetry run papyrus ops categories import-projection --config corpora/papyrus-steering.yml --target-corpus-key <key> --authority-corpus-key <key> --bundle <projection.json>
poetry run papyrus knowledge concepts import-types --config corpora/papyrus-semantic-relation-types.yml
poetry run papyrus knowledge concepts backfill --config corpora/papyrus-semantic-relation-types.yml
npm run test:bdd
npm run test:bdd:backend
npm run test:bdd:agent-live
```

Test suites and verification: [docs/verification.md](docs/verification.md), [docs/python-cli-and-testing.md](docs/python-cli-and-testing.md), [docs/layout-scenario-tests.md](docs/layout-scenario-tests.md).

## Where to read next

- [docs/README.md](docs/README.md): index of every documentation page.
- [AGENTS.md](AGENTS.md): the hard rules for agents, each with its enforcement.
- [CONTRIBUTING_AGENT.md](CONTRIBUTING_AGENT.md): Kanbus workflow for the PPY board.
- [docs/new-publication-from-corpus.md](docs/new-publication-from-corpus.md): start a new publication from a pile of files.
- [docs/code-map.md](docs/code-map.md): where the main files live.

---

Built by [Anthus AI Solutions](https://anth.us). We run this class of system in production.

If you need this operated, not just cloned, [talk to us](https://anth.us).
