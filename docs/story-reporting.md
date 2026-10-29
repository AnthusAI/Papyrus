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

To move a story between board stages without saving a draft:

```bash
papyrus stories move --story <lineage> --stage reporting [--reason "why"] [--author-label "ChatGPT"]
```

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
   records the curation as the person's: `actorKind: human`, `attestation:
   delegated`, `relayedBy` your agent name, `delegationId` and `instruction`, the person's
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
check it; removing direct write access to curation Messages is a separate
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
curation Message metadata beside `actorKind`. Only an accept that the signed-in
person made, or that the person delegated, counts as their section label.
