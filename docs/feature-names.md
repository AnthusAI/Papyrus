# Feature names

The names we use, in docs, on [p.apyr.us](https://p.apyr.us) and in conversation, for the Papyrus features worth talking about. Code identifiers, CLI commands and record types keep their existing names; this page maps the names people say to the places they live. Decided 2026-10-25 under the product-marketing push (Ryan: "anything is better than nothing").

Papyrus's mission is semi-supervised publications that surprise us every day with new things. What ties these features together is control over the algorithm: a steerable feed that ends up surprising you. The names should say what a thing does, in plain words, and should not promise more than is built.

Rules for the names: no newspaper or newsprint metaphors; "section", never "desk"; machine attribution reads "AI"; the shared tenant is an "Account"; Anthus offerings are "solutions".

## The recommended set

| Name | In one sentence | Status |
| --- | --- | --- |
| **Cited Trends** | Story drafts about what is rising or cooling in a publication's weekly map, where every sentence is traceable to the counts and releases behind it. | Built; weekly run is off by default |
| **Knowledge Map** | The weekly map of a publication's own items: topic clusters, typed entities and the relations between them, with a wiki and trend figures. | Beta |
| **Stage Bots** | Automations that fire when a story enters a stage, run a bot procedure that writes a new version, and let the engine move the story on. | Built; running on Distinctive Mark |
| **Review Requests** | Asks that a step in an automation raises for a person, as a flag, a soft review with a timeout or a hard gate. Review is never a story state. | Built |
| **Notification Center** | The console home page where review requests and steering opportunities are listed, safe to ignore. | Built |
| **Reader Steering** | Votes, ratings, flags and comments from signed-in readers, used as signals the publication steers by. | Built; turns on per site |
| **Proposals** | The queue where AI proposes a draft story, concept or change to the map, readers vote, and editors decide. | Built; example drafts on Shipped |
| **Editor Override** | The editor tier on Proposals: approve, decline, pin, hold, override the community with a public reason, set aside votes with a public note. | Built |
| **Automations** | Records that bind a trigger (a monitor, a story entering a stage) to a procedure, with enable, limits, cost, history and Run now. | Built |
| **Editorial Checks** | A publication's own policies, applied to a draft by Humanus policy packs, as findings that warn and never block publishing. | Built |
| **Relevance Routing** | One shared relevance Cyclotron deciding, for each collected item, which Account's sites want it. | Beta |

## Cited Trends

**Definition.** Once a week, after the knowledge run, Papyrus picks the rising and cooling signals in the Knowledge Map, attaches the releases behind each one, and has a model draft a story. The draft is kept only if a deterministic check passes: every sentence cites a signal or a release, at least two signals back the story, and every number and date comes from what that sentence cites. The chart is drawn by code from the real weekly counts. The draft is filed as an AI `story_draft` Proposal with one soft review request.

**Not.** It is not a story that publishes itself, and the check does not prove a sentence reads its evidence correctly, so an editor reads every draft. Approving a draft does not yet create a story. It is not "AI summaries of the news": it only writes about movement in the publication's own weekly counts.

**Where.** `papyrus ideas trends` (`src/papyrus_content/ideas/trends.py`); [idea-pipeline.md](idea-pipeline.md#trend-stories); the weekly job step in [knowledge-cloud-run.md](knowledge-cloud-run.md#trend-drafts-optional-off-by-default). Specs: `features_backend/idea-trend-stories.feature`.

**Demo.** [Shipped](https://shipped.anth.us/proposals/): the Proposals queue holds trend drafts. Worked example: the Shipped recipe in the p.apyr.us cookbook.

**Alternatives considered.**

- **Trend Briefs.** Short and plain, but "brief" says nothing about the thing that is different here, the citations.
- **Receipts.** Memorable and true to the idea (every claim comes with its receipt), but slangy, and it reads oddly in a console or in an enterprise document.
- **Evidence Stories.** Honest, but flat, and it sounds like a legal product.
- **Signal Stories.** Rejected: Shipped already calls its machine-learning releases "signals".

**Why Cited Trends.** It names the two things the feature is: it is about trends, and it is cited. It also names what it is not, because the word "cited" invites the question "by what?", and the answer is the deterministic check. A single draft is a "cited trend story".

## Knowledge Map

**Definition.** The weekly analysis of a publication's items: Biblicus topic-model clusters marked New, Growing or Cooling, typed entities (makers, models, licences) and typed relations between them such as "built on", an AI review whose every acceptance quotes the text, a weekly snapshot with a history archive, and projection to map pages, a wiki and trend figures.

**Not.** It is not generated when a reader loads a page, and nothing is fetched in the browser. It is not a general knowledge graph of the world: it holds what the publication's own items say.

**Where.** `papyrus knowledge ...` (`src/papyrus_content/knowledge_snapshot/`, `knowledge_cloud/`, `knowledge_wiki/`); [knowledge-snapshot.md](knowledge-snapshot.md), [knowledge-workstation-run.md](knowledge-workstation-run.md), [knowledge-cloud-run.md](knowledge-cloud-run.md), [public-wiki.md](public-wiki.md).

**Demo.** [Shipped](https://shipped.anth.us/map/): the map, the wiki, and the "built on" family tree on the front page.

**Alternatives.** Weekly Map (accurate, but drops the wiki and the entities), Living Map (warm, and says nothing checkable), Topic Atlas (an atlas implies geography). "The map" is what Shipped's readers already call it.

## Stage Bots

**Definition.** A story-state trigger fires when a story enters a stage. It starts a bot procedure (Tactus) that writes a new version of the story. The engine, not the procedure, then moves the story to the next stage. One run per story, stage and version; a hop limit stops a chain that goes on too long; versions a bot wrote are labelled as bot actions.

**Not.** A bot never publishes and never decides that a human is not needed: where a person is wanted, the engine raises a Review Request. Human input is never a stage.

**Where.** `papyrus automations create --on-stage ...` (`src/papyrus_content/story_triggers.py`); [automations.md](automations.md#story-state-triggers). Specs: `features_backend/story-state-triggers.feature`.

**Demo.** [Distinctive Mark](https://distinctive-mark.com): TTAB ruling analysis, then fact-check, then copy-edit (which runs the Editorial Checks), then typesetting, where an editor publishes. The procedures are in the open repository.

**Alternatives.** Stagehands (memorable, and apt: they work behind the stage, but it is a joke the docs would have to explain), Handoff Bots (accurate about the chain, vague about the trigger), Stage Triggers (the code's name; it describes the mechanism, not what you get).

## Review Requests and the Notification Center

**Definition.** A step asks a person to look without making review a story state. Three modes: a **flag** (nothing waits), a **soft review** (the process waits for a deadline and then proceeds, recording "proceeded without review") and a **hard gate** (never proceeds without an answer). The console home page, the Notification Center, lists them. If an editor only looks, the system keeps doing what it was doing; if they steer, the next run takes the steering into account.

**Not.** Not an approval workflow with a state for every handoff, and not an inbox that has to reach zero.

**Where.** `papyrus reviews ...` (`src/papyrus_content/review_requests.py`); [review-requests.md](review-requests.md), [notification-center.md](notification-center.md).

**Demo.** The console of each site. Shipped's trend drafts raise one soft review per run.

**Alternatives.** Nudges and Asks (friendly, but they undersell the hard gate); Review Queue (implies a queue that has to be emptied, which is exactly what this is not).

## Reader Steering, Proposals and Editor Override

**Definition.** Signed-in readers vote on any subject, rate, flag and comment. Proposals are the queue where AI proposes (draft stories, new concepts, renames, merges, splits), readers steer with votes, and editors decide. Editor Override is the editor tier: approve, decline, pin, hold, override the community with a public reason, and set aside votes with a public note and a way to restore them.

**Not.** Not a poll that decides. Votes rank the queue and advise editors; the editor decides, and when an editor overrides the readers, both results stay visible with the reason.

**Where.** The `reader-steering` plugin (`amplify/plugins/reader-steering/`, `src/papyrus_content/reader_steering/`), `papyrus proposals ...`; [reader-steering.md](reader-steering.md#proposals), [reader-steering.md](reader-steering.md#the-editor-tier). Specs: `features_backend/proposals*.feature`, `reader-*.feature`.

**Demo.** [Shipped](https://shipped.anth.us/proposals/): "AI proposes. You steer. Editors decide."

**Alternatives.** Community Steering (it is not a community product), Crowd Steering (sounds like a poll that wins), Proposals as "the Queue" (the queue is a view, not the idea).

## Automations

**Definition.** A named record in a site's own backend that says "when this happens, run that procedure with this input", with `enabled`, limits, cost, a run history that lists the tools each run used, and Run now.

**Where.** `papyrus automations ...` (`src/papyrus_content/automations.py`); [automations.md](automations.md).

**Demo.** Distinctive Mark's TTAB monitor and its stage bots.

**Alternatives.** Standing Orders (vivid, and no one searches for it), Routines.

## Editorial Checks

**Definition.** A publication's own editorial policies, checked against a draft with Humanus policy packs, with rewrite options. Findings warn; they never block publishing. A Tactus tool (`papyrus_check_story_version`) lets a bot run them, which is how a Stage Bot copy-edits.

**Where.** `src/papyrus_content/editorial_checks.py`, `editorial_policy_pack.py`; [editorial-checks.md](editorial-checks.md), [editorial-context.md](editorial-context.md).

**Demo.** Distinctive Mark's copy-edit stage.

**Alternatives.** Policy Checks (narrower), House Style (only part of what a policy can say).

## Relevance Routing

**Definition.** One shared relevance Cyclotron, an explainable classifier you can read, decides for each item a monitor collects which publications want it, and delivers only those. Editors' accepts and rejects on the references feed back to it.

**Not.** Not a separate model per site, and not auto-publishing: a delivered reference is still a candidate that an editor accepts or rejects.

**Where.** `papyrus_content/monitoring_router.py`, `monitoring_routing.py`; [monitoring-cloud.md](monitoring-cloud.md), [steering-and-relevance.md](steering-and-relevance.md#the-relevance-cyclotron-beta).

**Demo.** Distinctive Mark's TTAB monitor; the Hacker News monitor that feeds several Anthus publications.

**Alternatives.** Shared Relevance (shorter, vaguer), One Classifier, Many Sites (a tagline, not a name).

## Using the names

- Headlines and navigation use the name: "Cited Trends". Body copy may say "cited trend stories".
- Say what is built and what is planned on the same page. Known gaps, as of this page: approving a trend draft does not yet create a story; the weekly trend step is off by default and has run on Shipped only; a move made on the console board does not yet fire stage triggers (`papyrus stories fire-triggers` does).
- Link a demonstration, not a claim. Shipped and Distinctive Mark are open-code demonstration sites; the cookbook on p.apyr.us walks through each feature using them.
