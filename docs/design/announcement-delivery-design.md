# Announcements, Deliveries, guidelines and lifecycle: one design for pod and cloud

Date: 2026-11-16. Owner: Ryan (product owner). Design only. No code, commit, AWS call, post or board change was made.

Marks: **[V]** verified by reading; **[I]** my inference; **[P]** proposal.

Sources read: `~/Projects/papyrus-local-pod-standard.md`, `~/Projects/papyrus-vault-ld-assessment.md`, the memory notes named in the brief, Papyrus at `origin/develop` `c4c33541b` (16 Nov), Caducus `origin/develop`, and Jira DATAP-911. Two things I could not verify are listed in section 12.

---

## 0. The short version

1. **Two records, not one.** An **Announcement** is the decision to say something. It knows nothing about channels. A **Delivery** is one channel's version of it: the words, the picture, the account, what happened, and the address of the result.
2. **Retries are attempts. Corrections are new Deliveries.** A Delivery keeps a log of attempts that only grows. A corrected re-send is a new Delivery that names the one it replaces.
3. **Three cloud models become one.** X announcement rows, newsletter `ISSUE#` rows and alert de-dup rows all map onto Announcement plus Delivery. A fourth, the notifications plugin's `story.published` event, does too. The per-reader send ledger and the transport stay in Caducus.
4. **X stays off.** No live X rows exist, so the X model is reshaped before the first live post. Nothing is migrated there.
5. **Guidelines become files.** One guideline is a folder with a `GUIDELINE.md`: front matter (kind, scope, severity) and prose. The cloud stores the same files in S3. They can be checked on a laptop with no network.
6. **Lifecycle has the same field names in a pod and in the cloud.** In the cloud they sit on the Item record with immutable versions. In a pod they sit in note front matter with Git history. Kanbus stays the task board.
7. **Git history is weaker than newsroom versions, and I recommend we say so instead of hiding it.** A review recorded in a pod is a claim. It loads as a claim. It never counts as a newsroom review, a five-star approval or a passed gate.
8. **A pod with no site is private.** Nothing in it is ever published by a load.
9. **Anth.us stays a cloud newsroom.** Its knowledge-base repository becomes a private typed pod that may feed the newsroom.
10. All 14 open questions from the pod standard are answered in section 8, each with a default.

---

## PART 1. Announcement and Delivery

### 1. What exists today

| Model | Where | What it holds | Problem |
|---|---|---|---|
| X announcement rows (PPY-09ee86) [V] | `Announcement` table, id `<accountId>#<lineageId>`; text in S3; `AnnouncementSpend`, `XConnection`, `AnnouncementSettings` | Decision, channel, account, text, state, post id, cost, attempts, rounds, history: all in one row | The decision and the channel are welded together. A second channel means a second row shape. A correction has nowhere to go. A retry after a pause is "round 2" with a suffix on the event id. |
| Newsletter issue rows [V] | Newsletter table: `ISSUE#<id>`, `ISSUE#<id>/RENDER`, `ISSUE#<id>/SEND#<hid>`, `ROUNDUP#<listId>/PERIOD#<yyyy-ww>` | Send state, approval, counts, the rendered HTML and text, one ledger row per reader | Its own states, its own approval, its own once-only rows. The rendered HTML, and an alert's Markus body, are stored in DynamoDB rows. |
| Alert de-dup rows [V] | Newsletter table: `ALERT#<listId>/ITEM#<lineageId>` | "This Story was already alerted on this list" | A third once-only mechanism, tied to one list. |
| Notifications plugin event [V] | Caducus, event id `story.published:<lineage>` | Caducus's own once-only check | A fourth. |
| DataParade codebase newsroom (DATAP-911) | Named in the brief as `.dataparade/newsletter/evidence` and `issues` | Evidence and issues as files | Not found in any checkout; see section 12. |

All of these answer the same two questions: "did we decide to say this?" and "what happened on that channel?". Today each answers both in one place, in its own way.

Caducus already owns the transport [V]: a delivery log with a provider message id, a status that never moves backward, cost, pacing, a dead-letter path, the public audience, consent and suppression. This design does not copy any of that.

### 2. The two records [P]

```
Story (one or many)
   ^
   | announces                      one decision, no channel
   |
Announcement ----------------------------------------------+
   |  dedupeKey, kind, releaseAt, approval, state          |
   |                                                       |
   +--> Delivery 1  (x, @account)       state: sent        |
   |       attempts: [1 failed, 2 sent]  resultUrl         |
   |                                                       |
   +--> Delivery 2  (email, lists)      state: sent        |
   |       attempts: [1 sent]  counts                      |
   |                                                       |
   +--> Delivery 3  (x, @account)       state: sent        |
           supersedes: Delivery 1   (a corrected re-send)  |
           Delivery 1 is now: superseded                   |
```

**Announcement: the decision.**

| Field | Meaning |
|---|---|
| `id` | Permanent id, as for every other record. |
| `dedupeKey` | The once-only key. Created with a condition, so the same decision cannot exist twice. Examples: `story-published:<lineageId>`, `roundup:<listId>:<yyyy-ww>`, `correction:<lineageId>:<versionNumber>`. |
| `kind` | `story_published`, `roundup`, `correction`, `manual`. A plain string; a site may add its own. |
| `announces` | Links to the Stories it is about, each with the version that was looked at. One Story for a publish. Many for a roundup. This is a relation, so "where was this Story announced?" is one indexed read from the Story. |
| `releaseAt` | When Deliveries may go. Stored in UTC. Empty means "as soon as allowed". |
| `approval` | `none`, `soft` or `hard`. This is the existing review request (flag, soft review, hard gate), not a new state. |
| `approvedBy`, `approvedAt` | Who released it and when. `system` names the rule when approval is `none`. |
| `state` | `planned`, `released`, `cancelled`, `withdrawn`. |
| `createdBy`, `trigger`, `history` | Who or what made it, and a log that only grows. |

An Announcement holds no words for readers, no channel and no account.

**Delivery: one channel's version.**

| Field | Meaning |
|---|---|
| `id` | Permanent id. |
| `announcement` | The Announcement it belongs to. |
| `channel`, `account` | For example `x` and the account id, or `email` and the site's sending identity. |
| `audience` | For channels that fan out: the list ids. Empty for a broadcast account. |
| `mode` | `automatic` (Papyrus sends through Caducus) or `manual` (a person posts by hand and records the result). |
| text and image | The tailored words and any picture. Files in S3, attached to the Delivery. The row holds only the keys and a content hash. |
| `draftedBy`, `checks` | What wrote it, which guidelines it was written under (id, version, hash) and which checks it passed. |
| `state` | `drafted`, `ready`, `sending`, `sent`, `failed`, `blocked`, `dry_run`, `withdrawn`, `superseded`. |
| `blockedReason` | `paused`, `budget reached`, `account needs reconnecting`, `check failed`, `postal address missing`. |
| `resultUrl`, `providerId` | Where it ended up: the post, or the archive page for an email issue. |
| `cost`, `counts` | Money charged. For fan-out channels: queued, sent, failed, suppressed, delivered, bounced. |
| `attempts` | The attempt log. Append-only. Each entry: number, time, the Caducus event id, outcome, provider code. |
| `supersedes`, `supersededBy` | The Delivery this one corrects, and the one that corrected it. |

**The rules.**

- **One live Delivery per Announcement, channel and account.** A new one for the same three can be created only with `supersedes` set, in one transaction that marks the old one `superseded`.
- **A retry is an attempt.** Attempt N is one Caducus event, id `delivery:<deliveryId>:a<N>`. This replaces today's "round 2" suffix. A pause, a budget stop or a rate limit ends an attempt; the next try is the next attempt on the same Delivery.
- **No invented retry count.** An attempt sequence ends on a clear answer from the provider: sent, refused, or (for X, after an unknown outcome) the read that shows whether the post exists. That rule is already in the X plan [V].
- **A corrected re-send is a new Delivery.** Its text is new and is checked again. Where the channel can remove the old one (X), the old post is deleted as part of the correction. Where it cannot (email), the new text says it is a correction.
- **A Delivery is drafted once**, when its channel first qualifies. Nothing re-drafts on a schedule.
- **Channel rules decide whether a Delivery exists.** The X floor (five stars on Machines on Machines) and an email list's section rule are per-channel settings. The Announcement is created together with its first Delivery, in one transaction, so a publish that qualifies nowhere leaves no row (today's behaviour [V]). A rating that reaches the X floor a week later adds the X Delivery to the same Announcement.
- **Quality floor.** No channel may set a bar under three stars. Unrated and predicted never qualify. A machine never supplies the five.
- **Manual mode** covers what has no API or no budget: Papyrus drafts and checks the text, a person posts it and pastes the address, and the Delivery records `sent` with that person's name in the attempt log. Ryan reposting from his own account is this.
- **Dry run** stays a state: built, checked, not sent, cost 0.

**Storage (cloud).**

- Two catalog tables: `Announcement` and `Delivery`. Short fields only. Words, pictures and long provider errors are files in S3. This also removes the two places where the newsletter keeps text in DynamoDB.
- Reads by index only: an Announcement by its once-only key; an Announcement's Deliveries; an account's Deliveries newest first (today's list view); planned Announcements by `releaseAt` for the calendar; a Story's Announcements through the `announces` relation, which is already indexed both ways. Nothing lists a table.
- No AppSync subscriptions.
- Spend stays one counter per account and billing cycle. The account connection and the settings document stay as built.

### 2.1 Conscious editing: the draft is a working document [Ryan, 2026-11-16]

Added after the first review. The announcement is the touch point on each network, so it gets designed on purpose and is never an afterthought.

- **A Delivery is a draft with an edit window, not a one-shot.** The window runs from creation to `releaseAt`. A weekly newsletter has a week. A story post may have twenty minutes. The window is set per kind and per channel, as data.
- **Machine first draft, human curation.** The machine drafts the Delivery from the Story and the channel guidelines. People then edit it. Every edit is a new saved version of the Delivery text. Versions are kept; none is overwritten.
- **Human edits are pinned.** Blocks and lines a person changed are marked `owner: human, pinned`. A later machine redraft never overwrites a pinned block. This is the same rule the Story translations use.
- **One working surface per channel.** Newsroom shows the draft the way the channel will show it (X length and card, LinkedIn fold and line breaks, email preview), next to the checks that apply. Agents use the same operations through the CLI.
- **Per-channel guidelines.** A guideline folder may be scoped to a channel (`channel/x`, `channel/linkedin`, `channel/email`), so each network has its own craft rules: hook, length, links, tags, tone, image shape. The drafter and the checker both read them.
- **Several candidate versions.** A Delivery may hold alternative texts or images. One is chosen; the others are kept. This is also what makes later A/B comparison possible.
- **Newsletters are assembled, not generated whole.** An issue Delivery is built from slots that fill automatically as Stories qualify during the week (the machine's picks and blurbs), and an editor curates: reorders, rewrites, swaps, pins, drops. Pinned slots stay when the machine refills the rest.
- **Lock time.** At a set time before `releaseAt` the Delivery locks for the send job: the last approved version is sent. A late edit after the lock needs an explicit unlock. The attempt log records which version was sent.
- **Nothing is sent that no person looked at, where approval is `soft` or `hard`.** For `none`, the machine draft goes at `releaseAt` as today.
- **Effort is visible.** The Announcements list shows each Delivery's state, its edit window, who last edited it, and whether any human has touched it, with words and marks, never colour alone.

### 2.2 Human review is a per-publication setting [Ryan, 2026-11-16]

Some publications run fully automatic: the first person to see an announcement is a reader. Others, such as Machines on Machines, release only what a person has reviewed. Both are normal, so this is a setting and not a rule.

- **One setting, `announcementReview`, on the publication's settings.** Values: `none` (fully automatic), `soft` (a person may edit or stop it before the lock time; silence lets it go), `hard` (a person must release it). These are the existing approval values; the setting chooses the default for new Announcements.
- **Overrides, narrowest wins:** publication, then channel (for example LinkedIn `hard` while X is `none`), then Announcement kind (for example roundups `hard`, story posts `none`). Each override is optional.
- **A separate source rule, `requireReviewedSource`.** When on, an Announcement is created only for a Story that a person has reviewed (a human review stamp on its current version: the lineage's review step, `review_people` or a translation's `human_review`, done on the current version by a person or by an agent on a person's recorded instruction; PPY-473f8f). Machines on Machines turns this on, so nothing unreviewed is announced. Default off. A Story that is edited after review loses the stamp and returns the Announcement to waiting, as it does today.
- **Both settings are data, change at any time, and apply to Announcements created afterwards.** One already planned keeps the policy it was created under unless an editor changes that one Announcement.
- **Every Announcement records the policy it ran under** (`approvalPolicy`, where it came from), so the list can say "sent automatically by publication policy" or "released by a person".
- **Defaults.** New publications start at `soft` with `requireReviewedSource` off. Machines on Machines: `hard` for roundups and `requireReviewedSource` on. Other sites keep today's behaviour until their owner changes it. Nothing changes on any site as part of this slice.
- **Floors that no setting lowers.** The three-star floor and the rule that a machine never supplies a five apply under every policy.

**What Caducus keeps.** The transport, the provider message id, status from the provider, cost recording, the public audience, consent, suppression, and the per-reader send record. Papyrus holds counts on the Delivery, never one row per reader.

### 3. What each existing model maps onto

| Today | Becomes | Migrates? |
|---|---|---|
| X `Announcement` row | Announcement (`story_published`) plus one Delivery (`x`, account) | **Reshape, no data move.** X is off everywhere. Any dry-run rows are deleted, not converted. |
| X "round" and `:r2` event ids | Attempt numbers on one Delivery | Code only. Caducus 0.3.0 already takes `delivery:<id>:a<N>`: it treats an event id as an opaque string. |
| X withdraw | Delivery state `withdrawn`; Announcement `withdrawn` when all its Deliveries are | Code only. |
| `AnnouncementSpend`, `XConnection`, `AnnouncementSettings` | Unchanged. Settings gain nothing; channel rules already live there. | No. |
| Newsletter `ISSUE#` row, kind `roundup` | Announcement (`roundup`) that announces the issue Story at its approved version, plus one Delivery (`email`, lists). Approval and send time move to the Announcement. Counts move to the Delivery. `resultUrl` is the archive page. | **Yes.** Sent issues on Shipped and Distinctive are converted once by a command, so the archive and history stay whole. |
| `ROUNDUP#<listId>/PERIOD#<yyyy-ww>` | The Announcement's `dedupeKey` | Converted with the issue. |
| `ISSUE#/RENDER` (HTML and text in DynamoDB) | The Delivery's files in S3 | Converted; the old attribute is not carried. |
| `ISSUE#/SEND#<hid>` reader ledger | Caducus's public-audience delivery record | Moves with the planned move to Caducus (PPY-824c14). Not part of this epic. |
| "Edited after approval; approve again" | The Announcement pins the Story version. A newer version returns it to waiting for approval. | Behaviour kept. |
| `ALERT#<listId>/ITEM#<lineageId>` | `dedupeKey` `story-published:<lineageId>`, plus the email Delivery's audience | **Yes, keys only.** Each kept row becomes an Announcement with a `sent` email Delivery, so nothing alerts twice. |
| Alert issue with its Markus body on the row | The email Delivery's text file in S3 | Converted. |
| Notifications `story.published:<lineage>` event | The first attempt of the email Delivery | Code only; off everywhere. |
| Operator alerts (alarms to operators) | **Not an Announcement.** They are operations messages, not editorial decisions. They stay plain Caducus events. | No. |
| DATAP-911 `evidence` | Reference notes in a private pod, each with its source tier as a declared key | See section 7. |
| DATAP-911 `issues` | Story notes of the issue type, plus one Announcement note and its Delivery notes each | See section 7. |

One gain worth naming: an X post and an email alert about the same Story are now one Announcement with two Deliveries. The Story drawer shows one line per channel under one decision.

### 4. In a pod

An Announcement and a Delivery are notes, with the same field names.

```markdown
---
id: https://example.org/id/7c1e...
type: papyrus:Delivery
announcement: "[[2026-11-16-slow-water-published]]"
channel: x
account: "@example"
mode: manual
state: sent
resultUrl: https://x.com/example/status/123
attempts:
  - "1 2026-11-16T14:01Z sent by ryan"
---
The tailored post text, exactly as posted.
```

- The words are the body. The body is outside the graph and is never built into a page.
- `attempts` is a list of one-line entries. `pod check` fails if an earlier line changed since the last commit, the same way it guards an id.
- `supersedes: "[[older-delivery]]"` is a typed link.
- **A pod delivers in manual mode only.** Automatic sending needs a connected account, a budget guard and Caducus, which live in a newsroom. A pod has none and gets no local stand-in.
- On load, Announcement and Delivery notes become the same records, as history. A load never sends anything.
- Neither type is ever a page.

---

## PART 2. Guidelines as a local standard

### 5. One guideline is one folder [P]

Today [V]: guidelines are data in the cloud. A guideline document per kind (`writing`, `image`, `announcement`) and scope (site or section) is a versioned private `doctrine` Item with its JSON in S3. Saving writing guidelines derives copy-editing checks (`EditorialPolicy`: key, scope, language, severity, guidance, detectors). A section adds and never loosens. There is no file form a person or agent can keep in a repository and check offline.

**The file form.**

```
guidelines/
  plain-claims/
    GUIDELINE.md
    examples/before.md          optional supporting files
  x-post-voice/
    GUIDELINE.md
```

```markdown
---
id: https://example.org/id/2b9d...
type: papyrus:Guideline
name: plain-claims
description: State a claim as fact. Never "we believe".
kind: writing
scope: publication
severity: error
language: "*"
avoid: ["we believe", "we think", "arguably"]
---
Say "A is red". Do not say "we believe A is red". ...
```

| Key | Values | Meaning |
|---|---|---|
| `kind` | `writing`, `image`, `announcement` | Which work it governs. |
| `scope` | `publication`, `section/<id>`, `channel/<name>` | Where it applies. `channel/x` is how a Delivery's tailoring rules are written. |
| `severity` | `error`, `warn`, `guidance` | `error` holds a Story (today's rule [V]). `warn` reports. `guidance` is prose for the writer and is not checked. |
| `avoid`, `prefer`, `pattern`, `maxLength` | flat lists and numbers | The parts a program can check with no model. |
| body | prose | What the writer and the checking model read. |

It follows the profile's rules: flat keys only, an explicit id, unknown keys refused. A Guideline is never a page.

**Checkable offline.** `papyrus guidelines check --dir guidelines/ FILE...` runs every rule a program can decide (word lists, patterns, lengths, headline order) with no network and no model. For a rule that needs judgement it prints "not checked offline" and the rule's name. It never guesses. `pod check` validates the guideline files themselves.

**The same data in the cloud.** The cloud stores the files themselves: the guideline document for a kind and scope is its set of `GUIDELINE.md` files in S3, with the catalog row holding the version, who, when, why and a hash over the set. So:

- `papyrus guidelines save --kind writing --dir guidelines/` uploads the set as a new version (stale versions refused, as today).
- `papyrus guidelines export --dir` writes back byte-identical files.
- The resolver, the layering rules, the "section never loosens" rule, admin-only saving and the derived checks all stay. Each file with `error` or `warn` severity derives one check, with the source recorded as today.
- Today's structured fields (`voice`, `audience`, `tone`, `lexicon`, `glossary`, `headline`, `constraints`) become guideline files with fixed names. That is schema version 2 of the writing document, converted once per site by a command. There is no reader for both shapes afterwards.

**Why files and not a second export format:** one form means a guideline written on a laptop, checked there, and saved to a newsroom is the same bytes at every step. Nothing is translated, so nothing drifts.

**Decision for Ryan.** This changes a system that was just built (PPY-2a2a8a). *Default: yes, do it, before more sites write guidelines in the JSON shape. The longer we wait, the more there is to convert.*

---

## PART 3. Lifecycle in a pod and in the cloud

### 6. Same names, two homes [P]

Ryan's 17 October decision stands [V]: the content item is one record with one lifecycle field. Kanbus is the task board. It is not where a Story's lifecycle lives.

| Field | Cloud (on the Item record) | Pod (in the note's front matter) |
|---|---|---|
| `stage` | `idea`, `assignment`, `reporting`, `copywriting`, `illustration`, `typesetting`, `published`, `held`, `spiked`, `retired` | The same key and the same values |
| `type`, `section`, `format` | As today | The same keys (`type` as the class, per the profile) |
| `rating` | Stars, with who gave them | A number 1 to 4. A 5 is refused on load and listed as a five-star candidate for a person to confirm in the newsroom. |
| `reviewedBy`, `reviewedOn`, `reviewedHash` | Review stamps tied to an immutable version and a signed-in person | Three flat keys. `reviewedHash` is the hash of the body that was reviewed. `pod check` reports "review is stale" when the body no longer matches. |
| `spikedReason`, `heldReason` | Recorded on the stage change | Flat keys |
| Versions | Immutable, numbered, each with author and reason | Git commits |
| Checklist steps | Stored sub-task records, publish refused while a required step is open | **Not in a pod.** See below. |

**One switch, said once.** A note with a `stage` is built into a site only at `stage: published`. A note with no `stage` is built unless `draft: true`. A note may not carry both; the checker refuses it.

**Lossless load.** Every lifecycle key on a note lands on the Item field of the same name. Nothing is dropped or renamed. The load records the commit it came from. Git history is linked by that commit, not replayed into versions. *Decision: replay every commit as a newsroom version? Default: no. One version per load, with the commit recorded. The history stays in Git, where it is true.*

**Kanbus.** A Kanbus issue may quote a note's id. A pod never reads issues. Changing a note's `stage` is an edit to the note, not a card move. The old story-folder gates in the Anth.us knowledge base and Pilobolus stay what the pod standard called them: a Kanbus workflow over plain notes.

### 6.1 Is Git history good enough? An honest assessment

| What a newsroom version gives | What Git gives | Gap |
|---|---|---|
| A version can never be changed | History can be rewritten: amend, rebase, force-push | Real. A protected branch narrows it; nothing in a folder of files closes it. |
| "Who" is a signed-in Google account | "Who" is whatever name the committer typed, unless commits are signed | Real. An agent can commit under any name. |
| A review stamp points at one exact version, and a later edit visibly leaves it behind | A `reviewedBy` key is a line of text anyone can type | Real. `reviewedHash` catches a stale review. It cannot catch a false one. |
| A save against a stale version is refused | A merge resolves it, sometimes badly | Moderate. |
| Stage change, review and body change are separate, attributed events | One commit can change all three | Moderate. |
| Checklist with reasons for every skipped step; publish blocked on open steps | Nothing | Real. This was built because agents skipped steps unrecorded. |
| Five stars means a person approved | A number in a file | Real, and five stars drive announcements. |

**Verdict.** Git history is enough for authorship of one's own writing and for a site one person builds from files. It is not enough for accountability: it cannot prove who reviewed, cannot prove nothing was rewritten, and has no checklist.

**Recommendation.**

1. **Keep the pod lifecycle, and call its stamps claims.** They are useful working state. They are not evidence.
2. **A claim loads as a claim.** After a load, the newsroom shows "Recorded in the pod by <name>, not verified". It never satisfies a hard gate, a required checklist step, `publishRequiresRating` or a five-star rule. A person confirms in the newsroom, once, and that is the real stamp.
3. **Do not build a stronger pod.** No signature checks, no pod checklist, no local review ledger. Each would be a second accountability system to keep honest. A site that needs accountable review is a newsroom. That is what the newsroom is for.
4. **Say it in the docs and in `pod check`'s report**, in one plain line, so nobody mistakes a file-built site's review keys for the newsroom's.

The risk that remains: a file-only site can publish something nobody really reviewed, and its files will say otherwise. For Ryan's own small sites that is acceptable. For any site with more than one writer or with agents writing unattended, the default should be a newsroom.

---

## PART 4. Reconciling and deciding

### 7. DataParade's codebase newsroom (DATAP-911)

DATAP-911 [V, Jira] is the epic for a daily newsroom per codebase: DataParade supplies facts in four source tiers, Papyrus supplies the newsroom, and editor confirmations flow back as knowledge-base answers.

Its file layout, as the brief names it, maps cleanly:

| DATAP-911 | In this design |
|---|---|
| `.dataparade/newsletter/` | A typed pod: add the two context files. It has no `web/` folder, so it is private (section 8, item 3). That matches the epic's "customer code" risk. |
| `evidence/` | Reference notes. The source tier is one declared key (`sourceTier: 1`). Git events cite the commit as the Reference's address. |
| `issues/` | One Story note per issue (the site's issue type), plus one Announcement note and its Delivery notes. |
| "Each fact has a tier that controls how it may be stated" | Guideline files, `kind: writing`, `severity: error`: "a tier 3 claim is always attributed". The literal part is checkable offline. |
| Daily feed into a Papyrus newsroom | `papyrus pod load`, run each day (question 5: yes). |
| Editor confirmations back to DataParade | Outside this design. It is DataParade's answer path, not a sync back into the pod. |

Nothing in DataParade needs a model of its own for issues or sends.

### 8. The 14 open questions, answered

In the order suggested.

**First: Announcement.** Decided above. Two records, attempts inside a Delivery, corrections as new Deliveries, manual mode in pods.

**Second: lifecycle in a pod.** Decided above. Same field names; stamps are claims; Kanbus stays the board.

**Third: private by default for pods with no site.** A pod is private unless a site folder (`web/` with its settings) names it. For a private pod, `pod build` refuses, and `pod load` loads every note as private newsroom data at its `stage`; a load of a private pod never publishes. In a site pod, a note whose front matter says `stage: published` is published after it loads, through the site's normal publish step (PPY-50a7f5, 2026-11-18): every publish rule still applies (checklist, `publishRequiresRating`, a person's approval where the site requires it), a refusal is reported for that note and never forced, and a note that does not say published stays unpublished. This replaces the pod standard's "a non-draft Story loads published": only `stage: published` publishes. *Default: yes.*

**Then Anth.us and the rest.**

| # | Question | Answer (default) |
|---|---|---|
| 1 | Is Anth.us file-built or a newsroom? | **Stays a cloud newsroom.** Its articles, the Engage form and the router need a backend, and announcements and review stamps now do too. Its knowledge-base repository (46 story folders) becomes a private typed pod that may feed the newsroom. The file-only path is proven on sites that are already file-built. |
| 2 | Where do permanent ids live? | **On the owner's own address.** The Papyrus id space only for a pile with no address yet. A private pod still needs a base; it uses the owner's address and the ids never have to resolve. |
| 3 | Public unless draft, or private unless published? | **For a site pod: public unless `draft: true`, or `stage: published` when the note has a stage. Drafts are never built.** For a pod with no site: private, always. |
| 4 | Is the Kanbus site file-built or a newsroom? | **File-built. Retire its CMS.** It has no need for review stamps or automatic sending. If it ever wants automatic announcements, that is the day it becomes a newsroom. |
| 5 | May a pod keep feeding a newsroom? | **Yes.** Once a record is edited in the newsroom, the newsroom owns it. The Anth.us knowledge base and the DataParade pod are the first two. |
| 6 | The name "pod", `papyrus pod ...` | Yes. |
| 7 | Keys keep Papyrus's spelling | Yes. The new keys follow suit: `announces`, `supersedes`, `dedupeKey`, `releaseAt`. |
| 8 | Ids are random UUIDs | Yes. An Announcement's once-only key is separate from its id. |
| 9 | `aliases` are other names; old addresses go in `redirects` | Yes. |
| 10 | Widen `cites` and `authored_by` to Stories | Yes. Add `announces` (Announcement to Story) and `supersedes` (Delivery to Delivery) in the same change. |
| 11 | No copy of the ontology inside each pod | Yes. |
| 12 | First real load: the Pilobolus wiki | Yes. The Anth.us knowledge base second. |
| 13 | Docs sites join last | Yes. |
| 14 | Tactus-web | Treat as one more file-built site to convert once located. Still not found locally. |

### 9. Other decisions, each with a default

| Decision | Default |
|---|---|
| Reshape the X model before X goes live? | Yes. X stays off until the reshape is in and Ryan turns it on. No live rows exist, so nothing migrates. |
| Does a correction delete the old X post? | Yes, where the channel can delete. The deletion cost is recorded on the old Delivery. |
| One Announcement for X and email about the same Story? | Yes. One decision, one Delivery per channel. |
| Is an Announcement row written when no channel qualifies? | No. It is created with its first Delivery. |
| May a pod send automatically? | No. Manual mode only. |
| Guideline files replace the JSON guideline document? | Yes, as schema version 2, converted once per site. |
| A rating of 5 in a pod | Refused on load; listed as a candidate for a person. |
| Replay Git history as newsroom versions? | No. |
| Convert sent newsletter issues on Shipped and Distinctive? | Yes, once, by a command, with sends frozen for that window (already agreed for the Caducus move). |
| Newsroom name for the pair | "Announcement" for the decision. "Delivery" for a channel's version. Shown as one Announcement with a line per channel. |

### 10. Gherkin specs needed

Each line is one feature file. Scenarios are named, not written out.

**Announcement**

- *An announcement is decided once.* Same Story published twice makes one Announcement. A crash between the key and the first Delivery finishes on retry. A publish that qualifies on no channel leaves no row.
- *Approval and release.* Approval `none` releases at once. A hard gate waits. A newer Story version after approval returns it to waiting. Cancel before release. `releaseAt` in UTC; a past time releases now.
- *A Story shows where it was announced.* One line per Delivery, read through the relation, with no table listing.

**Delivery**

- *A retry is an attempt.* A failed attempt then a success is one Delivery with two entries. A pause or budget stop ends an attempt and the next try is the next attempt. Earlier entries never change.
- *A correction is a new Delivery.* It names the old one. The old one becomes `superseded`. On X the old post is deleted. A second live Delivery without `supersedes` is refused.
- *Channel rules.* X needs the floor rating; a later rating adds the X Delivery to the existing Announcement. No bar below three stars. Unrated and predicted never qualify.
- *Manual mode.* The text is drafted and checked; a person records the address; the attempt names the person.
- *Dry run and withdraw.* Built and not sent, cost 0. Withdraw deletes where possible and records who.
- *No text in the catalog.* A Delivery row holds no post text, HTML or Markus; the files are in S3.
- *Fan-out counts.* An email Delivery's counts match Caducus's records; a reader on two lists gets one message.

**Conversion**

- *Newsletter issues become Announcements and Deliveries.* A sent issue keeps its dates, counts, approver and archive address. Running the command twice changes nothing.
- *Kept alert rows still prevent a second alert* after conversion.
- *The X model has no round suffix*; old dry-run rows are gone.

**Guidelines**

- *A guideline folder is valid or refused.* Missing kind, unknown key, nested value, bad severity.
- *Offline check.* A listed word is found with no network. A judgement rule prints "not checked offline". Exit status reflects `error` findings only.
- *Save and export round trip.* Exported files are byte-identical to what was saved. A stale version is refused.
- *Layering.* A section adds and never loosens. `channel/x` rules reach the X drafter.
- *Derived checks.* Each `error` or `warn` file derives one check; a hand-written check is never touched.
- *One-time conversion* of each site's JSON document to files, with the resolved result unchanged.

**Lifecycle**

- *Pod lifecycle keys.* `stage` values are checked. `stage` and `draft` together are refused. A stale `reviewedHash` is reported.
- *Lossless load.* Every lifecycle key lands on the same-named Item field; the commit is recorded; loading twice writes nothing.
- *A claim stays a claim.* A pod review shows as "not verified" and does not satisfy a hard gate, a required step or `publishRequiresRating`.
- *A pod never grants five stars.*
- *A pod with no site is private.* `pod build` refuses. A load publishes nothing.
- *Announcement and Delivery notes.* They load as history and send nothing. A changed earlier attempt line fails the check. Neither is ever a page.

### 11. Proposed epic and slices (not filed)

**Epic: One Announcement, many Deliveries; guidelines and lifecycle the same in pod and cloud.**
Depends on the pod epic (profile, `pod check`, `pod load`) and on the Caducus move (PPY-824c14). Done when every slice is closed, the three old models are gone, and the p.apyr.us page is published.

| # | Slice | Notes |
|---|---|---|
| 1 | Announcement and Delivery records, indexes, the `announces` and `supersedes` relation types | Cloud only. No sender wired. |
| 2 | Attempt log and attempt event ids | Papyrus only: no Caducus change (Caducus 0.3.0 treats an event id as an opaque string). Remove the round suffix. |
| 3 | X on the new records | Rewire eligibility, drafting, budget guard, withdraw. X stays off. Delete the old row shape in the same change. |
| 4 | Corrections | New Delivery with `supersedes`; delete the old post on X. |
| 5a | Editing window, versions, pinned human edits, lock time | Delivery text versions; `owner: human, pinned`; candidate versions; lock and unlock. |
| 5b | Channel guidelines and the draft editor | `channel/x`, `channel/linkedin`, `channel/email` scopes; channel preview in newsroom; CLI parity. |
| 5c | Newsletter assembly | Slots fill during the week; editors curate; pinned slots survive refills. |
| 5 | Manual mode | Draft, copy, record the address. Newsroom and CLI from the one operation table. |
| 6 | Email alerts on the new records | Replace `ALERT#` rows and the alert issue; convert the kept rows. |
| 7 | Roundup issues on the new records | Replace `ISSUE#` and `ROUNDUP#` rows; move rendered text to S3; convert sent issues on Shipped and Distinctive. |
| 8 | Story drawer and Announcements list | One Announcement, one line per Delivery. Marks and words for state, never colour alone. |
| 9 | Guideline file form and `guidelines check` | Offline checker; `pod check` validates guideline files. |
| 10 | Guideline files in the cloud | Schema version 2; `save --dir`, `export --dir`; convert each site once; remove the JSON reader. |
| 11 | Lifecycle keys in the pod profile | `stage`, `rating`, review keys; the `stage`/`draft` rule; context generator. |
| 12 | Lifecycle on load | Same-named fields; claims shown as not verified; five-star candidates; private pods never publish. |
| 13 | Announcement and Delivery notes in a pod | Types, the append-only attempts check, load as history. |
| 14 | Anth.us knowledge base as a private pod | Type the finished articles; first feed into the Anth.us newsroom after the Pilobolus load. |
| 15 | Document it on p.apyr.us | Feature page: the two records, corrections, manual mode, guideline files, what a pod's review does and does not prove. |

Order: 1, 2, 3 first (X is off, so this is the cheapest moment). 9 and 11 can run beside them. 6 and 7 follow the Caducus move. 14 and 15 last.

### 12. What I could not verify

- **PPY-09ee86 on the board.** `kbs show PPY-09ee86` answered "not found" in the local Papyrus checkout, which is 583 commits behind `origin/develop`. I did not open the issue files directly, because the board forbids that. I read the epic's design and status from `docs/announcements.md` and `docs/plans/scheduled-publishing-and-announcements.md` on `origin/develop` instead.
- **`.dataparade/newsletter/evidence` and `issues`.** I found no such folder in any DataParade checkout, worktree or remote branch name, and no Jira issue under DATAP-911 mentions the path. The mapping in section 7 rests on the brief's description of it. Check it against the real files before slice work starts.
- **Live row counts.** I made no AWS calls, so "no live X rows" and "sent issues exist on Shipped and Distinctive" come from the docs and memory notes, not from the tables.
- **Severity values.** `error` and `warn` are in the editorial checks today. `guidance` is my addition.

---

## 13. Always-on agent review

Date: 2026-11-16. Requested by Ryan. Review only: no code or board change. Compared against the article "Building always-on agents" (claude.com/resources/articles/building-always-on-agents), this design including sections 2.1 and 2.2, and the filed epic PPY-a36492 (19 tasks, read with `kbs` in the `board-announcements` worktree).

How I read the article: through a fetch tool that returns a paraphrased outline, not the page word for word. The five ideas below are its structure; I have not quoted it.

### 13.1 What the article says, in one paragraph

An always-on agent is mostly asleep. Each wake-up is a short run: take an event, do the work, save what happened, sleep. Five parts make that safe. An **inbox**: a durable list of events, de-duplicated by the source's own id, with one worker at a time, so a crash loses nothing and two runs never compete. **Timers**: follow-ups and schedules kept apart from the inbox; when one is due it becomes an inbox event and does nothing else. **Memory**: a durable store of only what cannot be looked up again, including a record of what was already said. **Permissions**: each action is allowed, blocked, or waits for a person; the agent never holds the secret; a waiting request is saved and the worker moves on. **Outbox**: a run ends by sending, by sending nothing, or by asking; use a real outbox when pacing or recovery matters; start quiet.

### 13.2 How it maps onto Papyrus

| Article | Papyrus equivalent | Already in the design? |
|---|---|---|
| Inbox with de-duplication | The Announcement's `dedupeKey`, created with a condition | **Yes** for the decision. **No** for the trigger that leads to it (13.3, change A). |
| One worker per inbox | X has one queue consumer per account, so a budget check and a charge cannot race [V] | **Partly.** True for X sending. Not stated for other channels or for edits to a draft (changes B, C). |
| Events that arrive mid-run: queue, fold or restart | A person edits while the machine redrafts; Stories qualify while an issue is refilled | **Partly.** Pinned blocks cover overwriting. Stale saves and bursts are not covered (changes C, D). |
| Timers become events and do nothing else | `releaseAt`; the newsletter's start-send re-checks everything when it fires [V] | **Partly.** Lock time, soft-review silence and "try again after the rate limit resets" are timers with no named field (change E). |
| Memory: only what cannot be looked up; pointers otherwise | A Delivery points at a Story version and records the guideline id, version and hash it was written under | **Yes.** |
| Memory: what was already said | Sent Deliveries on an account are exactly this record | **Stored, not used.** The drafter does not read them (change F). |
| Memory: corrections from the person | An editor removing a newsletter item, or rewriting a draft | **Partly.** Ryan's 12 November rule (a removed item is never re-added) is not a field yet (change G). Learning from rewrites is a follow-up (13.5). |
| Task progress a new run can resume | Delivery state plus the attempt log | **Yes**, with one gap: an attempt that started and never reported (change H). |
| Allow, block or wait, per action | Review requests (flag, soft, hard); `announcementReview`; guidelines already answer `human_required` to an agent [V] | **Partly.** There is no list of which Delivery operations an agent may do (change I). |
| Agent never holds the secret | X keys in SSM, write-only, never returned by any route [V] | **Yes.** |
| A waiting approval is saved; the worker is not held | A review request waits; the answer arrives later | **Partly.** "Lock" in 2.1 can be read as something held. Approval is recorded on the Announcement, but 2.2 lets each channel differ (changes J, K). |
| Automatic checks first, people for what matters | Draft checks block a bad post under every policy [V] | **Partly.** A blocked draft is a dead end that tells nobody (change L). |
| Deep checks happen in the run, not at the door | The post may contain no link, mention or tag absent from the Story [V] | **Yes** for posts. Newsletter blurbs drawn from outside sources need the same rule (change G). |
| Outbox with pacing and recovery | Delivery is the outbox; Caducus is the dispatcher | **Yes.** This is the design's core. |
| A run may end by sending nothing | A publish that qualifies nowhere leaves no row | **Yes**, but nobody can ask why (change M). |
| Start quiet; tune volume with measurement | Five-star floor on Machines on Machines; budget | **Quiet, yes. Measured, no** (13.5). |

### 13.3 What I would change

Each has a default. None adds a cap, a fallback or a second system.

**A. Triggers must be durable.** Today a publish tells the newsletter and notifications functions with a short best-effort call, and every error is swallowed so a publish is never slowed [V]. That keeps publishing fast and can lose the event. The Announcement's once-only key cannot help if the event never arrives. *Change:* the two facts that start an Announcement, "this Story's page is live" and "this Story's rating changed", reach one announcement worker from the change stream of the records that already record them. The best-effort call is deleted. Publishing stays fast because it only writes its own record. *Default: yes. New task, placed before the X rewire.* [I: which record marks "page live" is chosen in the task.]

**B. One worker per channel account, for every channel.** State as a rule what X already does: all attempts for one channel account pass through one consumer. *Default: yes; part of the attempt-log task (a570e8).*

**C. A Delivery save names the version it replaces.** Guidelines and image profiles already refuse a stale save [V]. Delivery text needs the same, or a machine redraft and a person's edit made in the same minute silently lose one. A refused machine redraft is simply dropped: the person's version is newer. *Default: yes; in the editing-window task (e8ec54).*

**D. Bursts are folded.** Ten Stories qualifying in a minute should refill an issue once, not ten times. Use the standing rule: downstream work is coalesced in a window, shorter after a person acts. For broadcast channels, spacing between posts on one account is an owner setting in the channel's settings, empty by default. *Default: yes; coalescing in the assembly task (cb3cc9), spacing in the review-policy task (97c0f2).*

**E. Every wait is a named time on the record.** Add to Delivery: `lockAt` (explicit, filled from the per-kind and per-channel setting when the Delivery is created; equal to `releaseAt` when there is no separate lock), `nextAttemptAt` with `waitingFor` (`rate limit`, `budget cycle`, `release`), and one sparse `dueAt` that is the earliest of them. One index on `dueAt` gives two things: the schedule knows what to wake, and the list can show "Overdue" for anything due and untouched. When a time fires, it only raises an event; the worker re-reads the record and re-checks everything, as start-send does today. Soft review needs no time of its own: silence until `lockAt` is the rule. *Default: yes; fields in the records task (3792dd).*

**F. The drafter reads what the account already said.** Before drafting, read that account's recent sent Deliveries through the account index, so posts do not repeat a hook or phrase, and an issue does not repeat last week's blurb. It is a pointer read, not a new store. How far back is not a number we pick: it reads back to the previous Delivery about the same Stories or concepts, or the last issue for a newsletter. *Default: yes; in the channel-guidelines task (9c6b89).*

**G. A removed slot is remembered, and blurbs obey the link rule.** A newsletter slot an editor removes stays as a record (`removed`, by whom, when). A refill never adds that Story back. Any link in a slot must point at the site's own Story page or appear in that Story. *Default: yes; in the assembly task (cb3cc9).*

**H. An attempt is written before the call.** An attempt entry opens as `started` and closes as `sent`, `refused` or `unknown`. An entry left open or `unknown` is settled by Caducus's reconcile step (for X, the read of recent posts) and shows in the list as "Outcome unknown" until then. No timeout decides it. *Default: yes; in a570e8.*

**I. A plain table of who may do what.** One table in the operation definitions, by actor kind:

| Operation | Agent | Person |
|---|---|---|
| Draft, add a candidate, edit an unpinned block | Allowed | Allowed |
| Change or unpin a block a person pinned | Blocked | Allowed |
| Release under `none` | Allowed (the policy did it) | Allowed |
| Release under `soft` or `hard`; unlock after lock | Answers `human_required` | Allowed |
| Correct (a new public text) | Follows that Delivery's review value | Allowed |
| Withdraw (deletes a public post) | Allowed only when a Story is retired; otherwise `human_required` | Allowed |
| Change review policy, budget, account | Blocked | Admin |

*Default: yes; in the review-policy task (97c0f2), which should then come before the editing-window task.*

**J. Approval lives on the Delivery.** Section 2 put `approval`, `approvedBy` and `approvedAt` on the Announcement. Section 2.2 lets LinkedIn be `hard` while X is `none`. Both cannot be true. *Change:* each Delivery carries `approval`, `approvalPolicy` (where the value came from), `approvedVersion`, `approvedBy`, `approvedAt`. The Announcement keeps only the decision and `releaseAt`. An approval names one version; a later version is not approved. This corrects my own section 2. *Default: yes; in 3792dd, before anything is built on the old shape.*

**K. A lock is a fact, not something held.** Write it as `lockedAt` and `lockedVersion` on the Delivery. Unlock is an event from a person. Nothing expires and nothing waits holding a lease, so a person who never answers blocks only that one Delivery. *Default: yes; wording and fields in e8ec54.*

**L. A blocked draft asks for help once.** "Blocked: check failed" raises one review request (a flag; nothing waits) in the editor's inbox, grouped per Announcement, not per channel. The machine redrafts only when an input changes (the Story, the guidelines), never in a loop. *Default: yes; in the X task (efd06c) and the list task (e4ae3a).*

**M. "Why was this not announced?" is a question, not a row.** `papyrus announcements explain --story X` reads the eligibility rules and answers on demand. No row is written for things that did not happen. *Default: yes; small addition to e4ae3a.*

### 13.4 Slices and order

| Change | Task |
|---|---|
| J, E, and the `started`/`unknown` outcomes | 3792dd (records). Do these first: they are field changes and cost nothing now. |
| B, H | a570e8 (attempt log) |
| A | **New task: durable triggers for announcements.** After a570e8, before efd06c. |
| L | efd06c (X on the new records) |
| I, D (spacing) | 97c0f2 (review policy). **Move before e8ec54.** |
| C, K | e8ec54 (editing window and lock) |
| F | 9c6b89 (channel guidelines and editor) |
| D (coalescing), G | cb3cc9 (newsletter assembly) |
| M, overdue and "Outcome unknown" marks | e4ae3a (drawer and list) |

Revised order for the first half: 3792dd, a570e8, durable triggers, efd06c, 97c0f2, e8ec54, 9c6b89. The rest is unchanged. One new task; 20 in all.

New Gherkin features: a publish whose first trigger fails is still announced once; two saves against one version, the second refused; ten Stories in a burst, one refill; a removed slot is never refilled; an attempt left `started` is settled without a second post; an agent asking to release under `hard` gets `human_required`; a channel with `hard` waits while another with `none` goes; a due Delivery with no attempt shows "Overdue".

### 13.5 Follow-ups, outside this epic

- **Learn from edits.** When a Delivery is sent with human changes, the difference between the machine draft and what was sent is already stored as versions. A later task proposes guideline changes from those differences, for an admin to accept. It runs once per sent Delivery, not as a sweep. *Default: file after the epic.*
- **Measure before getting louder.** Record per-Delivery outcomes (visits by the campaign tag already on every link; email counts) and review them before lowering any channel's bar. *Default: file with the A/B work.*

### 13.6 What I would not take from the article

- **A new inbox table per user.** Change streams, the once-only key and Caducus's queue already give a durable, de-duplicated, single-worker path. A second list would be a second system.
- **A scheduler that polls on a fixed interval.** One-time schedules that raise an event are already the pattern here and are exact.
- **Reviewing past sessions on a schedule to tidy memory.** That is a corpus walk on a timer. The same benefit comes from the per-send follow-up above.
- **Agent memory as files.** The records are the memory. The Vault-LD assessment already decided this.
- **A simple send tool with no outbox.** The article says a real outbox is needed when pacing or recovery matters. Both matter for public posts and paid channels.
