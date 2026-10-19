# Documentation index

One line per page. The hard rules for agents are in [../AGENTS.md](../AGENTS.md); start there. Pages marked (archive) are historical logs and are not maintained.

## Start here

- [how-papyrus-works.md](how-papyrus-works.md): taxonomy and ontology model, solver vs renderer, content boundary, cloud credentials.
- [code-map.md](code-map.md): where the main files live.
- [how-a-publish-flows.md](how-a-publish-flows.md): what happens when an editor saves or publishes, and what to do when it looks wrong.
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

## Sites, hosting and deploys

- [site-hosting.md](site-hosting.md): hosting runbook for Markus (S3 and CloudFront) and Pretext (Amplify) sites.
- [site-stacks.md](site-stacks.md): ops UI and reader output as independent plugins.
- [site-theme-packs.md](site-theme-packs.md): theme packs and ops chrome on `SiteBrand`.
- [site-workspace.md](site-workspace.md): the local folder convention for a split reader and CMS.
- [standard-site.md](standard-site.md): the approved design for the standard Papyrus site.
- [pluggable-publishers.md](pluggable-publishers.md): Pretext and Markus publication front ends.
- [plugins.md](plugins.md): deploy-time site plugins.
- [google-oauth-setup.md](google-oauth-setup.md): Google sign-in for a publication.
- [aws-sandbox-personal.md](aws-sandbox-personal.md): standing up a personal Amplify sandbox.
- [hosting/](hosting/): Amplify build spec examples, edge notes and Pilobolus DNS and front door files.
- [migrations/](migrations/): per-site migration notes (copy backend, p.apyr.us, pilobol.us).
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
- [console-chat-runbook.md](console-chat-runbook.md): the editor-only console chat on `/newsroom`.
- [slack-agent.md](slack-agent.md): the Slack channel for the console agent.
- [newsroom-organizer-release.md](newsroom-organizer-release.md): the organizer layout and read-only Board release.
- [automation-ai-ml-academic-research-dispatch.md](automation-ai-ml-academic-research-dispatch.md): the cron that dispatches AI/ML paper discovery.
- [automation-chorus-code-review-research.md](automation-chorus-code-review-research.md): registering Chorus and starting two research assignments.

## Knowledge and agents

- [internal-knowledge-research.md](internal-knowledge-research.md): `knowledgeQuery` context packs for accepted references and the graph.
- [agent-loop-patterns.md](agent-loop-patterns.md): bounded explorer loops vs one-shot researchers.
- [cyclotron-priming.md](cyclotron-priming.md): relevance cyclotron, priming examples, the proof number and the publication panel.
- [cyclotron-ti-end-to-end-check.md](cyclotron-ti-end-to-end-check.md): the runbook that checks delegated Reference approval and Cyclotron training on a deployed site.
- [cyclotron-chatgpt-test-prompt.md](cyclotron-chatgpt-test-prompt.md): the prompt for a ChatGPT research session that tests the deployed flow.
- [newsroom-curation-integration.md](newsroom-curation-integration.md): the opt-in References curation seam.

## CLI and API

- [operator-cli.md](operator-cli.md): one `papyrus` command over local pod and cloud backends.
- [python-cli-and-testing.md](python-cli-and-testing.md): Poetry setup, CLI recipes, sandbox seeding and BDD suites.
- [schema-and-api-alignment.md](schema-and-api-alignment.md): fix schema drift by deploying, never by shims.
- [local-dev-431-troubleshooting.md](local-dev-431-troubleshooting.md): `HTTP 431` from oversized localhost cookies.

## Archive

- [archive/priming-acceptance-evidence-2026-10.md](archive/priming-acceptance-evidence-2026-10.md): priming acceptance verification log (archive).
- [archive/curation-integration-verification.md](archive/curation-integration-verification.md): References integration verification log (archive).
- [archive/web-console-chat-fix/](archive/web-console-chat-fix/): the web console chat IAM fix notes and verification (archive).
