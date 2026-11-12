# The Story procedure

One definition of how a Story moves through the newsroom. The command line reads it (`papyrus stories next`, and the reminders printed after a write), and the context pack will read it later. It lives in `src/papyrus_content/newsroom_process.py` as an ordered list of steps. It applies to people and agents alike. It is also the **template** of every Story's editorial checklist, which records what was and was not done ([the checklist](#the-checklist)).

## The sequence

| Step | Stage | Who | Command | Status |
| --- | --- | --- | --- | --- |
| choose | idea | Editor agent or a person | `papyrus ideas select --section SECTION` | live |
| direction | assignment | Editor | `papyrus stories assign-research --story LINEAGE --direction-file direction.md` | live |
| research | reporting | Reporter | `papyrus assignments research-multi ASSIGNMENT_ID` | live |
| outline | reporting | Editor agent | `papyrus stories outline --story LINEAGE` | live |
| draft | copywriting | Copywriter | `papyrus stories draft --story LINEAGE` | live |
| fact_check | copywriting | Fact-check agent | none yet (PPY-719a02) | not built |
| copy_edit | copywriting | Copywriter with Humanus | `papyrus editorial check-version --item VERSION_ID` | live |
| editor_review | copywriting | Editor agent | none (needs the `editor_review.tac` procedure, which no site has on) | off |
| review_people | copywriting | Editor or reviewing agent | `papyrus stories step --story LINEAGE --step review_people --state done --note FINDINGS` | live, by hand |
| review_reader_agents | copywriting | Editor or reviewing agent | the same, with `--step review_reader_agents` | live, by hand |
| review_search | copywriting | Editor or reviewing agent | the same, with `--step review_search` | live, by hand |
| review_social | copywriting | Editor or reviewing agent | the same, with `--step review_social` | live, by hand |
| concepts | copywriting | Editor or reviewing agent | `papyrus stories link-concept --story LINEAGE --concept NAME --note WHY`, then `papyrus stories step --story LINEAGE --step concepts --state done --note FINDINGS` | live, by hand, required |
| related_content | copywriting | Editor or reviewing agent | `papyrus stories suggest-links --story LINEAGE`, link the good ones with `stories link-story`, then `--step related_content --state done --note FINDINGS` | live, by hand, required |
| illustration | illustration | Editor, or an agent following the [figures skill](../.agents/skills/figures/SKILL.md) | `papyrus stories save-version --story LINEAGE --body-file draft.md --images ./pictures` (an approved cover); or a person records an exception with `papyrus stories step --story LINEAGE --step illustration --state skipped --reason WHY` | live, by evidence, required for the Story types that need a cover |
| typesetting | typesetting | Editor | none yet | not built, optional |
| publish | published | A person | `papyrus ops content publish --id ITEM_ID` | live |

The `concepts` and `related_content` steps come after the four review lenses and before publishing (template version 4). Both are required like the reviews: done with a findings note (the Concepts added and those left out; what was linked and what was left out and why), skipped with a reason, or not applicable with a reason. No Story command creates a Concept: make a missing one from a Reference (`references link --reference ID --concept NAME --create`) or in the newsroom.

The `illustration` step comes after `related_content` and before publishing (template version 5). See [The Illustration step](#the-illustration-step). The illustration and typesetting stages are described in [story-illustration-typesetting.md](story-illustration-typesetting.md).

## The Illustration step

Added in template version 5 after a Story was published with no cover while its checklist read 13/13. It is **live and required** for the Story types that need a cover, and it is a publish gate like the review steps.

- **Which types.** The design-system setting `illustrationRequiredTypes` (a list of Story types; set it in the design system's `settings.json`, see [figures.md](figures.md)). Unset, it is `["article"]`, so articles need a cover and posts and other types do not. A Story with no type yet counts as required until a type is chosen. For a type the site does not list, the step reads `not_applicable` in `stories next`, has no checklist item, and does not block publishing.
- **Done only by evidence, never by hand.** The step is done when the current version of the Story has a cover that is an approved stored asset: front matter `image` (or `cover`) names a picture that is a `MediaAsset` of that version (matched by `srcPath`; a remote address does not count), and a person approved it. The approval is an existing record, not a new one: the stock cover record `coverImage` (its `pickedBy` and `pickedAt`, written by the newsroom's Cover image) for that picture, or a figure's credit line `Approved by NAME` on the body's `::image{}` of that picture (a figure's `approved_by` from `papyrus figures render`; the `<name>` placeholder does not count). The checklist marks the step done by itself once that is true, as "Automatically, from the approved cover". `stories step --step illustration --state done` is accepted only when those records prove it, and otherwise refused with what is missing.
- **Light and dark.** Where the site requires dark figures (`requireDarkFigures`), a figure cover also needs a stored dark picture (`srcDark` on its image, or front matter `imageDark`/`coverDark`). A dark picture that is named must be a stored asset whether required or not. A stock photograph has no dark twin and is never asked for one. If the setting cannot be read, a light-only figure reads `unknown` and does not pass.
- **The exception.** A person can instead skip the step, or mark it not applicable, with a reason: `papyrus stories step --story LINEAGE --step illustration --state skipped --reason "WHY"`. The reason is recorded with who and when, like any skip. An agent cannot record this exception (it asks an editor). An exception stands for the Story and is not tied to a version.
- **Staleness.** The step is versioned: a `done` recorded against an earlier version reads `stale` in `stories next` once the cover is gone from the current version.
- **The gate.** Publishing (a first publication or a revision of a published Story) refuses a Story whose step is unresolved: it checks the version being published, so a step recorded done before the cover was removed does not pass. The error names the step and says how to resolve it (add an approved cover with `papyrus stories save-version ... --images`, or record the exception with `stories step`).
- **Published history is left alone.** A Story that was published before this step existed gets no item for it, `stories next` does not list it as remaining, and `stories checklist-backfill` does not add it. A revision of that Story (or a republish) is held to the step like any draft: it publishes once the step is closed by a cover or by an exception.
- **Existing drafts.** The next change to an unpublished Story adds the item (open, or done where the cover already proves it), exactly as for every earlier template step; `papyrus stories checklist-backfill` does the same for all of them at once and is safe to run again.

## Share a review link

The `draft` and `copy_edit` steps carry one more duty: after each save, show the editor the console link of the exact version (the `console` row of `stories save-version`, or `papyrus links --story LINEAGE --version N`), before asking for approval to publish. It is a description, not a step: the template keys and `TEMPLATE_VERSION` are unchanged. See [console-links.md](console-links.md).

## Two decisions

- The outline comes after the research. The editor writes it once the reporter's packet exists, and saves it with `--outline` so the draft step can tell the outline from the draft.
- A skipped step needs a recorded reason, and an open required step blocks publishing (the checklist, below). This replaces the earlier rule that a skipped step only warned. There are no new stages, and human review is never a stage: a person comes in through a review request ([review requests](review-requests.md)).
- The four review steps are the four audience lenses, one step each: human readers, AI agents that read the page for a person, search crawlers, and social previews (link cards). They come after the copy edit and before publishing, and they are required. No record proves them yet, so each is completed by hand with a short findings note. What each lens checks, and the final approval, are a later design (PPY-59c772df).

## The checklist

Every Story has one checklist, made from this template, so the record shows which steps happened, who did them and why any were skipped. It follows Kanbus: each live step of the template is a **sub-task** of the Story, stored as an `Item` of type `sub-task` in the same table as the Story (the newsroom's one issues table; there is no separate table). Steps that are off or not built have no sub-task, because they cannot be done; when one goes live it joins the checklist.

- **Fields of a sub-task Item.** `type` is `sub-task`; `parentLineageId` is the Story's lineage (the one attribute this added to `Item`); `lineageId` is `step-<story>-<key>`; `title` is the step's words; `status` is the state; `sortTitle` is the zero-padded step order; `versionCreatedBy` and `versionCreatedAt` are who and when; `changeReason` is the reason or findings note; `metadata.checklist` holds the step key, the template version, the command and that version's actor (kind and sign-in), reason, note and evidence reference. The tenant is stamped like any other Item. A sub-task has no stage, section or body.
- **Versions are the history.** Every change is a new version of the sub-task Item (the newest version is the step), so who changed it, when and why is never overwritten.
- **States.** `open`, `done`, `skipped` or `not_applicable`. A skipped or not-applicable step needs a reason, and a skip without one is refused. A review step needs a short findings note to be done. A person can reopen a step; an agent cannot.
- **One index, no scans.** The steps of a Story are one read of the Item index `itemsByParent` (`parentLineageId`, then `sortTitle`), made when a Story panel opens or a command needs them. The Story keeps a small summary (counts by state, and the required steps still open) on its current version's metadata (`checklist`), updated whenever a step changes, so a board card needs no extra query.
- **A sub-task is never a Story.** `sub-task` is a system Item type (with `wiki_page`, `doctrine` and `page`: `SYSTEM_ITEM_TYPES` in `content_item_lifecycle.py` and `lib/content-item-lifecycle.ts`), it has no stage so no board column or stage list reads it, it has no section so no section listing does, and it is never published: `publish_item` refuses it. The scans of the whole Item table that mean Stories (idea and duplicate logic, learning, the Reference-link plan, the backfills, the cross-story boilerplate check) leave sub-tasks out (`without_sub_tasks`).
- **Every way of making a Story makes its checklist.** `papyrus stories create` and the agent tool that wraps it (chat); every idea the idea pipeline files as an Item (`file_idea_item`); the monitor promotion, the editor's Create Story from a Reference and an approved story draft Proposal (all through `create_story_from_references`); an Assignment that mints a Story; and a Story an editor creates or saves in the console. Moving or changing a Story (picking an idea with `ideas select` is a move) brings its checklist up to date. The older `papyrus_newsroom` library writes Items directly and is not hooked: a Story it makes gets its checklist from its first write through any path above, from the sweep, or at publish time.
- **A change brings the checklist up to date once.** A step the template gained since is added as `open` (a published Story gets none: its checklist is a record), and an open step whose evidence now exists is marked done. Nothing runs on a schedule over all Stories.
- **Evidence marks steps done.** The same facts `papyrus stories next` reads decide it: a research packet marks research, the outline marker marks the outline, a version newer than the outline marks the draft, a finished editorial check without an error-level violation marks the copy edit, and so on. The step is shown as "Automatically, from the research packet" (or the outline, the draft version, the copy-edit check, the research direction, the Story's stage), and the evidence reference names the record. A step a person reopened is not marked done again by evidence. If a later edit makes the evidence stale the step stays done, except for the versioned steps (the copy edit and the four review lenses), which `stories next` shows as `stale` (see Staleness under Reading `papyrus stories next`).
- **Cloud roles.** The router (which files ideas) and the research worker (which writes research packets) hold grants to create Items and read the index, so an idea and a research packet get their checklist straight away. The worker has no `updateItem`, so its steps are created as new versions and the card summary is refreshed at the next change by an editor or the CLI.
- **Imported Stories.** A Story imported from Markdown (the Markdown import) gets a checklist with every step but publishing marked `not_applicable`, reason `imported from <source>`, so an import is not blocked. Wiki pages are not Stories (a system type) and have no checklist.
- **Notes.** Any step, in any state, can take notes for future context: an append-only log of who (a person or an agent, by name), when and the text, newest last. A note is one more version of the step's sub-task Item (created, never updated, so versions still say who and when), carrying the log in `metadata.checklist.notes` and leaving the state entry, reason and findings untouched. Versions fit Kanbus's model (an issue's history is its versions) and need no table; the log rides on each version so the newest read has everything. Nothing edits or deletes a note; a correction is a new note. `papyrus stories step --story L --step KEY --note "text"` (no `--state`) adds one. Agents see the notes in `papyrus stories next` (a `note` line each, and `--json`) and in the Story's context pack, under the procedure layer. The panel shows them under each step, the newest three open and older ones folded, and an Add note button on every row.
- **Marking a step by hand:** `papyrus stories step --story LINEAGE --step KEY --state done|skipped|not_applicable|open --reason TEXT --note TEXT [--agent NAME]`. The console's buttons call the `setStoryStep` mutation, which stamps the signed-in person and writes the sub-task Item; an agent acting through that session is recorded as the agent.
- **Publishing enforces it.** Publishing refuses while any required step (live and not optional, except publishing itself) is `open`. Every required step must be done, skipped with a reason, or not applicable with a reason. A Story with no checklist yet gets one first, with steps done where evidence exists, so an older Story cannot slip through. The error names each open step and the command that closes it. Publishing marks the publish step done.
- **On the board.** A Story card shows progress, for example `4/9 · 2 skipped` (done and not-applicable steps over all steps, then the skipped count). The Story panel shows the Story's own content first (title, fields, text) and the checklist after it, toward the bottom: Kanbus's own sub-task cards (`type: "sub-task"`, `parent` the Story), each with its state as a word and an icon, who changed it and when, and the reason or findings. Choosing a step shows buttons: mark done (a review step asks for what it found), skip, not applicable (each asks for a reason), or reopen. The commands an agent runs are not shown to people; they stay in the CLI output and the agent's context pack.
- **Existing Stories** get their checklists from one named sweep: `papyrus stories checklist-backfill --dry-run` prints the counts and writes nothing; without `--dry-run` it creates the checklists, published Stories included, marks steps done where evidence exists and leaves the rest open (so the four review steps start open). It pages by stage and is safe to run again.
- **Changing the template** means editing `STEPS` and raising `TEMPLATE_VERSION` in `newsroom_process.py`. Each sub-task records the version it came from.

## Reading `papyrus stories next`

`papyrus stories next --story LINEAGE` is read only and gives **one answer** about what remains. The Story's stored checklist is the record, so it decides the state of every step that has a checklist item; the records (research packet, outline, draft, copy-edit check) only add a `hint` and never contradict the state. Tab-separated lines, in this order:

- `status STATUS N TEXT`: `complete` (nothing remains), `ready` (only publishing is left), `blocked` (a required step is still open, which is what blocks publishing) or `stale` (nothing is open, but recorded steps need doing again for this version). `N` is how many `remaining` lines follow.
- one `step` line per step: key, state, status, stage, role, title. The state is `done`, `skipped`, `not_applicable`, `not_done`, `stale` or `unknown`. For a step with a checklist item it is that item's state (an `open` item reads `not_done`); a step with no item yet (a new template step, or no checklist yet) falls back to the records. Unknown is honest: a step that is not built is never reported as done.
- one `version` line per checklist item: the Story version it was recorded against, how we know (`recorded`, or `inferred from the time it was recorded` for an item written before versions were tracked), and `current` or `STALE: recorded against vN, story is now vM`.
- `hint KEY TEXT`, only where the records differ from the answer: the records show a step done that the checklist still has open; or the copy-edit check does not show for the current version either.
- the stored checklist: an `item` line per checklist item (key, stored state, title, actor, time, and the reason, note or evidence; this is the raw record, so a stale step shows `done` here and `stale` on its `step` line), a `note` line per note, and `checklist progress` such as `4/9 · 2 skipped`. Stale steps are not counted as answered and the line ends `· N stale`, so `13/13` means nothing remains. A Story with no checklist yet says so. `--json` adds `checklist`, `progress`, `currentVersion`, `status`, `remaining`, `blocking` and `stale`, and each step carries `evidence`, `source`, `recordedVersion`, `recordedBasis`, `freshness` and `hint`.
- one `remaining` line per live, required step that is not done, skipped or not applicable, in template order with publishing last (key, `open` or `stale`, title, command). This is the single list of what is left.
- `next`: the first `remaining` step. A step that is off or not built is never next. A Story that is spiked, held or published has none.
- `skipped` lists steps before the Story's current stage that the checklist still has open. Unknown, not built and optional steps are never listed.

### Staleness

A step marked `versioned` in `STEPS` depends on the Story's text: the copy edit and the four review lenses. When such a step is recorded `done`, the number of the Story version it was recorded against is stored with the change (`storyVersion` in the item's entry). Once the Story has a different current version, that `done` reads `stale`: it still remains, and recording it again (`papyrus stories step ... --state done --note ...`) records it against the current version. A copy-edit item marked automatically from the check is re-marked for the new version when the check of that version passes. `skipped` and `not_applicable` answers are decisions with a reason, not findings about a text, so they never go stale. `concepts`, `related_content` and the evidence steps (choose, direction, research, outline, draft, publish) belong to the Story's lineage or to an earlier stage and are not tied to a version, though their `version` line still says which version they were recorded against. An item written before versions were tracked is placed by its time among the Story's version times. Staleness is shown, and listed under `remaining`; it does not change the publish gate, which still refuses only while a required step is open.

How each step reads its record:

- choose is done when the Story is past the idea stage.
- direction is done when an Assignment on the Story has a direction (or instructions).
- research is done when an Assignment on the Story has a research packet.
- outline is done when the Story's current version carries the outline marker.
- draft is done when the current version number is above the outline's version number; with no outline, when the body is not empty and the Story is at copywriting or later.
- copy_edit is done when the stored editorial check of the current version has finished and has no error-level violation.
- editor_review is done when the stored review is for the current version and approves it.
- illustration is done when the current version has an approved, stored cover (see [The Illustration step](#the-illustration-step)); not applicable for a Story type the site does not list.
- publish is done when the Story is published.

`papyrus stories next` also prints one `lens` line for each of the four review steps (people, AI reader agents, search, social previews) that is not done or is stale, with its audience. Those steps and their checks are defined in [four-lens-review.md](four-lens-review.md).

## Reminders on writes

After a successful write (never on `--dry-run`), the checklist is brought up to date once (see above), and `stories create`, `stories move`, `stories save-version`, `stories link-reference`, `stories assign-research`, `assignments research-multi` and `assignments process-proposals` (when the Assignment is on a Story) print the `next` and `skipped` lines. With `--json`, the two assignment commands add `next` to their JSON. A failure computing the reminder prints one line to stderr and never changes the result of the write. `stories move` to a later stage also prints a warning on stderr naming each step skipped before that stage, and still moves; the reason is recorded on the checklist, and publishing is where an open required step stops a Story.

## The outline and the draft

`papyrus stories outline --story <lineage>` and `papyrus stories draft --story <lineage>` each make one model call from the agent's [context pack](newsroom-context-packs.md) and save a new version, so nothing earlier is lost. `--dry-run` calls the model and saves nothing. Neither publishes.

The draft moves a Story to copywriting if it was earlier, marks the References it cites and runs the check every save runs. A draft that cites a key it was not given, or cites nothing when the Story has References, is refused and saves nothing. Whether its claims are true of their sources is the fact check that follows, which is not built yet.

A body with `[@key]` markers and no `::citations{}` line is flagged by the review check A5 (a warning, to be mentioned in the review step's note), naming the markers; the page appends the bibliography so no marker links to a missing anchor ([markus markup](markus-content-markup.md#the-bibliography)). A marker whose key is not among the Story's entries is flagged the same way and is refused when the Story is saved.

Every pack also says where the Story is in this procedure, so an agent knows what came before it and what comes after, whatever started it.


## A site's own procedure

The list above is the default. A site saves its own with `papyrus guidelines save --kind procedure --file procedure.yml --reason "..." --expected-current-version-id none` (or `item-editorial-doctrine-procedure-v1` to replace a saved one). The document is `schemaVersion: 1` and `steps`, the whole ordered list, which must end with `publish`:

```yaml
schemaVersion: 1
steps:
  - key: choose
  - key: draft
    title: Write the piece
  - key: label_check          # a step of the site's own: it needs a title and a stage
    stage: copywriting
    title: Check the satire label
    role: Editor
    note: Confirm the label is on the page.
    optional: false
  - key: publish
```

- A **built-in step** (a key from the table above) keeps its status, its stage and the checks that decide whether it is done. The entry may change only its words (`title`, `role`, `command`, `note`) and `optional`. A built-in step left out of the list is not part of the site's procedure, and has no checklist item.
- A **step of the site's own** has a new key (lowercase letters, digits and underscores), a `title` and a `stage`, and may carry `role`, `command`, `note`, `optional` and `versioned`. No record proves it, so it is done by hand: marking it done needs a short findings note, exactly like a review step, and a versioned one goes stale when the Story changes.
- The Story's checklist, the reminders after a write, `papyrus stories next`, the process layer of an agent's context and the publish rule (publishing refuses while a required step is open) all follow the site's list. If the site's document cannot be read, nothing guesses: publishing is refused and a reminder is not computed, each saying why. A role that cannot read the site's documents (the monitoring router that files ideas) files no checklist; the idea gets its checklist, from the site's procedure, at its next change by a role that can.
- A site that has saved nothing gets the default list. The built-in steps' checks stay in code (they are facts about the records); only the list, the order and the words belong to the site. Code: `newsroom_process.procedure_of`, `Procedure`, `procedure_from_document`.
