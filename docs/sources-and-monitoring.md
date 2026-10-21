# Sources and monitoring

Sources are where candidate material comes from. Everything that arrives becomes a pending `Reference` in the publication's References queue. A pending Reference is a candidate, not a decision: an editor accepts or rejects it. How relevance is suggested is in [steering-and-relevance.md](steering-and-relevance.md).

Status words used here: Live, Beta, Not built yet.

## Hacker News Monitor (Beta)

A monitor that watches the Hacker News feed and offers items to the publications that want them.

- **Collector.** A Lambda that runs every 15 minutes (EventBridge Scheduler). It fetches the feed, dedupes by fingerprint, keeps a checkpoint and records receipts in a DynamoDB table. It holds no provider keys and writes nothing to any publication.
- **Router.** A second Lambda in the same stack, on its own schedule offset from the collector. It asks the shared Cyclotron which collected items each configured publication wants. It delivers only the items the relevance output labels `include`, as `pending` References with a provenance Message. It never creates an accepted Reference, and it never resets a human decision.
- **Modes.** The router config has `mode: dry-run` (no Cyclotron call, nothing written to a publication) and `mode: live`. Editor accepts and rejects can flow back to the Cyclotron as labels only when the config has `feedback: true` in live mode.
- **Deployment.** Both Lambdas are in the `papyrus-monitoring` CloudFormation stack, which is applied by hand with a change set. It is not part of any site's backend deploy.

Beta because it is one monitor with one source, configured as data by an operator.

Details: [monitoring-cloud.md](monitoring-cloud.md) (stack, table layout, router, operating notes), [monitoring-hn-pilot.md](monitoring-hn-pilot.md) (the earlier local worker, `papyrus monitors run` and `papyrus monitors status`), and the router config example in [monitoring-router-config.example.json](monitoring-router-config.example.json).

## Adding a reference by hand (Live)

- **From the newsroom.** The References tab has an "Add a reference" area with "Paste a URL" and, when the host supplies it, "Import a file". A pasted URL takes a label and an optional explanation; the page is read in the background by a worker. It is used to prime the relevance Cyclotron, described in [cyclotron-priming.md](cyclotron-priming.md).
- **From the CLI.** `papyrus references create-from-catalog --status pending` creates pending References from a catalog file. With an editor session it goes through the `intakePendingReferences` action; an operator can use IAM credentials. See [reference-intake/user-session-intake.md](reference-intake/user-session-intake.md).

## Inbound email (Live)

An editor or other registered user can email a link to the publication's submission address. The message is stored as a `Message`, and the `submissions.email.process` procedure files the references it cites. The sender address must match a registered user's email. See [inbound-email-submissions.md](inbound-email-submissions.md).

## Slack (Live)

A Slack app is another channel to the same console agent that the web console and email use. Filing a reference happens on the person's intent, not automatically for every URL. See [slack-agent.md](slack-agent.md).

## Research dispatch and web search (Live)

Research assignments find candidate sources.

- `papyrus editions dispatch-research` creates research assignments for an edition.
- `papyrus assignments research-intake-now` runs source discovery and proposal intake right away. A worked example with a schedule is [automation-ai-ml-academic-research-dispatch.md](automation-ai-ml-academic-research-dispatch.md).
- `papyrus assignments run-tavily-deep-research` and `papyrus assignments poll-tavily-deep-research` run Tavily Research tasks (`src/papyrus_newsroom/tavily_research.py`).
- Web search for references uses a provider chosen by the `WEB_SEARCH_PROVIDER` environment variable: `tavily` (the default) or `openai` (`src/papyrus_newsroom/web_search_providers.py`).

How assignments work: [automated-publication-research-workflow.md](automated-publication-research-workflow.md) and [newsroom-operations.md](newsroom-operations.md).

## Source-site enrichers (Live)

When a reference points at a known kind of site, a plugin resolves its identifiers and finds the best text. The plugins in `src/papyrus_content/source_site_plugins.py` are DOI, ACM, arXiv, YouTube and ACL Anthology. Other URLs use the default path.

## Not built yet

- **General RSS and Atom monitors** for a publication's own feeds (PPY-731c23).
- **Many monitors per publication** (PPY-7d9bbd). Today there is the one Hacker News monitor.
- **X search** as a source (PPY-e50a74).
- **Newsletter intake**, subscribing the publication to newsletters as a source (PPY-68d06c). Forwarding a newsletter by email to the submission address works today; a subscription does not.
