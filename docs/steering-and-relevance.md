# Steering and relevance

> The shared relevance Cyclotron that decides which sites want each collected item is called **Relevance Routing** (see [feature-names.md](feature-names.md#relevance-routing)). Its code is in [monitoring-cloud.md](monitoring-cloud.md).

Steering is how an editor tells a publication what it is about and what it should and should not cover. Papyrus keeps that guidance as data in the site's own backend, and the agents and checks read it. Editors decide. Nothing on this page changes what is published without an editor.

Status words used here: Live, Beta, Not built yet.

## Publication doctrine and section doctrine (Live)

- **Publication doctrine** is two private Items: a mission and a policy. Editors edit them at `/newsroom/administration/policies`.
- **Section doctrine** is four text fields on each `NewsroomSection`: editorial mission, editorial policy, assignment guidance and kill criteria. Editors edit them at `/newsroom/administration/sections`.
- A resolver reads both and builds one editorial context for researcher, reporter and copywriter runs, for editorial checks, and for the Cyclotron requests below. See [editorial-context.md](editorial-context.md).

From the command line:

```bash
papyrus sections doctrine set --kind mission --file mission.md --dry-run
papyrus sections doctrine set --kind policy --file policy.md
papyrus sections update --id <section id> --editorial-policy-file policy.md
```

`papyrus sections doctrine set` takes `--kind mission|policy` and `--file`. `papyrus sections update` takes `--id` and any of `--editorial-mission-file`, `--editorial-policy-file`, `--assignment-guidance-file`, `--kill-criteria-file` and `--enabled true|false`. Both accept `--dry-run`.

## Include and exclude decisions on references (Live, with a Beta classifier)

A pending `Reference` is a candidate source. An editor accepts it (include) or rejects it (exclude) in the Newsroom References tab. Those decisions are the labels everything else learns from. See [newsroom-operations.md](newsroom-operations.md).

### The relevance Cyclotron (Beta)

A relevance Cyclotron suggests include or exclude for each pending Reference, and editors review its suggestions.

```bash
papyrus references decide-relevance            # dry run: lists pending references, no model call
papyrus references decide-relevance --apply --doctrine <path>    # decide, send editor reviews, record status, save the store
```

What it does:

- Decides each pending Reference. It never accepts, rejects or archives one by itself in this sweep.
- Learns from editors: an accept is an `include` label, a reject as out of scope or policy exclusion is an `exclude` label.
- Seeds its first rubric from the publication doctrine.
- Shows a status strip in References, and lets an editor who may change curation set a review rate for confident decisions (0% to 100%, for 1 to 30 days). Low-confidence decisions and a random audit share are always reviewed.
- Can be primed with a pasted URL and a label ("Prime with a URL" in References).

Beta means: the code is built and tested with synthetic sources, but real-world acceptance on a production publication has not been completed. The status table in [cyclotron-priming.md](cyclotron-priming.md) is the source of truth for what is built and what is waiting. It needs the optional `cyclotron` Poetry group, described on that page.

### The per-Section site Cyclotron (Beta)

A second Cyclotron suggests which Section a Reference belongs in: one fit classifier per enabled Section and one selector. It learns only from a Section a person explicitly chose.

```bash
papyrus references decide-site-sections            # dry run
papyrus references decide-site-sections --apply --doctrine <path>
```

Its results are suggestions only; it never changes a Reference's curation status. It is shadow-only and Beta, like the relevance Cyclotron. Details: "Site cyclotron" in [cyclotron-priming.md](cyclotron-priming.md); per-tenant behavior in [multi-tenancy.md](multi-tenancy.md).

### Audit the relevance model against editors' decisions

`papyrus references audit` compares what the relevance model predicted with what editors actually did. It only reads a site's References and changes nothing, so it is safe to run at any time. It needs access to the site's backend, the same as the other `papyrus references` commands.

```bash
papyrus references audit           # a plain-text report
papyrus references audit --json    # the same numbers for a script
```

It considers the current version of each Reference. A Reference counts as scored when the model stored a predicted probability that an editor would accept it (`predictedAcceptProbability`). Each scored Reference is then one of:

- **accepted**: an editor accepted it.
- **rejected**: an editor rejected it.
- **untouched**: no editor has accepted or rejected it yet.

The report gives:

- **Counts**: all References, those with a prediction, and how many are accepted, rejected and untouched.
- **Median predicted probability** for accepted, untouched and rejected References.
- **AUROC, accepted versus untouched**: the chance that a randomly chosen accepted Reference was scored higher than a randomly chosen untouched one (ties count half). 0.5 means the scores tell the two groups apart no better than chance, and 1.0 means every accepted Reference outscored every untouched one. The comparison is imperfect: an untouched Reference may simply not have been reviewed yet, and it may be one the model sent to the feed on its own.
- **A table of bands of predicted probability**, each 0.1 wide, starting at the tenth that holds the lowest score the model gave and running to 1.0. For each band: how many References were delivered, how many were accepted, how many were rejected, and the accepted share (accepted divided by delivered).
- **The rejected References that had a prediction**, highest score first, with the editor's reason when one was recorded.

What the numbers cannot tell you: the model only scored what reached it, and editors only decide on what they see, so a high accepted share in a band reflects both the model and what was shown. Small bands give noisy shares. The audit is a check, not a proof that the model is right.

## Taxonomy and category steering (Live)

Analysis can propose changes to the category tree. A proposal is a `SteeringProposal`. An editor can accept it, reject it, or rewrite it; each choice writes an append-only `SteeringDecision`, and an accepted edit creates new `Category` versions under a versioned `CategorySet`. Ignoring a proposal is valid steering: no decision is recorded and the accepted course continues. Rejected proposals are exported as feedback before the next proposal cycle, so they influence it.

See [newsroom-operations.md](newsroom-operations.md) and [category-steering-runbook.md](category-steering-runbook.md).

## Editorial feedback on checks (Live)

Editorial checks run on drafts against the publication's policies. When an editor accepts, fixes or dismisses a finding, that decision is stored as `EditorialFeedback`. An admin can run `recalibrateEditorialPolicies` (Administration, Editorial checks) to turn those decisions into per-detector calibration for judgment checks. Details: [editorial-checks.md](editorial-checks.md).

## Not built yet

- **Collaborative steering by votes, ratings, karma and comments.** Readers and groups steering a publication this way does not exist. It is planned as initiative PPY-77bb3b, with epics PPY-73a82d, PPY-739cb4 and PPY-0b2cbb.
- **Reader accounts.** There are no reader accounts today. Planned as PPY-1546fc.
