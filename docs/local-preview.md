# Local preview

Review newsroom UI changes, the Board included, without deploying.

```bash
npm run dev:preview
```

Open <http://127.0.0.1:3002/newsroom/work>. The preview runs the real Next.js app with seeded sample records (one or two content items in every stage, plus references and assignments) and a signed-in editor. It needs no AWS credentials and no Cognito sign-in. Set `PAPYRUS_PREVIEW_PORT` or `PAPYRUS_PREVIEW_HOSTNAME` to change the address.

How it works:

- `NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW=1` (set by the script) turns on `lib/local-preview.ts`. Without it nothing changes.
- `NewsroomClientShell` hands the provider the demo dashboard, so the access gate sees a ready, signed-in session.
- The three Board loaders in `components/news-desk-taxonomy-client.ts` return the records from `lib/local-preview-seed.ts` instead of calling GraphQL.
- `/newsroom/work` (the Board) exists on every brand. Set `NEXT_PUBLIC_PAPYRUS_SITE_BRAND` to preview a specific publication's chrome and stages.
- The script swaps `amplify_outputs.json` for the demo stub while it runs and restores your real file on exit.

The seed uses the same record shapes the Board reads from GraphQL, so Board code changes show up without touching the seed.

## Screenshots, headless

With the preview running (any shell, including a cloud thread):

```bash
npm run preview:screenshots -- /newsroom/work /newsroom
```

This writes desktop, desktop dark and mobile PNGs per route into `preview-screenshots/` (override with `PAPYRUS_PREVIEW_SCREENSHOT_DIR`; point at another server with `PAPYRUS_PREVIEW_URL`). In a cloud thread, write them under `/mnt/project-files/previews/<topic>/` and attach them to the reply so the change can be reviewed before it deploys. It uses the pre-installed Chromium at `/opt/pw-browsers/chromium` when present; do not run `playwright install`.

## Real backend, read-only

`npm run dev:production` serves the app against a real site's backend using that site's `amplify_outputs.json`, and needs a Cognito sign-in. It is for checking real data, not for routine UI review; use the seeded preview for that.
