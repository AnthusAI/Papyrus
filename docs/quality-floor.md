# The quality floor: three stars is the minimum for anything public

Decision (Ryan, 2026-11-12, PPY-0e8d66): an item may appear on a public page or in a notification only when its effective human rating is at or above the site's floor. References, Posts, Articles, anything. Nothing else qualifies it.

## The rule

- The rating is `item_stars.effective_rating(...)["stars"]` and nothing else, so when a rating becomes an aggregate of votes (`aggregate_rating`, the seam) the floor follows with no change.
- Unrated is 0 and never qualifies. A Cyclotron prediction or confidence (`confidence`, `predictedAcceptProbability`, the "recommended" status) is a model's guess, not a rating, and never qualifies, however high.
- Accepting a Reference or publishing a Story without stars does not qualify it. A published Story keeps its page at its address; it is not listed, fed, in the sitemap, searched or mailed until someone rates it. Rating a pending Reference already accepts it, so the editor's one action is "rate it".
- Too few items: a list shows fewer. It never lowers the bar and never fills with unrated or AI-only items. A list with nothing that qualifies renders nothing (no heading, no empty box). A notification with nothing that qualifies is not made.
- Stars stay private (`assert_no_item_stars`): the floor is applied where the stars are known, so public files carry only items that passed.

## The setting

`quality` in `projection.json` (`src/papyrus_content/quality_floor.py`):

```json
{ "quality": { "floorStars": 3 } }
```

`floorStars` is a whole number from 1 to 5 and is 3 when the block is there without it. A site may raise it and can never go below 1, because unrated can never be included. **A site with no `quality` block has no floor and nothing changes for it**: the floor is turned on per site, one site under test first, after the read-only report of what would drop. Unknown keys are a build error naming the key.

## Where it applies

One filter, applied once where each consumer's candidate set is built:

| Surface | Where |
| --- | --- |
| Home page, section and tag pages, collections, listing includes (and their fallbacks), feeds (RSS, Atom), sitemap, llms-full, public data files (the public search index) | `StandardMarkusProjector._entries` through `entries.apply_floor`: a Story entry under the floor is not `listed`, not `feed_eligible`, not in the sitemap (`below_floor`), while its own page is still projected. The stars are the private Story ratings of the site index. |
| Public Reference snapshot (home page lists, Findings, Videos, every Reference block) | `home_page.export.is_chosen`: with the floor on only an accepted Reference rated at or above the floor is public; no pending (recommended) Reference is. `homePage.floor_stars` is filled from `quality`. The stored incremental state's fingerprint holds the floor, so turning it on or changing it reads the corpus once. |
| Newsletter roundup | `newsletter.selection.select` (called by `newsletter.roundup.select_for`): the draft names the Stories at the floor; the others follow under a `## Left out` section, each with its reason (below the floor among them), that the editor deletes before sending. The plugin setting `floorStars` (equal to `quality.floorStars`, kept by hand like `itemUrlStyle`) reaches the function as `FLOOR_STARS`. A scheduled week with nothing at the floor makes no draft. |
| Alerts and announcements | Already refuse anything under three stars (`announcements/intake.floor_refusal`, `list_cadence/announce.py`) and fire once ever per Story, when its page is live and rated (`story_wake.py`, the `rated` wake). |

A rating change rebuilds the pages that list the item through the existing path (the story-stars task for Stories, the home-page trigger for References); no new scan.

## Rollout

1. Read-only report per site: how many items on each public surface would drop, by title, so editors can rate what should stay. (Not built yet: tracked on PPY-0e8d66.)
2. The site adds `quality` (and, where it has the newsletter plugin, `floorStars`) in the same release bump that turns the floor on.

## Not covered here

- The Concepts pages list every accepted concept (Ryan, 2026-11-12): concepts are accepted, not star-rated, and are untouched by the floor.
- An editor's association of a one- or two-star Reference with a public Story or Reference (Ryan, 2026-11-12) is not implemented: related lists are not filtered by the floor today.
- The Worth-watching card and `select="recommended"` blocks show nothing once the floor is on, because no recommended Reference is public; whether to retire them or keep a marked AI-only block is open on PPY-0e8d66.
- Alerts and announcements keep their own hard floor of three (no setting lowers it); a list's `minStars` can raise it per list. A site-wide raise reaching the announcement lists is not wired.
- The public Reference snapshot still publishes `stars` on accepted References (PPY-ba2f19, since 2026-11-04) and the `minStars` include reads it; that is separate from this floor.

Specs: `features_backend/three-star-floor.feature`.
