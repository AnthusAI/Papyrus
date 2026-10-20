# Hacker News Monitor pilot

PPY-3212f1 implements a bounded local worker for the existing Reference intake.
It fetches the public HN RSS feed, registers pending References, and stores each
discovery's HN identity, source timestamp, URL, fingerprint and revision in a
private provenance Message linked to the Reference. Repeated discoveries reuse
the canonical Reference without resetting human curation. Each completed intake
is checkpointed separately so a later failure can be retried safely.

Run from the normal `papyrus` CLI using an explicitly selected existing worker
profile. This creates no credentials or access grants:

```sh
AWS_PROFILE=<existing-worker-profile> papyrus monitors run --config monitor.json --auth iam
papyrus monitors status --config monitor.json
```

Example configuration (use verified publication values):

```json
{
  "schemaVersion": 1,
  "monitorId": "hn",
  "publication": "example",
  "corpusId": "knowledge-corpus-example",
  "endpoint": "https://example.appsync-api.us-east-1.amazonaws.com/graphql",
  "state": "private-state/hn.sqlite3",
  "intervalSeconds": 900,
  "limit": 10
}
```

`publication` is the canonical corpus key. The worker verifies that the explicitly
selected endpoint has exactly one canonical corpus matching `corpusId`. An
optional `sourceIds` array restricts a review batch to HN item IDs; missing IDs
produce visible selection errors. The feed is bounded to 2 MB and 100 items per
run. References and provenance use the existing private GraphQL/S3 authoring
path. Source article bodies are not fetched by this adapter.

An existing scheduler can invoke `run` repeatedly: the checkpoint skips runs
before due. `--watch --max-runs 2` runs a bounded local scheduling loop.
`--force` permits one explicit recovery run. No scheduler is installed. SQLite
is only a private local worker checkpoint with a process lock; it is not a
hosted or distributed storage design. Keep one worker/checkpoint per Monitor.
The cloud deployment and distributed ownership remain separate work.

This worker requires explicit IAM operator selection. It never falls back from
editorial user authentication. Editorial-session intake is owned by
[PR367](https://github.com/AnthusAI/Papyrus/pull/367), including deployment of its
restricted `intakePendingReferences` action. This pilot does not duplicate that
handler, alter the schema, or change IAM permissions.

Collection does not classify, accept, reject, seed or train. The pilot experiment
records Ryan's explicit publication-specific yes/no and optional reason, runs
the real configured publication classifier baseline, and only afterward uses
verified previously human-accepted examples with their reasons for a comparison.
Keep evaluation items separate from seeds where feasible. Never infer human
labels from predictions, or report training/feedback success without verified
receipts. The legacy relevance sweep applies priming before prediction and is
therefore unsuitable for this baseline experiment without a separate safe path.

Initial live verification on 2026-10-20 registered HN 50154540 and 50136126 into
current academic Papyrus (`ds6yswxui41yi`, canonical `ai-ml-research`), and HN
50159341 into TI's canonical `threat-intelligence` corpus. Anth.us
has no canonical corpus yet. Current Papyrus main steering names `p-apyr-us`,
which differs from that live canonical corpus; TI main has no configured
relevance Cyclotron. The current Papyrus bucket contains an existing
`papyrus-relevance/state.tar.gz` snapshot (2026-10-20); TI has no objects under
`cyclotrons/`. Reuse the Papyrus incumbent after validating its binding; this
pilot creates no classifier. Resolve current classifier ownership/bindings and
obtain the requested human labels before real baseline predictions.
No model, human feedback, training, merge or deployment is
claimed by this pilot.
