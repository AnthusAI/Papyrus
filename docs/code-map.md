# Code map

Where the main files live. The boundaries between them are rules in [../AGENTS.md](../AGENTS.md).

- `docs/layout-system.md` explains the current layout-system invariants:
  vertical rhythm, mastheads, responsive front recipes, article composition,
  continuations, height policy, furniture, captions, footer, and archive.
- `lib/articles.ts` contains fixture article data, image asset metadata, and
  helpers for article text and image assets.
- `lib/content-repository.ts` loads GraphQL content by default and supports
  `?scenario=<id>` overrides for BDD/debug fixtures.
- `lib/graphql-content-repository.ts` loads Amplify Data records, resolves
  Storage paths to signed URLs, and normalizes cloud content into
  `PublicationItem` objects.
- `amplify/` defines the Gen2 Auth, Data, Storage, and seed resources for the
  cloud content backend.
- `papyrus` is the IAM-signed (SigV4) content authoring CLI for
  GraphQL inspect/list/diff/sync workflows.
- `lib/content-types.ts` defines `EditionContent` and `ContentRepository`.
- `lib/publication-items.ts` defines generic publication items and article
  adapters used by the solver and direct article routes.
- `lib/layout-scenarios.ts` contains reproducible layout scenario fixture sets
  used by the app and BDD tests.
- `lib/layout-plan.ts` defines and validates the Zod-backed composable layout
  language: pages, regions, blocks, responsive spans, media placement, pull
  quote placement, and content requirements.
- `lib/newspaper-layout.ts` owns the Pretext layout engine, responsive page
  grids, region/block solving, placed text ranges, adaptive furniture, and
  solved page heights.
- `components/newspaper.tsx` renders the solved newspaper scroll edition,
  measured text lines, continuation photos, and direct article links.
- `features/` contains executable Gherkin scenarios and Playwright-backed step
  definitions for layout behavior.
- `app/articles/[slug]/page.tsx` renders full direct article pages.
- `app/globals.css` contains the newspaper visual language and the CSS variables
  consumed from solver output.

Pretext measurement depends on browser canvas APIs, so the newspaper layout is
computed after client hydration. The server-rendered shell is intentionally
minimal.
