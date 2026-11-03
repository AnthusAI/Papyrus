# Reporting on a story: drafts, references and messages

A story is an `Item` lineage (see `content-item-lifecycle.md`). Everything an agent or editor records while reporting
it hangs off the story's **lineage id**. Nothing here needs a new table.

| Record | Where it lives | One per |
| --- | --- | --- |
| Draft version | `Item` row `<lineage>-v<n>`, highest `versionNumber` is the latest | save of a draft |
| Reference link | `SemanticRelation`, predicate `uses_evidence`, story to reference | story and reference |
| Message | `Message` in the story's `MessageThread` (`threadKind` `story_reporting`, anchor `item#<lineage>`) | note, packet or comment |
| Assignment | `Assignment.itemLineageId` | unit of research, reporting or copywriting work |

## Draft versions

Every time an agent changes the article, it records a **new version**; it does not overwrite the old one.

```bash
papyrus stories save-version --story <lineage> --body-file draft.md \
  [--front-matter-file front-matter.yml] \
  --reason "added the Vercel corroboration" --author-label "ChatGPT"
papyrus stories versions --story <lineage>
```

A new version keeps the previous version's board stage. Add `--stage <stage>` (or `--advance` for the next stage before publication) to save the draft and move the stage in one recorded step.

### Saving a draft with its pictures

A draft that uses pictures can carry them in the same command. Put the picture files in a folder next to the draft and
pass `--images <folder>`:

```bash
papyrus stories save-version --story <lineage> --body-file draft.md --images ./pictures \
  --reason "added the architecture diagram" --author-label "ChatGPT" [--dry-run]
```

Every local picture the text uses is uploaded exactly as the newsroom editor's "Insert image" does it: a `MediaAsset`
row on the new version (id `media-<version id>-<first 10 hex of sha256 of the stored path>`, the same id the editor and
the Markus import derive) and an S3 object at `media/assets/<story slug>/<file name>`. The saved text then points at
those stored paths. What counts as a picture:

- an `::image{src="..."}` line, or a Markdown `![...](...)`, whose `src` is a relative path that resolves to a file inside the folder (web addresses, absolute paths, and paths the folder does not hold are left alone; the latter are listed as `image-unresolved`);
- its dark version, if any: a file named like the light one with `.dark` before the extension (`figure.png`, `figure.dark.png`), or the file named by `srcDark="..."`. It is uploaded too and the `::image{}` line gets an explicit `srcDark` with the stored path. `srcDark="none"` keeps pairing off. A Markdown `![]()` has no `srcDark`, so its dark file is uploaded but only an `::image{}` line can show it.

Everything is checked before any write: at most 10 MB per file; a PNG, JPEG, GIF, WebP, AVIF or SVG picture; and a dark
version whose width-to-height ratio is within 0.5% of the light one's. A rejection names each bad file and saves
nothing. `--dry-run` prints one line per file (light or dark, source file, media id, stored path, size, and which light
picture a dark one belongs to) and writes nothing, to the backend or to S3. Like any save, each run records another draft
version.

**Re-runs and stable paths.** Running the command again with the same files reuses the same stored paths and S3 objects:
a file whose content is already stored for the story (any of its versions) keeps its exact `srcPath`, and the object is
only re-uploaded when the picture changed (compared by sha256). A name that already holds *different* content is never
overwritten; the new file gets `-2`, `-3`, as the editor numbers it. `MediaAsset` rows are keyed by story **version**
(the table is queried by item id, and the editor and the version carry-forward derive `media-<version id>-<hash of
srcPath>` the same way), so each saved version has its own rows pointing at the same objects; a row id repeats only for
the same version and path.

**Where the files live, and whether that moves.** The key is `media/assets/<slug>/<file>` with the slug the story has when
the file is first stored; a story with no real slug yet has the generated `draft-unsectioned-<hash>` slug and the CLI
uses it exactly as the editor does. The path does not move afterwards: publishing, `stories set-slug` and a section
change never rewrite media keys or the saved body (the body keeps the stored `srcPath`), so pictures keep working, and
their URLs stay the same, after publish. A later slug change only affects pictures added after it.

Both sign-in lanes work, and they reach S3 differently:

| Lane | Rows (`MediaAsset`) | S3 objects |
| --- | --- | --- |
| `PAPYRUS_GRAPHQL_AUTH=iam` | IAM-signed GraphQL | the AWS credentials of the caller (bucket from `--bucket`, `PAPYRUS_MEDIA_BUCKET` or `amplify_outputs.json`) |
| `PAPYRUS_GRAPHQL_AUTH=user` (`papyrus login`) | Cognito user token; the `editor` or `admin` group may write `MediaAsset` | the signed-in ID token is traded for temporary credentials from the site's Cognito identity pool, the way the browser editor uploads; the group's `media/*` write rule applies; the identity pool must trust the app client the CLI signed in on (below) |

A site that moved the CLI onto its Prospectus federation client (`cliOnFederationClient`) has the backend register that
client on the identity pool too, with the same Token role mapping as the web client, so a CLI ID token gets the same
`editor` or `admin` group role as the browser. Until a site runs a backend with that change, the exchange fails with "Token
is not from a supported provider of this identity pool". The user lane needs the identity pool id: `--identity-pool-id`, `PAPYRUS_IDENTITY_POOL_ID`, or `auth.identity_pool_id` in
`amplify_outputs.json`. The `createModelAttachmentUpload` presigned-URL mutation cannot serve this command: it only
issues keys under `newsroom/payloads` and `media/payloads`, never `media/assets`.

**Publishing from the CLI.** `papyrus ops content publish --id <item-id>` writes the published records and then projects the
page. Three things to know:

- **Placeholder slugs are refused.** A story created from the CLI keeps the generated `draft-<section>-<hash>` slug (for
  example `draft-unsectioned-1a2b3c4d5e6f7a8b`) until `papyrus stories set-slug --story <id> --slug <new-slug>` gives it
  one. `content publish` (a `--dry-run` too) stops with that command in the error and writes nothing; there is no override.
  Unpublishing is not blocked. (The newsroom's own Publish button does not check this: the editor only requires a non-empty
  slug, so a story published from the console can still go live at a placeholder address.)
- **The signed-in lane projects through the newsroom.** With `PAPYRUS_GRAPHQL_AUTH=user` there are no AWS credentials to invoke
  the content-actions function, so after writing the records the CLI calls the `publishItem` mutation (`unpublishItem` for
  an unpublish) that the console's Publish button calls. It is idempotent: it finds nothing left to change, projects the
  page, and reports whether the page is live. The IAM lane still invokes the function directly. (That second call does not
  announce the publish to the newsletter; the console's Publish does.)
- **A failed projection is a failed command.** If the page could not be projected, the command exits 1 and says the data is
  published but the page is not, with the exact retry: `papyrus ops content publish --id <item-id>` (repeating it changes
  nothing already written). With `--json` the payload has `"ok": false`, `"dataPublished": true`, `"pagePublished": false`,
  `"retry"` and `"message"`. `--no-trigger` skips projection on purpose and is not a failure. `stories set-slug` on a
  published story projects the same way.

To move a story between board stages without saving a draft:

```bash
papyrus stories move --story <lineage> --stage reporting [--reason "why"] [--author-label "ChatGPT"]
```

**`--stage published` does not publish.** It only moves the card; no page is written and nothing goes live. The command prints a
warning on stderr saying so (in a `--dry-run` too; stdout keeps its tab-separated lines) and naming
`papyrus ops content publish --id <item-id>`, which is what publishes.

This is the same `Item.stage` update a card move makes. The stage must be one of the content item stages (`idea`, `assignment`, `reporting`, `copywriting`, `illustration`, `typesetting`, `published`, `held`, `spiked`), and each move posts a note in the story's Reporting trail. The `moveStoryStage` GraphQL mutation (input `{ lineageId, stage, reason }`, editor groups) does the same for browser and agent clients.

The new `Item` row gets `versionNumber` n+1, `previousVersionId`, `versionCreatedBy`, `versionCreatedAt` and
`changeReason`; the previous latest version becomes `superseded`. The editor preview always shows the **latest**
version. Older versions are listed in the story's Reporting trail and open read-only. Publishing still publishes the
latest version. Add `--dry-run` to any command to preview.

"Latest draft" and "published" are different records. The **current** record (`versionState` `current`) is the working
draft: saving a version or publishing one makes that record current and supersedes the rest. The **published** record is
the one the lineage's `PublishedItem.sourceItemId` names. Neither is picked by the highest `versionNumber`, and
publishing never changes any record's `versionNumber` (the publish counter lives on `PublishedItem`). `stories set-slug`
always acts on the published record, and keeps the old address as a redirect.

To repair a lineage whose numbers are muddled (duplicate numbers, several current records), preview and then apply:

```bash
papyrus stories repair-versions --story <lineage> --dry-run   # lists the changes
papyrus stories repair-versions --story <lineage>             # renumbers 1..n by creation order, one current record
```

Content is not changed. The live record stays current if the story is published; otherwise the newest record is.

A human editing in the story editor presses "Save draft" to correct the current draft in place, or "Save as new version"
to keep the previous text.

## References: consulted versus cited

Attach a reference as soon as you read it. One link exists per story and reference. Its `role` says what the reference
became:

* `consulted`: found or reviewed during reporting. It may or may not appear in the article.
* `cited`: it is a citation in the article. Give the Markus citation key so the link and the text agree.
* `based_on`: the story is made from this Reference. Every path that makes a story from a Reference writes it, and a later `consulted` or `cited` link never replaces it ([core rules](reference-curation-pipeline.md#6a-stories-based-on-a-reference-core-rules)).

```bash
papyrus stories link-reference --story <lineage> --reference <reference id> \
  --role consulted --note "primary source, sandbox escape write-up" --author-label "ChatGPT"
papyrus stories link-reference --story <lineage> --reference <reference id> \
  --role cited --citation-key pwn2026 --author-label "ChatGPT"
```

Running `link-reference` again for the same pair changes its role and keeps who added it and when. The Reporting trail
shows each reference with its role, note and the person or agent who attached it, and marks a reference "in the text" when
the latest draft's citations include its citation key.

## Messages

Use messages for everything said during reporting: what you found, what you decided, what is still open, packets, editor
comments. They are kept in one ordered thread per story, each with author, time and kind, and shown newest first in the
story's Reporting trail.

```bash
papyrus stories note --story <lineage> --author-label "ChatGPT" \
  --summary "Vercel corroborates the host-memory disclosure" \
  --body-file note.md [--kind note|research_packet|reporting_context_packet|draft_note|editor_note] \
  [--reference <reference lineage>] [--version <n>]
```

`--reference` ties the message to a reference you discuss; `--version` ties it to the draft version it is about.
There is no separate "insight" record: a note about a reference or a story is a message.

## Reading it back

```bash
papyrus stories show --story <lineage>
```

prints the latest version, how many versions exist, and every attached reference with its role.

## Assigning research and the reporter context pack

An editor can attach a research assignment, with their own direction, to a Story. The assignment works on the Story's lineage, in the Story's section.

```bash
papyrus stories assign-research --story <lineage> --direction "Find the court rulings on model output" \
  [--direction-file direction.md] [--type research.multi] [--title "..."] [--dry-run]
```

The assignment is open, its type defaults to `research.multi`, its title to the Story's title, its `instructions` and `metadata.direction` hold the direction, and its `metadata.contextProfile` is `reporter`. An `AssignmentEvent` records the creation. A Story at the `idea` stage moves to `assignment` through the recorded stage move (`stories show` lists it); a Story at any other stage stays where it is. The command does not fire stage-entry triggers; run `papyrus stories fire-triggers` if the stage should start one. `--dry-run` writes nothing.

`papyrus assignments context-pack` shows what a reporting agent is given. It only reads.

```bash
papyrus assignments context-pack --story <lineage> [--assignment <id>] [--direction TEXT] [--format text|json] [--max-characters N]
```

The pack (contract `newsroom-context-pack/v1`, module `newsroom_context_pack.py`) is built without a model, the same way every time. Its `system` text is never trimmed: the profile's role text, the publication mission and policy, and the Story's section mission, policy, assignment guidance and kill criteria. A section with no mission or policy is a warning in `warnings`; nothing is invented, and a missing publication policy stops the build. Its `user` text has ten layers, most specific first, and `layers` reports each one's entries (with source ids), characters, `droppedCount` and `droppedReason`:

| Layer | Holds |
| --- | --- |
| `assignment` | The editor's direction, the assignment title and who asked |
| `story` | Title, deck, the current version's text, stage, type and section |
| `story_references` | References linked to the Story (any role), with title, address, summary, published date, accept reason, stars, the note on the link, and the notes editors wrote on how they connect to other References |
| `related_references` | The other end of every `related_to` edge on the Story's References, in both directions, each once, with the full summary, its curation status (accepted or pending), the Story Reference it connects to and the editor's note. An edge a person accepted ranks first, then suggested edges by descending `score`; rejected edges and rejected References never appear. A Reference here is not repeated in the outer layers |
| `story_conversation` | Messages on the Story's `story_reporting` and `story_conversation` threads, oldest first, with author |
| `prior_research` | The research packets earlier assignments on this Story made, newest first: the direction given, summary, claims and open questions |
| `desk_published` | Published Stories in the same section, newest first |
| `desk_references` | Accepted References that belong to the section: curated for it (`curationSectionId`), or used as evidence (`uses_evidence`) by any other Story in the section at any stage, ideas included; best first |
| `publication_published` | Published Stories in other sections, newest first |
| `publication_references` | Accepted References in other sections, best first |

The outer layers are for awareness, so each entry is one line: title, date, address and the first sentence of the summary or deck, with the accept reason and stars when an editor gave them. Full summaries appear only in `story_references`. A Reference whose title is empty or is only its address shows no title line in the top layers, and in a one-line entry it leads with the first sentence of its summary. The outer layers leave out system item types, retired Items, the Story itself and References already in `story_references`. Rejected and pending References never appear. References rank by an editor's vote or stars first (stars, then a written reason), then by newest; an auto-accepted Reference ranks below every one an editor voted on or rated. Reads go through the client, so a tenant's pack holds only that tenant's records.

There is no fixed count and no day window. `max_characters` is the only bound; without `--max-characters` it defaults to 100,000, half of the 200,000 characters the research run allows its model input. The first five layers are filled first. If they alone exceed it, the oldest conversation messages go first, then the oldest research, then the References' summaries, and the layer records what it dropped. The room left is shared outward in halves: `desk_published` may use up to half of it, `desk_references` up to half of what is then left, and so on, with unused room rolling forward. Entries are whole or absent, and published Stories are read newest first only until a layer's share is full. The ranked Reference layers rank on the Reference records and read an entry's summary only when the entry is considered for the budget. The related-References layer reads the edges already stored (`current` and `suggested` states of `related_to`; a rejected edge is in neither state key) and does not use the References search, which is a `searchReferences` query open only to signed-in editor and admin sessions, not to the IAM lane the authoring client uses, and whose meaning lane runs inside that service. The layer takes half of the room left after the first five layers (assignment, Story, its References, conversation and earlier research); the outer layers share the rest.

`contextHash` is a hash of the rendered `system` and `user` text and the layers' provenance, excluding any fetch time; it changes when the policy, the Story or any included record changes. `editorialContextHash` is the hash of the editorial context inside `system`.

`papyrus assignments research-multi <assignment>` uses the pack when the assignment's `contextProfile` is `reporter` and it works on a Story: the pack's `system` text is put before the planning and synthesis prompts, and the pack's `user` text is the brief. The packet records the pack in `multiSearch.contextPack` (the two hashes and the size of each layer, never the text). The packet Message stays a machine record linked to the assignment by `produces`; it is not added to any thread, because Messages come only from people. The Reference records made from the proposed sources are linked to the Story as `consulted` (a Reference the Story already has, in any role, is left as it is). The Story's text is never changed. Other assignments behave as before.

## Approving a Reference on a person's behalf

Until a deployment includes the delegation mutations, an agent that runs
`papyrus references review-curation` changes a Reference's admission status, but
the curation is recorded without a human actor kind and never teaches a
classifier. Do not tell a person their approval was recorded as a label unless
the command below printed "on behalf of".

When a person tells you, in a live session, that a Reference is approved or
rejected, the system records it as the person's own label, but only with a
delegation the person granted. You cannot assert it yourself, and your own
judgment never becomes a label this way.

1. The person signs in to the Newsroom and creates a delegation (the
   `createCurationDelegation` mutation): your agent name and how long it lasts
   (eight hours by default, 72 at most). They hand you the token it shows once.
   They can revoke it at any time (`revokeCurationDelegation`).
2. Record their decision. The token can be passed as `--delegation-token` or as
   `PAPYRUS_DELEGATION_TOKEN`:

   ```bash
   papyrus references approve --reference <record id> --on-behalf-of <person's sign-in email> \
     --agent <your name> --instruction "<the person's exact words>" --note "<their reason>"
   papyrus references reject --reference <record id> --on-behalf-of <person's sign-in email> \
     --agent <your name> --instruction "<the person's exact words>" --reason-code out_of_scope --note "<their reason>"
   ```

3. The `recordDelegatedCuration` mutation checks the token (unexpired,
   unrevoked, granted to your agent name, granted by the person you named), then
   records the curation as the person's on the Reference: `curationActorKind: human`, and
   `curationDelegation` holding `relayedBy` (your agent name), `delegationId` and `instruction`, the person's
   words as you quoted them. The token proves the person let you relay decisions,
   not that they made this one, so the quote is what makes each label auditable.

### Getting a delegation without pasting a secret (device authorization)

Prefer this flow: the secret is made on the agent's machine and never passes
through chat or through the server in plaintext.

1. The agent runs:

   ```bash
   papyrus references request-delegation --agent <your name> [--hours 8] --wait
   ```

   It generates `curation-delegation-<uuid>~<random secret>`, writes it to a
   private file (mode 0600, by default under `~/.config/papyrus/delegations/`,
   or `--token-file <path>`), sends only the SHA-256 hash
   (`requestCurationDelegation`), and prints only an approval code such as
   `ABCD-2345` and the file path. The secret is never printed.
2. Tell the person: open the Newsroom, Delegations, approve that code. The
   request is pending for ten minutes, and at most five can be pending at once.
3. The person approves (`approveCurationDelegation`) or denies
   (`denyCurationDelegation`). Approval makes them the grantor and starts the
   requested lifetime (default eight hours, 72 at most). `--wait` polls
   `getCurationDelegationStatus` until approved, denied or expired.
4. Record decisions with the file, so the token never appears in a prompt:

   ```bash
   papyrus references approve --reference <record id> --on-behalf-of <person's sign-in email> \
     --agent <your name> --instruction "<the person's exact words>" --delegation-file <path>
   ```

   `--delegation-token` and `PAPYRUS_DELEGATION_TOKEN` still work.

`recordDelegatedCuration` refuses a delegation that is pending, denied or
unapproved (`not-approved`) and keeps every other check. A person can still
revoke an approved delegation at any time.

#### For the approve screen

All of these need a signed-in Newsroom editor, except the two the agent calls.

- `listCurationDelegations` (query) returns a list of `CurationDelegationResult`:
  `ok`, `delegationId`, `token` (always null here), `agentLabel`,
  `grantorLabel`, `expiresAt`, `revokedAt`, plus the new `state`
  (`pending|approved|denied|expired|revoked`), `userCode` (`XXXX-XXXX`, only
  while pending), `requestedHours`, `pendingExpiresAt`, `approvedAt`,
  `deniedAt`. Live pending requests from every agent are included; for a
  pending request `expiresAt` equals `pendingExpiresAt`.
- `approveCurationDelegation(userCode: String!)` (mutation) returns a
  `CurationDelegationResult` with `state: approved`. The code is accepted in
  any case, with or without the hyphen. Unknown, expired or already decided
  codes are refused.
- `denyCurationDelegation(userCode: String!)` (mutation) returns a
  `CurationDelegationResult` with `state: denied`.
- `revokeCurationDelegation(delegationId: ID!)` still revokes an approved
  delegation (and also works on a pending one).
- Agent only (IAM): `requestCurationDelegation(delegationId, tokenHash,
  agentLabel, hours)` returns `{ ok, delegationId, userCode, pendingExpiresAt,
  requestedHours }`; `getCurationDelegationStatus(delegationId)` returns
  `{ delegationId, state, expiresAt, grantorLabel }`. Neither returns a secret
  or hash.

Only relay what the person actually said. If you are unsure, quote their words in
`--note` and ask. A delegation lets you record a human decision; it does not let
you decide.

Limit to know about: an agent with direct write access to the data models could
still write curation metadata itself. The delegation makes the honest path
verifiable, and the audit trail (delegation id, agent, grantor) lets a person
check it; removing direct write access to the Reference's curation fields is a separate
hardening step.

### Naming the section

An accept, direct or relayed, can also say which newsroom Section the Reference
belongs in:

```bash
papyrus references approve --reference <record id> --on-behalf-of <person's sign-in email> \
  --agent <your name> --instruction "<the person's exact words>" --section <newsroom section id>
papyrus references review-curation --reference <record id> --action accept --section <newsroom section id>
```

`reviewReferenceCuration` and `recordDelegatedCuration` take an optional
`sectionId`. It must be the id of an enabled `NewsroomSection`; an unknown or
disabled section is refused before anything is written, and a section on a
reject, reopen or archive is refused. The id is stored as `sectionId` in the
`curationSectionId` on the Reference beside `curationActorKind`. Only an accept that the signed-in
person made, or that the person delegated, counts as their section label.
