# The Story procedure

One definition of how a Story moves through the newsroom. The command line reads it (`papyrus stories next`, and the reminders printed after a write), and the context pack will read it later. It lives in `src/papyrus_content/newsroom_process.py` as an ordered list of steps. It applies to people and agents alike.

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
| illustration | illustration | Editor | none yet | not built, optional |
| typesetting | typesetting | Editor | none yet | not built, optional |
| publish | published | A person | `papyrus ops content publish --id ITEM_ID` | live |

The illustration and typesetting steps are described in [story-illustration-typesetting.md](story-illustration-typesetting.md).

## Two decisions

- The outline comes after the research. The editor writes it once the reporter's packet exists, and saves it with `--outline` so the draft step can tell the outline from the draft.
- A skipped step warns and never refuses. Publishing stays the only hard gate. There are no new stages, and human review is never a stage: a person comes in through a review request ([review requests](review-requests.md)).

## Reading `papyrus stories next`

`papyrus stories next --story LINEAGE` is read only. It prints one `step` line per step with its state, then the `next` line, then one `skipped` line for each step the Story passed without doing.

- A state is `done`, `not_done` or `unknown`. Unknown is honest: a step that is not built, or whose record cannot be read, is never reported as done.
- `next` is the first live step that is not done; when none is left it is the first step that is not done.
- `skipped` lists steps before the Story's current stage that are not done. Unknown, not built and optional steps are never listed.
- A Story that is spiked or held has no next step.
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

After a successful write (never on `--dry-run`), `stories create`, `stories move`, `stories save-version`, `stories link-reference`, `stories assign-research`, `assignments research-multi` and `assignments process-proposals` (when the Assignment is on a Story) print the `next` and `skipped` lines. With `--json`, the two assignment commands add `next` to their JSON. A failure computing the reminder prints one line to stderr and never changes the result of the write. `stories move` to a later stage also prints a warning on stderr naming each skipped step, and still moves.

## The outline and the draft

`papyrus stories outline --story <lineage>` and `papyrus stories draft --story <lineage>` each make one model call from the agent's [context pack](newsroom-context-packs.md) and save a new version, so nothing earlier is lost. `--dry-run` calls the model and saves nothing. Neither publishes.

The draft moves a Story to copywriting if it was earlier, marks the References it cites and runs the check every save runs. A draft that cites a key it was not given, or cites nothing when the Story has References, is refused and saves nothing. Whether its claims are true of their sources is the fact check that follows, which is not built yet.

Every pack also says where the Story is in this procedure, so an agent knows what came before it and what comes after, whatever started it.
