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
| illustration | illustration | Editor | none yet | not built, optional |
| typesetting | typesetting | Editor | none yet | not built, optional |
| publish | published | A person | `papyrus ops content publish --id ITEM_ID` | live |

The `concepts` and `related_content` steps come after the four review lenses and before publishing (template version 4). Both are required like the reviews: done with a findings note (the Concepts added and those left out; what was linked and what was left out and why), skipped with a reason, or not applicable with a reason. No Story command creates a Concept: make a missing one from a Reference (`references link --reference ID --concept NAME --create`) or in the newsroom.

The illustration and typesetting steps are described in [story-illustration-typesetting.md](story-illustration-typesetting.md).

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
- **Evidence marks steps done.** The same facts `papyrus stories next` reads decide it: a research packet marks research, the outline marker marks the outline, a version newer than the outline marks the draft, a finished editorial check without an error-level violation marks the copy edit, and so on. The step is shown as "Automatically, from the research packet" (or the outline, the draft version, the copy-edit check, the research direction, the Story's stage), and the evidence reference names the record. A step a person reopened is not marked done again by evidence. If a later edit makes the evidence stale the step stays done; judging what an edit changed, and reopening only the affected steps, is a later rule.
- **Cloud roles.** The router (which files ideas) and the research worker (which writes research packets) hold grants to create Items and read the index, so an idea and a research packet get their checklist straight away. The worker has no `updateItem`, so its steps are created as new versions and the card summary is refreshed at the next change by an editor or the CLI.
- **Imported Stories.** A Story imported from Markdown (the Markdown import) gets a checklist with every step but publishing marked `not_applicable`, reason `imported from <source>`, so an import is not blocked. Wiki pages are not Stories (a system type) and have no checklist.
- **Notes.** Any step, in any state, can take notes for future context: an append-only log of who (a person or an agent, by name), when and the text, newest last. A note is one more version of the step's sub-task Item (created, never updated, so versions still say who and when), carrying the log in `metadata.checklist.notes` and leaving the state entry, reason and findings untouched. Versions fit Kanbus's model (an issue's history is its versions) and need no table; the log rides on each version so the newest read has everything. Nothing edits or deletes a note; a correction is a new note. `papyrus stories step --story L --step KEY --note "text"` (no `--state`) adds one. Agents see the notes in `papyrus stories next` (a `note` line each, and `--json`) and in the Story's context pack, under the procedure layer. The panel shows them under each step, the newest three open and older ones folded, and an Add note button on every row.
- **Marking a step by hand:** `papyrus stories step --story LINEAGE --step KEY --state done|skipped|not_applicable|open --reason TEXT --note TEXT [--agent NAME]`. The console's buttons call the `setStoryStep` mutation, which stamps the signed-in person and writes the sub-task Item; an agent acting through that session is recorded as the agent.
- **Publishing enforces it.** Publishing refuses while any required step (live and not optional, except publishing itself) is `open`. Every required step must be done, skipped with a reason, or not applicable with a reason. A Story with no checklist yet gets one first, with steps done where evidence exists, so an older Story cannot slip through. The error names each open step and the command that closes it. Publishing marks the publish step done.
- **On the board.** A Story card shows progress, for example `4/9 · 2 skipped` (done and not-applicable steps over all steps, then the skipped count). The Story panel shows the Story's own content first (title, fields, text) and the checklist after it, toward the bottom: Kanbus's own sub-task cards (`type: "sub-task"`, `parent` the Story), each with its state as a word and an icon, who changed it and when, and the reason or findings. Choosing a step shows buttons: mark done (a review step asks for what it found), skip, not applicable (each asks for a reason), or reopen. The commands an agent runs are not shown to people; they stay in the CLI output and the agent's context pack.
- **Existing Stories** get their checklists from one named sweep: `papyrus stories checklist-backfill --dry-run` prints the counts and writes nothing; without `--dry-run` it creates the checklists, published Stories included, marks steps done where evidence exists and leaves the rest open (so the four review steps start open). It pages by stage and is safe to run again.
- **Changing the template** means editing `STEPS` and raising `TEMPLATE_VERSION` in `newsroom_process.py`. Each sub-task records the version it came from.

## Reading `papyrus stories next`

`papyrus stories next --story LINEAGE` is read only. It prints one `step` line per step with its state, then the `next` line, then one `skipped` line for each step the Story passed without doing.

- A state is `done`, `not_done` or `unknown`. Unknown is honest: a step that is not built, or whose record cannot be read, is never reported as done.
- `next` is the first live step that is not done; when none is left it is the first step that is not done.
- `skipped` lists steps before the Story's current stage that are not done. Unknown, not built and optional steps are never listed.
- A Story that is spiked or held has no next step.
- It then prints the stored checklist: one `item` line per checklist item (key, state, title, actor, time, and the reason, note or evidence) and a `checklist progress` line such as `4/9 · 2 skipped`. A Story with no checklist yet says so. `--json` adds `checklist` and `progress`.
- `--json` prints the same assessment as JSON.

How each step reads its record:

- choose is done when the Story is past the idea stage.
- direction is done when an Assignment on the Story has a direction (or instructions).
- research is done when an Assignment on the Story has a research packet.
- outline is done when the Story's current version carries the outline marker.
- draft is done when the current version number is above the outline's version number; with no outline, when the body is not empty and the Story is at copywriting or later.
- copy_edit is done when the stored editorial check of the current version has finished and has no error-level violation.
- editor_review is done when the stored review is for the current version and approves it.
- publish is done when the Story is published.

`papyrus stories next` also prints one `lens` line for each of the four review steps (people, AI reader agents, search, social previews) that is not done, with its audience. Those steps and their checks are defined in [four-lens-review.md](four-lens-review.md).

## Reminders on writes

After a successful write (never on `--dry-run`), the checklist is brought up to date once (see above), and `stories create`, `stories move`, `stories save-version`, `stories link-reference`, `stories assign-research`, `assignments research-multi` and `assignments process-proposals` (when the Assignment is on a Story) print the `next` and `skipped` lines. With `--json`, the two assignment commands add `next` to their JSON. A failure computing the reminder prints one line to stderr and never changes the result of the write. `stories move` to a later stage also prints a warning on stderr naming each step skipped before that stage, and still moves; the reason is recorded on the checklist, and publishing is where an open required step stops a Story.

## The outline and the draft

`papyrus stories outline --story <lineage>` and `papyrus stories draft --story <lineage>` each make one model call from the agent's [context pack](newsroom-context-packs.md) and save a new version, so nothing earlier is lost. `--dry-run` calls the model and saves nothing. Neither publishes.

The draft moves a Story to copywriting if it was earlier, marks the References it cites and runs the check every save runs. A draft that cites a key it was not given, or cites nothing when the Story has References, is refused and saves nothing. Whether its claims are true of their sources is the fact check that follows, which is not built yet.

A body with `[@key]` markers and no `::citations{}` line is flagged by the review check A5 (a warning, to be mentioned in the review step's note), naming the markers; the page appends the bibliography so no marker links to a missing anchor ([markus markup](markus-content-markup.md#the-bibliography)). A marker whose key is not among the Story's entries is flagged the same way and is refused when the Story is saved.

Every pack also says where the Story is in this procedure, so an agent knows what came before it and what comes after, whatever started it.
