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

**Tables and quotations (Humanus 0.34).** Text in Markdown table cells is checked like any other
prose, by both lanes, so claims kept in a table are no longer skipped. Rule findings that fall
entirely inside a direct quotation (double quotes or a block quote) are not reported, because the
words are the source's, not the publication's; tool artifacts such as placeholder leaks still are.
A policy or detector can opt back in with `quotations: "check"`.

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
may call `appsync:GraphQL` only on the model operations it needs (the list is `EDITORIAL_CHECKS_FUNCTION_FIELDS` in `amplify/functions/editorial-checks/wire.ts`).

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

**Reading a check from the command line.** `papyrus editorial check-version --item VERSION_ID` prints the summary line and then every finding, violations first and then those for review: status, severity, policy, probability, id, message and excerpt. `--json` prints the summary and the full findings. A judgment that is about the whole story has no passage to quote, so Humanus gives it an empty excerpt (and one id per detector, so the id does not change when the text does); Papyrus starts its message with "Applies to the whole story." so it never reads as a missing excerpt.

**Passages copied across stories.** Each server check of a saved version (`checkItemVersion`, which `papyrus
editorial check-version`, `papyrus stories save-version` and the article editor's save all use) also looks for
boilerplate: a run of 12 or more consecutive words (the same `COPIED_RUN_WORDS` the reference copy guard uses) that
also appears, in the same order, in the latest version of another story on the same site. Each shared passage becomes
one finding under the policy id `cross-story-boilerplate`, severity `warn`, whose message names the other stories by
slug and lineage. It exists because a closing section pasted into seven articles goes stale in all of them at once.
It lives in Papyrus, not Humanus, because it needs the site's other stories; it is string matching with no model
call. The other stories' windows are built once per check. Rules:

- Compared: the latest current or draft version of every other story. A story's own earlier versions never count.
- Not compared: front matter, code, directive lines such as `::citations{}`, `[@key]` citation markers, link and
  image addresses, block quotes, and quoted text (inside straight or curly double quotes).
- Runs do not cross those excluded spans, so a quotation in the middle of a paragraph splits it.
- These findings are recomputed on every check, even when the story's own text is unchanged, because another story
  may have changed. They are stored in the version's `EditorialCheckRun` like any finding, so the editor and the
  filing gate show them. A policy-pack file (`--pack`) has no corpus and reports none.
- The function's role needs `listItemsByVersionStateAndUpdatedAt` (added to the least-privilege list); a site picks
  it up when its backend next deploys.

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
