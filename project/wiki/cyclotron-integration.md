# Cyclotron integration: relevance decisions at reference intake

Written 2026-10-09. The full design lives in the Cyclotron engine's wiki:
[papyrus-integration.md](https://github.com/AnthusAI/Cyclotron/blob/docs/papyrus-integration/project/wiki/papyrus-integration.md)
(branch `docs/papyrus-integration`, engine epic decision-flywheel-a73f05cc).
This page is the Papyrus-side summary. Papyrus epic: PPY-b0396fee. Operator guide:
[docs/relevance-cyclotron.md](../../docs/relevance-cyclotron.md).

## What changes

Research dispatch, research packets, citation-led discovery and inbound email
all end as a pending `Reference` with a `curation.reference-intake`
Assignment. A cyclotron now makes a decision about each pending Reference:
is this item relevant to this publication, given its doctrine? Editors
review the decision in the References tab with thumbs up or down, a reason
and an explanation. The cyclotron aligns to that feedback. Nothing becomes
accepted evidence without a person in phase one.

## What it reuses

- The item: the pending `Reference`, addressed by `lineageId`.
- The review: the existing `reviewReferenceCuration` mutation and its
  `reference_curation` Message, with two optional fields added.
- The label rule: `scopeTrainingLabelForReference` in
  `lib/reference-policy.ts`. Accepted is `include`; rejected as out of scope
  or policy exclusion is `exclude`; other reasons give no label.
- The decision record: a `SemanticRelation` (`relevance_decision_is`) using
  the existing `score`, `confidence`, `classifierId`, `modelVersion` and
  `reviewRecommended` fields.
- The status: a `KnowledgeRawPayload` snapshot, like the Newsroom summary.
- The single writer: an exclusive Assignment claim.
- The parameters: publication doctrine seeds the rubric; a doctrine edit
  makes a new cyclotron version.

## Words

Papyrus uses the Cyclotron glossary in this work, so the UI, code and
marketing say the same thing.

| Concept | Word |
|---|---|
| The pending Reference being judged | item |
| The relevance decision system | cyclotron |
| The one question inside it ("relevant") | classifier |
| The fast model that answers | decision model |
| The small model trained on editor labels | ML model |
| The model that proposes rubric changes | LLM optimizer |
| What the cyclotron outputs | decision |
| How sure it is | confidence |
| The editor who checks a decision | reviewer (editor in UI copy) |
| The act of checking | review |
| The recorded answer | label |
| A label that differs from the decision | correction |
| The written reason | explanation |
| Labels and explanations together | feedback |
| One pass: decide, review, learn | cycle |
| A numbered state of the cyclotron | version |

Keep Papyrus's own words where they mean something else: `curationStatus`
values (accepted, rejected) are curation states, and rejection reason codes
stay as they are.

## Tasks, in order

1. PPY-cc99d6de: configure the relevance cyclotron per publication.
2. PPY-4ac3d0c5: record decisions and reviews in the existing models.
3. PPY-7a1ca2f7: the `references decide-relevance` sweep.
4. PPY-820acd11: rating UI in the References tab.
5. PPY-049b6e24: status strip and review-rate override.
6. PPY-54957abe: recording for the marketing demo.

Tasks 3 to 6 also wait on engine tasks named in their descriptions.

## Open questions for Ryan

- Which publication goes first.
- Whether `include` decisions not picked for review may ever be accepted
  automatically.
- Which decision model and whose provider key.
