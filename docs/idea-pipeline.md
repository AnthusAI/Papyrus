# Idea pipeline (v0)

`papyrus ideas digest` and `papyrus ideas synthesize` turn a site's recent references into private story ideas. This is the first
version of PPY-8ffc18: a digest and a synthesis, run by hand against the cloud CMS. `papyrus ideas trends` adds the trend-story path
([below](#trend-stories)). Scheduling comes later. Executable specs: `features_backend/idea-pipeline.feature`,
`features_backend/idea-trend-stories.feature`; unit tests: `procedures/newsroom/tests/test_ideas.py`, `test_idea_trends.py`.

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
  Proposals, so an IAM run cannot dedupe against earlier drafts held as Proposals: it skips them, says so in the run record
  (`proposalDedupe`), and still dedupes against the JSON store, stories and declined ideas. Cited references are listed in the body,
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
2. **Signals, no model.** Up to 6 named clusters (growing, new, cooling, then the rest) and up to 8 trending entities plus up to 3 new
   entities with at least 3 items in four weeks. A signal carries what the snapshot holds: the weekly counts with their week dates, the
   four-week change (`percent` is null on a small base and the model is told so), neighbours and related item titles of an entity, the
   previous archived week's item count of a cluster. Signal ids are `cluster:<uid>` and `entity:<key>`; the model sees handles S1, S2, ....
3. **Draft.** One call to GPT-6 Luna (same model, transport, prices and `--max-cost-usd` cap as `synthesize`). The headline, the dek and each
   body sentence are separate entries, each with the handles it rests on. The model also names one to three cited signals to chart and
   writes the chart title and caption; it never supplies chart data.
4. **Citation check, deterministic.** A draft is kept only if every entry (headline and dek included):
   - cites at least one handle and every handle is a signal in the snapshot (`no_citation`, `unknown_signal:S99`);
   - is one sentence, writes no handle in its text, and has no banned word;
   - holds only numbers and ISO dates that appear in the signals it cites. A date's month and day never ground a bare number, so "3" must be
     a count the signal holds (`number_not_in_cited_signals:40`). The same rule applies to the figure title and caption;

   and the draft as a whole cites 2 to 10 signals, has at least 3 body sentences, a section the site has, and 1 to 3 figure signals that it
   cites. Number words ("four") are not checked; the prompt asks for digits. A failing draft is **not filed**. The run record
   (`invalid[]`) has its headline and a `citationCheck` listing each problem with the sentence (`where`, `reason`, `text`). A passing draft
   keeps its `citationCheck` (`status: passed`, sentences, signals cited) and every sentence with its signal ids (`sentences[]`).
5. **Dedupe.** Near-duplicates of recent and in-flight stories, earlier drafts and earlier kept ones, as for `synthesize`. Then **same
   targets**: a draft whose target set is identical to an earlier non-declined `story_draft` Proposal (readable as an editor) or to a
   trend draft in the JSON store is dropped (`same_targets`). A declined one does not block. Under IAM the Proposals cannot be read, so that
   comparison is skipped and the run records `proposalDedupe`, as above.
6. **File.** A `story_draft` Proposal in state `draft`, proposer `ai` (shown as AI), with these fields:

   | Field | Value |
   | --- | --- |
   | `title` | the headline (200 characters) |
   | `summary` | the dek (300 characters) |
   | `body` | the dek and paragraphs with `[n]` markers after each sentence, a `## Figure` section (title, caption, the series values), `## Signals cited` (number, readable fact, link, signal id) and the section |
   | `targets` | one per cited signal: `{type: "cluster", id: <uid>}` or `{type: "entity", id: <entity key>}` (at most 10) |
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
`--max N` (3), `--model`, `--dedupe-threshold`, `--max-cost-usd`, `--story-days`, `--out`, `--report FILE`, `--json`.

Limits: the check proves that every sentence points at the snapshot and that its digits come from the signals it cites; it does not prove
that the sentence reads the signal correctly, so an editor still reads every draft. Snapshot counts are the site's own published items.
Trend drafts are not scheduled yet (PPY-8ffc18).

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
