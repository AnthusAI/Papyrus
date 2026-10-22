# Reader steering

Readers sign in, pick a handle, upvote, mark "I used it" and rate the items of a publication. Editors and readers
steer ranking together. The `reader-steering` plugin (initiative PPY-77bb3b) builds the reader identity, the reader
API, votes and ratings; the snapshot that puts live numbers on static pages and the page components are described
in the sections that follow them.

**Production switch.** Everything here is built and tested but stays off in production until Prospectus returns a
per-site `siteSubject`. Until then every reader route answers `503 reader_identity_unavailable` and the page
components say "Reader sign-in is not open yet". There is no other flag. See [The switch-on condition](#the-switch-on-condition).

## Enabling it

Reader steering is a plugin (see [plugins.md](plugins.md)). In the site's `papyrus.config.ts`:

```ts
export default defineSite({
  // ...
  backend: {
    plugins: [
      {
        name: "reader-steering",
        computeRoleArn: "arn:aws:iam::<account>:role/<the CmsComputeRoleArn output>",
        dimensions: ["real", "useful", "notable", "novel"],
      },
    ],
  },
});
```

Enabling it is a backend deploy: three models, the `reader-actions` function and a rate-window table are added.
A site that does not list it synthesizes exactly what it did before.

| Setting | Default | Meaning |
|---|---|---|
| `computeRoleArn` | required | IAM role of the CMS app's server runtime. It is the only principal allowed to invoke `reader-actions` (a resource policy on that one function). |
| `dimensions` | `[]` | The publication's rating dimensions: lowercase names, at most 24 characters. `up` and `used-it` always exist and cannot be dimension names. |
| `limits.actionsPerHour` | 120 | Votes and ratings one reader may make in a clock hour (they share the allowance). |
| `limits.newAccountHours` | 24 | A profile younger than this gets `actionsPerHour / newAccountDivisor`. |
| `limits.newAccountDivisor` | 3 | |
| `reservedHandles` | `[]` | Handles nobody may take, on top of the built-in list. |
| `karma.upvoteWeight`, `karma.usedItWeight` | 1, 2 | See [Karma](#karma). |
| `ranking.*`, `snapshot.*` | see below | The snapshot and ranking settings. |
| `retirementPoll` | `false` | Reserved for Prospectus's retired-subject poll. `true` is refused until the route exists. |

The deployed backend publishes `custom.readerSteering.actionsFunction` (the function name the CMS routes invoke) and
`custom.papyrusPlugins["reader-steering"]` (`contract`, `dimensions`) in `amplify_outputs.json`.

## Privacy rules

- A reader's identity is `person.siteSubject`: `"ss1_"` plus 43 base64url characters, a per-site pairwise id that
  Prospectus returns. There is no global id for readers of a public-reader site.
- The accessor `readerSubject(session)` in `lib/reader-subject.ts` is the only place identity is decided. It returns the
  siteSubject the sealed session carries, or `null`. [lib/reader-subject.md](../lib/reader-subject.md) covers the
  development-only interim value.
- The global Prospectus person id is never stored by the plugin and never appears in a model, public JSON, snapshot, URL,
  HTML attribute, feed, `llms` file or log line that reaches a client.
- `ReaderProfile` is keyed on the siteSubject. Public data uses only `readerId`, a random UUID stored on the profile, and the
  reader's chosen handle, so not even the siteSubject is public.
- No model has a guest, API key or custom rule. Editors may list the three models and admins may delete; the function
  writes the tables with its own role.
- The privacy scan test renders the snapshot and the projected pages of a fixture site with votes and profiles and fails
  if any person id pattern, `ss1_` or `ssdev_` value or email address appears.

## The reader API

Next route handlers in the CMS app: `app/api/reader/*`, `Cache-Control: no-store`. Each one:

1. reads the sealed Prospectus session (`401 signed_out` without one) and asks `readerSubject` (`503 reader_identity_unavailable` when it is `null`);
2. for writes, checks that `Origin` equals `PAPYRUS_SITE_ORIGIN` (`403 origin_mismatch`; a missing Origin fails too);
3. for writes, checks the content type is `application/json` (`415`) and the body is at most 4096 bytes (`413`);
4. invokes the `reader-actions` function with `{publication, siteSubject, isStaff, action, payload}`. `isStaff` is true when the
   `cognito:groups` claim of the session's access token holds `editor` or `admin`; the browser never sends it.

| Route | Body | Answer |
|---|---|---|
| `GET /api/reader/me?subjects=a,b` (at most 50 item keys) | | `{readerId, handle \| null, karma, state, votes: {subjectKey: {up: 1, "used-it": 1, real: 4, ...}}}`. Creates the profile on first call. `401` when signed out. |
| `POST /api/reader/handle` | `{handle}` | Sets the handle once: 3 to 24 characters of `[a-z0-9_-]`, case-insensitive (stored lowercase). `409 handle_taken`, `409 handle_already_set`, `422 reserved_handle`, `422 invalid_handle`. |
| `POST /api/reader/vote` | `{subject, dimension: "up" \| "used-it", on: boolean}` | `on: true` stores the vote (idempotent), `on: false` removes it. |
| `POST /api/reader/rating` | `{subject, dimension, value: 1..5 \| null}` | A new value replaces the old one; `null` removes it. |

The subject is the lineage id of a published item. The function checks it against the `PublishedItem` table (`404
unknown_subject`). Votes and ratings answer `{subject, dimension, value}`.

Other answers: `429 rate_limited` with `retryAfter` seconds (and a `Retry-After` header); `403 reader_banned` and
`403 reader_limited` (the profile `state`); `502 reader_actions_failed`; `503 reader_actions_unavailable` when the site
did not enable the plugin; `503 site_origin_not_configured`.

Rate limits are conditional counters per `readerId` and action in a function-owned table with a TTL: votes and ratings
share `limits.actionsPerHour` (a third of it for profiles younger than `limits.newAccountHours`), handle changes get 10 an
hour. The function has reserved concurrency 10. There is no WAF.

A vote or rating asks for one debounced `reader-snapshot` run (at most one asynchronous invoke of `content-actions` per
60 seconds, a conditional write on the rate table). A vote made inside the window waits for the next vote or the scheduled run.

## Data

| Model | Key (`id`) | Fields |
|---|---|---|
| `ReaderProfile` | the siteSubject | `siteSubject`, `readerId` (UUID, public), `handle`, `state` (`active`, `limited`, `banned`), `karma` (materialised by the snapshot), `createdAt` |
| `ReaderHandle` | the lowercase handle | `readerId`. A claim written together with the profile's handle in one transaction, which is what makes a handle unique. |
| `ReaderVote` | `subjectKey#readerId#dimension` | `subjectKey`, `readerId`, `dimension`, `value` (1 for `up` and `used-it`, 1 to 5 for ratings), `voterRole` (`editor` or `reader`), `createdAt`, `updatedAt` |

A revote overwrites and keeps `createdAt`; an unvote deletes. `ModerationAction` belongs to the submission and moderation
epic; the profile `state` is where it will land.

## The switch-on condition

Reader features open per site when Prospectus returns `person.siteSubject` on the resolve and `identities/me` responses.
The sign-in callback stores it in the sealed session cookie; from then on `readerSubject` is non-null and the routes work.
Nothing else changes: no flag, no deploy. Because production writes stay closed until then, no production row is ever
keyed on a development value and no remap from `ssdev_` to `ss1_` is needed.

Prospectus's `/session` route returns the person from the accounts directory to the browser. A reader site must not
forward a global person id there; that is an open point for the Prospectus change (see the pull request notes).
