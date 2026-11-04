# Fact checking and hallucination defence

Epic PPY-b32e85, first story PPY-d4d5bd. Everything a model writes that a person or another agent will rely on goes through one shared check, in layers from cheap and certain to costly and judged. The module is `src/papyrus_content/fact_check.py` (contract `fact-check/v1`); it is pure except for the judge it is handed, so any generator can use it. Specs: `features_backend/fact-check.feature`.

A prompt that says "use only the sources" is not a safeguard. A real research packet wrote a first name the source did not give, and a state of residence the source did not give, under exactly that rule.

## The layers

| Layer | What it does | Built |
| --- | --- | --- |
| 1. Instructions to the writer | The writer is told to use only the titles, snippets and page text it is given. Necessary, not sufficient. | Yes (the research prompts) |
| 2. Citations exist | Every claim cites a source that exists; a claim without one is dropped (`droppedClaims`). | Yes (research, ideas) |
| 3. Literal check | Each name, number, date, place and quotation in a claim must appear in the texts of the sources the claim cites. Code, free, certain. | Yes |
| 4. Independent judge | A separate model call, told nothing about how the claim was written, says whether the cited text supports it and must quote the text word for word. Code looks for the quote. It fails closed. | Yes, wired into multi-search research. Not yet run live in CI: the specs use a fake judge. |
| 5. Source strength | Distinct registered domains behind each claim and a `singleSource` flag; which sources carry the most claims. Reported, never a failure. | Yes |
| 6. Consequences | A claim that is not verified is never silently deleted and never passed on as fact. It is held with its reasons, and later agents see it labelled. | Yes for research packets and the Story context pack. Nothing else yet. |
| 7. People | The editor sees each claim's status; a hard gate before publishing through `review_requests`. | No. The console does not show claim status yet (another change renders `unverifiedClaims`), and there is no publishing gate. |

Where the check applies, in the order of the epic: research packets (done), Reference summaries, idea drafts, Story drafts before publishing, then agent conversations on Chatticus. Only research packets are done.

**The judge is asked more than once.** Its answer on the same claim and text changes between runs: 4 of 28 real claims changed verdict across three replays on 2026-11-03, one of them an allegation stated as fact. A claim is `verified` only if all `JUDGE_PASSES` answers agree; the first doubt stops the asking and that answer stands. A claim that already failed the literal check is asked once, because it cannot become verified. This lowers the chance of a wrong `verified` but does not remove it.

## `check_claims(claims, sources, *, judge=None, urls=None)`

`claims` is a list of `{claim, sources}`; `sources` maps a source id to its text. For research the text is the source's title, its snippets and the page text the run read, because that is all the writer was told to use. `urls` maps source ids to URLs for the source-strength count. It returns `{contract, counts, claims, sourceLoad}`; each claim has `verdict`, `literal.unmatched` (`[{term, kind}]`, kind is `name`, `number` or `quotation`), `judge` (or `null`), `reasons` and `sourceStrength` (`{domains, singleSource}`).

Verdicts, in two tiers of doubt so an editor can tell a nuance from an invention:

- `verified`: the literal check passes, the judge said `supported` with every quote found in the cited text, and the claim does not state as fact what the source only attributes to a party (or attributes it to the wrong party).
- `needs_check`: the literal check passes, but the judge said `partly_supported` or `attribution_lost`. Reasons: `judge_partly_supported`, `attribution_lost`.
- `rejected`: a literal failure (`unmatched_terms: Rodney, Tennessee`), or the judge said `not_supported` or `source_silent`, or a quote is not in the source (`quote_not_in_source`), or the claim cites no text (`no_cited_text`).
- `unchecked`: the literal check passed but there is no judge (`no_judge`) or the judge failed (`judge_failed: ...`). Never counted as verified.

A literal failure is never overridden by the judge.

### The literal check

Case, diacritics, curly quotes, dashes and white space are ignored. Numbers match across `$200,000`, `200,000`, `200000`, `3.50` and `3.5`, and a number the source spells out (`fifteen`, `twenty-three`) matches its digits. A quotation must appear whole. A name is a run of capitalized words (a connector such as `of` or `van` joins two); every word of the run must appear in the sources, so `Rodney Reid` fails when the source has only `Reid`. A name is also found when:

- the source uses its initials (`GAO` for Government Accountability Office, `NY` for New York);
- a cited source's host is the name or spells it out (`orlando.gov`, `stateofsurveillance.org`), or carries a state's postal code (`leg.wa.gov` for Washington). The writer saw the URL, so the host counts; the path does not, and neither does a year in a URL.

Months, weekdays, spelled-out numbers and a short list of generic words (`GENERIC_WORDS`, found by reading real claims) are not names. A name at the start of a sentence is still checked, so a plain word at the start of a claim that the sources lack is flagged; the generic list is the place to fix a false flag, and each addition should come from a real claim.

What it cannot do: it does not know that a name is wrong, only that the cited sources do not contain it. A name the writer expanded from an acronym the source never mentions (`Congressional Research Service`) is flagged although it is correct, and a name taken from a different source than the one cited is flagged, which is the useful case. A name that appears anywhere in the cited text passes even if the claim attaches it to the wrong thing; that is the judge's job.

### The judge

`llm_judge(llm)` makes one call per claim, in a thread pool with one worker per claim, so the provider's own rate limit is the only limit. The model is `DEFAULT_LLM_MODEL`. The prompt gives it the claim and the cited source texts and nothing about how the claim was written. Each source is given with its id, title, host and text; the judge may name a source's publisher from the title and host. It answers `verdict` (`supported`, `partly_supported`, `not_supported`, `source_silent`), `quotes` (one per supported part of the claim), `claim_is_only_about_source_limits`, `explanation` and `attribution_lost` under a strict JSON schema. Code normalizes each quote and the source text and checks that the quote is in the text; a quote with an ellipsis is split there and each piece is checked. If any quote is missing, or a `supported` answer has no quote and the claim is not only about what the source lacks, the verdict becomes `not_supported` with reason `quote_not_in_source`. A part of a claim that says what a source does not say ("the account does not specify...") is supported when the source is silent on it and needs no quote; the judge is told so.

## Multi-search research

After synthesis, `run_multi_search` calls `fact_check_synthesis`:

- `claims` keeps verified claims only. The rest, `needs_check`, `rejected` and `unchecked`, are in `unverifiedClaims`, each `{claim, sources, reasons, verdict}`.
- With a Story context pack the writer is told to give one fact per claim, to put a caveat in its own claim or in the open questions, and a year or date only if the page text, a title or a snippet gives it, because a claim with one unsupported part fails whole.
- Disagreement positions get the literal check only. A failing position stays, labelled `unverified: true` with `reasons`.
- The summary and recommended angle are written again by one model call from the verified claims alone. The rewrite must pass the literal check against the sources of all verified claims; if it does not, or there are no verified claims, a plain summary built from the counts is used (`factCheck.plainSummaryBecause` says why). The summary and the angle are checked apart, a single capitalized word that opens a sentence is not taken for a name unless the sources also capitalize it inside a sentence, and the plain summary leaves the angle empty.
- Direction coverage: when the editor's direction names people or places, each name (found with the literal check's own name extraction) must appear in a verified or unverified claim, a disagreement or an open question. A name that does not goes into `factCheck.directionGaps` (`name`, `inSources`, `note`), gets an open question (the run has sources but wrote nothing on it, or found nothing), and is listed in the packet body under "Named in the direction, not covered:" and in the Work section.
- The packet gets `factCheck`: counts, the per-claim results, the per-position results and `sourceLoad`.
- The packet body shows claims, then a "Could not verify:" section with the reasons.
- The cited-only intake reads `claims` and disagreement positions, so a source cited only by a failed claim is not taken in as a Reference.
- The `prior_research` layer of the Story context pack lists `needs_check` claims under "Needs a check ... do not rely on:" unchecked ones under "Unchecked ... do not rely on:" and rejected ones (or any without a verdict) under "Rejected ... do not rely on:".
- A judge that fails does not fail the run: those claims are `unchecked`, held with the reason. The `research.multi.completed` event records the counts.

Nothing here is applied to packets made before this change; they have no `factCheck`. Replay them:

```bash
papyrus assignments fact-check --message <research packet message id> [--judge true|false] [--format text|json]
```

It reads the packet's Message (through the metadata attachment when the row has none), runs the check on its claims and positions, prints the result and writes nothing. `--judge true` (the default) makes one model call per claim.

## Not built

Reference summaries, idea drafts, Story drafts and Chatticus conversations do not call the check. The console shows no claim status. There is no hard gate before publishing. The judge has not been run on real packets in CI, so its false-support rate is not known. The literal check reads titles and snippets, not the pages, so a true claim from a page the writer never saw cannot be verified.
