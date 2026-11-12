# Announcements (X)

Status: backend built and merged to `develop` (epic PPY-09ee86, stories PPY-9f4d66, PPY-ae9d06, PPY-64378c, PPY-a326aa, PPY-8037b8, PPY-24358c); off everywhere. Posting waits for the Caducus `x` channel release and for the account connection (PPY-2deb63). Design: `docs/plans/scheduled-publishing-and-announcements.md`. Owner setup guide: `docs/x-announcements-setup.md`.

A Story that qualifies is announced once on the publication's own X account, automatically. There is **no approval step**: the text passes the automatic checks or is not posted.

## What decides

`src/papyrus_content/announcements/`:

| Module | What it owns |
| --- | --- |
| `settings.py` | The `AnnouncementSettings` row (id `settings`): mode Off (default) / Dry run / On, the minimum stars (1 to 5, never below the quality floor, 3 by default, `quality.floor_stars` in `projection.json`), Story types, optional sections, the account, the budget for each X billing cycle (no default), the billing cycle day, X's price list with the date it was copied, the label confirmation, and the pause. Every rule is checked and every problem listed. |
| `eligibility.py` | Published, not retired, type and section announced, effective human rating at or above the bar. Unrated and predicted never qualify; References are never announced. A Story that is not eligible leaves no row. |
| `drafting.py`, `post.py` | The post: drafted by the policy default model (GPT-6 Luna) from title, dek and summary under the site's `writing` guidelines and `announcement` rules (`papyrus guidelines save --kind announcement`), then checked: length as X counts it (links weigh 23, a link carries `utm_source=x&utm_medium=social&utm_campaign=announcement`, no shortener, no media), no invented mention, hashtag or link, the editorial rule lane when wired, and the layered fact check against the Story. A failed draft is `Blocked: check failed` and is never retried by itself. |
| `budget.py`, `guard.py` | One `AnnouncementSpend` counter per account and cycle, raised for every charge Caducus records. `SpendGuard` is the `Guard` Caducus asks before every post (`refusal`) and after each charge (`charged`). Reaching the budget pauses announcements with the reason; a budget pause ends by itself when there is room, a person's pause never does. |
| `engine.py` | `process_story(services, lineage_id, trigger=...)`: one entry for first publish and rating changes, safe to call any number of times. `sync_row` copies Caducus's delivery result onto the row. `release_blocked` and `resume` announce what waited. |
| `store.py` | `Announcement` rows (id `<accountId>#<lineageId>`, created with a condition), the post document in S3 (ModelAttachment role `announcement_document`), the account index. |
| `channel.py` | The contract with Caducus's `x` channel (PR #13 in AnthusAI/Caducus). |

Storage follows the standing rules: catalog rows only, text in S3, no table is listed (the account's rows are read newest first through the one index on the new `Announcement` table, the other two models are read by id), no AppSync subscription, no new index on an existing table.

## States

`posting` (handed to Caducus), `posted`, `failed` (X's message kept), `blocked` (paused, budget reached, account needs reconnecting, check failed), `dry_run` ("Dry run: not sent", cost 0), `withdrawn`. Each row keeps a history of who did what and when; it is never rewritten.

## Through Caducus

Papyrus hands Caducus one `story.announce` event per announcement (event id `story.announce:<accountId>:<lineageId>`, class `broadcast`, `audience` `CHANNELACCT#x#<accountId>`, `facts.text` and `facts.url`). Caducus claims the delivery, posts, handles unknown outcomes (it reads the account's recent posts before any retry), waits out rate limits and records the post id and cost. A guard refusal is final for its event id, so the announcement made after the guard lifts is round 2 (`...:r2`).

What Papyrus supplies at deploy: the token provider (the account connection), `SpendGuard`, the price table (`channel.prices_from_settings`), `Directory.account`, the `story.announce` kind and an `x` queue with one consumer (so a budget check and a charge cannot race). That wiring ships with the Caducus release.

## CLI and MCP

`papyrus announcements list|show|dry-run|pause|resume|settings show|settings set|account status`, from the one operation table (`src/papyrus_content/images/operations.py`, group `announcements`); see `docs/agent-cli-guide.md`. `settings set` is for a person only.
