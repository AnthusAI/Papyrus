# Combining editor and reader scores

Exploration PPY-0b2cbb (story PPY-1bf366; Shipped ship-1f3d29).

**Decision: adopted 2026-10-22, all five points; Readers tab skipped for launch.** Implemented in the reader-steering plugin as
`ranking.combination: "shrinkage"` (default stays `blend`, so other sites are unchanged), `ranking.shrinkageK` (20), `ranking.readerShareCap` (0.4),
`ranking.newAccountWeight` (1/3) and `ranking.risingMinimumAccountHours` (24); Shipped's site config turns them on. No Wilson bound. The active
values are published in `board.json` `parameters`, the used-it reporter count is `usedItReporters` in `items.json`, and
`procedures/newsroom/tests/test_score_combination.py` reproduces the key numbers below from `sim.py` with the plugin's own ranking functions. See
[reader-steering.md](reader-steering.md). What follows is the original recommendation text.

The original recommendation read: **nothing here changes production**: the formula in `src/papyrus_content/reader_steering/ranking.py` (editor composite, then a 0.5 blend after
`readerMinimum` ratings, times a 48 h half-life decay) was untouched. The simulation is in
[score-combination/](score-combination/): `sim.py` (fixed seed 20261022), `items.csv` (the 70 real editor scores) and the
output tables (`results.md` and one CSV per scenario). Run `python3 sim.py` from that directory.

## Recommendation in five lines

1. Replace the cliff-and-blend (A) with **Bayesian shrinkage per dimension, prior strength k = 20, reader share capped at 0.4**:
   `score = mean over dimensions of E + share * (readerMean - E)`, `share = min(n / (20 + n), 0.4)`, where `E` is the editor mean.
   This is `ranking.k = 20`, `ranking.readerShareMax = 0.4`; `readerMinimum` goes away because few ratings already move little.
2. Count each rating at weight 1, or 1/3 from a profile younger than `limits.newAccountHours` (24). The weight goes into `n` and the
   mean. This is the cheapest brigade defence the data supports and the plugin already knows the account age.
3. Keep decay as it is. Keep the hype gap and the "Shipped" stamp outside the score (below). Do not use Wilson on upvotes for Front.
4. Rising stays an upvote count but counts only distinct profiles older than 24 h with a per-profile cap. The score formula cannot protect it:
   3 sock upvotes reach the top 5.
5. Treat a separate "Readers" tab (option C) as an optional addition, not a replacement: stable Front, but the tab itself is as
   brigade-able as the worst option here.

Cost of the recommendation, stated plainly: it follows genuine reader disagreement more slowly than A once an item has 10 or more
ratings (gap closure 0.28 against 0.43 at 10 raters, 0.36 against 0.44 at 30), and it never lets readers move a score by more than 40% of
the distance from the editor's.

## The data

70 published Shipped items (69 `shipped`, 1 `pending`), the editor's AI-assisted first pass on Real, Useful, Notable and Novel (1 to 5,
halves). Editor composite: mean 3.54, standard deviation **0.28**, range 2.62 to 4.12. That is a tight spread: the middle half of the items
sit between 3.38 and 3.75, so a small shift in score moves an item a long way in rank. Every rank quoted below is out of 70.
There are no reader votes yet; readers are simulated. Scores are compared before time decay, because decay multiplies every option by
the same per-item factor; it does matter in practice (an item two days old counts half) and it limits how long a brigade pays off on
Front, but it was not simulated.

## The options

`E` is the editor's mean on a dimension (composite `Ē` is the mean over dimensions), `r̄` the reader mean, `n` the number of reader
ratings on that dimension (the largest `n` for A, which follows the code), `d` the decay.

- **A. Linear blend, fixed weight (as built).** `n < 5`: `Ē · d`. `n ≥ 5`: `(0.5·Ē + 0.5·R̄) · d`.
  Simple to explain. Two flaws: the fifth rating makes the score jump by half the distance to the readers (7 ranks on average in the
  simulation), and the fifth sock counts as much as the fifth honest reader.
- **B. Bayesian shrinkage.** Per dimension `m = (k·E + Σ ratings) / (k + n)`; score = mean of `m` times `d`. Editor score is a prior worth
  `k` ratings. No cliff, no minimum. The recommendation adds a cap on the reader share, `n / (k + n) ≤ 0.4`, which bounds what any
  crowd, honest or not, can do to one item.
- **C. Separate tracks.** Front: `Ē · d`. Readers tab: `R̄` shrunk toward the site-wide reader mean (k = 10), needing 1 rating to appear.
  No blend, so editorial and reader opinion are both visible, and Front is exactly as stable as the editor.
- **D. Wilson lower bound on upvotes.** Front and Rising: `1 + 4 · Wilson95(upvotes, views) · d`, items under 5 views unranked;
  dimension ratings displayed, never ranked. Needs a view count, which the plugin does not record today.

### Hype gap and the "Shipped" stamp

- **Hype gap** (`mean(notable, novel) − mean(real, useful)`) is computed twice, from readers and from the editor, and shown, not ranked.
  It is independent of A, B and C; it is what protects readers from the hype in D: in the simulation a popular overhyped item
  (readers rate Real and Useful 2, Notable 4.5, Novel 4; 60% upvote rate) has a reader hype gap of +2.2 under every option, but under D it is
  **rank 1 of 70** while under A, B and C it is rank 54 to 62. With D the gap is the only warning the page gives. A brigade of sock
  accounts rating everything 5 closes the reader gap, so the gap needs the same account-age weighting as the score. Keep
  `snapshot.hypeMinimum` at 5 under every option, and do not shrink the gap toward the editor's.
- **"Shipped" stamp** (3 "I used it" reports) is a count, not a score. No option changes it. It is also the cheapest thing to fake: 3 sock
  accounts flip it. Count only reports from profiles older than `limits.newAccountHours`; a profile created to push one item then has to
  wait a day before it can. Do not let the stamp feed the score: a reader's "used it" is evidence for the stamp, and Real is the dimension
  that records it.

## Simulation

Scenarios (all with the real 70 editor scores; honest readers rate all four dimensions around the item's reader truth with
standard deviation 0.8, integer 1 to 5; about 8 honest ratings per item and about 120 views per item unless stated):

| Scenario | What it does |
|---|---|
| S1 | Honest readers who agree with editors (per-item disagreement sd 0.3); two independent reader populations; 200 trials |
| S2 | Readers disagree by 1.5 points on 10 random items; 2, 5, 10 and 30 raters per item; 100 trials |
| S3 | Brigade: m sock accounts give one item 5 on every dimension and an upvote; target is the editor's rank-35 or rank-10 item; also at 1/3 weight; 40 trials. S3b: 20 socks rate the top item 1 |
| S4 | Cold start: every item has 1 or 2 ratings and about 15 views; 200 trials |
| S5 | Popular but overhyped item, with the editor either seeing through it or fooled; 100 trials |

### Key numbers

Rank stability (S1; split Spearman between two independent reader populations, top-10 overlap, correlation with the editor-only order):

| Option | Split | Top-10 overlap | vs editor |
|---|---|---|---|
| A | 0.92 | 0.80 | 0.92 |
| B k=10 | 0.94 | 0.83 | 0.93 |
| B k=20 (cap 0.4) | 0.97 | 0.91 | 0.96 |
| C Front | 1.00 | 1.00 | 1.00 |
| C Readers tab | 0.76 | 0.56 | 0.75 |
| D | 0.17 | 0.23 | 0.33 |

D's figure depends on how much upvote rate tells you about quality and how many people look (S1b: 0.17 at 120 views per item,
0.39 at 500, 0.69 at 2000, and 0.89 at 2000 views with a steep rate). It is a poor ranking signal at Shipped's likely early volume.

Brigade (S3, median over trials, 5 on every dimension plus an upvote). "Socks to top 5" for the editor's rank-35 item; second figure counts
each sock as 1/3:

| Option | Socks to top 5 | At 1/3 weight | Rank after 20 socks | Rank of the top item after 20 down-socks (S3b) |
|---|---|---|---|---|
| A | 13 | 40 | 3 | 67 |
| B k=10 | 8 | 25 | 1 | 70 |
| B k=20 | 13 | 40 | 1 | 69 |
| **B k=20, cap 0.4** | **28** | **96** | **7** | **63** |
| C Front | not possible | not possible | 35 | 1 |
| C Readers tab | 3 | 9 | 1 | 70 |
| D | 10 | 25 | 1 | 23 |

For the editor's rank-10 item the answer is 1 to 7 socks under every reader-aware option (A: 2, B cap: 4, D: 7). With a spread this tight
there is no formula that stops determined accounts reaching the top; the formula sets how far 20 accounts move a score: 0.54 points
for A, 0.43 for the capped B, 0.80 for B k=10. Account trust and rate limits do the rest.

Responsiveness to genuine disagreement (S2; gap closure = how much of the editor-to-reader gap the score covers, 1 is fully):

| Raters per item | A | B k=10 | B k=20 | B k=20, cap 0.4 | C Front |
|---|---|---|---|---|---|
| 2 | 0.02 | 0.14 | 0.08 | 0.08 | 0 |
| 5 | 0.25 | 0.29 | 0.17 | 0.17 | 0 |
| 10 | 0.43 | 0.43 | 0.29 | 0.28 | 0 |
| 30 | 0.44 | 0.66 | 0.53 | 0.36 | 0 |

At 30 raters the capped B recovers 0.79 of the reader-truth top 10 against A's 0.86 and uncapped B k=20's 0.88: the cap trades about a tenth of
that recovery for double the socks needed.

Cold start (S4, one or two ratings per item, readers agree with editors):

| Option | Mean rank shift vs editor | Mean score shift | Rank jump when the 5th rating arrives |
|---|---|---|---|
| A | 0 | 0 | 7.3 |
| B k=10 | 14.3 | 0.28 | 1.6 |
| B k=20 | 10.0 | 0.15 | 1.2 |
| B k=40 | 6.0 | 0.08 | 1.1 |
| C Front | 0 | 0 | 0 |
| C Readers tab | 21.9 | 0.45 | 0 |
| D | 21.6 | n/a | 0 |

A is quiet until the fifth rating and then lurches; B moves a little from the first rating on. The 10-rank mean shift for k=20 is a
0.15-point score shift, magnified by the packed editor scores. k=40 halves it at the price of slower response (S2 closure 0.38 at 30 raters).

Overhyped item (S5), rank of 70: with the editor seeing through it, A 60, B 59, C Front 54, D 1. With the editor fooled (Ē 4.25), C Front 1,
D 1, A 20, B k=20 7, so readers correct a fooled editor only with B and A, and B k=20 corrects more.

Rising (current rule, a count of upvotes in 6 h): 3 sock upvotes reach the top 5 (6 at 1/3 weight). Wilson on the window needs 2 (6 at 1/3
weight). Wilson does not resist a brigade whose accounts all view and upvote; the lever is whose upvotes count.

## What each option gives up

- **A** keeps the current behaviour and its cliff; 13 socks beat it for a mid-table item.
- **B** is the most stable honest blend and removes the cliff. It follows readers less quickly than A at moderate `n` unless `k` is small,
  and a small `k` is what a brigade exploits. The cap is what makes `k` safe to set low enough to be responsive.
- **C** is the only option with no brigade path into Front and the best stability, because Front is the editor. It also never lets a
  correct crowd overrule a wrong editor (S5, editor fooled). The Readers tab is an honest second opinion on its own page, but three
  accounts reach its top 5.
- **D** ignores the editors, is the least stable at plausible volume, rewards popularity over quality (the overhyped item ranks first), buries
  new items (a Wilson bound is low until views accumulate), and needs view counts. It does not resist brigades.

## Caveats

Simulated readers, no real votes. The assumptions that matter most: rating noise 0.8, about 8 honest ratings per item, a naive brigade
(5 on everything), and upvote behaviour (13% to 22% rate, lognormal views, independent of quality) for D. A smart brigade that rates
close to the editor does less damage and does not trip the shrinkage cap; it would need a person to spot. Re-run `sim.py` when real votes
exist and compare the real `n` per item and the spread of reader means with these assumptions before choosing `k` and the cap.

## If Ryan approves

A follow-up story under the votes, ratings and karma epic: add `ranking.k` and `ranking.readerShareMax` to `config.ts`; replace
`front_score` with the shrinkage form, which needs the per-dimension editor means and a weighted `n` in the snapshot (the weights need
`createdAt` of each voter's profile); keep `readerMinimum` as a deprecated no-op for one release. The snapshot already writes the raw
components next to the score, so ranking can change without migrating data.
