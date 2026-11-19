# The time-bucketed quality ranking

One module, `src/papyrus_content/quality_ranking.py`, orders every list of Stories and References that ranks by quality. It knows nothing of pages, snapshots or records: it takes accessors for what it reads. Specified in `features_backend/quality-ranking.feature`, tested in `src/papyrus_content/quality_ranking_test.py` (including properties over seeded random inputs).

## Inputs

For each item: its **stars** (a whole number 1 to 5, anything else is unrated), its **confidence** (the Cyclotron's P(accept), or none), its **arrival** (for ties), its **key** (for ties) and the **date** it is bucketed by. Plus the **bucket** (`day` or `week`) and the **as-of day** (a UTC day, not a time).

## Windows

Rolling, in UTC, counted back from the as-of day. `week` is the last seven days, the seven before that, and so on; `day` is the last day, the day before, and so on (`rolling_age` gives the window number, 0 the newest). The newest window comes first and every item of an older window follows every item of a newer one. An item dated after the as-of day is in window 0; an item with no usable date is in the oldest window.

**The bucket date** is the date the consumer already orders by: for a Story its front-matter date, else when it was published (`entry.date`); for a Reference when it was accepted, and for one with no accepted time (a recommended one) its arrival, and with neither the oldest window (`home_page/ordering.bucket_moment`).

## Order inside a window

1. Three, four and five stars, the most stars first.
2. Items nobody rated: the highest Cyclotron confidence first, then every item with no confidence at all. A missing confidence is not 0.5 and never ties with a real 0.5; it ranks below every scored item.
3. One and two stars, the most stars first. A low rating is a real downgrade and beats a confident prediction.

Equal items go to the newest arrival, then the smallest key. Where a consumer passes no arrival or key (Story listings, which arrive newest first), equal items keep the order they came in.

## What a rating never changes, and what time does

A rating never changes an item's window, because the bucket date does not move with it. Time alone moves an item to an older window, on the day it turns a whole window old, so a ranked list can change at most once a day and only for items that crossed. Nothing is dropped, and ranking a subset gives the same relative order as filtering the ranked whole.

## Public API

| Function | What it does |
| --- | --- |
| `rank(items, stars=, confidence=, newest=, key=)` | The order inside one window. |
| `rolling_age(moment, bucket, as_of)` | The window number of a date. |
| `in_windows(items, moment=, bucket=, as_of=)` | Newest window first; a stable sort, so pass items already ranked. |
| `rank_in_buckets(items, ...)` | The whole algorithm: `in_windows` over `rank`. |
| `valid_stars`, `utc_today`, `BUCKETS` | Shared helpers and constants. |

## Who calls it

- Stories: `projection/standard/story_order.py` (`listings.bucket`, includes, the home list, section, collection and tag pages, the `page.ranked` hook call) and `story_signals.py` (the `stories list` signals).
- References: `home_page/ordering.py` turns the order into a position (`rank`) when the snapshot is written, and orders by that position and the windows when a page is built (`order_in_buckets`); `projection/standard/home_page_blocks.py` places the `confident`, `recommended` and bucketed includes with it, which includes the Worth Watching row.

## With the quality floor

With a site's quality floor on ([quality-floor.md](quality-floor.md)) the unrated and one-to-two-star tiers cannot reach a public page, so the public order is the rating and then the confidence among items at the floor. The newsroom keeps every tier, and a site with no floor keeps every tier everywhere.

## Open

- Whether a one- or two-star rating should stay a hard sink below unrated (it is moot on public pages under the floor).
- Whether the window width should ever be learned from a site's publishing rate instead of day and week.
- The roundup does not order with this module: it lists the items of a window oldest first, grouped by section (PPY-849bf1 decides its selection).
