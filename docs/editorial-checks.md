# Editorial checks

> **Editorial Checks** apply a publication's own policies to a draft. Findings warn and never block publishing. A bot can run them with the `papyrus_check_story_version` tool, which is how a Stage Bot copy-edits. See [feature-names.md](feature-names.md#editorial-checks).

Editorial checks are core Papyrus functionality, built into every site's backend and newsroom.
The editorial context they apply (mission, policy, section guidance) is data in the site's cloud
backend, edited in the newsroom; see `docs/editorial-context.md`.


**What it is.** The article editor checks drafts against the publication's own
editorial policies and offers rewrite options, through
[Humanus](https://github.com/AnthusAI/Humanus) (`humanus[jev]`, bundled into the
editing function). Papyrus owns the policies, the settings and the editors'
decisions; Humanus is stateless and receives a policy pack with every call.

**Always there, configured as data.** Every Papyrus site's backend and newsroom include editorial
checks; there is nothing to enable in `papyrus.config.ts` and no per-site code. They are on by
default. A publication turns them off, or changes how they run, in Administration → Editorial
checks → Settings, which writes `EditorialCheckSettings` in the site's own backend (`enabled`,
default true when no record exists). Turning them off only stops checks and rewrites: the function,
its least-privilege IAM grants and the policies stay. Before the first deploy, set
the Amplify secrets `TYPESAFE_API_KEY` (Jev, the decision model) and
`OPENAI_API_KEY` (rewrite suggestions and drafted questions). Without
`TYPESAFE_API_KEY` judgment policies report "not configured" and rule policies
still run.

**Data.**

| Model | Who | What |
|---|---|---|
| `EditorialPolicy` | editors read, admins manage | One policy: key, scope (`publication` or a section key), version, title, guidance, severity (`info`/`warn`/`error`), enabled, detectors (Humanus `policy-pack-v1` detectors), examples, rewrite guidance, source (`custom` or `starter:<pack>`). A section policy replaces the publication policy with the same key for that section's articles. |
| `EditorialCheckSettings` | editors read, admins manage | One row, id `settings`: `enabled` (default true), lanes, decision and rewrite models, the judgment-check deadline (default 20 s, inside AppSync's 30 s), token budget, examples per question, house guidance, check while typing, publish warning. |
| `EditorialFeedback` | editors create and read, admins manage | An editor's decision on a finding (`accepted`, `fixed`, `dismissed`, optional reason). Judgment decisions keep the sentence's text so later checks can use it as an example; `recalibrateEditorialPolicies` turns them into per-detector calibration. |

**Operations.** All are handled by one function that composes the policy pack
and calls Humanus: `checkEditorial` and `suggestEditorialRewrite` (editors),
`tryEditorialPolicy`, `draftEditorialQuestions`, `importEditorialStarterPack` and
`recalibrateEditorialPolicies` (admins). Nothing is open to guests. The function
may call `appsync:GraphQL` only on the five model operations it needs.

**Newsroom.** The article body is a CodeMirror editor; when checks are on,
findings are underlined in place (wavy for violations, dotted for "needs your
judgment") and listed beside the editor, grouped by policy. An editor can apply a
deterministic fix, ask for rewrite options for a finding or for any selected text
(with an optional note), mark an unsure finding as a real problem, or dismiss it
with a reason. Publishing is never blocked: open findings only produce a warning.
Administration has an Editorial checks panel for policies (including the
AI-writing tells starter pack, a "try it" box and drafted judgment questions),
settings and recalibration.

**Checks run by themselves.** The editor checks the body a moment (two seconds) after the body or section
stops changing, one check at a time (a result for text that has since changed is dropped), and again as soon as
a save finishes. Findings mark the body and fill the panel with no click. `checkWhileTyping` in the settings
controls this: on by default, and a missing or null value counts as on; only an admin setting it to false stops it
(the Check now button still works). A failed check shows its error in the panel and is not retried until the text
changes. Each save also asks the server to check the saved version (`checkItemVersion`), as `papyrus stories
save-version` and `papyrus_save_story_version` do, and the result is stored in `EditorialCheckRun` for that version.
Results are keyed by the version's content hash plus its section: identical content is never checked again (the
stored result is kept, or copied to a new version with the same content), while a check whose judgment lane did not
finish is retried on the next update. A failed server check never undoes the save.

**The copy-edit gate.** After copywriting saves a version, `papyrus editorial copy-edit --story LINEAGE [--version ID] [--no-suggest] [--dry-run] [--json]` (and the Tactus tool `papyrus_copy_edit_story_version`) sorts the findings. It never publishes and never moves a stage.

- **Mechanical fixes are applied.** Mechanical means a deterministic replacement that the site's own policies declare: a rules finding that carries a `replacement`. That is a phrase policy that names what the phrase becomes (a stale product name, say), or the built-in `uncontracted_forms` check in a policy the site enabled because its house voice wants contractions. Policy data decides what is mechanical: a policy with no replacement, and every judgment (classifier) finding, is never rewritten by this step. Overlapping edits keep the first; an edit whose text no longer matches the finding is skipped. All the fixes land as one new version with the reason `copy edit: N mechanical fixes (policy ids)` and the author `AI`.
- **Everything else stays a finding with rewrite options.** The new version is checked in full, and each surviving violation or review finding that quotes text (not `info` severity) gets up to three rewrite options from the same operation as the editor's Rewrite options button. They are stored in the version's `EditorialCheckRun` on the finding as `suggest` (id, replacement, rationale, `factVerificationRequired`, `unresolvedQuestions`), and the run's `lanes.copyEdit` records the count of fixes and how many options were attached. Nothing is applied. No provider key means no options: the result and `lanes.copyEdit.options.unavailable` say so once.
- **A surviving error finding holds the story.** If a violation of `error` severity survives, the result has `hold: true` and a `reason`. Return `{version, hold, reason}` from a stage bot and the engine raises a flag review request instead of advancing ([automations](automations.md)); the command line raises that flag itself (`rr-copy-edit-<version id>`). A clean or warn-only version carries `hold: false` and the engine advances it as it does after any bot.
- **Running again on the same text does nothing**: a version whose stored check already carries `lanes.copyEdit` is skipped without a model call.
- `--dry-run` prints the mechanical fixes and writes nothing. The step writes through the caller's credentials, so a role that may not write `EditorialCheckRun` still gets the new version and the result, with `checkRun.stored: false`.

**Odd editorial context never stops a check.** A section value that matches no `NewsroomSection` (matched by id,
slug or name, ignoring case; or ambiguous) checks against the publication's policies with no section guidance. A
publication with no current mission, or more than one, checks without the mission and its judgment lane is
skipped. Both log a warning that names the publication. Real failures (the provider or Humanus being unavailable)
still surface as an error in the panel.

**From a file.** Operators and agents without a signed-in admin can load policies,
including judgment (classifier) questions, from a Humanus `policy-pack-v1` file with
`papyrus editorial policies add --file pack.json`, and write the site's policies back
out with `papyrus editorial policies export --file pack.json`. `add` saves what the
panel saves (new policies at version 1, changed ones at the next version, identical
ones untouched), `--dry-run` shows the plan first, and each policy's source records
the pack and actor. A judgment question is a `classifier` detector:
`{"id": "...", "lane": "classifier", "scope": "document", "question": {"type": "noul",
"instructions": "..."}, "violation": {"answer": "yes"}, "threshold": 0.7, "reviewAt": 0.4,
"message": "..."}`. Details: [operator-cli.md](operator-cli.md#editorial-policies).
