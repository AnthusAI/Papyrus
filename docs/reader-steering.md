# Reader steering

Readers sign in, pick a handle, upvote, mark "I used it", rate the items of a publication and submit links. Editors and
readers steer ranking together. The `reader-steering` plugin (initiative PPY-77bb3b) builds the reader identity, the reader
API, votes and ratings, public link submissions (see [Submissions](#submissions)), comments as a steering signal (see [Comments](#comments)), the snapshot that puts live numbers on
static pages and the page components that show them.

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

Enabling it is a backend deploy: five models, the `reader-actions` function, a rate-window table and, when
`snapshot.schedule` is on, one EventBridge rule are added. A site that does not list it synthesizes exactly what it did before.
`computeRoleArn` is the `CmsComputeRoleArn` output of the app-shell stack. The plugin does not edit that role: it puts a
resource policy on `reader-actions` that lets exactly that role invoke exactly that function.

| Setting | Default | Meaning |
|---|---|---|
| `computeRoleArn` | required | IAM role of the CMS app's server runtime. It is the only principal allowed to invoke `reader-actions` (a resource policy on that one function). |
| `dimensions` | `[]` | The publication's rating dimensions: lowercase names, at most 24 characters. `up` and `used-it` always exist and cannot be dimension names. |
| `limits.actionsPerHour` | 120 | Votes and ratings one reader may make in a clock hour (they share the allowance). |
| `limits.newAccountHours` | 24 | A profile younger than this gets `actionsPerHour / newAccountDivisor`. |
| `limits.newAccountDivisor` | 3 | |
| `reservedHandles` | `[]` | Handles nobody may take, on top of the built-in list. |
| `karma.upvoteWeight`, `karma.usedItWeight` | 1, 2 | See [Karma](#karma). |
| `ranking.halfLifeHours` | 48 | Front: the editor composite loses half its weight every this many hours. |
| `ranking.risingWindowHours` | 6 | Rising counts upvotes made in this window. |
| `ranking.readerMinimum` | 5 | Reader ratings an item needs (on any one dimension) before the reader composite counts in Front. |
| `ranking.editorWeight` | 0.5 | Weight of the editor composite in Front once readers have rated; readers get the rest. |
| `snapshot.schedule` | `false` | Create the EventBridge rule that runs the snapshot every `snapshot.intervalHours`. |
| `snapshot.intervalHours` | 6 | 1 to 24. Four runs a day was approved for the pilot. |
| `hypeGap` | unset | `{ plus: [...], minus: [...] }`: the dimensions whose mean is added and subtracted to make the hype gap (Shipped: plus `notable`, `novel`; minus `real`, `useful`). Both lists are required, must be rated dimensions and cannot overlap. Without it no hype gap is published. |
| `snapshot.hypeMinimum` | 5 | Reader ratings every dimension in `hypeGap` needs before the reader hype gap is published. |
| `reservedConcurrency` | unset | Reserved concurrent executions for `reader-actions`. Unset reserves none. An account with a small total Lambda quota cannot reserve any: papyrus-production has 10 in total, and Lambda requires 10 left unreserved. |
| `submissions.perDay` | 10 | Submissions one reader may make in a UTC day. A profile younger than `limits.newAccountHours` gets `perDay / limits.newAccountDivisor` (3 by default). |
| `submissions.similarHours` | 48 | Another submission from the same domain inside this window is returned as a `similar` warning. |
| `submissions.kinds` | `["link"]` | The kinds a reader may pick on the form (lowercase names). One kind hides the radio. |
| `comments.perHour` | 30 | Comments, replies and edits one reader may make in a clock hour (a third of it for a profile younger than `limits.newAccountHours`). |
| `comments.editWindowMinutes` | 10 | The author may edit a comment this long after posting it. `0` turns editing off. |
| `comments.maximumLength` | 2000 | Characters in a comment. |
| `comments.maximumLinks` | 3 | Links (`http://`, `https://` or `www.`) in a comment. |
| `retirementPoll` | `false` | Poll Prospectus for retired reader subjects in each scheduled run. Needs `snapshot.schedule: true`, and `cms.readerRetirementPoll: true` in the site's app-shell `site.json` (see [the retirement poll](#the-prospectus-retirement-poll)). |

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
- Public text (a submission's title and note, its URL) cannot contain an email address: the function answers `422` and the
  reader is asked to remove it. A reader's text is shown only with their handle and `readerId`.
- No model has a guest, API key or custom rule. Editors may list the five models and admins may delete; the function
  writes the tables with its own role.
- The privacy scan test renders the snapshot and the projected pages of a fixture site with votes and profiles and fails
  if any person id pattern, `ss1_` or `ssdev_` value or email address appears.

## The reader API

Next route handlers in the CMS app: `app/api/reader/*`, `Cache-Control: no-store`. Each one:

1. reads the sealed Prospectus session (`401 signed_out` without one) and asks `readerSubject` (`503 reader_identity_unavailable` when it is `null`);
2. for writes, checks that `Origin` equals `PAPYRUS_SITE_ORIGIN` (`403 origin_mismatch`; a missing Origin fails too);
3. for writes, checks the content type is `application/json` (`415`) and the body is at most 4096 bytes (`413`; 8192 for a submission, 12288 for a comment or an edit);
4. invokes the `reader-actions` function with `{publication, siteSubject, isStaff, action, payload}`. `isStaff` is true when the
   `cognito:groups` claim of the session's access token holds `editor` or `admin`; the browser never sends it.

| Route | Body | Answer |
|---|---|---|
| `GET /api/reader/me?subjects=a,b` (at most 50 item keys) | | `{readerId, handle \| null, karma, state, votes: {subjectKey: {up: 1, "used-it": 1, real: 4, ...}}}`. Creates the profile on first call. `401` when signed out. |
| `POST /api/reader/handle` | `{handle}` | Sets the handle once: 3 to 24 characters of `[a-z0-9_-]`, case-insensitive (stored lowercase). `409 handle_taken`, `409 handle_already_set`, `422 reserved_handle`, `422 invalid_handle`. |
| `POST /api/reader/vote` | `{subject, dimension: "up" \| "used-it", on: boolean}` | `on: true` stores the vote (idempotent), `on: false` removes it. |
| `POST /api/reader/rating` | `{subject, dimension, value: 1..5 \| null}` | A new value replaces the old one; `null` removes it. |
| `POST /api/reader/comment` | `{subject, body, parent?, ratingContext?}` | `201 {id, subject, parent, body, createdAt, ratingContext}`. See [Comments](#comments). |
| `POST /api/reader/comment/edit` | `{id, body}` | `200 {id, body, editedAt}`; `403 edit_window_closed`; `404` for a comment that is not the caller's. |
| `POST /api/reader/comment/delete` | `{id}` | `200 {id, state: "deleted"}`; idempotent. |
| `POST /api/reader/submit` | `{url, title, kind?, note?}` | `201 {subject, url, title, kind, state: "pending", extraction: "pending", similar: [{subject, url, title}]}`. `409 duplicate_submission` with `existing: {subject, url, title, state}`. See [Submissions](#submissions). |

The subject is the lineage id of a published item, or the id of a visible submission (`sub-` plus 24 hex characters). The
function checks it against the `PublishedItem` table or the `ReaderSubmission` table (`404 unknown_subject`; a hidden
submission is unknown). Votes and ratings answer `{subject, dimension, value}`.

Other answers: `429 rate_limited` with `retryAfter` seconds (and a `Retry-After` header); `403 reader_banned` and
`403 reader_limited` (the profile `state`); `502 reader_actions_failed`; `503 reader_actions_unavailable` when the site
did not enable the plugin; `503 site_origin_not_configured`.

Rate limits are conditional counters per `readerId` and action in a function-owned table with a TTL: votes and ratings
share `limits.actionsPerHour` (a third of it for profiles younger than `limits.newAccountHours`), handle changes get 10 an
hour. There is no WAF. The function reserves no concurrency unless the site sets `reservedConcurrency` (see the settings table).

A vote or rating asks for one debounced `reader-snapshot` run, trailing edge: the first write in a 60 second window (a
conditional write of a marker on the rate table) creates a one-off EventBridge Scheduler schedule that fires at the end
of the window and invokes `content-actions` with the snapshot task. Further writes inside the window schedule nothing,
because the run at the end of the window reads them all; the first write after the window opens the next one. A vote is
therefore on the page about a minute later, not on the next vote.

Why Scheduler and not an SQS delay queue: a queue would add a queue, an event source mapping and a handler branch in
`content-actions` for SQS records, and a delay queue also caps at 15 minutes and has no per-window name to deduplicate on.
Scheduler needs one role, no queue and no handler change: the target input is the same JSON the scheduled rule sends. The schedule is named
`papyrus-reader-snapshot-<window end>`, uses `ActionAfterCompletion: DELETE` (no leftovers) and no retries. If creating the
schedule fails, the vote still succeeds and the window is reopened so the next write tries again. The plugin creates the
role (assumed by `scheduler.amazonaws.com`, allowed to invoke `content-actions` only), and gives `reader-actions` only
`scheduler:CreateSchedule` on `schedule/default/papyrus-reader-snapshot-*` and `iam:PassRole` on that one role.

## Data

| Model | Key (`id`) | Fields |
|---|---|---|
| `ReaderProfile` | the siteSubject | `siteSubject`, `readerId` (UUID, public), `handle`, `state` (`active`, `limited`, `banned`), `karma` (materialised by the snapshot), `createdAt` |
| `ReaderHandle` | the lowercase handle | `readerId`. A claim written together with the profile's handle in one transaction, which is what makes a handle unique. |
| `ReaderSubmission` | `sub-` + the first 24 hex characters of the SHA-256 of the canonical URL | `canonicalUrl`, `domain`, `title`, `kind`, `note`, `readerId`, `state` (`pending`, `promoted`, `hidden`), `similar` (submission ids), `signals` (JSON string), `extractionState`, `itemId`, `reviewedAt`, `createdAt`. A secondary index `submissionsByDomain` (`domain`, `createdAt`) finds recent items from one site. |
| `ReaderComment` | `cmt-` + 32 hex characters | `subjectKey`, `readerId`, `body` (empty once deleted), `parentId`, `ratingContext` (JSON string `{dimension, value}`), `state` (`visible`, `hidden`, `deleted`), `signals`, `reviewedAt`, `editedAt`, `deletedAt`, `createdAt` |
| `ReaderVote` | `subjectKey#readerId#dimension` | `subjectKey`, `readerId`, `dimension`, `value` (1 for `up` and `used-it`, 1 to 5 for ratings), `voterRole` (`editor` or `reader`), `createdAt`, `updatedAt` |

A revote overwrites and keeps `createdAt`; an unvote deletes. `ModerationAction` belongs to the moderation work; the profile `state`
is where it lands.

## The snapshot

`reader-snapshot` is a projection task of the `content-actions` function. It reads every vote and profile with the
function's own role, the publication time of each voted item through the authoring client, and writes four files, and one file for each item or submission that has comments, into
the site bucket under the projection's URL policy (so `urls.basePath: "posts"` gives `posts/_data/reader/items.json`).
The page-reconcile step knows these files belong to the task and never reports them as orphans. It then purges exactly the four
paths on the edge distribution when the backend knows one (`PAPYRUS_EDGE_DISTRIBUTION_ID`; never a wildcard) and
materialises karma on the profiles.

Every file has a top-level `generatedAt` (UTC, seconds). Means are rounded to four decimals.

`_data/reader/items.json`:

```json
{
  "generatedAt": "2026-10-21T10:00:00Z",
  "items": {
    "<subjectKey>": {
      "up": 5, "usedIt": 2,
      "ratings": {
        "real": {
          "reader": { "mean": 4.2, "n": 5, "hist": [0, 0, 1, 2, 2] },
          "editor": { "mean": 4.0, "n": 1, "hist": [0, 0, 0, 1, 0] }
        }
      },
      "editor": 4.0, "reader": 4.2, "hypeGap": { "reader": -1.0, "editor": 2.5 }
    }
  }
}
```

`hist[i]` counts the ratings of `i + 1`. `editor` and `reader` are the composites: the mean of the dimension means that exist.
`hypeGap` is `null` when the site sets no `hypeGap` groups. Otherwise it is `{reader, editor}`, each `mean(plus
dimensions) - mean(minus dimensions)` over the dimension means of that group of voters (a negative gap is possible).
The reader gap is `null` unless every dimension in either group has at least `snapshot.hypeMinimum` reader ratings; the
editor gap is `null` unless an editor rated every dimension in either group. The two gaps are computed separately, so
the editor gap shows as soon as an editor has rated, before readers have.

`_data/reader/board.json`:

```json
{
  "generatedAt": "2026-10-21T10:00:00Z",
  "parameters": { "halfLifeHours": 48, "risingWindowHours": 6, "readerMinimum": 5, "editorWeight": 0.5 },
  "front": [ { "subject": "<subjectKey>", "score": 3.5, "editor": 4.0, "reader": null, "readerN": 0, "ageHours": 12.0 } ],
  "rising": [ { "subject": "<subjectKey>", "upvotes": 3 } ]
}
```

Front is the editor composite times time decay (`0.5 ^ (ageHours / halfLifeHours)`) until an item has `ranking.readerMinimum`
reader ratings on some dimension; after that it is `editor * editorWeight + reader * (1 - editorWeight)`, times decay. An
item with neither is not ranked. Rising is the upvotes in the last `risingWindowHours`, most first. Ties break on the
subject key. The formula is one module of pure functions, `src/papyrus_content/reader_steering/ranking.py`, and the raw
components sit beside each score because how editor and reader scores combine is an open exploration (PPY-0b2cbb).

`_data/reader/readers.json`:

```json
{ "generatedAt": "2026-10-21T10:00:00Z", "readers": [ { "readerId": "<uuid>", "handle": "quiet-fox", "karma": 4 } ] }
```

The top 50 readers by karma who have a handle and a karma above zero.

Only items that are still published appear. The files are cached like pages (`s-maxage`), so without an edge distribution
a number can lag by the cache lifetime.

`_data/reader/submissions.json` lists the newest 200 visible submissions (see [Submissions](#submissions)).
`_data/reader/comments/<subject>.json` holds the visible comments of one subject (see [Comments](#comments)), and `items.json`
carries a `comments` count for every subject (zero when there are none; a subject with comments and no votes still gets an entry).

### Karma

`karma = upvotes received by the reader's submissions from others × karma.upvoteWeight + used-it reports on items the reader
submitted × karma.usedItWeight` (defaults 1 and 2; a reader's own votes on their own submissions do not count). A
submission earns its submitter karma from votes on the submission (while it is pending) and on the draft item it became once
an editor promoted it and published it (the submission's `itemId`); the same reader voting on both counts both. Votes on a
hidden submission earn nothing. A site with no submissions has karma 0 for everyone. The materialised value on
`ReaderProfile.karma` is what `/api/reader/me` returns.

### Schedule

With `snapshot.schedule: true` the plugin creates an EventBridge rule that invokes `content-actions` with
`{"projectionTask": {"task": "reader-snapshot"}}` every `snapshot.intervalHours` (time decay and Rising change without any
vote). Off by default; the site turns it on.

### The Prospectus retirement poll

When Prospectus deletes or merges a person, each public-reader site they used gets retirement records at
`GET /v1/accounts/site-subjects/retired?since=<cursor>`, answered as `{retired: [{siteSubject, reason: "deleted" | "merged",
survivingSiteSubject?, retiredAt}], cursor, more}`. With `retirementPoll: true` the scheduled run (not the debounced runs
that follow votes) applies them before it builds the numbers:

- `deleted`: the profile, the handle claim and every vote and rating of that reader are deleted. The handle is free again.
- `merged`: everything moves to `survivingSiteSubject`. If the survivor has no profile, the profile row is re-keyed and keeps its
  `readerId`, handle and votes. If the survivor has one, the retired reader's votes are re-keyed onto the survivor's `readerId`;
  where both have a row for the same item and dimension, the newer one (by `updatedAt`) is kept. The survivor keeps its own
  handle (or adopts the retired one if it has none), takes the stricter `state`, and karma is recomputed by the same run.
- Each record is "ensure dropped" or "ensure re-keyed", so a repeat, a chain of merges in one page and a retry after a failure
  part way are all safe. The profile row is removed last, so a retry still finds it.
- The cursor is stored on a `retirement-cursor` row in the `reader-actions` rate table (no TTL) after each applied page, the run
  follows `more` (at most 50 pages), and a failure leaves the cursor at the last applied page. A failing poll is reported
  (`retirementPoll.error` in the run's answer) and never stops the numbers.

**IAM design.** Prospectus admits exactly one caller per site, the app's compute role (the `roleArn` of the site's registration),
and decides which site is asking from that role. A dedicated role for the scheduled Lambda would be a different principal,
and Prospectus refuses a role that is shared with any other registration or that is not registered, so option (a) of "a
dedicated role with the same `execute-api` grant" cannot work without a second registration that would see different
subjects. Widening the compute role's trust policy so `content-actions` can assume it would need the app-shell, which is
deployed before the backend, to know the backend's role. So the poll goes through the compute role, which already holds
`execute-api:Invoke` on `GET/v1/accounts/*`:

1. The app-shell stack, when `site.json` has `cms.readerRetirementPoll: true` (it requires `prospectusAccountsApiStageArn`),
   generates the SSM SecureString `/papyrus/<siteId>/reader-poll-secret`, lets the compute role read that one parameter and
   passes its name as `PAPYRUS_READER_POLL_SECRET_PARAMETER`.
2. The CMS route `GET /api/reader/retired?since=` (`lib/reader-retirement-route.ts`) answers only a caller that sends the secret
   in `x-papyrus-reader-poll-secret` (401 otherwise, 503 when the parameter is not set), validates `since`, calls Prospectus
   as the compute role and passes the page through with `no-store`. The SigV4 transport signs the query string.
3. The plugin, with `retirementPoll: true`, gives `content-actions` the site origin (`PAPYRUS_SITE_ORIGIN`), the parameter
   name, `ssm:GetParameter` on that one parameter, read and write on the vote, handle and rate tables, and makes the EventBridge
   rule send `{"projectionTask": {"task": "reader-snapshot", "retirementPoll": true}}`. Without the poll none of these grants exist.

Nothing new is open to the internet: the route is useless without the secret, and the secret is readable only by the compute
role and `content-actions`.

## Submissions

A signed-in reader with a handle submits a link: `POST /api/reader/submit {url, title, kind?, note?}`. Submissions are public
immediately; moderation (when a site turns it on) acts after the fact.

**Storage choice.** A plugin model, `ReaderSubmission`, not a `Reference`. The Reference intake
(`intakePendingReferences`, `canonical_source_url` in `reference_intake.py`) is an editor-session AppSync action: it
validates a Cognito editor identity, records `user:<sub>` as the actor and writes import runs and S3 provenance
attachments. A reader has none of that, and a Reference carries no field for reader provenance. A submission therefore
lives in its own table, keyed by the canonical URL, with the reader's `readerId` as provenance. The plugin
function canonicalises with a verbatim copy of `canonical_source_url` (the function ships alone, without the package); a test
pins the two to the same answers. A later extraction step (below) is where a submission meets References and entities.

**The request.** Validation, then the rate limit, then the duplicate check:

- `url` is canonicalised (scheme and host lowercased, default port and fragment dropped, path, query and order kept; `http` and
  `https` only, no credentials, at most 2048 characters, no email address in it). `title` is 1 to 200 characters with spaces
  collapsed; `note` is optional, at most 500; neither contains control characters or an email address. `kind` is one of
  `submissions.kinds`. Unknown fields are refused (`422`). The reader needs a handle (`422 handle_required`); a `limited` or
  `banned` reader gets `403`.
- Rate limit: `submissions.perDay` per UTC day, a third of it for a new account (`429` with `retryAfter`). A duplicate counts;
  a malformed request does not.
- Duplicate: an exact canonical URL returns `409 duplicate_submission` with the existing subject (the item's key once promoted).
  A hidden submission answers `409` with no details. Other visible submissions from the same domain in the last
  `submissions.similarHours` come back as `similar` (at most five, newest first), a warning only; the ids are stored.
- The row is created with `state: "pending"` and `extractionState: "pending"`, and a snapshot run is scheduled (the debounce above).

**Signals, in the worker.** The `reader-snapshot` run reviews every submission that has no `reviewedAt` before it builds the files
(at most 50 a run; a failure is reported as `review.error` and never stops the numbers). It stores `signals` as a JSON string
of `{source, policy, detector, severity, excerpt}` built from Humanus rule checks, with no model call: the built-in
`ai-writing-tells` pack and a small `reader-spam` pack (promotion, shouting), both on title and note, plus a URL shortener check
(`reader_steering/signals.py`). Signals are advice for moderators; they never hide anything. Nothing runs in the request.

**Extraction hook.** Entity extraction is not LLM based and runs later in the worker. For now the submit path stores the link and
the reader's text only, and `extractionState` stays `pending`; the worker step that fills it in (owned by the knowledge-base
work) reads `pending` rows and leaves `pending` alone until it succeeds. Nothing in the request waits for it.

**Public file.** `_data/reader/submissions.json`:

```json
{
  "generatedAt": "2026-10-22T10:00:00Z",
  "submissions": [
    { "id": "sub-0123456789abcdef01234567", "url": "https://example.com/post", "domain": "example.com", "title": "A small tool",
      "kind": "link", "note": "Worked well", "readerId": "<uuid>", "handle": "quiet-fox", "createdAt": "2026-10-22T09:00:00.000Z",
      "state": "pending", "similar": ["sub-..."], "itemId": "<only once promoted>" }
  ]
}
```

Newest first, at most 200, `pending` and `promoted` only: a hidden submission is never listed and its votes are not counted.
`note` and `itemId` appear only when present. Signals, the extraction state, the siteSubject and any email never appear. Votes
on a submission use the existing vote route with `subject` set to its id, and appear in `items.json` under that id.

A deleted reader's submissions are deleted by the retirement poll and a merged reader's move to the surviving profile.

## Comments

Signed-in readers with a handle comment on published items and on visible submissions: `POST /api/reader/comment`.

**Storage choice.** A plugin model, `ReaderComment`, not a `Message` with `messageKind: reader_comment`. The `Message` model
is the newsroom's append-only inbox: editors can create and read but not update, and its rows are realtime-subscribed
and indexed for the newsroom feed. Comments need edits (the author's ten minutes), deletes that leave a stub and a state that
moderation changes, and reader text should not flood the editors' feed. The snapshot already is the only public read path, so a
staff-only table loses nothing.

**Rules.** Plain text, at most `comments.maximumLength` characters (counted as characters, not bytes), at most
`comments.maximumLinks` links, no control characters other than newlines and tabs, and no email address (`422`). Text is stored
as typed and shown by the island as text, so markup never runs; links are not made clickable. A reader needs a handle and must
not be `limited` or `banned`. The subject must be a published item or a visible submission (`404 unknown_subject`).
`comments.perHour` comments, replies and edits an hour, a third of that for a new account (`429`).

**Threads.** One level: `parent` must be a visible top-level comment on the same subject (`422 invalid_parent` otherwise, which
includes a reply to a reply, to a deleted comment and to another item's comment).

**Edit and delete.** The author edits for `comments.editWindowMinutes` (`403 edit_window_closed` after); an edit asks for a new
review of the text. A delete by the author clears the text and keeps the row as a stub (`state: "deleted"`). Someone else's
comment, or a comment moderation has hidden, looks missing (`404`).

**Rationale at rating time.** `ratingContext` is `{dimension, value}` and must equal the caller's own current vote on that
subject and dimension (`up` or `used-it` with value 1, or a rating dimension with 1 to 5); otherwise `422
rating_context_mismatch`, so a comment cannot claim a rating nobody gave. A reply carries none. The `Rating` island shows "Why?
(optional, public)" under a dimension right after the reader rates it and posts the answer as a comment with that context. The
context is never in the public file, because that would pair a reader with their rating.

**Public files.** `_data/reader/comments/<subject>.json` (only subjects that are safe as a file name):

```json
{
  "generatedAt": "2026-10-22T10:00:00Z",
  "subject": "item-one",
  "comments": [
    { "id": "cmt-...", "readerId": "<uuid>", "handle": "quiet-fox", "body": "Worth reading.", "createdAt": "2026-10-22T09:00:00.000Z", "parent": null, "edited": false },
    { "id": "cmt-...", "stub": true, "parent": null, "createdAt": "2026-10-22T09:05:00.000Z" }
  ]
}
```

Oldest first. Only visible comments appear, plus a stub (no author, no text) for a deleted or hidden top-level comment that
still has visible replies, so the thread stays readable. A comment that is hidden or deleted and has no replies leaves no trace.
A file is rewritten and purged on the edge only when its content changes (the freshness stamp alone is not a change), and when a
subject has no comments left its file is emptied, not deleted, so a page that asks for it still gets valid JSON.

**Signals.** The `reader-snapshot` run adds Humanus rule signals to new and edited comments, like submissions (stored as a JSON
string; advice for moderators, never an automatic hide).

### Steering: the feedback export

Comment text is a steering signal. Cyclotron has no generic reader-feedback input (its inputs are the relevance sweeps and the
priming examples, see [cyclotron-priming.md](cyclotron-priming.md)), so reader comments leave through an export that the loop pulls
when it is ready; nothing in a reader request calls Cyclotron.

```bash
papyrus reader feedback export --since 2026-10-22T00:00:00Z --out reader-feedback.jsonl
```

It needs an editor session (`papyrus login`) or the authoring role, since the model is staff-only. One JSON object per line, for
every comment whose `updatedAt` is after `--since` (all of them without it), oldest update first:

```json
{"schema":"papyrus.reader-feedback/v1","source":"reader","status":"active","commentId":"cmt-...","readerId":"<uuid>","subject":"item-one","subjectKind":"item","parentId":null,"rating":{"dimension":"real","value":4},"rationale":"The benchmarks held up.","createdAt":"...","updatedAt":"..."}
```

`rating` is `null` for a comment that explains no vote. `subjectKind` is `submission` for a submission id. A comment that was hidden
or deleted comes out as `"status": "retracted"` with no `rationale` or `rating`, so a consumer that ingested the earlier line can
drop it. Attribution is the public `readerId` only, and `source: "reader"` keeps these records apart from editor signals, which come from
editor votes and the curation reviews. The consumer keeps the greatest `updatedAt` it has seen as the next `--since`.

## The page components

Static assets shipped to the site bucket when the plugin is enabled: `_plugins/papyrus-reader@1.js` and
`_plugins/papyrus-reader@1.css`. Vanilla JavaScript, no framework. Add both to the site's pages (the page chrome or the islands
bundle) and place mount points where the site owns the HTML; they follow the islands contract (`data-island` plus
`data-props`, see [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md#islands)):

| Island | Props | Shows |
|---|---|---|
| `ReaderSignIn` | none | Header control. Signed out: a "Sign in" link to `/api/auth/prospectus/sign-in?returnTo=<path>`. Signed in with no handle: a handle picker. Otherwise: the handle, karma and a "Sign out" button. |
| `Vote` | `subject`, `up` | Upvote toggle with a count. |
| `UsedIt` | `subject`, `usedIt` | "I used it" toggle with a count. |
| `Rating` | `subject`, `dimensions`, optional `ratings` | One to five per dimension, the reader's own value (optimistic), the reader and editor numbers. Selecting the current value clears it. After a rating it asks "Why? (optional, public)" and posts the answer as a comment that carries the rating. |
| `Freshness` | optional `generatedAt` | "Updated N min ago". |
| `Comments` | `subject`, optional `count`, `editMinutes`, `maximumLength` | The comments of one item or submission: a threaded list (handles and text only, a stub reads "This comment was removed."), a form and, for top-level comments, Reply. The author's own comments show Edit (inside the edit window) and Delete. Fetches `<base>_data/reader/comments/<subject>.json`, refetches it every 60 seconds while visible, and shows the reader's own new, edited and deleted comments at once until a newer file arrives. A reply or edit being typed survives a refresh. |
| `Submit` | optional `kinds` | The `/submit/` form: link, title, kind radio (when there are several kinds) and note. It warns, without blocking, when the link is already in `submissions.json` or the site has a recent submission, saves a draft in `localStorage` and says so ("Saved locally ..."), clears the draft on success and then shows "Pending — we're reading the link." and any `similar` links. |

`subject` is the lineage id of the published item. Props prerender the last snapshot values; each page then fetches
`<base>_data/reader/items.json`, refetches it every 60 seconds while the tab is visible, and asks `/api/reader/me` once for every
subject on the page. A site under a base path sets `window.papyrusReader = { base: "/posts/" }` before the script (the API stays
at `/api/reader`). Buttons carry `aria-pressed`, every state is also words, controls stay focusable while a write is in flight, and
handles are only ever set as text. While the API answers `503 reader_identity_unavailable`, every control is disabled and says
"Reader sign-in is not open yet".

## Testing it

- `scripts/test-reader-subject.ts`, `scripts/test-reader-api.ts`: the accessor and the route checks (503, 401, 403, 413, 415, 429).
- `scripts/test-reader-steering-plugin.ts`: config, schema, the invoke permission, environment, the schedule rule.
- `procedures/newsroom/tests/test_reader_actions.py`: the function against moto DynamoDB tables shaped like the Amplify
  model tables (handles, vote idempotence and overwrite, rate limits, the debounce).
- `procedures/newsroom/tests/test_reader_snapshot.py`: the snapshot math, ranking, URL policy keys, the task against moto,
  reconcile, and the privacy scan; `scripts/test-reader-snapshot-privacy.ts` repeats the scan from TypeScript over the snapshot
  writer's output.
- `features_backend/reader-steering.feature`: a signed-in reader votes, rates and sees the snapshot after the run.
- `procedures/newsroom/tests/test_reader_submissions.py` and `features_backend/reader-submissions.feature`: submit, the canonical URL
  parity with reference intake, dedupe, similar, validation, the daily limit, votes and karma, the snapshot file, the review signals
  (with real Humanus rules) and retirement of submissions, against moto.
- `procedures/newsroom/tests/test_reader_comments.py`, `test_reader_feedback_export.py` and `features_backend/reader-comments.feature`: comments, threading, the
  edit window, delete stubs, rating context, limits, the snapshot files (only changed files written, stale ones emptied), signals,
  retirement and the feedback export, against moto.
- `scripts/test-reader-write-routes.ts`: the checks every text-carrying route shares (503, 401, 403, 415, 413, 429, pass-through).
- `scripts/test-reader-islands.ts`: the islands in a real browser against a fake API.

A full Amplify sandbox was not used. The function and the snapshot task run against moto, the in-process DynamoDB
fake, and the routes against an injected invoker. To try the whole path locally, set `SITE_ENV=development` and
`PAPYRUS_READER_DEV_SECRET` (16 or more characters) for the Next server; the accessor then derives an `ssdev_` subject for a
signed-in person.

## The switch-on condition

Reader features open per site when Prospectus returns `person.siteSubject` on the resolve and `identities/me` responses.
The sign-in callback stores it in the sealed session cookie; from then on `readerSubject` is non-null and the routes work.
Nothing else changes: no flag, no deploy. Because production writes stay closed until then, no production row is ever
keyed on a development value and no remap from `ssdev_` to `ss1_` is needed.

Prospectus now returns `person: { siteSubject }` (no id, no `createdAt`) for public-reader sites from resolve,
`identities/me` and `GET /v1/accounts`; errors are `{error, message}` only and a missing secret on its side answers 503.
`scripts/test-reader-sign-in-flow.ts` drives the sign-in callback with a stubbed Prospectus transport: a siteSubject in
the response reaches `readerSubject` and the reader API, and a response without one leaves `readerSubject` null and the
API at 503.

`GET /api/auth/prospectus/session` answers the browser with `signedIn`, `cyclotronLabAccess`, `publishingAccounts` and
`selectedAccountId` only. It never returns the person record (id, siteSubject, `createdAt`) or the raw account list.
