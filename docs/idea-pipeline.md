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

## Human review (not built yet)

`request_human_review(run, ideas)` in `ideas/review.py` is the single place a review will be raised. Today it logs
`review pending` and records `review: {status: pending, requested: false}` in the run. Reviewer feedback returns through
`--feedback FILE`, a JSON list of `{title, verdict: accept|decline|revise, note}`; synthesis shows it to the model and treats a
declined title as a reason not to propose that idea again.

## Running without a cloud backend

These are local commands against a cloud CMS. A site with no cloud backend (a local pod) has no `Reference` store to read, so the
digest does not run there; that waits for the local-pod runtime (PPY-93faf2) and the run contract (PPY-433383). Scheduling goes
through automations on that contract.
