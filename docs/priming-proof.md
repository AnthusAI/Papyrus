# Priming proof

"The classifier uses the editor's labels" is a claim until there is a number.
This page defines that number, how to produce it, and where visitors see it.
Story: PPY-200acd, under epic PPY-7a0ac8. Code: `papyrus_content.priming_proof`.

## The number

**Agreement with editors on a fixed held-out set, at N = 0 and after N priming
labels.** Agreement is the share of held-out sources where the relevance
classifier gives the same label the editor gave. Precision and recall of the
positive label (`include`, shown to editors as publish) are reported beside it.

- **Held-out set.** References that editors already reviewed in the Newsroom,
  labeled by the existing scope-training rule (accepted is `include`; rejected
  as out of scope or a policy exclusion is `exclude`; anything else is left
  out). It is balanced, half per label, so a classifier that always gives one
  answer scores 50%. Selection is deterministic: references are ranked by
  `sha256(proofId, lineageId)`. The set is frozen once per proof id, carries a
  fingerprint over its items and labels, and is never regenerated. A new set
  needs a new proof id. Default size 40, at least 5 per label. Held-out items
  use the operational projection without the editor's review note, which would
  otherwise give the label away.
- **Labels (N).** `--teach-from` picks the source. `reviews` is the teaching
  pool frozen with the held-out set: every other labeled review, in review
  order, with the editor's note as its explanation. `catalog` is the accepted
  priming examples: a source URL an editor pasted, reviewed after Papyrus
  curated it, and labeled with an optional explanation, in acceptance order.
  `both` uses reviews first, then the catalog. The catalog's classifier must
  match `relevanceCyclotron` exactly (id, question, include/exclude labels).
  An example whose item id or source URL is in the held-out set is dropped and
  counted in the report (`excludedBecauseInHeldOut`), so a held-out source can
  never teach the classifier.
- **Conditions held fixed.** Every point opens a fresh Cyclotron store with only
  the first N examples as priming context, the configured decision model, the
  publication doctrine as the only rubric, no LLM optimizer and no review
  program. The only thing that changes between points is N.
- **Schedule.** N = 0, 5, 10, 20, 40 by default, capped at the number of usable
  examples. N = 0 is always included.

The report (`cyclotron-priming-proof/v1`) holds aggregate numbers, counts,
fingerprints, the decision model identity and dates. It holds no item text, no
explanations and no reviewer names.

## Produce it

The run calls the decision model, so it runs where the provider key is
(Ryan's Mac, by Remote Control), never from a cloud agent session.

```bash
# Once per proof id. Reads reviewed References; no model call; writes nothing to Papyrus.
poetry run papyrus references freeze-priming-held-out --proof-id ti-2026-10 \
  --output .papyrus-runs/proofs/ti-2026-10.held-out.json --size 40

# One decision-model call per held-out source per point.
poetry run papyrus references prove-priming --held-out .papyrus-runs/proofs/ti-2026-10.held-out.json \
  --teach-from reviews --output .papyrus-runs/proofs/ti-2026-10.reviews.report.json

# With pasted examples too (--teach-from catalog for pasted examples alone).
poetry run papyrus references prove-priming --held-out .papyrus-runs/proofs/ti-2026-10.held-out.json \
  --teach-from both --catalog <priming examples.sqlite3> --list-id <list id> \
  --classifiers '[{"id":"relevant","revision":1}]' \
  --output .papyrus-runs/proofs/ti-2026-10.report.json
```

Keep the held-out file private: it holds source titles, URLs and editor notes. Cost is
`held-out size x number of points` decision calls (200 for the defaults).

## Where visitors see it

The publication's `/cyclotron` page shows the headline ("agreement went from
X% with no labels to Y% after N labels"), the full before-and-after table and
the method. `/api/cyclotron/priming-proof` serves the same report as JSON for
other surfaces such as the Cyclotron site. Until a report is approved the page
says no approved run has been published and still explains the method.

A report becomes public only by a reviewed commit: save it as
`publications/priming-proofs/<site brand id>.json` and import it into
`lib/approved-priming-proof-reports.ts`. Ryan approves a report before it is
committed, as with relevance recordings. Brands whose newsroom owns the site
root rewrite `/cyclotron` into the newsroom; for those, link the API route.

## The continuous path, and what is left

| Step | Where it lives | State |
| --- | --- | --- |
| Paste a URL | `PrimingPanel` in References (`NewsroomCurationProvider`) | Built; opt-in per host |
| Papyrus curates it | `PapyrusPrimingCuration` (arXiv/GROBID paper path; web path via Biblicus worker pin) | Paper path live locally; web path needs its spend approval |
| Publish or reject, optional explanation | Shared `PrimingPanel` acceptance | Built (PR 213) |
| Save it | `PrimingService` catalog | Local SQLite; hosted S3 authority adapter not built (fails closed) |
| The classifier uses it | `AcceptedPrimingSnapshot` seeds a new store; the proof measures it | Built; an existing production store refuses new priming (engine rule) |
| A number visitors see | This page | Built; needs a first real run |

The hosted newsroom waits on PPY-58f107 (Prospectus accounts): the curation
host's `resolve_context` and `authorize` come from Prospectus, and the priming
catalog needs the account-scoped S3 authority adapter. Both sit behind
`create_curation_host` and `GuardedPrimingService`, so they plug in without
changing the panel, the curation code or this proof.
