# The Papyrus specifications

These feature files say what Papyrus does, in the words an editor, a reader or an operator would use, and the
behave run proves each sentence against the real code. Read them in the order below to learn the product: each
area is one directory, and each area's first features explain the idea before the later ones cover the edges.

Papyrus is a newsroom for publications that are written with AI and edited by people. Monitors bring in
References, editors rate them, ideas become Stories, agents research and write, people review, and the result
is published as a static site that readers can steer. One engine serves many publications.

## Reading order

| Area | What it explains | Start with |
| --- | --- | --- |
| [stories](stories/) | A Story's path from idea to published page: the procedure, the checklist, Assignments, review requests, pictures, scheduling, publishing and taking a Story down. | [story-procedure](stories/story-procedure.feature), [story-checklist](stories/story-checklist.feature), [review-requests](stories/review-requests.feature), [publish-item](stories/publish-item.feature), [scheduled-publishing](stories/scheduled-publishing.feature), [story-withdraw-restore](stories/story-withdraw-restore.feature) |
| [references](references/) | How a source enters the newsroom, by monitor, email or a reader, and how editors rate, search and cite it. | [reference-lifecycle](references/reference-lifecycle.feature), [reference-intake](references/reference-intake.feature), [reference-stars](references/reference-stars.feature), [reference-search](references/reference-search.feature) |
| [ideas](ideas/) | How References become story ideas: the daily pipeline, trends, duplicates and what an editor selects. | [idea-lifecycle](ideas/idea-lifecycle.feature), [idea-pipeline](ideas/idea-pipeline.feature), [idea-selection](ideas/idea-selection.feature), [idea-trend-stories](ideas/idea-trend-stories.feature) |
| [monitoring](monitoring/) | The monitors that watch feeds and the web, the router that decides what each publication receives, and the relevance model that learns from editors. | [monitoring-hacker-news](monitoring/monitoring-hacker-news.feature), [monitoring-decision-contract](monitoring/monitoring-decision-contract.feature), [cyclotron-relevance-recording](monitoring/cyclotron-relevance-recording.feature), [monitoring-view](monitoring/monitoring-view.feature) |
| [knowledge](knowledge/) | The publication's wiki: concepts, entities, tags and the links suggested between them. | [knowledge-cloud-run](knowledge/knowledge-cloud-run.feature), [concept-tags](knowledge/concept-tags.feature), [knowledge-entity-extraction](knowledge/knowledge-entity-extraction.feature), [suggest-links](knowledge/suggest-links.feature) |
| [agents](agents/) | The always-on agents: what a definition is, the policy and rungs a person sets, what wakes an agent, the one gate every call passes, and how a run ends and is paid for. | [agent-definition](agents/agent-definition.feature), [agent-policy](agents/agent-policy.feature), [operation-gate](agents/operation-gate.feature), [change-feeds](agents/change-feeds.feature), [wake-keys](agents/wake-keys.feature), [run-outcomes](agents/run-outcomes.feature), [spend-ledger](agents/spend-ledger.feature) |
| [pods](pods/) | A pod is a folder of Markdown notes that can be checked offline and loaded into a publication. | [pod-init-and-id](pods/pod-init-and-id.feature), [pod-check](pods/pod-check.feature), [pod-lifecycle](pods/pod-lifecycle.feature), [pod-load-publish](pods/pod-load-publish.feature) |
| [announcements](announcements/) | Announcing a published Story once on each channel: the decision, the Delivery, the edit window, budgets, dry runs, corrections and withdrawals. | [announcement-decided-once](announcements/announcement-decided-once.feature), [announcement-settings](announcements/announcement-settings.feature), [delivery-edit-window](announcements/delivery-edit-window.feature), [announcements-x-dry-run-and-sending](announcements/announcements-x-dry-run-and-sending.feature), [announcements-withdraw](announcements/announcements-withdraw.feature) |
| [readers](readers/) | What a reader can do: subscribe, choose what they receive, vote, comment, submit and file proposals. | [reader-steering](readers/reader-steering.feature), [proposals-core](readers/proposals-core.feature), [newsletter-double-opt-in](readers/newsletter-double-opt-in.feature), [notifications-reader-pages](readers/notifications-reader-pages.feature), [subscription-preferences](readers/subscription-preferences.feature) |
| [site](site/) | The published site: projection, the standard front end, the home page, Markdown twins, addresses and refreshing a page. | [projection](site/projection.feature), [standard-frontend](site/standard-frontend.feature), [home-page-snapshot](site/home-page-snapshot.feature), [page-twins](site/page-twins.feature), [urls-by-type](site/urls-by-type.feature), [projection-lease](site/projection-lease.feature) |
| [translation](translation/) | Publishing in more than one language: which languages a site serves, translating a Story, and copy written separately for a language. | [translation-lifecycle](translation/translation-lifecycle.feature), [editorial-languages](translation/editorial-languages.feature), [story-localize](translation/story-localize.feature), [language-serving](translation/language-serving.feature) |
| [guidelines](guidelines/) | A publication's own rules: writing and image guidelines, the brand pack and the design system. | [guidelines-store](guidelines/guidelines-store.feature), [guidelines-files](guidelines/guidelines-files.feature), [brand-pack-applied](guidelines/brand-pack-applied.feature), [image-profile](guidelines/image-profile.feature) |
| [cli](cli/) | The `papyrus` command: signing in, choosing a site, and what every command promises. | [operator-cli](cli/operator-cli.feature), [cli-user-auth](cli/cli-user-auth.feature), [cli-site-selection](cli/cli-site-selection.feature), [cli-help-never-runs](cli/cli-help-never-runs.feature), [agent-cli-guide](cli/agent-cli-guide.feature) |
| [mcp](mcp/) | The hosted MCP server, through which an AI client works on a site: signing in with OAuth, the tools it is given, and the safety rules for writes. | [mcp-oauth](mcp/mcp-oauth.feature), [mcp-domain-tools](mcp/mcp-domain-tools.feature), [mcp-story-version-safety](mcp/mcp-story-version-safety.feature), [mcp-publish-request](mcp/mcp-publish-request.feature) |
| [tenancy](tenancy/) | Many publications on one stack: the tenant on every record, the claims in a session and the isolation between tenants. | [tenancy-mode](tenancy/tenancy-mode.feature), [tenant-records](tenancy/tenant-records.feature), [tenant-session-claims](tenancy/tenant-session-claims.feature), [tenant-scoping](tenancy/tenant-scoping.feature), [tenant-isolation-adversarial](tenancy/tenant-isolation-adversarial.feature) |
| [platform](platform/) | What keeps the engine safe to release and cheap to run: index limits, optional features, cost reports and the rule that one correct path fails clearly. | [gsi-ledger](platform/gsi-ledger.feature), [optional-features-off](platform/optional-features-off.feature), [no-fallbacks](platform/no-fallbacks.feature), [cost-accounting-reports](platform/cost-accounting-reports.feature), [release-classification](platform/release-classification.feature) |

## Rules for a new feature

- Put it in the area whose paragraph above describes it. A feature at the top of `features_backend/` fails the build.
- Name the file in lower case with hyphens.
- Open with a few sentences that say what the behaviour is for, in the reader's words, before the first scenario.
- Every `Then` must check the thing its sentence says. A step that only runs another test file and reads its exit code proves nothing a reader can see.
- Step definitions for every area live in `steps/`, and shared data in `fixtures/`.

## Running

```bash
poetry run behave features_backend --tags=~@live-agent
poetry run behave features_backend/stories
poetry run behave features_backend/stories/story-procedure.feature
```
