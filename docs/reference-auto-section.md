# Automatic Section of accepted References

A site's public pages group References by newsroom Section (on Machines on Machines, the Videos and Findings pages), and a Reference with no
Section cannot be grouped. Tagging used to be optional and by hand. Now an accepted Reference is given a Section automatically when the site
cyclotron is sure enough, and never against a person's choice.

Code: `src/papyrus_content/site_auto_section.py` (the rules, the phase and the command), the site function's automatic lane in
`setReferenceSection` (`amplify/functions/category-action/handler.ts`), the calibration pairs in `src/papyrus_content/section_proof.py`.
Specs: `features_backend/reference-auto-section.feature`, `src/papyrus_content/site_auto_section_test.py`, `scripts/test-reference-section.ts`.

## What decides the Section

The **site cyclotron's section selector** ([Cyclotron, "Site cyclotron: a classifier per Section"](cyclotron-priming.md#site-cyclotron-a-classifier-per-section)).
Nothing new was needed: it is the same Jev decision model, store and review program as every site cyclotron classifier, its labels are the site's
enabled Section ids (prefixed ids such as `machines-on-machines#security` work as they are), its rubric is seeded from each `NewsroomSection`
record's title, mission and policy (never from code), and it learns only from Sections editors chose. A machine Section never teaches it
(`human_section_for_review` refuses `curationSectionActorKind: cyclotron`).

**Labelled data** is every accepted Reference a person placed in a Section: an accept that named one, or `papyrus references set-section`
(the console and the CLI agents acting in a person's session record `human`). Stories editors filed in Sections are a second source that is not
used yet (see "Not yet built").

## When a Section is "sure enough": learned, per site, from held-out editor choices

There is no fixed confidence. The threshold is learned from the **approved Section proof** (`papyrus references prove-site-sections --apply`,
report `cyclotron-section-proof/v1`), which cross-validates the selector: every Reference an editor placed is decided once by a fresh cyclotron
taught only by the other folds. The proof now records one `(confidence, agreed with the editor)` pair per held-out Reference in
`selector.calibration` (numbers only, no Reference). From those pairs the threshold is the smallest confidence at which the held-out decisions at
or above it agree with editors with a **Wilson 95% lower bound at or above the target precision** (`autoSection.precision`, default 0.9): the rule
the automatic accept uses for relevance (`auto_accept.learn_threshold`).

- With too few held-out choices, or choices that disagree too often, no confidence qualifies: **nothing is set**, and the reason is printed
  (for example "no confidence reaches the target precision 90%: 60 held-out editor Section choices, best 95% lower bound 84.0%").
- A proof run with another decision model than the cyclotron's, a dry-run proof, or no proof gives no threshold either.
- So does a proof of another Section list: the selector's id names its Section set, and the proof's selector must be the site's
  current one. (`decide-site-sections` and `prove-site-sections` read the Section seed file on a single-tenant backend, `auto-section` reads the
  `NewsroomSection` records; if the two differ, this check says so instead of applying evidence about other Sections.)
- The proof teaches each fold with four fifths of the labels and the live cyclotron with all of them, so the measured agreement is, if anything,
  pessimistic.

## The rules

| | |
| --- | --- |
| Which References | Current, accepted, and with a Section nobody but the machine has touched (`person_owns_section`). |
| A person set a Section | Never changed. A Section recorded with an accept before the actor kind existed counts as a person's. |
| A person cleared a Section | Never re-tagged: the clear records who and `curationSectionActorKind` (`human`, or `agent` for an operator on AWS credentials). |
| Below the threshold | No Section. A Section the machine set earlier whose newest decision no longer reaches the threshold is cleared by the machine. |
| A new version | The selector's decision is about one version (`subjectVersionNumber`); a new version is decided again and the machine's own tag follows it. |
| The Section list changes | The selector's id names its Section set, so a changed list is decided again by the new selector. |
| Race with a person | The site function checks ownership again at the write and refuses quietly (`skipped`), so a person who acted first wins. |

## What is recorded

The machine's Section is written by the site function's automatic lane of `setReferenceSection` (`decisionRelationId` and `machineReason`), in the
same fields a person's Section uses, so every reader treats it the same:

- `curationSectionId`: the Section.
- `curationSectionUpdatedBy`: `auto:cyclotron` (the automatic accept's signature), `curationSectionUpdatedAt`: when.
- `curationSectionActorKind`: `cyclotron` (a person's choice records `human`, an operator's `agent`).
- `curationSectionReason`: the evidence, for example "Section set automatically by the site cyclotron's section selector (papyrus-relevance-sections,
  model version 3): 95.0% sure this belongs in Security, at or above the 95.0% learned from 60 held-out editor Section choices (the 40 at or above it
  agreed 100.0%, 95% lower bound 91.2%, target 90%; proof sections-1). An editor can change or clear it."
- `curationSectionDecisionRelationId`: the `site_decision_is` relation it acted on, which carries the label, the probabilities, the model version
  and fingerprint, the cyclotron id and the doctrine and teaching fingerprints.

The site function refuses a decision that is not this Reference's current section-selector decision, or that chose another Section. The vote
(status, note, the vote's actor kind, stars) is never touched, so nothing is re-handed-off to the relevance cyclotron.

An accept that names a Section now records the same provenance (`human` or `agent`), and a person setting the Section the machine chose makes it
theirs (`human`, no reason, no decision).

## Changing or clearing a machine Section

Exactly as for any Section: `papyrus references set-section --reference <lineage id> --section <name|slug|publication#slug>` or `--clear`
(or the MCP tool `reference_set_section`). That is a person's choice from then on, and the machine never changes it again.

## The public pages

The Videos and Findings pages (and every public reader of `curationSectionId`, such as the home page data) treat a machine Section and a person's
Section the same: the Section's label comes from the `NewsroomSection` record, and who set it is never published.

## When it runs

- **On accept: the site sweep.** `papyrus references decide-site-sections --apply` teaches the site cyclotron, decides pending References, and
  then gives a Section to each Reference accepted (or given a new version) since its last completed pass. It reads the accepted-status index
  (`referencesByCurationStatusKey`, sorted by `updatedAt`) newest first and stops at the stored watermark (`cyclotron-auto-section`
  KnowledgeRawPayload of the cyclotron), so a pass reads only what changed. Its decisions count toward `maxDecisionsPerDay`.
- **The backfill: `papyrus references auto-section`.** The same pass on its own. Writes by default; `--dry-run` decides in a throwaway copy of
  the cyclotron store and prints what it would set, with the confidence, the top three Sections and the evidence, and writes nothing to the site,
  the bucket or the store; `--json` prints the same as JSON. Without a watermark (the first run) or with `--all` it reads the whole accepted
  partition (a named sweep); otherwise it starts after the last completed pass. It is idempotent (a Reference whose current decision it already
  applied is `unchanged`, and a decided version is never decided again) and resumable (an interrupted pass, for example at the daily decision
  cap, does not move the watermark, and the next pass repeats no decision and no write). `--doctrine` is required unless `--dry-run`, as for
  the sweep.

```bash
papyrus references prove-site-sections --proof-id sections-1 --apply --output proofs/sections-1.json   # the held-out evidence (model calls)
# name it in the steering config: siteCyclotron.autoSection.proofPath: proofs/sections-1.json
papyrus references auto-section --doctrine <doctrine.yml> --dry-run        # what it would set; writes nothing
papyrus references auto-section --doctrine <doctrine.yml>                  # the backfill
papyrus references decide-site-sections --apply --doctrine <doctrine.yml>  # each later pass: teach, decide, tag what was accepted since
```

## Configuration

```yaml
siteCyclotron:
  autoSection:
    enabled: true                       # default true
    precision: 0.9                      # the target agreement with editors; default 0.9
    proofPath: proofs/sections-1.json   # the approved cyclotron-section-proof/v1 report; without it nothing is set
```

The sweep and the command need a steering config with `relevanceCyclotron` and `siteCyclotron` blocks, the decision model's key in the environment,
and AWS credentials for the store snapshot in the private bucket, like `decide-site-sections`.

## Not yet built

- Stories as labelled data: a Story an editor filed in a Section, and the References it is `based_on`, would add labels where References have
  few.
- The console does not yet show who set a Section or offer a Section control; the CLI and the MCP tool do.
- Nothing schedules the site sweep in the cloud yet: it runs where `decide-site-sections` runs.
- One threshold for all Sections: a Section the selector is worse at shares the threshold the others earn.
