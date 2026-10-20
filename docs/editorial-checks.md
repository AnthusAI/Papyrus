# Editorial checks

Editorial checks are core Papyrus functionality, built into every site's backend and newsroom.
The editorial context they apply (mission, policy, section guidance) is data in the site's cloud
backend, edited in the newsroom; see `docs/editorial-context.md`.


**What it is.** The article editor checks drafts against the publication's own
editorial policies and offers rewrite options, through
[Limatus](https://github.com/AnthusAI/Limatus) (`limatus[jev]`, bundled into the
editing function). Papyrus owns the policies, the settings and the editors'
decisions; Limatus is stateless and receives a policy pack with every call.

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
| `EditorialPolicy` | editors read, admins manage | One policy: key, scope (`publication` or a desk key), version, title, guidance, severity (`info`/`warn`/`error`), enabled, detectors (Limatus `policy-pack-v1` detectors), examples, rewrite guidance, source (`custom` or `starter:<pack>`). A desk policy replaces the publication policy with the same key for that desk's articles. |
| `EditorialCheckSettings` | editors read, admins manage | One row, id `settings`: `enabled` (default true), lanes, decision and rewrite models, the judgment-check deadline (default 20 s, inside AppSync's 30 s), token budget, examples per question, house guidance, check while typing, publish warning. |
| `EditorialFeedback` | editors create and read, admins manage | An editor's decision on a finding (`accepted`, `fixed`, `dismissed`, optional reason). Judgment decisions keep the sentence's text so later checks can use it as an example; `recalibrateEditorialPolicies` turns them into per-detector calibration. |

**Operations.** All are handled by one function that composes the policy pack
and calls Limatus: `checkEditorial` and `suggestEditorialRewrite` (editors),
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
