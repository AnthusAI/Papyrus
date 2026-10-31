# Editor agents

Papyrus runs agents in the roles a newsroom has: editor, reporter, copywriter and researcher. They do the work between a source arriving and a draft being ready. People decide what is published. An agent can write a draft; it does not publish one.

Status words used here: Live, Beta, Not built yet.

## The roles (Live)

Each role is a Tactus procedure in `procedures/newsroom/`: `editor.tac`, `reporter.tac`, `copywriter.tac` and `researcher.tac`, plus `research_explorer.tac` and others. Procedures are stored in the site's backend as `ProcedureDefinition` and `ProcedureVersion` records and seeded from those files. See [newsroom-procedures-runbook.md](newsroom-procedures-runbook.md).

- **Researcher** returns research packets from assignments.
- **Editor** plans an edition and proposes assignments.
- **Reporter** prepares a private reporting packet for an assignment: facts, source trail, open questions, risks and a brief for the copywriter.
- **Copywriter** turns a selected packet into a reader-facing draft. The procedure must never place it in an edition.

Packets are private work products. How they move, and how assignments are handled, is in [automated-publication-research-workflow.md](automated-publication-research-workflow.md) and [newsroom-operations.md](newsroom-operations.md).

## Assignments (Live)

An `Assignment` is a unit of research, reporting or copywriting work. Editors create and cull them in the `/newsroom` workspace. Agents claim and complete them. Work that must not run twice at once, such as `analysis.reindex`, requires an exclusive claim.

## Editorial checks (Live)

Drafts are checked against the publication's own editorial policies through [Humanus](https://github.com/AnthusAI/Humanus). Checks have been on by default since release 5.9.0.

- Policies are data in the site's backend (`EditorialPolicy`), edited in Administration, Editorial checks. A policy can apply to the publication or to one section.
- An admin turns checks off or changes how they run in `EditorialCheckSettings`.
- Findings are underlined in the article editor. An editor can apply a fix, ask for rewrite options, or dismiss a finding with a reason. Publishing is never blocked by an open finding; it only produces a warning.
- Those decisions are stored and can recalibrate the checks.

Details: [editorial-checks.md](editorial-checks.md). The mission, policy and section guidance that agents and checks read is in [editorial-context.md](editorial-context.md).

## Story versions and the reporting trail (Live)

Every time an agent changes an article it records a new version instead of overwriting the old one.

```bash
papyrus stories save-version --story <lineage> --body-file draft.md --reason "added a corroborating source" --author-label "<name>"
papyrus stories versions --story <lineage>
```

Older versions are listed in the story's Reporting trail and open read-only. In the newsroom article editor, an older version cannot be saved or published; publishing publishes the latest version. Each stage move and note is also recorded in the trail. See [story-reporting.md](story-reporting.md) and [content-item-lifecycle.md](content-item-lifecycle.md).

## The operator CLI and the API (Live)

Agents run newsroom operations through the same surfaces a person has.

- `papyrus` is one command over a local pod and the cloud newsroom. Cloud requests are signed with AWS credentials, so there is no token to manage. See [operator-cli.md](operator-cli.md) and [cli-login.md](cli-login.md).
- The console chat in `/newsroom` and the Slack channel run an agent that can call the same operations. See [console-chat-runbook.md](console-chat-runbook.md) and [slack-agent.md](slack-agent.md).
- All of it goes through the site's authorized GraphQL API.

## Editor review (stage bot) (Beta)

`procedures/newsroom/editor_review.tac` is the first editor decision built: whether a draft is done. It is one procedure for every publication; a site adds only its editorial context (mission, policy, section guidance), its editorial policies and, optionally, a brief. It is built and tested but **not turned on for any site**: no procedure is registered and no automation exists until an operator does it (below).

**What triggers it.** A story-entry [automation](automations.md#story-state-triggers) on `copywriting` (configurable). The engine starts the procedure with the story and the version that entered the stage, one run per story, stage and version, within the bot hop limit.

**What it reads.** The version (front matter and Markus body); its pipe tables, listed separately because the editorial check skips tables; the References linked to the story, with their source URL and publication date; the brief; the editorial context with its hash; and the editorial check run on that exact version (Humanus rules, plus the Jev lane over the publication's classifier policies). The brief is, in order: `metadata.editorBrief` on the version, the `assignment_brief` attachment (then the summary) of the newest copywriting Assignment whose `itemLineageId` is the story, or none. With none, the doctrine and policies in the editorial context are the brief, and the review says so.

**What it decides.** Eight generic acceptance criteria, each pass, fail or not applicable, with a severity and a note: every outside claim attributed to its source and linked; every number about the publisher's own systems traceable to a record or public file; no present-tense claim about the publisher's operations that it cannot show; dates taken from dated sources; promises kept (a promised link is there); tables checked by hand; the brief met; the doctrine fitted. GPT-6 Luna writes the review; Jev contributes through the editorial check, which the review reads as evidence and never repeats. Asking Jev each criterion as its own yes/no question is not built: it needs the criteria as classifier policies in the site's editorial pack (`papyrus editorial policies add --file`), which is a content decision per publication.

**What it writes.** `Item.metadata.editorReview` on the version it reviewed: `verdict` (`approve`, `revise` or `reframe`), `findings` (one per criterion), `revisionNotes`, `illustrationPlan`, `typesettingPlan`, `summary`, `editorialCheck` (status, counts, blocking rules), `model`, `contextHash`, `at`, `versionId`, `versionNumber`. A newer version inherits the earlier metadata, so compare `versionId` before trusting a review. Nothing else: no Message (Messages come from people), no new version, no stage move, no publishing.

**The contract.** The procedure returns `{version, hold, reason, verdict}`. It returns the version it received, because the editor does not edit. Approve returns `hold: false` and the engine moves the story to the automation's `nextStage` as the bot. Revise or reframe returns `hold: true` with the revision notes as the reason, and the engine raises a **flag** review request and leaves the story in `copywriting`; the copywriter or a person reads the notes. Human review is a review request, never a stage.

**It cannot approve a draft it should not.** Before storing, the record tool applies these rules and turns `approve` into `revise` (recording `downgradedFrom: "approve"`): a criterion the reviewer did not assess counts as failed; an error-level failure blocks; a version with a table cannot mark tables not applicable; an error-level editorial-check violation blocks (a `review` finding, or a warning, does not). A verdict that is not one of the three fails the run, and the engine raises a flag for the failed run.

**Turn it on for a site** (an operator, from a checkout of this repository or the site's; the site's backend must be on a release with story-state triggers, and its router publication needs the endpoint and `openaiKeyParameter` that the runner reads, see [automations](automations.md#story-state-triggers)):

```bash
papyrus procedures register --file procedures/newsroom/editor_review.tac --key <site>.editor-review --dry-run --json   # validates, writes nothing
papyrus procedures register --file procedures/newsroom/editor_review.tac --key <site>.editor-review
papyrus automations create --id <site>.editor-review --title "Editor review of a draft" \
  --on-stage copywriting --next-stage typesetting --monitor <monitor> --publication <site> \
  --procedure <site>.editor-review --max-hops 5 --dry-run
```

Drop `--dry-run` on the `create` to create it. `--monitor` is any monitor partition whose `CONFIG#router` lists the publication (it holds the run rows). The runner's role must be allowed to call the site's API: [granting a newsroom to the runner](procedure-runner.md#granting-a-newsroom-to-the-runner). Every bot run on a story, a held one included, counts as a hop; keep `--max-hops` high enough for all the bots the story meets.

**Not built yet.** The copywriting brief written as an Assignment attachment when a story is made from a draft (the review then has a real brief, not only the doctrine); Jev per criterion; a limit of one revision round before a soft review; the editor re-assigning the notes to the copywriter; the illustration and typesetting stages acting on the plans; the share of the editor's decisions a person overturned.

## Who decides

Editors decide what is published. Accepting a reference, choosing a packet for copywriting, placing a story in an edition and publishing are editor actions. Agent output is a suggestion or a draft until an editor acts.
