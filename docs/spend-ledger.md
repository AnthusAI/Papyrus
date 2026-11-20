# The spend ledger

One counter for every scope and budget cycle (PPY-fa165c). It holds numbers only, in integer millionths of a dollar. Code: `src/papyrus_content/spend_ledger.py`.

## Where it lives

The shared monitoring table, because the procedure runner is one stack for every site and a site's own tables cannot be named in its role. Rows:

- `pk = SPEND#<tenant>#<scope>#<cycle start>`, `sk = TOTAL`: `microUsd`, `calls`, `unpricedCalls`, `updatedAt`.
- `pk` as above, `sk = RUN#<run id>`: a marker that the run was counted in this scope (ttl 30 days).

Scopes: `ai` (a site's model spend), `ai:<responsibility>` (one agent), `x:<accountId>` (an X account).

## Who writes and reads

| Who | What | How it reaches the table |
| --- | --- | --- |
| The procedure runner | adds a finished run's cost to `ai` and `ai:<responsibility>`, once per run (marker and totals in one transaction) | the runner role's `SpendLedger` statement, `SPEND#*` keys |
| The X queue's consumer (notifications plugin) | reads before a post, adds after it, in `x:<account>` by the account's X billing cycle | `amplify/functions/announcements/spend-ledger-wire.ts`: the table name from the monitoring parameter, `SPEND#<tenant>#x:*` keys |
| The announcements function | answers `announcementsXSpend` for the budget on the Announcements page and for `papyrus announcements` | the same wiring |
| The announce agent (runner child) | reads before it queues a Delivery | the runner's own environment |

A person's own client never touches the table. A site with no `PAPYRUS_TENANT_ID` on its build gets no ledger variables or grant, and the X counter says it needs one.

## Cycles

AI spend counts in the budget period of the site's agent policy (`day`, `week` from Monday, `month`; a site with no budget counts by the month). X spend counts in the owner's X billing cycle.

## Partial totals

A model call with no entry in the price table is counted in `unpricedCalls`, never as free. A cycle with any is partial.
