# Idea pipeline (v0)

`papyrus ideas digest` and `papyrus ideas synthesize` turn a site's recent references into private story ideas. This is the first
version of PPY-8ffc18: a digest and a synthesis, run by hand against the cloud CMS. Scheduling, weekly trends and human review
come later. Executable spec: `features_backend/idea-pipeline.feature`; unit tests: `procedures/newsroom/tests/test_ideas.py`.

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
  evidence. This needs the reader-steering plugin's Proposal model on the site and an editor or admin session
  (`papyrus login`): `fileProposal` is not open to IAM. Cited references are listed in the body, because proposal targets cannot
  name references.
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

## Friction for the run contract

Notes from running v0 by hand, for PPY-433383 (run contract) and PPY-93faf2 (local-pod runtime):

- **No site registry.** The operator has to find each site's AppSync endpoint (the API's `amplify:app-id` tag is the only link to the
  app) and export `PAPYRUS_GRAPHQL_ENDPOINT`. An automation needs the site, endpoint, account and credential source as data.
- **Credentials.** The SSO session often needs `aws configure export-credentials` before botocore signs requests. A scheduled local
  run needs a non-interactive credential source.
- **Filing Proposals is not open to IAM.** `fileProposal` checks the editor or admin group, so an unattended run cannot file
  Proposals today; only a person with a `papyrus login` session can. The run contract needs either a service identity the function
  accepts or a different way to hand ideas to review.
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
