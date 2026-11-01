# Sources and monitoring

Sources are where candidate material comes from. Everything that arrives becomes a pending `Reference` in the publication's References queue. A pending Reference is a candidate, not a decision: an editor accepts or rejects it. How relevance is suggested is in [steering-and-relevance.md](steering-and-relevance.md).

Status words used here: Live, Beta, Not built yet.

## Hacker News Monitor (Beta)

A monitor that watches the Hacker News feed and offers items to the publications that want them.

- **Collector.** A Lambda that runs every 15 minutes (EventBridge Scheduler). It fetches the feed, dedupes by fingerprint, keeps a checkpoint and records receipts in a DynamoDB table. It holds no provider keys and writes nothing to any publication.
- **Router.** A second Lambda in the same stack, on its own schedule offset from the collector. It asks the shared Cyclotron which collected items each configured publication wants. It delivers only the items the relevance output labels `include`, as `pending` References with a provenance Message. It never creates an accepted Reference, and it never resets a human decision.
- **Modes.** The router config has `mode: dry-run` (no Cyclotron call, nothing written to a publication) and `mode: live`. Editor accepts and rejects can flow back to the Cyclotron as labels always in live mode for Cyclotron-decided monitors; there is no feedback switch.
- **Deployment.** Both Lambdas are in the `papyrus-monitoring` CloudFormation stack, which is applied by hand with a change set. It is not part of any site's backend deploy.

Beta because it is one monitor with one source, configured as data by an operator.

## TTAB decisions monitor (Beta)

A monitor that watches the USPTO TTAB Reading Room for new Board decisions and delivers every final decision to the publications it is configured for. First used by Distinctive Mark's TTAB rulings section.

- **Source.** The Reading Room's decision search (`sourceType: ttab-decisions`), a JSON POST over a rolling `lookbackDays` window (30 by default). Each final decision becomes one item: the opinion PDF is its canonical URL and the TTABVUE proceeding page its item page. A decision redesignated as precedential within the window is collected again as a new revision.
- **Direct routing.** The router config has `decisions: direct`: no relevance call, every collected item goes to every configured publication as a `pending` Reference, and the provenance Message says it came from the monitor's own rule. A rulings tracker wants every decision, so there is nothing to decide; notability comes later, from the publication's own review or Cyclotron. Direct monitors have no feedback.
- **Schedules.** It collects once a day (its `intervalSeconds`; the schedule wakes it every 6 hours) and routes hourly.

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
- `papyrus assignments research-multi <assignment>` runs `research.multi`, an opt-in mode an editor picks per assignment: one planned set of queries on every configured search provider, merged and synthesised into one research packet with per-provider contribution. It is never the default; see [automated-publication-research-workflow.md](automated-publication-research-workflow.md#multi-search-research-researchmulti).
- Web search for references goes through `papyrus_content.web_search` (providers `tavily`, `openai`, `perplexity`, `gemini`, `bedrock`), chosen by `WEB_SEARCH_PROVIDERS`, an ordered fallback chain such as `openai,tavily`, or the older single `WEB_SEARCH_PROVIDER`; `perplexity,openai` is the default (Perplexity is the normal search; Gemini and Tavily are used where an operator names them). `src/papyrus_newsroom/web_search_providers.py` only shapes the answer for the research tools, and the payload's metadata records the chain, the provider that answered and why others were skipped. Keys: `<PROVIDER>_API_KEY` or the SSM SecureString named by `PAPYRUS_<PROVIDER>_KEY_PARAMETER` (standard names `/papyrus/search/<provider>-api-key`). See `docs/monitoring-cloud.md` for the failure kinds and the stack parameters.

How assignments work: [automated-publication-research-workflow.md](automated-publication-research-workflow.md) and [newsroom-operations.md](newsroom-operations.md).

## Source-site enrichers (Live)

When a reference points at a known kind of site, a plugin resolves its identifiers and finds the best text. The plugins in `src/papyrus_content/source_site_plugins.py` are DOI, ACM, arXiv, YouTube and ACL Anthology. Other URLs use the default path.

## Not built yet

- **General RSS and Atom monitors** for a publication's own feeds (PPY-731c23).
- **Many monitors per publication** (PPY-7d9bbd). Today there are two monitors, Hacker News and TTAB decisions, each configured by an operator in the table.
- **A monitor that starts a procedure** (PPY-9a79b5): for example, the TTAB monitor starting a publication's ruling-analysis procedure for each new decision.
- **X search** as a source (PPY-e50a74).
- **Newsletter intake**, subscribing the publication to newsletters as a source (PPY-68d06c). Forwarding a newsletter by email to the submission address works today; a subscription does not.
