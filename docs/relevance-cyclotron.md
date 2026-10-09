# Relevance cyclotron

A relevance cyclotron decides, for each pending `Reference` (a candidate
source found by research dispatch, research packets, citation-led discovery or
inbound email), whether it should become a reference for this publication.
Editors review its decisions in the Newsroom References tab, and it aligns to
their labels and explanations. Engine guide:
[Cyclotron docs/embedding.md](https://github.com/AnthusAI/Cyclotron/blob/main/docs/embedding.md).
Plan: `project/wiki/cyclotron-integration.md`, epic PPY-b0396fee.

## Configure it

One installation is one publication, and it has at most one relevance
cyclotron. Add a top-level `relevanceCyclotron` block to the publication's
steering config (`corpora/<publication>-steering.yml`). Every field has a
default except where shown; the values below are placeholders.

```yaml
relevanceCyclotron:
  cyclotronId: "papyrus-relevance"
  classifierId: "relevant"
  question: "Should this candidate source become a reference for this publication?"
  labels: ["include", "exclude"]
  positiveLabel: "include"
  decisionModel:            # must be a batched decision model
    provider: "jev"
    model: "jev-1.13.0"
  optimizer:                # null: decide and record only
    provider: "openai"
    model: "gpt-6-luna"
    maxCalls: 10
  store:
    localPath: "var/cyclotrons/papyrus-relevance"
    s3Prefix: "s3://<private media bucket>/cyclotrons/papyrus-relevance/"
  maxRequestsPerSweep: 200
  reviewProgram:            # placeholders until the engine's review-rate experiments
    rates: [1.0, 0.5, 0.25, 0.1]
    auditShare: 0.05
    confidenceThreshold: 0.7
    targetAccuracy: 0.85
    maxGapPoints: 5
    window: 100
    windowsRequired: 2
    minWindowLabels: 20
```

Rules the loader enforces:

- **Batched decision model.** A cyclotron asks its classifiers in one
  request, so the decision model must implement `classify_many`. Jev's adapter
  does.
- **Doctrine seeds the first rubric, never the question.** The question and
  labels are the cyclotron definition, which its store refuses to change. The
  publication doctrine (mission and policies) becomes the classifier's first
  rubric when the store is created; after that the LLM optimizer owns the
  rubric. Changing the question or the labels later needs the engine's
  definition versions (decision-flywheel-ade3088c).
- **No keys in configuration.** Provider keys come from the environment (for
  example `TYPESAFE_API_KEY` for Jev and `OPENAI_API_KEY` for the optimizer)
  or SSM on a worker. A field whose name looks like a key, token, secret,
  password or credential is refused.
- **Snapshots stay private.** The store snapshot holds item values,
  explanations and transcripts; `store.s3Prefix` must point at the private
  media bucket.

## Install the engine

The engine is the optional `cyclotron` extra, pinned to one Cyclotron main commit (9874b71):

```bash
poetry install --extras "newsroom cyclotron"
```

## Run the sweep

```bash
poetry run papyrus references decide-relevance            # dry run: lists pending references, no model call
poetry run papyrus references decide-relevance --apply    # decide, send reviews, record status, save the store
```

Run it after research intake (`assignments research-intake-now --apply`) and
on a schedule. Each run:

1. Claims the `cyclotron.relevance` Assignment for this cyclotron; a second
   worker stops before any model call while the claim is held.
2. Restores the cyclotron store from `store.s3Prefix` when this worker has no
   local copy.
3. Sends editors' reviews of decided references to the cyclotron. The label
   follows the existing scope-training rule: accepted is `include`; rejected
   as `out_of_scope` or `policy_exclusion` is `exclude`; other outcomes close
   the decision without a label. The editor's note is the explanation and the
   curation Message id is the review id, so a rerun records nothing twice.
4. Decides every current pending reference of the canonical corpus and
   records each new decision as a `relevance_decision_is` relation. An
   unchanged reference keeps its decision without a model call.
5. Records the `cyclotron-status/v1` snapshot
   (`knowledge-raw-payload-cyclotron-status-<cyclotronId>`), saves the store
   snapshot to the private bucket, and releases the claim.

The sweep never accepts, rejects or archives a reference. A reference an
editor reopens to pending is decided again only when a new version is
promoted.

## What editors see

The References tab shows the cyclotron's status strip above the list (version,
agreement, calibration as "says N%, right M%", the review rate and its
state), read from the status snapshot the sweep records. "What the cyclotron
is doing" opens the detail card: recall, precision and accuracy with plain
explanations, the review rate's reason and next step, and the last change.

Editors who may change curation can set a manual review rate for confident
decisions (0% to 100%, for 1 to 30 days) or clear it. The Newsroom records
the request as a `KnowledgeRawPayload`
(`knowledge-raw-payload-cyclotron-review-rate-request-<cyclotronId>`); the next
sweep applies it once, and the status then shows who set it and when it
expires. Low-confidence decisions and the random audit share are always
reviewed.

## Record a run for the Cyclotron site

```bash
poetry run papyrus references export-relevance-recording --output papyrus-relevance-run.json \
  --optimizer-price 0.40,0.10,1.60 --optimizer-price-source "<provider's published price page>, read <date>"
```

The export restores the latest store snapshot from the private bucket (or
reads `--store <dir>`), makes no model call and writes nothing to Papyrus. It
follows the Cyclotron editorial-run fixture's schema 2 with
`source: "papyrus-live"`: one cycle per decision in order (the source's title
and public URL, the decision shown before the review, the editor's label and
reason code, the review program's reason and propensity, and the cyclotron's
changes), windows of 100 decisions with metrics on reviewed decisions, routing,
and measured usage and cost, and `usage_total` with the price basis.

- **Consent.** An editor's explanation is included only when the editor ticked
  "My explanation may be quoted publicly" on that review.
  `--no-explanations` leaves every explanation out. Reviewer names never
  appear.
- **Prices.** Jev is priced at TypeSafe's published list price. Any optimizer
  calls need `--optimizer-price IN,CACHED,OUT` (USD per million tokens) and
  `--optimizer-price-source`; the export refuses to guess.
- **Approval.** Ryan approves a recording before it is copied into
  Cyclotron-web.
