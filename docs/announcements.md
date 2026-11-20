# Announcements (X)

Status: X is built on the Announcement and Delivery records (PPY-efd06c, slice 3 of epic PPY-a36492) and is **off everywhere**: the mode is Off by default, the deliver side refuses to send unless the mode is On, and the Caducus `x` channel is not deployed on any site. The first build of X (epic PPY-09ee86) wrote one row of its own for each Story and account; that row shape, its model `Announcement`, its account index and its round suffix are deleted. Owner setup guide: `docs/x-announcements-setup.md`. Design: [announcement records](announcement-records.md) and `docs/design/announcement-delivery-design.md`.

A Story that qualifies is announced once on the publication's own X account, automatically. X is **one channel of the Story's Announcement**: the announce agent (woken by the Item change feed when a page goes live or a rating changes) asks whether the Story qualifies on X, and the Announcement is made together with its first Delivery, or the X Delivery is added to the Announcement that already exists. How much human review a Delivery gets is the announce rung of the agent policy ([review policy](announcement-records.md#review-policy-ppy-97c0f2)); the text itself passes the automatic checks or is not sent.

## What decides

`src/papyrus_content/announcements/`:

| Module | What it owns |
| --- | --- |
| `settings.py`, `x_account.py`, `stores.py`, `actions.py` | The account connection and the settings document (PPY-2deb63, PPY-ae9d06), unchanged: mode Off (default) / Dry run / On, the pause switch with reason, the bar (minimum stars, never below the 3-star quality floor), Story types, sections, the budget for each X billing cycle (no default), the billing cycle day, X's price list with its date, the Automated-label confirmation, the edit windows and the post spacing; the write-only app keys in SSM SecureString, the refresh under a DynamoDB lease, `needs_reconnecting` with an automatic pause. The `announcements` function serves them to the console and the CLI. |
| `rules.py` | One flat read of the settings document and the connection. |
| `eligibility.py` | The channel's own rules: published, not retired, type and section announced, effective human rating at or above the bar (`refusal` says which rule and why). Unrated and predicted never qualify; References are never announced. |
| `x_announce.py` | What decides whether X gets a Delivery, in order: the mode, the channel's rules, the floors under every policy (nothing under three stars, a five only from a person), a connected account, the source rule and the review policy. Then the draft and its checks, a dry run, the blocked draft that asks once, and the redraft that happens only when an input changed. |
| `drafting.py`, `post.py` | The post: drafted by the policy default model from title, dek and summary under the site's `writing` guidelines and `announcement` rules (`papyrus guidelines save --kind announcement`), then checked: length as X counts it (links weigh 23, a link carries `utm_source=x&utm_medium=social&utm_campaign=announcement`, no shortener, no media), no invented mention, hashtag or link, the editorial rule lane when wired, and the layered fact check against the Story. The Delivery's words are the post exactly as it will go. |
| `x_channel.py`, `channel.py` | `XChannel`, the one adapter between an X Delivery's attempt and Caducus's `x` channel (the contract is `channel.py`): hand over one attempt's event, read Caducus's record as the attempt log's answer, delete a post. |
| `x_runner.py` | The deliver side: `SpendControl` (the pause, the account connection, the budget against the cycle's spend), `XRunner` (sends one due X Delivery through its account's single worker, and refuses unless the mode is On), `resume_blocked`. |
| `budget.py`, `guard.py`, `spend.py` | One counter per account and billing cycle in the shared spend ledger (`spend.SpendLedger`, scope `x:<accountId>`, `docs/spend-ledger.md`), raised atomically for every charge Caducus records. The X consumer and the announce agent read it from the table; a person's command line reads it through the announcements function (`announcementsXSpend`). The old `AnnouncementSpend` model is no longer used and is removed in a later release. `SpendGuard` is the `Guard` Caducus asks before every post (`refusal`) and after each charge (`charged`). Reaching the budget pauses announcements with the reason; a budget pause ends by itself when there is room, a person's pause never does. |
| `withdrawals.py` | Withdraw a Delivery, and delete the post a correction replaced. |

Settings are never stored twice: this package reads the document `settings.py` owns. The token provider for Caducus is `channel.CaducusTokens`, over `XAccounts.access_token`. Storage follows the standing rules: catalog rows only, text in S3, no table is listed (an account's Deliveries are read newest first through the account index; the spend counter is read by id), no AppSync subscription, no new index.

## Channel rules

- **X needs the floor rating, a Delivery is made for the channel only when the Story qualifies on it.** A publish that qualifies on no channel leaves no row. A later rating that reaches the X bar adds the X Delivery to the Announcement the first wake made (`Deliveries.add` through the same once-only key), with an edit window counted from then.
- **Quality floor.** No setting lowers three stars. Unrated Stories and a model's prediction never qualify. A machine never supplies the five: a five counts only when a person gave it (`intake.floor_refusal`).
- **A Delivery is drafted once.** A Story whose Announcement already has an X Delivery is not drafted for again, whatever woke the agent.

## States

A Delivery's states are the records' (`drafted`, `ready`, `sending`, `blocked`, `sent`, `failed`, `dry_run`, `withdrawn`, `superseded`). On X, `blocked` carries a reason: `paused`, `budget reached` (the attempt was refused by Caducus's guard), or `check failed` (the draft did not pass). Each Delivery keeps a history of who did what and when; it is never rewritten. A pause, the budget or a rate limit ends an attempt; the next try is the next attempt of the same Delivery.

## Blocked draft: one request, no loop

A draft that fails a check is a blocked Delivery and **one** review request, a flag nobody waits for, for the Announcement (not one for each channel or each wake). It is drafted again only when an input changed: the Story's version or the guidelines (the draft's checks record the version and a fingerprint of the guidelines it was written under). The check is made whenever the announce agent wakes for the Story; a guidelines change has no wake of its own yet.

## Dry run, and X off

A dry run builds the Delivery, runs every check and sends nothing: its state is `dry_run`, its cost is 0, it waits for no time and no channel ever sees it. With the mode Off nothing is made. With the mode On the Delivery goes through its account's one worker like any Delivery: the attempt is written before Caducus is called, Caducus posts and records the post id and cost, and Papyrus reads the record (`x_runner.XRunner.settle`). `XRunner` refuses to send unless the mode is On.

## Withdraw and corrections

`papyrus announcements withdraw DELIVERY` stops a Delivery that has not gone and takes back one that went where the channel can: a post on X is deleted through Caducus (never blocked by a pause or the budget), and the Delivery keeps who withdrew it (its history) and what the post cost in all. A sent email or a post made by hand cannot be taken back and is refused. A person always may; an agent only when every Story the Announcement is about was retired. When every Delivery of an Announcement is withdrawn the Announcement is too.

A correction is a new Delivery that supersedes the old one. On X the old post is deleted as part of it, and the deletion cost is written on the old Delivery: by the site's own X channel when the correction is made, otherwise by the deliver side just before it sends the corrected Delivery (the signed-in command line holds no rights on Caducus). Both are safe to repeat after a crash.

## Through Caducus

Papyrus hands Caducus one `story.announce` event per attempt (event id `delivery:<deliveryId>:a<N>`, no round suffix; class `broadcast`, `audience` `CHANNELACCT#x#<accountId>`, `facts.text` the post and `facts.url` its link). Caducus claims the delivery, posts, handles unknown outcomes (it reads the account's recent posts before any retry), waits out rate limits and records the post id and cost. A guard refusal closes the attempt, and the try after the guard lifts is the next attempt (`...:a2`).

What Papyrus supplies at deploy, and where it lives: the token provider (`channel.CaducusTokens` over the account connection), `guard.SpendGuard`, the price table (`caducus_x.SettingsPrices`, read from the settings document on every use), `caducus_x.SiteAccounts` (`Directory.account` answers the connected account), the `story.announce` kind (`notifications/data/notification-kinds.json`) and the `x` queue with one consumer (the notifications plugin: queue, dead letter queue and alarm, and the consumer function with reserved concurrency 1 so a budget check and a charge cannot race; `notifications/x_sender.py`). `caducus_x.CaducusBroadcaster` is the `Broadcaster` over Caducus's router, delivery log and `XChannel`; the notifications runtime builds it only when the function has `X_QUEUE_URL` (`runtime.x_wiring`). The announce agent's deliver step (`x_delivery.send_due`) uses it; a site set to On without it raises `ChannelNotAvailable`, and a site that is Off or in a dry run needs none. X is off everywhere until the owner turns it on, and nothing in the specs reaches X (`features_backend/announcements/announcements-x-through-caducus.feature` runs Caducus's own router, delivery log and `x` channel against a fake X server on localhost).

## CLI and MCP

`papyrus announcements where|recent|explain|dry-run|blocked|retry|pause|resume|withdraw|correct|settings show|settings set|account status|account connect|account set-app`, from the one operation table (`src/papyrus_content/images/operations.py`, group `announcements`); see `docs/agent-cli-guide.md`. `settings set` and `retry` are for a person only. `account status` also shows our count of the posts sent this billing cycle (a deleted post still counts: X charged for it) and a budget suggestion from the site's own pace over the last 60 days at the link price, shown as a pace and never applied as a limit; `blocked` lists the Stories that qualified and wait, each with its reason; `retry` puts a failed Delivery back to ready (the attempts stay in its log); `account connect` prints the newsroom page (Administration > Announcements) where the account is connected, because connecting is a browser step. The app's keys are saved with `account set-app --client-id ID` (a person who is an admin; the secret from `PAPYRUS_X_CLIENT_SECRET` or standard input, never a flag, and a `--dry-run` shows it as `(hidden)`): the secret goes to SSM SecureString and the ID to the connection record in one call, the same as the console's Save keys button. The list and show commands of the old row shape are gone: a Story's Announcements are read with `where`, the list with `recent`.
