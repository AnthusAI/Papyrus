# Idea pipeline (v0)

> **Cited Trends** is the name for the trend-story path below: story drafts about what is rising or cooling in the weekly Knowledge Map, with every sentence cited and checked by code, filed as AI Proposals for people to steer. See [feature-names.md](feature-names.md#cited-trends). Shipped files them as example drafts at <https://shipped.anth.us/proposals/>. Approving a draft does not yet create a story.

`papyrus ideas digest` and `papyrus ideas synthesize` turn a site's recent references into private story ideas. This is the first
version of PPY-8ffc18: a digest and a synthesis, run by hand against the cloud CMS. `papyrus ideas trends` adds the trend-story path
([below](#trend-stories)). Scheduling comes later. Executable specs: `features_backend/idea-pipeline.feature`,
`features_backend/idea-trend-stories.feature`, `features_backend/idea-monitor-stories.feature`; unit tests: `procedures/newsroom/tests/test_ideas.py`, `test_idea_trends.py`, `test_monitor_stories.py`.

## Running it

Both commands run on your machine against one site's CMS. Point them at the site's AppSync endpoint and sign with your AWS
credentials (the site's account, for example `aws configure export-credentials`), or use a `papyrus login` session:

```bash
export PAPYRUS_GRAPHQL_ENDPOINT=https://<api-id>.appsync-api.us-east-1.amazonaws.com/graphql
export PAPYRUS_GRAPHQL_AUTH=iam OPENAI_API_KEY=...
papyrus ideas digest --publication <corpus-key> --since 7d
papyrus ideas synthesize --publication <corpus-key> --digest <digest-id> --max 5 --report ideas.md
```

`--publication` is the knowledge corpus key (`knowledge-corpus-<key>`); an unknown key lists the keys the backend has.

## The digest

Deterministic, no model. It reads the site's **current** references in the asked-for curation statuses that arrived (`createdAt`)
inside the window, newest first, up to `--max-references` (60). Default status is `accepted`, because only accepted references are
evidence. `--status accepted,pending` adds references that a monitor delivered but no editor has reviewed yet; the digest marks
each one's status and the synthesis prompt tells the model they are unreviewed. `--excerpts` fetches a short plain-text excerpt of
each source page (public http(s) addresses only); without it a reference carries only what the CMS holds.

Each reference records its title, source domain, status, arrival time, corpus (its "section"), the Cyclotron relevance label and
score when a decision exists, any semantic-node entities, and why it was included (the curation reason plus the classifier's
decision). Groups are (section, label); the id is a hash of the publication, statuses and references, so the same references give
the same digest.

## The synthesis

One call to GPT-6 Luna (`gpt-6-luna` through the OpenAI Responses API, strict JSON output, key from `OPENAI_API_KEY`). The model
sees references by handles (R1, R2, ...), the site's mission and policy, its allowed sections, its published stories from the last
`--story-days` (90) and its in-flight ones, earlier drafts, and optional reviewer feedback. An idea is kept only if it:

- cites at least two distinct references that exist in the digest,
- backs every claim with cited references it also lists,
- uses a section the site has, and avoids the banned words (`desk`).

Everything else is dropped and reported with its reason. Each kept idea has a working title, an angle paragraph, a section, the
cited references, claims, and a novelty note. Nothing in an idea is checked against the source pages beyond that tracing: a person
reviews it.

## Dedupe

Before saving, each idea is compared (cosine similarity over words and word pairs, weighted by rarity) with the site's recent and
in-flight stories, earlier drafts (the JSON store, and the site's `story_draft` Proposals with `--store proposals`), ideas a reviewer
declined, and ideas already kept in the same run. At or above `--dedupe-threshold` (0.5) the idea is dropped and the run records what
it resembled and the score. A model-embedding comparison can replace `similarity` in `ideas/dedupe.py` without touching the callers.

## Storage and privacy

Ideas are private by default.

- **`--store json` (default).** One JSON file per digest, idea and run under `~/.papyrus/ideas/<publication>` (or `--out`,
  `PAPYRUS_IDEAS_DIR`). The directory is refused if it sits inside `_data`, `public` or `static-root`.
- **`--store proposals`.** Each idea is filed as a `story_draft` Proposal in state `draft`, proposer AI, with the digest in the
  evidence. This needs the reader-steering plugin's Proposal model on the site. It works with an editor or admin session
  (`papyrus login`) and with `PAPYRUS_GRAPHQL_AUTH=iam` as an operator role of the site's own AWS account, so an unattended run can
  file drafts ([reader-steering.md](reader-steering.md#operator-filing)). Under IAM the proposer is still AI and the history records
  `operator:<principal ARN>`; the role needs `appsync:GraphQL` on `Mutation/fields/fileProposal`. Only editors and admins can read
  Proposals in full, but an operator may list the story drafts (`listStoryDrafts`: id, title, summary, targets, state and createdAt, nothing
  else, [reader-steering.md](reader-steering.md#operator-filing)), so an IAM run dedupes against earlier drafts held as Proposals as well as
  the JSON store, stories and declined ideas. That needs `appsync:GraphQL` on `Query/fields/listStoryDrafts` and a backend that has the
  query; a refused read fails the run instead of silently skipping the dedupe. Cited references are listed in the body,
  because proposal targets cannot name references.
- **Publishing is opt-in.** The reader snapshot used to publish every proposal in every state. It now writes
  `_data/proposals/` only when the site sets `proposals.publish: true` in its reader-steering config (default off). See
  [reader-steering.md](reader-steering.md#proposals). The ideas commands never call `proposals publish`.

## The run record

Every synthesis run saves a ledger (`runs/<run-id>.json`) and prints a summary: inputs counted (references by status, stories,
drafts, feedback entries), ideas proposed, invalid ideas dropped, near-duplicates dropped, ideas created, model, tokens (input,
cached, output) and cost in dollars. Cost uses the recorded price for the model ($0.10, $0.01 cached and $0.50 per million tokens
for `gpt-6-luna`, LiteLLM standard tier, read 2026-10-11). A run whose estimate is over `--max-cost-usd` (0.50) stops before the call.
`--report FILE` writes the ideas and the drop lists as markdown.

## Human review

Review goes through review requests ([review-requests.md](review-requests.md)) and shows in the Notification Center.

- **Raising.** When a run creates ideas, `request_human_review(client, run, ideas)` in `ideas/review.py` calls `raise_batch_review`: ONE
  soft review per run, "N new story ideas to review", 7-day deadline, subject `{batch, <run id>}`, idempotent per run. Ideas filed as
  Proposals are linked by Proposal id. Ideas kept as JSON are linked by idea id, which the console cannot open: a limit of the JSON
  store. A run with no ideas raises nothing.
- **Reading back.** At the start of a run, `steering_for(client, raised_by="idea-pipeline")` returns what editors said about earlier
  batches. Each answer becomes reviewer feedback for every idea that batch held (reject = decline, approve = accept, feedback =
  revise, with any note and steer). The model sees it, and a declined idea is not proposed again. After the model call the run calls
  `mark_applied`, so the console shows "Applied in run Y". A run that makes no model call leaves the steering unapplied.
- **Manual override.** `--feedback FILE` (a JSON list of `{title, verdict: accept|decline|revise, note}`) is merged after the steering
  and wins for the same title.
- **Sites without the review models.** A site that has not deployed review requests cannot take a request. The run keeps its ideas and
  records `review: {status: not_raised, error}` and `steering.error`; nothing fails.

## Trend stories

`papyrus ideas trends` turns the weekly knowledge snapshot ([knowledge-snapshot.md](knowledge-snapshot.md)) into story drafts. This is
the automated trend-story path of PPY-8ffc18 (story PPY-fb4dfa). The flow:

1. **Snapshot.** `--snapshot` is one of: a weekly archive entry (`.../_data/knowledge/history/2026-10-19.json`, self-contained), an
   `index.json`, or the `_data/knowledge/` directory or address (it reads `index.json`, `clusters.json`, `entities/<key>.json` and, for the
   cluster item counts of the last archived week before this one, `history/`). Paths and `http(s)` addresses both work.
2. **Signals, no model.** Up to 6 named clusters (growing, new, cooling, then the rest) and entities chosen by `select_entities`, from the
   index's eight-week series (the published `trending` order is not used, so the selection works on any snapshot, old or new). A signal carries what the snapshot holds: the weekly counts with their week dates, the
   four-week change (`percent` is null on a small base and the model is told so), neighbours of an entity, the previous archived week's
   item count of a cluster. Signal ids are `cluster:<uid>` and `entity:<key>`; the model sees handles S1, S2, ....

   **Which entities (`select_entities`).** Raw counts mislead: a licence, a task or a platform has the biggest count every week and rises with
   the corpus. Each entity with at least 3 mentions in the last four weeks is scored by Poisson surprise over its own prior four weeks, scaled by the growth of the
   corpus's total weekly mentions (the same function as the snapshot's `trending`, [knowledge-snapshot.md](knowledge-snapshot.md)), times a weight by kind.
   Then:

   - **Anchors**: the best 8 whose kind may anchor (`maker`, `model_family`, `model`, `concept`, `technique`) and whose weighted score is at least 1.0. Licence, task and platform never anchor.
   - **Notable makers only.** A maker anchors only if it is on the watchlist, or the site has an item about it in the window, or at least 2 of its models were recorded in the window with likes adding up to 100 or downloads to 10,000, and in either case at least 10 likes (downloads alone are not notability) (read from the records' summaries in the entity file, the newest 12 of them). One individual with a handful of small fine-tunes cannot anchor a draft, however sharp the jump looks.
   - **Context**: up to 2 broad-kind entities (licence, task, platform) that sit beside the anchors (their neighbours, most connected first). They carry `role: "context"` in the model's input, and the prompt says a context signal may be cited for where the releases sit but is never the subject of a headline or dek.
   - The run record keeps `selection` (anchors with their scores and why a maker is notable, entities passed over with the reason, the thresholds), so a person can see who was left out.

   **Thresholds** are configuration with these defaults (`TrendConfig`): `minimum_recent` 3, `minimum_score` 1.0, `baseline_smoothing` 1.0, `broad_kind_weight` 0.2, `other_kind_weight` 0.7, `minimum_models` 2, `minimum_likes` 100, `minimum_downloads` 10000, `likes_floor` 10, `window_days` 28, `cooldown_days` 7, `watchlist` (entity keys or names, lower-cased; empty), `broad_kinds`, `preferred_kinds`, `anchor_kinds`. Override them with `--trend-config FILE`, a JSON object of those names (for example `{"watchlist": ["maker--nvidia"], "minimum_likes": 50}`); an unknown name is refused.

   **Items, the releases behind a signal.** An entity signal also carries up to 5 **items**: the entity file's `relatedItems` published in
   the four weeks to the end of the snapshot's week (newest first). Each has its title, date, site path and, when the snapshot is read from
   an `http(s)` address, its site URL and a one-line summary, which is the first block-quote line of the item's published Markdown
   (`<item url>.md`; a page that cannot be read is only a missing summary). Item ids are `item:<path>`; the model sees handles I1, I2, ...
   once per distinct item (at most 40 in total, so the input stays far under the 120,000-character limit) and the signals each item sits
   behind. The snapshot publishes no member list for a cluster, so a cluster signal has no items. A snapshot read from a local file has no
   site address, so its items carry titles and dates but no summaries or URLs.

   **Monitor records as items.** When the site counts monitor records ([knowledge-cloud-run.md](knowledge-cloud-run.md#monitor-records-optional-off-by-default)), the entity file also has `relatedRecords`, and an entity signal's items include up to 3 of them in the same four weeks, after the site's own items. A record is a release recorded from a monitored source, not a story: its item has the model id as title, the release date, the source's own card as its address (never fetched), a one-line `summary` built from the structured fields (task, maker, licence, likes, downloads, base models), and `from` (`from the Hugging Face Hub`). The model sees `from` and is told to call it a release or a model and never something the publication published; the citation check treats its title, summary and date like any item's, so a number in a sentence citing it must be in that summary.
3. **Draft.** One call to GPT-6 Luna (same model, transport, prices and `--max-cost-usd` cap as `synthesize`; 12,000 output tokens, because
   three cited drafts and the reasoning ran past the 6,000 of the other commands). The prompt asks for a story an informed reader would find
   new: what shipped, who made it, what is different about it and what the pattern across the releases suggests, in plain specific prose that
   leads with the releases and uses the counts as support, with any interpretation framed as "suggests" and tied to cited items. The
   headline names the concrete thing. The headline, the dek and each body sentence are separate entries, each with the handles (S for a
   signal, I for an item) it rests on. The model also names one to three cited signals to chart and
   writes the chart title and caption; it never supplies chart data.
4. **Citation check, deterministic.** A draft is kept only if every entry (headline and dek included):
   - cites at least one handle and every handle is a signal or an item in the input (`no_citation`, `unknown_signal:S99`, `unknown_signal:I9`);
   - is one sentence, writes no handle in its text, and has no banned word;
   - holds only numbers and ISO dates that appear in the signals and items it cites (an item's title, summary and date count). A date's month and day never ground a bare number, so "3" must be
     a count the signal holds (`number_not_in_cited_signals:40`). The same rule applies to the figure title and caption;

   and the draft as a whole cites 2 to 10 signals (items never count toward the two), has at least 3 body sentences, a section the site has, and 1 to 3 figure signals that it
   cites. Number words ("four") are not checked; the prompt asks for digits. A failing draft is **not filed**. The run record
   (`invalid[]`) has its headline and a `citationCheck` listing each problem with the sentence (`where`, `reason`, `text`). A passing draft
   keeps its `citationCheck` (`status: passed`, sentences, signals cited) and every sentence with its signal ids (`sentences[]`).
5. **Dedupe.** Near-duplicates of recent and in-flight stories, earlier drafts and earlier kept ones, as for `synthesize`. Then **same
   targets**: a draft whose target set is identical to an earlier non-declined `story_draft` Proposal (an editor reads them in full, an IAM
   operator through `listStoryDrafts`) or to a trend draft in the JSON store is dropped (`same_targets`). A declined one does not block.
   Before the model is asked there is also a **cooldown** (step 2): an entity that anchored a non-declined draft in the last `cooldown_days`
   (default 7, `--cooldown-days N`, 0 is off) cannot anchor another, so a daily run does not write about the same maker every day. The
   run record's `cooldown` lists the entities cooling down with the date of the draft each anchored, and `selection.excluded` says
   `cooldown: anchored a story draft filed <date>`. A broad kind is only ever context, so it never cools down.
6. **File.** A `story_draft` Proposal in state `draft`, proposer `ai` (shown as AI), with these fields:

   | Field | Value |
   | --- | --- |
   | `title` | the headline (200 characters) |
   | `summary` | the dek (300 characters) |
   | `body` | the dek and paragraphs with `[n]` markers after each sentence (signals are numbered first, then the cited items), a `## Figure` section (title, caption, the series values), `## Signals cited` (number, readable fact, link, signal id), `## Sources` (number, item title, date and URL; only when an item is cited) and the section |
   | `targets` | one per cited signal (never an item): `{type: "cluster", id: <uid>}` or `{type: "entity", id: <entity key>}` (at most 10) |
   | `evidence` | `{signals: <n cited>, source: "knowledge snapshot <asOf> (<site>), papyrus ideas trends", figure: {...}}` |

   The figure spec is drawn by code from the cited signals' weekly counts, never from model output:

   ```json
   {"type": "line", "title": "Items per week", "caption": "Hugging Face peaked at 7 items in one week.", "unit": "items per week",
    "source": "knowledge snapshot 2026-10-19", "x": ["2026-08-31", "...", "2026-10-19"],
    "series": [{"signal": "entity:platform--hugging-face", "label": "Hugging Face", "values": [1, 2, 3, 4, 7, 3, 3, 2]}]}
   ```

   `x` is the Monday of each ISO week, oldest first, ending with the snapshot's week; every series has one value per `x`; one to three series.
   The reader-actions function keeps `evidence.figure` only when it has this shape (type `line` or `bar`, title, caption, unit, source, 2 to 60
   weeks, 1 to 6 series, numeric values, 8,000 bytes at most; otherwise `invalid_evidence`), and drops unknown keys. A site that has not deployed
   a backend with this release drops the figure silently (the body still lists the series values), so deploy before the first real run.
   The figure is published only if the site publishes proposals (`proposals.publish`), like the rest of the Proposal.
7. **Review.** One soft review request per run through the same `request_human_review` ("N new trend story drafts to review", 7 days,
   subject `{batch, <run id>}`, links the Proposals). Approving the Proposal (`papyrus proposals approve`, after an editor moves it through
   steering and review) approves the copy and the figure together. The command never transitions, approves or publishes anything. The
   trend drafts are also kept in the JSON store, so an editor's answer to the batch reaches the next `synthesize` run as feedback.

```bash
papyrus ideas trends --site <site> --snapshot https://<site host>/_data/knowledge/ --store proposals --dry-run
papyrus ideas trends --site <site> --snapshot ./history/2026-10-19.json --store proposals --max 3 --report trends.md
```

`--site` is the key of the JSON store directory and the run record (use the same key as `--publication` so the stores are shared). The
command reads the site's mission, policy, sections and stories through the CMS (a `papyrus login` session or `PAPYRUS_GRAPHQL_AUTH=iam`,
as above) and needs `OPENAI_API_KEY`. **`--dry-run`** does everything but file: it calls the model, runs the citation check and prints each
passing draft in full and each failing draft with its problems; it stores nothing, files nothing and requests no review. Other options:
`--max N` (3), `--trend-config FILE`, `--cooldown-days N` (7; 0 is off), `--window-days N` (7, 14, 21 or 28; default 28, the last N days against the N before, counted in whole weeks of the snapshot's weekly series; a shorter window gives the signals `items_last_<n>_weeks` and `items_prior_<n>_weeks`, and the items behind them are those inside the window), `--model`, `--dedupe-threshold`, `--max-cost-usd`, `--story-days`, `--out`, `--report FILE`, `--json`.

Limits: the check proves that every sentence points at the snapshot and that its digits come from the signals it cites; it does not prove
that the sentence reads the signal correctly, so an editor still reads every draft. Snapshot counts are the site's own published items and, for a site that counts them, monitor records.
The weekly cloud knowledge run can run this command after it publishes the snapshot, off by default ([knowledge-cloud-run.md](knowledge-cloud-run.md#trend-drafts-optional-off-by-default)).

## Monitor stories

`papyrus ideas monitor-stories` writes about the items a site's **monitors** found ([monitoring in the cloud](monitoring-cloud.md)). A monitor
delivers pending `Reference`s into the site's canonical knowledge corpus (`knowledge-corpus-<site>`), each with a provenance Message linked by an
`ingestion_rationale` relation whose metadata names the monitor (`monitorId`: `hn`, `huggingface`, an email intake) and may carry the source's
structured `details`. Most of what arrives is never written about. This command picks the few most worth a story and files one cited draft for each.
It is the same for every monitor: no source is named in the code, so a new site with any monitoring source uses it by configuration alone.

1. **Read.** References of the site that arrived in the window (`--since`, default 7d), pending or accepted (a rejected one is never read),
   that a monitor delivered (a Reference with no `monitorId` provenance is not a monitored item), that no item carries yet (a promoted record,
   [monitoring-cloud.md](monitoring-cloud.md#promoting-a-record-to-an-item)) and that no earlier draft cites. A Reference the relevance Cyclotron judged *not*
   relevant is left out. The run record counts each kind left out.
2. **Rank.** The source-agnostic signal is the Cyclotron's verdict, which the router records per delivered item as a `relevance_decision_is`
   `SemanticRelation` from the Reference to the node `relevance.<label>` ([cyclotron-priming.md](cyclotron-priming.md), [monitoring-cloud.md](monitoring-cloud.md)): the label, and `score`, the probability of the positive label
   (the decision's `metadata.positiveLabel`, `include` when it names none). The order is: judged relevant before not judged; a higher score
   before a lower one; then, only to break a tie, the source's own numbers when the item has them (`likes`, then `downloads`, in `SECONDARY_SIGNALS`);
   then the newest arrival; then the Reference id, so the same input always gives the same order. An item with no verdict (a site whose monitor runs
   without the Cyclotron) ranks after the scored ones.
3. **Fetch.** The linked page as plain text (a meta description and a few paragraphs, 4,000 characters at most) through the digest's reader, which
   only reads public http(s) addresses. A page that cannot be read is not an error: the story then rests on the title and the details the monitor stored
   (a `summary` or `description`, and the simple facts such as numbers and short text). An item with nothing but a title is skipped with the reason
   `no_source_text` and no model call, because a story needs something to stand on.
4. **Draft.** One call to the repository's default model (`gpt-6-luna`, `--model` overrides) per item, through the same transport as the trends path.
   The model sees the site's mission and policy, its allowed sections, the source (handle `I1`: title, address, monitor, dates, summary, facts, page text)
   and the recent and in-flight stories. It does not see the relevance score. It writes a headline, a dek and one or two short paragraphs, every
   sentence its own entry with `cites: ["I1"]`.
5. **Check.** The Cited Trends sentence check, `trends.check_sentence`, shared and not copied: a sentence with no handle or an unknown one, more than one sentence in an
   entry, a handle written in the text, a banned word, or a number or ISO date that is not in the source it cites fails the whole draft. The draft also needs at
   least two body sentences, at most three paragraphs and a section from the allowed list. Because the only handle is the source, every sentence cites the source.
   A failing draft is not filed; the run record says which sentence failed and why, and the next ranked item takes its place (at most twice `--limit` attempts a run).
6. **File.** The record has the shape of a trend draft and goes through the same `ProposalStore.file_story_draft` (formerly `file_trend_draft`) as a `story_draft` Proposal in state
   `draft`, proposed by AI, with `request_human_review` raising one soft review request for the run ("N new monitor story drafts to review", 7 days). Under IAM the
   operator path is the one trends use: `fileProposal` and the read-only `listStoryDrafts`.

   | Field | Value |
   |---|---|
   | `title`, `summary` | the headline (200 characters) and the dek (300) |
   | `body` | Markus: the dek, the paragraphs with `[1]` after each sentence, `## Source` with the title, the date and the address, and a closing line that names the monitor ("Drafted by AI from an item the hn monitor found") and the relevance verdict |
   | `targets` | `[{"type": "entity", "id": "reference:<Reference lineage id>"}]` |
   | `evidence` | `{signals: 1, source: "<monitor> monitor: <address>"}` |

   The target is how a later run knows the Reference is drafted: the operator can read targets (not bodies) through `listStoryDrafts`, a declined draft keeps
   its target, and the Proposal model has no target type for a Reference, so the `entity` type carries an id that no Knowledge Map entity has. It is
   also how the JSON store (`ideas/<id>.json`, `referenceLineageId`) and the Proposals agree. A Reference is never drafted twice, whatever happened to its draft.

```bash
papyrus ideas monitor-stories --site <site> --dry-run
papyrus ideas monitor-stories --site <site> --limit 3 --since 7d --store proposals --report monitor-stories.md
```

`--limit N` (default 3) is the number of stories wanted, `--since` the window (`7d`, `36h`), `--store json|proposals` (default `json`; the cloud step uses `proposals`),
`--dry-run` calls the model and checks but stores, files and requests nothing and prints each passing draft, `--model`, `--dedupe-threshold` (near-duplicates of
existing stories and earlier drafts are dropped, as for trends), `--max-cost-usd` (the run stops before a call that would pass it; `stoppedForCost` in the run record),
`--story-days`, `--out`, `--report FILE`, `--json`. It needs `OPENAI_API_KEY` (or `openai.apiKey` in the Papyrus config) and a `papyrus login` session or
`PAPYRUS_GRAPHQL_AUTH=iam`. The run record has the ranking (the first `2 x limit` candidates with their verdicts), the counts, the drafts, the failures with their
problems, `modelCalls` (the usage of each call, for the ledger) and the cost. The weekly cloud knowledge run can run it after the trend drafts, off by default
([knowledge-cloud-run.md](knowledge-cloud-run.md#monitor-stories-optional-off-by-default)).

Limits: the check proves each sentence points at the source and that its digits come from it; it does not prove the sentence reads the source correctly,
so an editor reads every draft. Turning an approved draft into a story is a later step; nothing here transitions, approves or publishes a Proposal.

## Friction for the run contract

Notes from running v0 by hand, for PPY-433383 (run contract) and PPY-93faf2 (local-pod runtime):

- **No site registry.** The operator has to find each site's AppSync endpoint (the API's `amplify:app-id` tag is the only link to the
  app) and export `PAPYRUS_GRAPHQL_ENDPOINT`. An automation needs the site, endpoint, account and credential source as data.
- **Credentials.** The SSO session often needs `aws configure export-credentials` before botocore signs requests. A scheduled local
  run needs a non-interactive credential source.
- **Filing Proposals under IAM is narrow.** An operator role of the site's own account can file AI proposals and move a draft to
  `in_steering` or `declined`; it cannot read Proposals or take an editor action. The run contract still needs the role named as
  data, and a way to dedupe against earlier Proposals without reading them.
- **Dedupe memory is local.** Earlier drafts come from the JSON store on one machine (or the site's Proposals). A run on another
  machine, or a Lambda, would not see them unless it uses the Proposal store.
- **The run ledger is a local JSON file,** not a `ProcedureRun` record, so the console cannot list these runs yet.
- **The OpenAI key comes from the operator's environment.** Cloud runtimes read per-site SSM parameters; the local one does not.
- **Monitors deliver `pending` references,** and only accepted ones are evidence, so an unattended pipeline reads nothing until
  someone accepts references or a site adopts an auto-accept policy. `--status accepted,pending` is the v0 workaround.

## Running without a cloud backend

These are local commands against a cloud CMS. A site with no cloud backend (a local pod) has no `Reference` store to read, so the
digest does not run there; that waits for the local-pod runtime (PPY-93faf2) and the run contract (PPY-433383). Scheduling goes
through automations on that contract.
