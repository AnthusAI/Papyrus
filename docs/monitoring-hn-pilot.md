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
50159341 into TI's canonical `threat-intelligence` corpus. All three pending
References and their private provenance bodies were read back successfully. Anth.us
has no canonical corpus yet. Current Papyrus main steering names `p-apyr-us`,
which differs from that live canonical corpus; TI main has no configured
relevance Cyclotron. The current Papyrus bucket contains an existing
`papyrus-relevance/state.tar.gz` snapshot (2026-10-20); TI has no objects under
`cyclotrons/`. This is inventory, not the selected first-stage backend.

## Required two-layer classification contract

Ryan's clarified rollout uses both supported modes from the start:

1. One shared **remote** Cyclotron evaluates the same discovered source once
   across relevance outputs for academic Papyrus, Threat Intelligence, Anth.us
   and Pilobolus (added by Ryan with his first labels).
   This shares Jev work; independent model calls are not equivalent.
2. Each publication's **integrated** Cyclotron evaluates its section outputs
   together in that publication's Papyrus backend.

Preserve the immutable discovered-item revision and shared decision identity,
then bind each result and human label to the correct account, publication,
output, binding revision and prediction fingerprint. Section feedback belongs
to its publication's integrated backend. Both layers need real end-to-end
verification before this learning slice is accepted. Do not silently substitute
an embedded first stage, independent models, or labels/seeds on another backend.

`monitoring_routing.route_discovery` composes the existing HTTP publication
client, remote transport and guarded integrated BFF transport. The trusted host
supplies verified publication/output/binding identities and fresh authorization;
no identity or role is inferred from source data. Identical source revisions
must yield one shared decision across the remote projections before integrated
work starts. Only positive relevance outputs reach their publication's section
engine. A changed account, actor, output, version or binding fails explicitly;
there is no automatic paid retry or local fallback. A `RoutingFailure` retains
completed stage receipts for reconciliation. No feedback, seeding or training
operation is called. The existing Papyrus snapshot is inventory only.

Offline tests execute the native SDK through actual HTTP/ASGI and guarded
integrated transports with explicitly synthetic providers. They prove one
shared model request for four relevance outputs, scoped multi-section results,
negative-route skipping, stale-binding refusal, split-decision refusal and
zero human labels. They do not prove deployed providers or production grants.

## Current deployment evidence and remaining gates

Read-only AWS inspection on 2026-10-20 verified account `682849160744`, stack
`cyclotron-console`, public origin `https://lab.cyclotron.anth.us` and backend
`https://o01d28uizl.execute-api.us-east-1.amazonaws.com`. `/api/session` returned
`{"authenticated":false,"loginUrl":"/auth/login"}`. This is separate from the
static marketing hostname `cyclotron.anth.us`.

The deployed OpenAPI has console `/graphql`, session, account and event routes;
the read-only publication status probe at `/publications/papyrus/operations`
returned 404. All three initialized console account catalogs were read through
canonical S3 adapters: no runs, classifiers or Cyclotron definitions existed.
Current core `HostedConfig.from_environment` leaves `allow_live=False`, and
`cloud_entry.runtime()` injects no provider factory or publication host. Thus
the shared remote first stage needs source composition and an authorized
release, not just ordinary publication configuration. No new IAM grant is
inherently established as necessary by these findings. No deployment is
authorized here.

The deployed BFF artifact itself was inspected with a 32 MB download cap and
immediate archive deletion: it contains no `decision_flywheel/publication_lab.py`.
Its extracted `hosted_runtime.py` SHA-256 is
`0dddf9bc500d3f1bad4f018d78dae28b1a19f027ee804ee3f52333ab65f76c0e`;
it likewise leaves live execution off and injects no provider factory. This is
deployed-source evidence, not an inference from the marketing repository.
The existing worker's environment variable names list only the ten host/storage/
OAuth configuration fields; no provider configuration field is present. Its
existing IAM policy covers scoped storage, queue, session decryption and
Prospectus authorization. Provider setup needs a concrete reviewed choice;
these findings do not authorize reading secrets or adding grants.

The Papyrus central adapter already uses the signed-in person's current
Prospectus access token and role-capped capabilities through
`central_lab_http_client_factory` / `ProspectusCentralPublicationAccess`.
AWS administrative access to storage is not a Prospectus human session and
must not be substituted for those role checks. Integrated section construction
already derives one fit output per enabled NewsroomSection plus its selector,
but live site bindings and deployment composition still need verification.

Ryan supplied eight explicit yes/no labels in message
`Sentinel_bd250f6fa2e4819195e197b2b115d12a` at 2026-10-20T03:54:30Z. The
pending feedback record, including undecided entries and supplied reasons,
is kept privately outside Git. It has not been applied to curation, used as
seeds or sent to a learner. The delegated-human path still requires a valid
delegation, verified grantor identity and correct target prediction; received
feedback is not an applied receipt. The CLI's private session metadata was
inaccessible in this sandbox. No publishing approval follows from those labels.

No real model prediction, applied feedback, training, merge or deployment is
claimed by this pilot.

Further labels arrived in `Sentinel_ab732a5df51c819184ab1201748e8a79` at
04:06:52Z and `Sentinel_ccc7c8f1c01081919875ae491dd950ad` at 04:08:04Z.
There are 18 explicit yes/no decisions received across the batches, zero
applied. The final Laminar/Pilobolus yes supersedes that pair's undecided state;
Ryan's supplied ouroboros framing is editorial rationale, not a verified
technical assertion. The Anth.us `#greatideas` suggestion is a section proposal,
not an automatic section creation. All pending feedback stays private outside
Git with message provenance; no missing reasons or labels are filled in.
