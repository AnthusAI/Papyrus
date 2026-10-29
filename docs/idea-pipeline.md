# Idea pipeline (v0)

> **Cited Trends** is the name for the trend-story path below: story drafts about what is rising or cooling in the weekly Knowledge Map, with every sentence cited and checked by code, filed as AI Proposals for people to steer. See [feature-names.md](feature-names.md#cited-trends). Shipped files them as example drafts at <https://shipped.anth.us/proposals/>. Approving a draft does not yet create a story.

`papyrus ideas digest` and `papyrus ideas synthesize` turn a site's recent references into private story ideas. This is the first
version of PPY-8ffc18: a digest and a synthesis, run by hand against the cloud CMS. `papyrus ideas trends` adds the trend-story path
([below](#trend-stories)). Scheduling comes later. Executable specs: `features_backend/idea-pipeline.feature`,
`features_backend/idea-trend-stories.feature`, `features_backend/idea-monitor-stories.feature`; unit tests: `procedures/newsroom/tests/test_ideas.py`, `test_idea_trends.py`, `test_monitor_stories.py`, `test_excluded_hosts.py`; excluded source hosts: `features_backend/idea-excluded-source-hosts.feature`.

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
  evidence. Every site's backend has the Proposal model (it is core, not part of the reader-steering plugin), so this needs only a backend on a release that includes it. It works with an editor or admin session
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
  soft review per run, "N new story ideas to review", no deadline (it stays open until handled), subject `{batch, <run id>}`, idempotent per run. Ideas filed as
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
   index's weekly series (`seriesWeekly`, the full history from the entity's first week, else `series26`, the last 26 weeks; a snapshot that only has `series8` is scanned over those eight; the published `trending` order is not used, so the selection
   works on any snapshot, old or new). A signal carries what the snapshot holds: the weekly counts with their week dates, for an entity the
   window the scan chose and its counts (below), neighbours of an entity, the previous archived week's
   item count of a cluster. Signal ids are `cluster:<uid>` and `entity:<key>`; the model sees handles S1, S2, ....

   **Which entities (`select_entities`).** Raw counts mislead: a licence, a task or a platform has the biggest count every week and rises with
   the corpus. So each entity is scanned for its most surprising recent window, with no fixed span:

   - **Adaptive window (a scan statistic).** The most recent 1, 2, 4, 8, 16, ... weeks are each tried as the window, against everything before
     it, as long as at least `minimum_baseline_weeks` (4) weeks of baseline remain (26 weeks of history give 1, 2, 4, 8 and 16). A spike is
     found at 1 week, a slow build at 16.
   - **Surprise of a window.** The exact conditional test for two Poisson counts: with `count` mentions in the window and `baseline` in the
     weeks before, if the entity's rate had not changed each of the `count + baseline` mentions falls in the window with probability
     `share`, the window's part of the corpus's total volume (the sum of every entity's weekly counts) in window and baseline together, so a
     corpus that grows is not a trend. `count` is then Binomial and the p-value is its upper tail. Unlike comparing the count with a plug-in
     expectation it allows for a baseline rate estimated from few weeks.
   - **Correction for trying several windows: Bonferroni.** The smallest p-value of the windows tried is multiplied by their number and capped at one.
     Taking the best of several windows would otherwise flag plain noise. Bonferroni is the simplest correction that is sound whatever the
     dependence between the windows (nested windows are strongly dependent, so it is conservative, never liberal); it needs no random draws, so the
     same snapshot gives the same signals (a permutation or Monte Carlo calibration would be tighter but needs a seed and a run time, for at most five windows);
     and at five windows it costs little power. Over 500 simulated steady entities, at most one in a hundred passes the default level.
   - **Score.** The z-score of the corrected p-value times a weight by kind (broad kinds are demoted). The entity needs at least `minimum_recent` (3) mentions in
     its chosen window. It is a trend only when the corrected p-value is within `significance` (0.01).
   - **Reported.** The chosen window is part of the signal (`windowWeeks`, `windowCount`, `baselineWeeks`, `baselineCount`). The model sees
     `window_weeks`, `items_in_window`, `weeks_before_window` and `items_before_window` and the full weekly history, and is told to say the span as it is ("rising over the last 4 weeks"); the
     cited signals list in the body says "32 items in the last 2 weeks against 12 in the 24 weeks before (about 4.07 expected; p=2.9e-23 after correcting for 5 windows tried)".
     No percentage is offered. Because the chart needs the same length for every signal it still draws the last eight weeks.
   Then:

   - **Evidence, not days.** An entity that already anchored a draft (any state, declined included) anchors another only when its window now holds significantly more than that draft reported; see step 5.
   - **Anchors**: the best 8 whose kind may anchor (`maker`, `model_family`, `model`, `concept`, `technique`) and whose weighted score is at least 1.0 and whose corrected p-value is within `significance`. Licence, task and platform never anchor.
   - **Notable makers only.** A maker anchors only if it is on the watchlist, or the site has an item about it in its chosen window, or at least 2 of its models were recorded in the window with likes adding up to 100 or downloads to 10,000, and in either case at least 10 likes (downloads alone are not notability) (read from the records' summaries in the entity file, the newest 12 of them). One individual with a handful of small fine-tunes cannot anchor a draft, however sharp the jump looks.
   - **Context**: up to 2 broad-kind entities (licence, task, platform) that sit beside the anchors (their neighbours, most connected first). They carry `role: "context"` in the model's input, and the prompt says a context signal may be cited for where the releases sit but is never the subject of a headline or dek.
   - The run record keeps `selection` (anchors with their scores and why a maker is notable, entities passed over with the reason, the thresholds), so a person can see who was left out.

   **Thresholds** are configuration with these defaults (`TrendConfig`): `minimum_recent` 3, `minimum_score` 1.0, `broad_kind_weight` 0.2, `other_kind_weight` 0.7, `minimum_models` 2, `minimum_likes` 100, `minimum_downloads` 10000, `likes_floor` 10, `minimum_baseline_weeks` 4, `significance` 0.01, `watchlist` (entity keys or names, lower-cased; empty), `broad_kinds`, `preferred_kinds`, `anchor_kinds`. Override them with `--trend-config FILE`, a JSON object of those names (for example `{"watchlist": ["maker--nvidia"], "minimum_likes": 50}`); an unknown name is refused.

   **Items, the releases behind a signal.** An entity signal also carries up to 5 **items**: the entity file's `relatedItems` published in
   its chosen window, the weeks to the end of the snapshot's week (newest first). Each has its title, date, site path and, when the snapshot is read from
   an `http(s)` address, its site URL and a one-line summary, which is the first block-quote line of the item's published Markdown
   (`<item url>.md`; a page that cannot be read is only a missing summary). Item ids are `item:<path>`; the model sees handles I1, I2, ...
   once per distinct item (at most 40 in total, so the input stays far under the 120,000-character limit) and the signals each item sits
   behind. The snapshot publishes no member list for a cluster, so a cluster signal has no items. A snapshot read from a local file has no
   site address, so its items carry titles and dates but no summaries or URLs.

   **Monitor records as items.** When the site counts monitor records ([knowledge-cloud-run.md](knowledge-cloud-run.md#monitor-records-optional-off-by-default)), the entity file also has `relatedRecords`, and an entity signal's items include up to 3 of them in the same window, after the site's own items. A record is a release recorded from a monitored source, not a story: its item has the model id as title, the release date, the source's own card as its address (never fetched), a one-line `summary` built from the structured fields (task, maker, licence, likes, downloads, base models), and `from` (`from the Hugging Face Hub`). The model sees `from` and is told to call it a release or a model and never something the publication published; the citation check treats its title, summary and date like any item's, so a number in a sentence citing it must be in that summary.
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
   operator through `listStoryDrafts`) or to a trend draft in the JSON store is dropped (`same_targets`), unless it rests on an entity whose evidence was renewed (below). A declined one does not block here;
   an entity anchor is guarded by the evidence rule instead, so a declined trend is not proposed again without new evidence, and a draft that only cites clusters is guarded by this check.
   Before the model is asked there is also the **repeat rule** (step 2), which uses evidence and not a count of days. An entity that already
   anchored a draft, in any state (a declined one included), anchors another only when its evidence now materially exceeds what that
   draft reported:

   - What a draft reported is the window it chose: its length and its count. A trend draft keeps it in its evidence (`evidence.windows`, one
     per cited entity: `signal`, `windowWeeks`, `count`, `baselineWeeks`, `baselineCount`, `expected`, `pValue`, `correctedPValue`, `tested`), in the JSON store. A Proposal carries only the
     evidence keys the reader-actions function keeps (it drops unknown keys, and an IAM operator's `listStoryDrafts` returns no evidence at all), so a
     draft without a stored window is rebuilt from the data: the same scan over the entity's series and the corpus volume cut off at the week the draft was made (its snapshot's
     week, else its filing week). Scanning is deterministic, so that is the window the run chose then. A draft made before the history reaches back far enough to scan reports nothing.
     When several drafts anchored on an entity, the one with the highest weekly rate is the one to beat.
   - Materially more means the same test as the scan: the new window's `count` against the reported `count` (each mention of the two falls in
     the new window with probability `L / (L + L_reported)`; Binomial upper tail), multiplied by the number of windows tried, within `significance`. The same
     rate over a longer window is not new (6 in a week, then 12 in two weeks); a few more is not new (6 then 7); a surge several times larger is (6 then 40).
   - The entity is passed over in `selection.excluded` with `no new evidence: the draft filed <date> (<state>) reported <n> in <L> week(s); now <n> in <L> (p=..., needs <= 0.01)`.
     The run record's `priorDrafts` lists every anchor candidate that has an earlier draft: what it reported, what the data says now, the p-value and whether it was `renewed`. A renewed
     anchor is not dropped by the same-targets check below. A broad kind is only ever context, so it never has a prior draft to beat. There is no day count and no `--cooldown-days`.
6. **File.** A `story_draft` Proposal in state `draft`, proposer `ai` (shown as AI), with these fields:

   | Field | Value |
   | --- | --- |
   | `title` | the headline (200 characters) |
   | `summary` | the dek (300 characters) |
   | `body` | the dek and paragraphs with `[n]` markers after each sentence (signals are numbered first, then the cited items), a `## Figure` section (title, caption, the series values), `## Signals cited` (number, readable fact, link, signal id), `## Sources` (number, item title, date and URL; only when an item is cited) and the section |
   | `targets` | one per cited signal (never an item): `{type: "cluster", id: <uid>}` or `{type: "entity", id: <entity key>}` (at most 10) |
   | `evidence` | `{signals: <n cited>, source: "knowledge snapshot <asOf> (<site>), papyrus ideas trends", figure: {...}, windows: [...]}`; `windows` (the window each cited entity reported) is kept in the JSON store, and the Proposal keeps the keys its function allows |

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
7. **Review.** One soft review request per run through the same `request_human_review` ("N new trend story drafts to review", no deadline,
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
`--max N` (3), `--trend-config FILE` (`--window-days` and `--cooldown-days` are retired and refused: the window comes from the data and a repeat needs new evidence), `--model`, `--dedupe-threshold`, `--max-cost-usd`, `--story-days`, `--out`, `--report FILE`, `--json`.

Limits: the check proves that every sentence points at the snapshot and that its digits come from the signals it cites; it does not prove
that the sentence reads the signal correctly, so an editor still reads every draft. Snapshot counts are the site's own published items and, for a site that counts them, monitor records.
The weekly cloud knowledge run can run this command after it publishes the snapshot, off by default ([knowledge-cloud-run.md](knowledge-cloud-run.md#trend-drafts-optional-off-by-default)).

## Monitor stories

`papyrus ideas monitor-stories` writes about the items a site's **monitors** found ([monitoring in the cloud](monitoring-cloud.md)). A monitor
delivers pending `Reference`s into the site's canonical knowledge corpus (`knowledge-corpus-<site>`), each with a provenance Message linked by an
`ingestion_rationale` relation whose metadata names the monitor (`monitorId`: `hn`, `huggingface`, an email intake) and may carry the source's
structured `details`. Most of what arrives is never written about. This command picks the few most worth a story and files one cited draft for each.
It is the same for every monitor: no source is named in the code, so a new site with any monitoring source uses it by configuration alone.

1. **Read.** Every Reference of the site, however old (there is no default window; `--since` is an optional filter and the cloud step passes none; the index is paged to the end), **accepted** (by an editor, or automatically: [automatic acceptance](monitoring-cloud.md#automatic-acceptance)). Pending References are left out and counted as `notAccepted` in the run record; `--status accepted,pending` reads them too, and a rejected one is never read. The cloud step uses the default,
   that a monitor delivered (a Reference with no `monitorId` provenance is not a monitored item), that no item carries yet (a promoted record,
   [monitoring-cloud.md](monitoring-cloud.md#promoting-a-record-to-an-item)) and that no earlier draft cites. A Reference the relevance Cyclotron judged *not*
   relevant is left out. The run record counts each kind left out. Reading costs two indexed queries per Reference (its provenance, then its decision; the decision is skipped for a Reference an earlier draft already cites) on one connection, so a corpus of a few thousand References takes minutes, not seconds.
2. **Rank.** The source-agnostic signal is the Cyclotron's verdict, which the router records per delivered item as a `relevance_decision_is`
   `SemanticRelation` from the Reference to the node `relevance.<label>` ([cyclotron-priming.md](cyclotron-priming.md), [monitoring-cloud.md](monitoring-cloud.md)): the label, and `score`, the probability of the positive label
   (the decision's `metadata.positiveLabel`, `include` when it names none). The order is: judged relevant before not judged; a higher score
   before a lower one, where the score is multiplied by a **freshness weight** `exp(-age / tau)` (age in days at the run) and `tau` is learned per site from its editors' own decisions: the median age at curation (`curationStatusUpdatedAt` minus arrival) of the monitored References they accepted, divided by ln 2 (for an exponential the median is `tau * ln 2`). With fewer than 10 such examples there is no weight at all (the score alone ranks, newest arrival breaking ties); no constant is guessed. An old, highly relevant item is therefore never excluded, only ranked lower when this site's editors tend to act fast. The run record's `freshness` holds `tauDays`, `medianAgeDays` and `examples` (or `tauDays: null` and a note); then, only to break a tie, the source's own numbers when the item has them (`likes`, then `downloads`, in `SECONDARY_SIGNALS`);
   then the newest arrival; then the Reference id, so the same input always gives the same order. An item with no verdict (a site whose monitor runs
   without the Cyclotron) ranks after the scored ones.
3. **Fetch.** The linked source as plain text, 4,000 characters at most (the model's input budget, not a limit on the source), through `ideas/source_text.py`, which
   only reads public http(s) addresses (redirects are re-checked, a PDF is capped at 8 MB). An HTML page gives its meta description and a few paragraphs. A
   PDF (by content type or a `.pdf` address) gives the text of its first four pages, which for a decision or a paper carries the caption, the holding and the
   summary of grounds, extracted by the shared `papyrus_content/pdf_text.py` (pypdf; the same helper is the `papyrus_fetch_pdf_text` Tactus tool, and it
   knows that a TTAB Reading Room document downloads at its double-slash address). An HTML page with little text of its own whose first PDF link is on the
   same host is read through that PDF. Details the monitor stored on the provenance relation (`details`) are facts for the model as before. A page that cannot be read is not an error: the story then rests on the title and the details the monitor stored
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
   `draft`, proposed by AI, with `request_human_review` raising one soft review request for the run ("N new monitor story drafts to review", no deadline). Under IAM the
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
papyrus ideas monitor-stories --site <site> --status accepted,pending --dry-run   # also the pending ones (default: accepted only)
papyrus ideas monitor-stories --site <site> --limit 3 --store proposals --report monitor-stories.md
# a site whose References live in a corpus of another name (knowledge-corpus-<key>):
papyrus ideas monitor-stories --site <site> --corpus-key <key> --dry-run
```

`--limit N` (default 3) is the number of stories wanted, `--since` an optional filter that leaves out older arrivals (`7d`, `36h`; no default), `--store json|proposals` (default `json`; the cloud step uses `proposals`),
`--dry-run` calls the model and checks but stores, files and requests nothing and prints each passing draft, `--model`, `--dedupe-threshold` (near-duplicates of
existing stories and earlier drafts are dropped, as for trends), `--max-cost-usd` (the run stops before a call that would pass it; `stoppedForCost` in the run record),
`--story-days` (how many days of the site's own recent stories the model is shown as context; it does not select items), `--out`, `--report FILE`, `--json`. It needs `OPENAI_API_KEY` (or `openai.apiKey` in the Papyrus config) and a `papyrus login` session or
`PAPYRUS_GRAPHQL_AUTH=iam`. The run record has the ranking (the first `2 x limit` candidates with their verdicts), the counts, the drafts, the failures with their
problems, `modelCalls` (the usage of each call, for the ledger) and the cost. The weekly cloud knowledge run can run it after the trend drafts, off by default
([knowledge-cloud-run.md](knowledge-cloud-run.md#monitor-stories-optional-off-by-default)).

**Daily, from the monitoring router.** Every publication the `hn` monitor lists also gets its monitor stories once a day with no knowledge-run stack and no configuration: the router task `monitor-stories`
([monitoring-cloud.md](monitoring-cloud.md#monitor-stories-daily)) runs this same code in process, at 07:30 UTC. It drafts **every** accepted, not yet drafted, monitored Reference (no `--limit`), best ranked first,
and is bounded only by the Lambda's remaining time, a per-run model-spend backstop and a filing error (`stoppedBy` in its log line). The Proposals and the soft review request are the same as the CLI's; a Reference
is never drafted twice, whichever path drafted it. A publication opts out with `"monitorStories": {"enabled": false}` in its router entry. Distinctive Mark has its own schedule; its TTAB References are drafted here unless its Automation has already made, or is making, the story.

Limits: the check proves each sentence points at the source and that its digits come from it; it does not prove the sentence reads the source correctly,
so an editor reads every draft. Turning an approved draft into a story is a later step; nothing here transitions, approves or publishes a Proposal.

## Turning a draft into a story

A `story_draft` Proposal that an editor (or an automation) accepts becomes a draft story at the copywriting stage with
`story_from_story_draft` (`src/papyrus_content/story_from_reference.py`). The story's body is the draft's own cited text, never the
source page's text, and the story is linked to every Reference the draft names in its `reference:` targets, as `based_on`
(`semantic-relation-type-uses-evidence`, by lineage ids). A body that repeats 12 or more consecutive words of a Reference's captured
text is refused. A `post` also gets the Reference's preview image, credited to its site. These are core rules of the automated
newsroom: [Stories based on a Reference](reference-curation-pipeline.md#6a-stories-based-on-a-reference-core-rules).

## Excluded source hosts

A site can list source hosts that must never be cited in an AI draft, for example a competing publication. In the site file:
`"knowledgeRun": {"excludedSourceHosts": ["ipwatchdog.com"]}`. The scheduled run passes them to `papyrus ideas trends` and
`papyrus ideas monitor-stories` as `--exclude-host HOST` (repeatable; a comma-separated value is several hosts; an address is reduced to its host). A host
matches itself and every subdomain (`ipwatchdog.com` matches `www.ipwatchdog.com`, not `notipwatchdog.com`).

**The site lists hosts explicitly.** Papyrus does not classify source hosts by kind (news, blog, publication) anywhere, so there is no
`excludedSourceKinds` setting. To exclude "any other blog or news-publication host", name each host.

- **Monitor stories.** A Reference whose `sourceUri` host is excluded is never read further and never a candidate. The run record counts them in
  `inputs.excludedHost` (also in the CLI summary line, the report and the ledger row's `details.result.excludedHost`) and lists the hosts in `excludedSourceHosts`.
- **Cited Trends.** An item (a published story or a recorded release) whose address is on an excluded host is never shown to the model as citable
  evidence and never appears in a draft's cited items or its Sources list. The run record counts them in `inputs.itemsExcludedByHost` and the signal
  names them in `excludedItemIds`. **The statistics still count them**: a signal's item counts, window counts and weekly history come from the published
  snapshot and describe the topic, not the source, so an excluded host's items can still make a topic rise. Only the evidence the story may cite and
  quote is filtered.
- **The citation check.** Defence in depth: a sentence that cites an excluded item fails with `cites_excluded_source_host:<handle>`, even though no
  excluded item is offered, so the draft is not filed.

### References an automation handles

Monitor stories skip a Reference only when an **Automation** of the site has really taken it on, so a site that turns monitor stories on does not get a second draft of
what the automation drafted or is drafting. A Reference counts as handled when a story is already `based_on` it (the `uses_evidence` relation, role `based_on`, read from the relations
the run already loads for each Reference), or, in the router task, when a monitor-triggered Automation (see [automations](automations.md)) has a procedure run for it that is completed, deferred
to start, or in flight (begun inside the run's timeout plus its grace period). They are counted in `inputs.handledByAutomation`. An Automation that is merely configured for the monitor
handles nothing: a Reference it never started a run for, or whose run failed, is drafted like any other. A story based on a Reference from a monitor no Automation is configured for is counted in `inputs.hasStory`.
The monitors enabled Automations are configured for are listed in the run record's `automatedMonitors`; a disabled Automation hides nothing. If the Automation records cannot be read the run goes
ahead and records `automationLookupError`. (The weekly knowledge run has no access to the router's trigger rows, so there only the `based_on` story counts.)

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
- **Monitors deliver `pending` references,** and only accepted ones are evidence. Monitor stories read only accepted References by default, so an
  unattended pipeline waits for an editor, or for the router's [automatic acceptance](monitoring-cloud.md#automatic-acceptance) (on by default, learned per
  publication). `--status accepted,pending` reads the pending ones too.

## Running without a cloud backend

These are local commands against a cloud CMS. A site with no cloud backend (a local pod) has no `Reference` store to read, so the
digest does not run there; that waits for the local-pod runtime (PPY-93faf2) and the run contract (PPY-433383). Scheduling goes
through automations on that contract.
