# How Papyrus works

The taxonomy and ontology model, the solver and renderer split, the content boundary, and cloud credentials. Moved out of the README; [../AGENTS.md](../AGENTS.md) holds the hard rules.

## A Taxonomy-Aware, Ontology-Aware CMS

Papyrus is a CMS, but it manages the newsroom around the articles, not just the
articles themselves: references, knowledge artifacts, canonical topics,
ontology, assignments, drafts, published items, editions, and editorial
decisions.

The taxonomy layer decides what the publication covers. Newspaper sections are
a separate editorial configuration that defines the role a piece serves in the
issue (for example News vs History vs Methods). Papyrus stores an accepted, versioned category tree
as `CategorySet` + strict parent/child `Category` rows. Editors can accept,
reject, rename, move, split, merge, or ignore proposed topic changes; accepted
changes shape the publication, and rejected proposals become steering memory
for future cycles.

The ontology layer stores meaning, not just association. `Reference` records
hold strict external identifiers and provenance. `SemanticNode` records model
typed entities and concepts. `SemanticRelation` records preserve explicit,
versioned subject/object relationships, while seeded `SemanticRelationType`
records define official relationship keys, domains, inverse labels, and
context-pack tags. `SemanticRelation.predicate` remains a compatibility field;
new relation writers also denormalize `relationTypeId`, `relationTypeKey`, and
`relationDomain`. Together they let Papyrus track what a
thing is, what it refers to, how it relates to other things, and why it matters
to the publication.

Papyrus cultivates that model with human review plus aggregate, unsupervised,
and semi-supervised proposal cycles. Automated analysis can find patterns in
the knowledge base, propose topics, suggest ontology relationships, cluster
references, or identify weak sections. Editors can guide heavily, lightly, or
not at all for a while; the CMS keeps the accepted model stable and carries
rejected ideas forward as constraints.

That makes agent context richer than vector search alone. Instead of retrieving
only nearby text, research, editor, and reporter agents can receive context
packs with accepted taxonomy, steering decisions, citations and references,
related publication items, semantic neighbors, open assignments, and the
relationship paths that explain why something matters. The same model can power
reader-facing structure: coherent sections, source-grounded context,
related-article links, and navigation around emerging ideas.

The output is a real newspaper-style reader experience: a Next.js/React site
powered by [`@chenglou/pretext`](https://github.com/chenglou/pretext), with
planned front page teasers, exact continuation handoff, shared continuation
pages, and solver-owned editorial furniture such as images and pull quotes.
Pretext is the text-fit oracle. Papyrus owns the edition layout plan,
responsive grids, page regions, block geometry, scoring, continuation labels,
and React rendering.

## Newspaper layout, not web layout

Normal web layouts usually let text flow in a single article view. Newspapers do
something more complex:

- put several article starts on one front page;
- stop each article at a precise cutpoint;
- continue articles elsewhere without duplicating or skipping words;
- combine more than one article tail on a shared page;
- use photos, optional pull quotes, rules, and page furniture to balance short or long
  copy;
- keep the whole layout responsive.

Papyrus treats this as a deterministic layout-solving problem. It uses a
validated composable layout language rather than a fully open-ended optimizer:
an edition has pages, pages have regions, regions have blocks, and blocks can
own local grids and furniture. The solver turns those editorial instructions
into concrete geometry, then asks Pretext to measure exactly which lines fit
inside each solved block.

## Solver vs. Renderer

In a normal browser-first layout, React renders article markup and CSS gives the
browser constraints such as columns, width, floats, and line height. The browser
then decides the actual line breaks and element positions during layout. That is
great for ordinary article pages, but it makes newspaper continuations hard:
the app does not naturally know which exact word was last visible on page 1, or
where page 3 should resume.

Papyrus flips that responsibility. The solver runs before the newspaper page is
drawn. It takes articles, page width, viewport context, edition recipes, planned
continuation pages, and optional furniture candidates. It asks Pretext to fit
text into explicit boxes and around explicit obstacles. The solver then returns
the finished layout: page heights, story boxes, measured text lines, image and
pull-quote rectangles, continuation labels, and exact text cursors.

The renderer is deliberately simpler. `components/newspaper.tsx` and CSS draw
the solved result. They should not decide how many lines fit, where an article
continues, whether a pull quote fits, or how tall a page should be. If an object
changes the available copy area, it belongs in the solver first so Pretext can
measure text around it.

## Layout System Guide

The durable rules for the current design system are documented in
`docs/layout-system.md`. Read that guide before changing vertical rhythm,
masthead chrome, responsive front-page recipes, article-frame composition,
continuation height policy, furniture sufficiency, captions, the front footer,
or the archive grid.

## How It Works

Fixture articles still live in `lib/articles.ts`. They are the stable base for
tests and reproducible layout scenarios. Edge-case BDD fixture variants live in
`lib/layout-scenarios.ts`.

The app does not read any store directly from UI components. Content flows
through a `ContentRepository` boundary, which returns normalized
`EditionContent`: edition metadata, generic publication items, and a required
layout plan. The default content source is Amplify GraphQL in every environment.
URLs with `?scenario=<id>` load named fixture scenarios for BDD/debug only.

The GraphQL repository maps Amplify Data records into the same
`PublicationItem`, `ArticleImageAsset`, and `EditionContent` shape before
layout starts. Storage media is stored as S3 paths on `MediaAsset` records,
then resolved into signed display URLs at request time.

`buildNewspaperLayout` in `lib/newspaper-layout.ts` builds the active edition
from normalized publication items, the edition layout plan, the current page
width, and viewport height. It creates article flows, solves each page region,
solves each block, and returns generic solved pages for React to render.

Each article flow keeps a cursor into prepared Pretext text. When a block lays
out text, it consumes from the current cursor and returns a new cursor. That
range is recorded as a `PlacedTextRange`, which is the source of truth for
continuations.

The front page is now just a composable page using the `front.mosaic` preset
with `articleFrame` blocks. Those blocks still use solver-owned story boxes:
the solver measures each story's label, headline, deck, byline, body slot, and
continuation jump area so stories in the same row share the same rendered
height.

Continuation pages are planned before layout starts. The plan lives on the
Amplify `Edition.layoutPlan` record. It names page presets, regions,
blocks, local grid preferences, cut policies, jump targets, media placement
rules, pull-quote options, and content requirements. Page labels such as
`SEE READING ON A3` come from that plan, not from whatever page happens to be
generated next. Continuation headings use the article's `shortSlug` when it
exists, as in `READING FROM A1`; without one they fall back to `FROM A1`.

Article blocks try a bounded set of responsive local-grid and furniture
variants. The solver can inset aspect-preserving images into one or more
columns, place or omit optional pull quotes, change text column heights, and
then use Pretext to fit the remaining copy around the resulting obstacles. The
best valid variant is chosen deterministically. The stored plan controls
placement intent and constraints; TypeScript remains the source of truth for
how those constraints are solved.

`components/newspaper.tsx` renders the solved layout. It does not decide where
text cuts, how tall pages are, or which image variant wins. It receives placed
pages, blocks, lines, images, and CSS variables from the layout engine.

## Cloud Content

Papyrus includes an Amplify Gen2 backend in `amplify/`. The backend is defined
in TypeScript:

- Auth creates an `editor` group for seed/editor writes.
- Data exposes a general CMS model centered on `Item`, plus `Tag`,
  `MediaAsset`, `Edition`, and `EditionItem`.
- Storage keeps media in a private S3 bucket with guest read through Amplify
  Storage APIs and editor write/delete on `media/*`. The same Amplify bucket
  also owns private `corpora/*` prefixes for Biblicus corpus working data.

The first cloud media strategy uses signed Storage URLs, not raw public S3
object URLs. `MediaAsset.storagePath` is stable data. `GraphQLContentRepository`
calls Amplify Storage `getUrl` and injects temporary URLs into normalized
article image assets. Because signed URLs expire, GraphQL-backed pages render
dynamically.

The Data API is multi-auth. Public site reads use the API key from Amplify
outputs. Cognito user-pool auth remains available for future app/editor
surfaces. CLI authoring uses IAM: requests are signed with SigV4 from the
standard AWS credential chain (an SSO or role profile that assumes the site's
`<siteId>-papyrus-authoring` role, an OIDC role, or an Amplify build role).
There is no token or shared secret to deploy or rotate.

Cloud content is seeded from fixture content in `lib/articles.ts` and
`lib/layout-plan.ts`. The seed uploads article images to Storage and creates the
related CMS records. It does not create a CMS UI.

## Credentials

Use an AWS profile for AWS access. That is the right credential mechanism for
Amplify sandbox, deployment, and seeding from a local machine.

Papyrus already follows that split:

- AWS credentials come from the normal AWS SDK/CLI chain, usually
  `AWS_PROFILE` plus your local `~/.aws` config.
- App-level settings belong in `.env`.
- The seed script can still use Cognito editor credentials when seeding through
  Amplify Auth.
- The content CLI signs authoring requests with SigV4 from the AWS credential
  chain (`AWS_PROFILE`). It does not log into a Papyrus user pool and stores no
  token.

Papyrus has three distinct GraphQL auth lanes:

- the site reads GraphQL content with API-key auth;
- Cognito user-pool auth remains available for app/editor surfaces;
- the authoring CLI writes content with IAM (SigV4) credentials for the
  authoring role.
