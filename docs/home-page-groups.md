# Home page groups: the include lines for the Machines on Machines design (PPY-f24696)

This is the handoff for the site's session. Core supplies the options below on `::include`; the site draws the tiles (its `card` hook and `page_finish`) and lays the rows out with its own CSS. Nothing here is deployed yet: the options exist once the Papyrus version that carries this page is released, and a site that does not use them renders byte for byte as before.

## The four questions

**What does a section-filtered listing look like?**

```
::include{kind="listing" type="article" section="privacy-security" count="2" card="large" layout="bare" unique="true"}
```

`type` is a short form of `types` and `section` of `sections`. Several values are separated by `|` or `,`. A section is named by its `name` in `projection.json` (the stored section), as `sections` always was. Stories are ordered best first: the editors' stars inside a rolling `bucket` (the site's `listings.bucket`, `week` unless the include says `day`, `week` or `none`), then newest. The stars are never printed.

**How is no-repeat scoped?** Per page render. `unique="true"` on a listing claims every Story it places in the page ledger, in document order, and skips any Story an earlier listing on the same page claimed; the next candidate fills the slot. References have always done this (`reference:<key>`), and videos are References, so a video shown in one place is not shown in another on the same page. Stories and References never exclude each other. Nothing is shared between pages. The Markdown twin of the page applies the same rules.

**Is the explainer a block or part of the references include?** Part of the references include, so the card sits inside the grid (as its first `<li>`), not beside it. The text is on the include, so the page is the only place the words live:

```
::include{kind="references" select="recommended" count="16" explainer="How It Works" explainerKicker="About this grid" explainerBody="Automated monitors watch sources across the web..." counts="true"}
```

It draws `<li class="home-page-explainer"><div class="home-page-explainer-card"><p class="home-page-eyebrow">kicker</p><h3 class="home-page-title">How It Works</h3><p class="home-page-explainer-body">body</p></div></li>`. It is not a Reference, never counts toward `count`, and `page_finish`'s tile redraw leaves it alone. When the selection is empty the whole include, explainer too, draws nothing (or its `empty` text).

**How are videos selected by quality?** `medium="video"` with `select="confident"`: accepted videos in the shared order, an editor's stars first (five, four, three), then unrated ones by the Cyclotron's prediction, the unscored last, then one and two stars. Add `bucket="week"` to put this week's best first, then the week before. Ties go to the newest arrival. Stars shape the order and are never shown by core.

## The options

Listing (`kind="listing"`):

| Option | Meaning |
| --- | --- |
| `type="article\|post"`, `section="a\|b"` | Short forms of `types` and `sections`. |
| `sections="N" per="M"` | One group per section: the N sections whose best Story ranks highest (one ranking over `type` and `fallback` together, stars first inside the rolling window, so a section's rank is that of the Story it would show), each with up to M Stories, best first. A digit string is the group count; anything else is still a list of section names. `per` may be a list (`per="2,1"` means 2, then 1 for every later group). A section with nothing to show is skipped, so there is no empty group. |
| `fallback="post"` | When a selection, or a section in a group, has no Story of `type` left (none exist, or `unique` already placed them), use these types instead. It is empty only when there are none of those either. Combine with `unique="true"` so posts used here do not repeat in later post listings. |
| `unique="true"` | Claim and skip through the page ledger (above). |
| `counts="true"` | The wrapper carries `data-count="N"` (how many cards it holds) and the class `papyrus-has-lead` (the first is the best, so the largest). On by default for groups. The `card` hook also receives `count` when it takes that name, next to `variant` and `index`. |
| `heading="true"`, `more="More in {section}"` | Each group starts with `<header class="papyrus-group-head"><h2 class="papyrus-group-title">Label</h2><a class="papyrus-group-more" href="...">More in Label</a></header>`. |
| `tag`, `class` | The group's element (a `section` by default) and its class, as for a bare listing. |

A group is `<section class="papyrus-group {class} papyrus-has-lead" data-section="privacy-security" data-label="Privacy &amp; Security" data-index="0" data-count="2">header + cards</section>`.

References (`kind="references"`), new options:

| Option | Meaning |
| --- | --- |
| `image="none\|any"` | Keep only References with no picture (`none`, text-only cards), or only those with one (`any`). |
| `explainer`, `explainerKicker`, `explainerBody` | The card above, first in the grid. |
| `counts="true"` | `data-count="N"` on the section and the grid (the number of References, the explainer not counted) and the class `home-page-has-lead` on the grid. |

`select="confident"` (accepted) and `select="recommended"` (not yet accepted) already order by stars and then prediction; `recommended` is the Just Found order.

## The five sections as include lines

Put these in `web/pages/home.md` between `::raw` regions that open and close the site's own wrappers. Counts come from the design; every list is best first, nothing repeats, and an empty slot is skipped.

1. Top Articles: the lead, the This Week rail, then the section pair and feature rows.

```
::include{kind="listing" type="article" fallback="post" count="1" card="lead" layout="bare" unique="true"}
::include{kind="listing" type="article" fallback="post" count="2" card="line" tag="div" class="mom-post-lines" counts="true" unique="true"}
::include{kind="listing" type="article" fallback="post" sections="3" per="2,1" card="large" heading="true" more="More in {section}" class="rh-group" unique="true"}
```

   The first group is the pair (two cards); the later groups are the feature rows. The site's CSS alternates the feature rows with `.papyrus-group:nth-of-type(even)`.

   Worth Watching, the row of three videos that closes the first block in the screenshot:

```
::include{kind="references" select="confident" medium="video" count="3" heading="Worth Watching" more="/videos/" counts="true"}
```

2. The band: `::include{kind="block" name="loop-band" role="machine"}` (the site's own block, unchanged).

3. Latest Posts: ten tiles placed in this order inside the site's `<div class="rh-mosaic">` raw wrapper. The order of the lines is the order the ledger claims in, so the first line gets the best post.

```
::include{kind="listing" type="post" count="1" card="tile" layout="bare" unique="true"}
::include{kind="references" select="confident" medium="video" count="1" counts="true"}
::include{kind="listing" type="post" sections="3" per="2,1,1" card="large" heading="true" more="More" class="rh-panel" unique="true"}
::include{kind="references" select="confident" medium="video" count="2" heading="Worth Watching" more="/videos/" counts="true"}
::include{kind="references" select="confident" medium="video" count="1" counts="true"}
::include{kind="listing" type="post" count="1" card="tile" layout="bare" unique="true"}
```

   That is two post tiles, four videos and four panel posts (2 + 1 + 1). The site's hook sizes each by `data-count` and its place so every row is full at every width; core never lays the mosaic out.

4. The second band, as in 2.

5. Just Found, with the How It Works card first and up to sixteen References by quality:

```
::include{kind="references" select="recommended" count="16" heading="Just Found" more="/wire/" explainer="How It Works" explainerKicker="About this grid" explainerBody="Automated monitors watch sources across the web and bring back anything new. Cyclotron, our relevance model, guesses how likely our editors are to accept each one, and it keeps learning from every accept and reject. These cards link to other sites, and we have not written about them yet." counts="true"}
```

## What the site builds itself

- The `card` hook variants (`lead`, `large`, `tile`, `line`) and the hook's use of `index`, `count` and the first-is-largest rule.
- The CSS for `.papyrus-group`, `.papyrus-has-lead`, `[data-count]`, the mosaic and the explainer card, so every row is full at every width. With `data-count` on the wrapper the layout is a plain function of the count.
- The `page_finish` redraw of tiles into reference cards stays as it is; the explainer and the group wrappers are not tiles.
- The loop band blocks and the raw wrappers in `home.md`.
