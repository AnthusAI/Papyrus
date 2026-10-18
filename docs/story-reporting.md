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

The new `Item` row gets `versionNumber` n+1, `previousVersionId`, `versionCreatedBy`, `versionCreatedAt` and
`changeReason`; the previous latest version becomes `superseded`. The editor preview always shows the **latest**
version. Older versions are listed in the story's Reporting trail and open read-only. Publishing still publishes the
latest version. Add `--dry-run` to any command to preview.

A human editing in the story editor presses "Save draft" to correct the current draft in place, or "Save as new version"
to keep the previous text.

## References: consulted versus cited

Attach a reference as soon as you read it. One link exists per story and reference. Its `role` says what the reference
became:

* `consulted`: found or reviewed during reporting. It may or may not appear in the article.
* `cited`: it is a citation in the article. Give the Markus citation key so the link and the text agree.

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

Only relay what the person actually said. If you are unsure, quote their words in
`--note` and ask. A delegation lets you record a human decision; it does not let
you decide.

Limit to know about: an agent with direct write access to the data models could
still write curation metadata itself. The delegation makes the honest path
verifiable, and the audit trail (delegation id, agent, grantor) lets a person
check it; removing direct write access to curation Messages is a separate
hardening step.
