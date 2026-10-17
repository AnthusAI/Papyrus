# Verification checklist

What to run before calling a change done, and the browser smoke test for the newspaper reader.

Run these after changes:

```bash
npm run lint
npm run typecheck
npm run build
npm run test:bdd
npm run test:bdd:agent-live
```

Amplify checks when cloud content changes:

```bash
npm run sandbox
npm run seed:amplify
poetry run papyrus ops content seed-edition
npm run build
```

Only run sandbox provisioning when the user expects AWS resources to be created
or updated. It requires configured AWS credentials and may create cloud
resources.

For archive or production content changes, also verify the reader endpoint that
the public page uses:

```bash
curl -sS "$PAPYRUS_BASE_URL/api/archive/editions?limit=1"
```

Browser smoke test these viewports:

- `1280x900`
- `1280x1600`
- `640x1200`
- `390x900`

Check all of the following:

- Page 1 renders one active page.
- The active page count matches the loaded `Edition.layoutPlan.pages.length`.
- The production AI/ML corpus edition currently renders as an 8-page issue:
  Page 1 is the front mosaic, Pages 2 through 7 are planned continuation pages,
  and Page 8 is a stacked page for the ASR and ML-history stories.
- Front-page continuation labels route to the planned page numbers.
- No `.measured-line` is vertically cropped inside `.story-measure` or
  `.continuation-column`.
- Page flipping works one page at a time in both directions.
- No console errors appear during flip or resize.

If the user is running the dev server on port `3001`, use it for smoke tests but
do not stop or restart it unless asked.

`npm run test:bdd` expects a running app and defaults to `http://localhost:3001`.
Use `PAPYRUS_BASE_URL` for another server. Use `PAPYRUS_HEADLESS=false` or
`npm run test:bdd:headed` when debugging geometry visually.

Frontend BDD is site-brand aware. The running app exposes reader capabilities on
`<html>` through `data-site-brand`, `data-default-presentation`,
`data-forced-presentation`, and `data-presentation-choices`. Scenarios declare
requirements with tags such as `@newsprint`, `@blog`, `@presentation-choice`,
and `@brand-agnostic`; incompatible scenarios skip automatically on locked fork
brands instead of failing during setup.

- **Full newspaper regression:** start the app with the canonical BDD brand from
  `config/bdd-canonical.env.example` (`PAPYRUS_SITE_BRAND=papyrus`,
  `NEXT_PUBLIC_PAPYRUS_SITE_BRAND=papyrus`), then run
  `npm run test:bdd:canonical`.
- **Fork checkout CI:** run `npm run test:bdd` against the fork's normal brand.
  Newspaper-only scenarios skip; blog scenarios run when the fork forces or
  defaults to blog.
- **Preflight only:** `npm run test:bdd:check-brand` reports the active site
  profile. Set `PAPYRUS_BDD_REQUIRE_CANONICAL_BRAND=1` to fail when the server
  is not on the canonical Papyrus reader profile.

`npm run test:bdd:agent-live` runs backend live-agent BDD (Behave/Python),
not frontend browser geometry checks.
