# Documentation index

One line per page. Read [../README.md](../README.md) for what the repository is and how a change ships, then [../AGENTS.md](../AGENTS.md) for the rules and the common commands. Pages marked (archive) are historical logs and are not maintained. Status words: Live, Beta, In progress, Planned. Pages with a design status in their first lines (for example the standard site design) can lag the code; the README wins when they disagree.

## By task

- **Orient**: [../README.md](../README.md), [../AGENTS.md](../AGENTS.md), [code-map.md](code-map.md), [how-papyrus-works.md](how-papyrus-works.md).
- **Ship a change**: [releasing.md](releasing.md), [site-hosting.md](site-hosting.md#deploy-on-merge-to-main), [verification.md](verification.md).
- **Start a new site**: [../README.md#start-a-new-papyrus-site](../README.md#start-a-new-papyrus-site), [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md), [../infra/amplify-app-shell/README.md](../infra/amplify-app-shell/README.md), [google-oauth-setup.md](google-oauth-setup.md).
- **Re-project or repair a site**: [site-hosting.md](site-hosting.md#operations-runbook), [site-hosting.md](site-hosting.md#projection-lease-one-projection-at-a-time).
- **Add a site to Hacker News routing**: [monitoring-cloud.md](monitoring-cloud.md), [../AGENTS.md](../AGENTS.md#add-a-site-to-the-hacker-news-routing).
- **Register a procedure or an automation**: [procedure-runner.md](procedure-runner.md), [automations.md](automations.md).
- **Run the weekly knowledge run**: [knowledge-workstation-run.md](knowledge-workstation-run.md), [knowledge-cloud-run.md](knowledge-cloud-run.md).
- **Review requests and the Notification Center**: [notification-center.md](notification-center.md), [review-requests.md](review-requests.md). The console home is ignore-safe (only a hard gate waits for a person), steering is fed back to the step that raised the request, and marks accompany every colour.

## Features at a glance

- [agent-readable-sites.md](agent-readable-sites.md): Markdown twins, llms.txt, Accept negotiation, page actions, feeds, sitemap and robots on Markus sites.
- [steering-and-relevance.md](steering-and-relevance.md): doctrine, include and exclude decisions, the relevance Cyclotron (Beta), category steering, and what is not built.
- [sources-and-monitoring.md](sources-and-monitoring.md): the Hacker News Monitor (Beta), email, Slack, research dispatch, source-site enrichers.
- [editor-agents.md](editor-agents.md): editor, reporter, copywriter and researcher procedures, editorial checks, story versions.
- [knowledge-base.md](knowledge-base.md): concepts wiki, taxonomy, graph, context packs, the trending report (Beta), Biblicus.
- [public-wiki.md](public-wiki.md): the public wiki: draft pages from accepted entities and beats, review stamps, suggest an edit.
- [knowledge-components.md](knowledge-components.md): the components that render knowledge data on static pages.
- [knowledge-snapshot.md](knowledge-snapshot.md): the public knowledge JSON of a site (`papyrus knowledge snapshot`, `publish-run`, entity review).
- [knowledge-workstation-run.md](knowledge-workstation-run.md): the weekly workstation run, end to end: corpus export, Biblicus topics, trends, identity, typed entities, import, review, snapshot, wiki.
- [knowledge-cloud-run.md](knowledge-cloud-run.md): the same run as an unattended weekly job in AWS (EventBridge, Step Functions, Fargate), its AI review, state, alarms and cost.
- [newsletter.md](newsletter.md): signup capture, the double opt-in `newsletter` plugin with clean `/newsletter/*` pages, branded email theme, roundups, alerts and SES sending (Live on Shipped).
- [reader-steering.md](reader-steering.md): the `reader-steering` plugin: votes on any subject, ratings, flags, comments, submissions, moderation, snapshots and Proposals (built; reader writes closed in production until Prospectus returns a site subject).
- [automations.md](automations.md): automation records binding a monitor to a procedure, with `enabled`, limits, cost, history and Run now (PPY-9ff95b slices 1 and 2).
- [idea-pipeline.md](idea-pipeline.md): `papyrus ideas digest` and `synthesize`, v0 (PPY-8ffc18; scheduling in progress).

## Start here

- [how-papyrus-works.md](how-papyrus-works.md): taxonomy and ontology model, solver vs renderer, content boundary, cloud credentials.
- [code-map.md](code-map.md): where the main files live.
- [how-a-publish-flows.md](how-a-publish-flows.md): what happens when an editor saves or publishes, and what to do when it looks wrong.
- [multi-tenancy.md](multi-tenancy.md): several publications on one backend, with `--tenant`.
- [content-item-lifecycle.md](content-item-lifecycle.md): one content item and one lifecycle, with a configurable name (default Story).
- [verification.md](verification.md): what to run before calling a change done, plus the reader browser smoke test.
- [local-preview.md](local-preview.md): `npm run dev:preview` seeded newsroom Board with no AWS, plus headless screenshots for reviews.
- [agent-rules-detail.md](agent-rules-detail.md): the full text behind each rule summarized in AGENTS.md.
- [releasing.md](releasing.md): lockstep npm and PyPI releases with Semantic Release.

## Layout and reader

- [layout-system.md](layout-system.md): newspaper layout rules enforced by the solver and BDD scenarios.
- [solver-and-data-contracts.md](solver-and-data-contracts.md): solver and renderer boundary, data contracts, solver flow, how to extend an edition.
- [layout-scenario-tests.md](layout-scenario-tests.md): how the Gherkin layout scenarios work.
- [blog-layout-brand-slots.md](blog-layout-brand-slots.md): the rhythm blog layout and brand slots a publication supplies.
- [markus-content-markup.md](markus-content-markup.md): Markus responsive images and inline citations.
- [video-loading.md](video-loading.md): why reader videos were fetched repeatedly and the component fix.
- [video-pipeline.md](video-pipeline.md): `papyrus videos` with VideoML, plus the agent rules for video work.
- [favicon-pipeline.md](favicon-pipeline.md): generating favicon assets from the theme.
- [public-surface.md](public-surface.md): what an anonymous visitor to a static Markus site can reach.
- [public-forms.md](public-forms.md): the public form endpoint for contact forms and newsletter signups.

## Sites, hosting and deploys

- [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md): the one standard front end for Markus sites: `projection.json`, theme, hooks, migration checklist.
- [site-hosting.md](site-hosting.md): hosting runbook for Markus (S3 and CloudFront) and Pretext (Amplify) sites.
- [site-stacks.md](site-stacks.md): ops UI and reader output as independent plugins.
- [site-theme-packs.md](site-theme-packs.md): theme packs and ops chrome on `SiteBrand`.
- [site-workspace.md](site-workspace.md): the local folder convention for a split reader and CMS.
- [standard-site.md](standard-site.md): the approved design for the standard Papyrus site (design record, 2026-10-05; the packages it calls a spike are now published).
- [pluggable-publishers.md](pluggable-publishers.md): Pretext and Markus publication front ends.
- [hosting/edge-under-the-cms-backend.md](hosting/edge-under-the-cms-backend.md): design notes (status: design only) for putting each site edge under its CMS backend.
- [plugins.md](plugins.md): deploy-time site plugins.
- [score-combination.md](score-combination.md): exploration of how editor and reader scores combine (PPY-0b2cbb), with the simulation.
- [google-oauth-setup.md](google-oauth-setup.md): Google sign-in for a publication.
- [aws-sandbox-personal.md](aws-sandbox-personal.md): standing up a personal Amplify sandbox.
- [hosting/](hosting/): Amplify build spec examples, edge notes and Pilobolus DNS and front door files.
- [migrations/](migrations/): per-site migration notes (copy backend, p.apyr.us, pilobol.us).
- [migrations/app-shell-repository.md](migrations/app-shell-repository.md): connecting the Amplify apps to the site repository from `infra/site.json`.
- [migrations/tenant-scoped-ids.md](migrations/tenant-scoped-ids.md): rollout order for tenant-scoped ids and adopting older records.
- [production-content-operations.md](production-content-operations.md): targeted production content refreshes through the IAM authoring CLI.

## Newsroom

- [newsroom-operations.md](newsroom-operations.md): the `/newsroom` workspace, assignments, Coverage Themes, packets and steering.
- [automated-publication-research-workflow.md](automated-publication-research-workflow.md): assignment work products and the slot decision matrix.
- [newsroom-procedures-runbook.md](newsroom-procedures-runbook.md): how seeded Tactus procedures reach the cloud and how to verify a run.
- [newsroom-worker-bootstrap.md](newsroom-worker-bootstrap.md): making a Mac or EC2 worker ready for analysis assignments.
- [new-publication-from-corpus.md](new-publication-from-corpus.md): starting a publication from a pile of files.
- [category-steering-runbook.md](category-steering-runbook.md): pointer to the category-steering skill.
- [reference-processing-terminology.md](reference-processing-terminology.md): vocabulary for reference workflows.
- [inbound-email-submissions.md](inbound-email-submissions.md): suggesting references by email.
- [reference-intake/user-session-intake.md](reference-intake/user-session-intake.md): pending Reference intake with an editor session.
- [monitoring-cloud.md](monitoring-cloud.md): the Hacker News and TTAB collectors, the router, the shared Cyclotron routing to several sites, and the Monitoring page.
- [procedure-runner.md](procedure-runner.md): the cloud Lambda that runs a site's registered Tactus procedure; `papyrus procedures register`.
- [monitoring-hn-pilot.md](monitoring-hn-pilot.md): the local Hacker News monitor worker.
- [console-chat-runbook.md](console-chat-runbook.md): the editor-only console chat on `/newsroom`.
- [slack-agent.md](slack-agent.md): the Slack channel for the console agent.
- [newsroom-organizer-release.md](newsroom-organizer-release.md): the organizer layout and read-only Board release.
- [notification-center.md](notification-center.md): the CMS console home: review requests, Cyclotron items and the auto-decided stream; the ignore-safe principle.
- [review-requests.md](review-requests.md): flags, timed soft reviews and hard gates; the model, the deadline, the CLI, the steering read-back and the idea-pipeline hook.
- [automation-ai-ml-academic-research-dispatch.md](automation-ai-ml-academic-research-dispatch.md): the cron that dispatches AI/ML paper discovery.
- [automation-chorus-code-review-research.md](automation-chorus-code-review-research.md): registering Chorus and starting two research assignments.

## Knowledge and agents

- [internal-knowledge-research.md](internal-knowledge-research.md): `knowledgeQuery` context packs for accepted references and the graph.
- [agent-loop-patterns.md](agent-loop-patterns.md): bounded explorer loops vs one-shot researchers.
- [cyclotron-priming.md](cyclotron-priming.md): relevance cyclotron, priming examples, the proof number and the publication panel.
- [cyclotron-ti-end-to-end-check.md](cyclotron-ti-end-to-end-check.md): the runbook that checks delegated Reference approval and Cyclotron training on a deployed site.
- [cyclotron-chatgpt-test-prompt.md](cyclotron-chatgpt-test-prompt.md): the prompt for a ChatGPT research session that tests the deployed flow.
- [newsroom-curation-integration.md](newsroom-curation-integration.md): the opt-in References curation seam.
- [editorial-checks.md](editorial-checks.md): Humanus editorial checks, policies and editor feedback.
- [editorial-context.md](editorial-context.md): the mission, policy and section guidance that agents and checks read.
- [story-reporting.md](story-reporting.md): story versions, reference links and the reporting trail.
- [biblicus-1-14-upgrade.md](biblicus-1-14-upgrade.md): Biblicus catalog changes and upgrade steps.

## CLI and API

- [operator-cli.md](operator-cli.md): one `papyrus` command over local pod and cloud backends.
- [cli-login.md](cli-login.md): native Google CLI session, secure storage, renewal and required provider configuration.
- [idea-pipeline.md](idea-pipeline.md): `papyrus ideas digest|synthesize`, private story ideas from a site's recent references (v0).
- [python-cli-and-testing.md](python-cli-and-testing.md): Poetry setup, CLI recipes, sandbox seeding and BDD suites.
- [schema-and-api-alignment.md](schema-and-api-alignment.md): fix schema drift by deploying, never by shims.
- [local-dev-431-troubleshooting.md](local-dev-431-troubleshooting.md): `HTTP 431` from oversized localhost cookies.

## Archive

- [archive/priming-acceptance-evidence-2026-10.md](archive/priming-acceptance-evidence-2026-10.md): priming acceptance verification log (archive).
- [archive/curation-integration-verification.md](archive/curation-integration-verification.md): References integration verification log (archive).
- [archive/web-console-chat-fix/](archive/web-console-chat-fix/): the web console chat IAM fix notes and verification (archive).
