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

## Who decides

Editors decide what is published. Accepting a reference, choosing a packet for copywriting, placing a story in an edition and publishing are editor actions. Agent output is a suggestion or a draft until an editor acts.
