# Multilingual publishing: one publication in every supported language

Status: plan, revised 2026-11-12 with Ryan's answers to the twelve questions. Nothing built. Initiative: PPY-82f150. Epics: PPY-5deff0 (M1 model), PPY-251157 (M2 background sync), PPY-376e85 (M3 copy-edit and verify), PPY-756495 (M4 publish and navigate), PPY-6f91de (M5 backfill, operate, evaluate), PPY-df65d3 (spikes), PPY-dd2754 (Slice 1). Related: guidelines as data (`docs/plans/guidelines-as-data.md`, PPY-2a2a8a), fact-checking (`docs/fact-checking.md`), content item lifecycle (`docs/content-item-lifecycle.md`), how a publish flows (`docs/how-a-publish-flows.md`), notifications (`docs/notifications.md`), multi-tenancy (`docs/multi-tenancy.md`).

Note on the board: PPY-4748b6 belongs to the newsroom-pod Slice 1 (PPY-d0931707), not to this initiative. The multilingual specifications task is PPY-9753e6.

## What Ryan asked for

1. **Primary language at the root.** A site names a primary language. On Machines on Machines (MoM) the primary is English, and `https://machines-on-machines.anth.us/` is the English root, not `/en/`. Other languages go under a prefix.
2. **Language-prefixed mode.** Other sites may put every language under its code, with the base URL sending visitors to their preferred language. Primary-at-root sites offer the same welcome.
3. **Two synchronization policies** per site with a Story override: derive every localization from the primary, or propagate an edit in any language to the others, except local readability tweaks, which never propagate. Human wording is protected, conflicts are shown, who, when and why is recorded, and re-translation happens once per change without O(N) work.

Standing rules that shape the design: fix causes; no workarounds, fallbacks or shims; simplest thing that meets the need; narrative Gherkin for every behaviour; no arbitrary fixed limits; DynamoDB is the catalog, text lives in S3; no whole-table reads or O(N) work per change; no AppSync subscriptions; nothing made by hand in the cloud; plain UI text, Lucide icons, flat fills, no borders; layered checks on everything a model writes; AI-translated pages say so; model spend bounded by data-driven budgets, never silent.

## Ryan's decisions (2026-11-12)

| # | Question | Decision |
| --- | --- | --- |
| 1 | Chinese code and URL | Language tag `zh-Hans`, URL prefix `/zh/`, a configured setting so `/zh-hant/` can be added for Traditional readers. Never `/cn/`. Simplified versus Traditional audience stays an open item. |
| 2 | Reviewers | A translation is **not** blocked on a reviewer. People responsible for catching translation flaws subscribe to a translation notification per site and language and get a link to correct the page. An authorized corrector role per language. With nobody subscribed the page still appears, clearly labelled AI-translated. Spanish has two reviewers; Chinese has none yet. |
| 3 | When a localization appears | Just in time (JIT): generated automatically by a defined multi-step procedure at the trigger, not assembled by hand. |
| 4 | English original corrected | The translation stays up with a subtle, brief "updating" notice that does not look like an error; it is re-translated promptly. |
| 5 | Sync policy | Derive from primary by default; propagate as a site setting with a Story override; no section override for now. |
| 6 | Language switching | On by default: a small, welcoming countdown banner in the visitor's language on **any** page (home, listings, articles) that exists in the language the visitor's browser prefers. Client-side; no server redirect. Off switch per site. |
| 7 | Slugs | **Tentative** ("sure?"): translated slugs for Latin-script languages, fixed once published; Chinese uses the primary's slug. Ask again before Slice 2. |
| 8 | Trigger | Translate when the English Story is published (cheapest), as a per-publication setting so a bilingual newsroom can later translate at approval. |
| 9 | Quotations | Translate, label as translated, original wording one tap away; never present machine-translated words as the speaker's verbatim quote. |
| 10 | Ratings and Cyclotron | One star rating and one Cyclotron prediction per Story across all languages. Audit and remove any English-only sources policy in Cyclotron training data. |
| 11 | Budget | Tracked separately as "translations" spend per site, set from measured spend, pausing visibly when reached. |
| 12 | Scope | In the MVP that follows: Concepts Wiki pages and concept names are JIT-localized; reader messages are localized with the original always shown first; the console gets its own language setting. Localized Caducus emails later. Right-to-left languages: not now. |

Ryan's decisions 2 and 3 change one standing rule for this initiative: localized pages publish **before** a person reviews them. The layered automatic checks still run before publish and hold back anything that changes facts; people correct afterwards through the notification flow.

## What exists today

Short version: Papyrus has **no language dimension** anywhere except one site-wide setting. Everything marked "absent" exists only in plans.

| Area | In code today | Where |
| --- | --- | --- |
| Site language | `site.language` (default `"en"`) in `projection.json`; used for `<html lang>`, RSS and Atom only | `projection/standard/config.py:108,647`, `projector.py:1687`, `feeds.py:86,136` |
| Story versions | Every version is an `Item` row on a lineage (`lineageId`, `versionNumber`, `versionState`, `versionCreatedBy`, `changeReason`, `contentHash`, `stage`, `slug`, `section`); body text in S3 via `ModelAttachment` | `amplify/data/schema.ts:2345-2407,2234`, `model_attachments.py` |
| Published copy | `PublishedItem`, id = prefix + `lineageId`: one published row per lineage | `schema.ts:2534`, `publishing.py:80` |
| Publish gate | Checklist closed, per-site approval keyed by record id and content hash, images present; slug locked once published | `publishing.py:209-216,342-430`, `publish_gate.py:104` |
| Post-publish fan-out | `announce_published` after a successful projection (newsletter and the `story.published` notification), async, errors swallowed. No DynamoDB stream on `Item` or `PublishedItem` | `content-actions/handler.py:172-214`, `publish_alerts.py:59-89` |
| Checklists | Sub-task Items from one code template `STEPS` (`TEMPLATE_VERSION=5`); no per-Story template choice | `newsroom_process.py:41-118`, `story_checklist.py` |
| Guidelines as data | Designed, not built | `docs/plans/guidelines-as-data.md` |
| Notifications | Built, off on every site. One Papyrus kind (`story.published`); recipients are an SSM operator list; Caducus 0.2.0 has no subscriptions for admin or public classes and no locale support | `notifications/data/notification-kinds.json`, `docs/notifications.md`, Caducus `notify/routing.py:228-234` |
| Roles | Cognito groups admin, editor, curator; editing a Story is all-or-nothing by group; `UserRoleAssignment` has no scope field | `amplify/auth/resource.ts:90`, `schema.ts:28,149-169`, `manage-user-role/handler.ts:14` |
| Sign-in from a link | Google sign-in returns to the saved path and query | `components/reader-auth-control.tsx:34-48,93-103` |
| Language fields | `Item.language`, `languageGroupId`, `sourceLineageId`, `sourceVersionNumber`, `sourceContentHash`, `syncState` and the index `listItemsByLanguageGroupAndLanguage` (PPY-843a7c, deploy 1); `papyrus stories languages` backfills them. `PublishedItem` and the listing keys still have none | `schema.ts`, `item_language.py` |
| Language in URLs, hreflang, `og:locale` | **Absent** | `projection/standard/urls.py`, `head.py` |
| Listings | Driven by `typeStatus` and `sectionStatus` index keys, which have no language part, so a translation would appear in English listings | `publishing.py:170`, `schema.ts:2394-2404` |
| Item ids | `item_id_for(section, slug)` builds ids from section and slug, so a Chinese localization sharing the English slug would collide | `publishing.py:71-73` |
| Slug lookups | Seven call sites read `itemBySlug` and expect one match | `publish_commands.py:72`, `story_commands.py:768`, `section_editing.py:42`, others |
| Sitemap, search | One sitemap; one search index whose tokenizer drops non-Latin scripts | `sitemap.py`, `papyrus-search.js:27-35` |
| Edge | One CloudFront Function: KeyValueStore and pattern redirects, Markdown negotiation, directory index | `amplify/publication/redirect-and-index.js` |
| Markus | No `lang` on spans, no block identifiers | `docs/markus-content-markup.md` |
| Checks | Humanus packs carry an unused `language` field; `fact_check.py` is English-only | `editorial_checks.py:381`, `fact_check.py:88-270` |
| Model cost | Per-run estimates from `data/model_prices.json`; no central spend budget | `model_cost.py` |
| Messages | Public thread export for reference and story conversations | `home_page/threads.py`, `docs/home-page.md:154-177` |
| Wiki | Wiki pages are ordinary `wiki_page` Items written by `knowledge wiki sync`, review-stamp gated | `knowledge_wiki/sync.py`, `docs/public-wiki.md` |
| Console | No i18n; `lang="en"` hard-coded | `app/layout.tsx:57` |

## The model in one picture

- A **language group** is one Story told in several languages. Its key is the primary Story's `lineageId`.
- Each language is its own **localization**: an ordinary Story lineage with its own versions, checklist, published row and URL, plus `language`, `languageGroupId` and, on each version, the exact source it came from (`sourceLineageId`, `sourceVersionNumber`, `sourceContentHash`).
- Each localization version carries an **alignment** file in S3: for every block, the source block it came from, its owner (`machine` or `human`) and whether it is pinned.
- The site config declares its languages: BCP 47 tag, URL prefix (empty for the primary in primary-at-root mode), display name in its own language, state (`off`, `preview`, `public`), and the publication's sync policy and translation trigger.

## Hard problem 1: what a localization is

| Option | For | Against |
| --- | --- | --- |
| A. A version on the same lineage | No new linkage | Breaks the linear version history, `versionState` per lineage, one `PublishedItem` per lineage, and checklists that go stale per version: special cases everywhere |
| B. A sibling Story joined by a language group (**chosen**) | Reuses versions, checklists, approval by content hash, `PublishedItem`, retire with redirect and the projection unchanged | Group facts must be read from the primary; one new index |
| C. A rendition table | Clean separation | A second copy of versions, publish and projection forever |

Data changes (one new index per table per deploy):

- `Item`: `language` (required), `languageGroupId` (tenant-prefixed), and on localization versions `sourceLineageId`, `sourceVersionNumber`, `sourceContentHash`, `syncState`. New GSI `languageGroupId + language`. Deploy 1.
- `PublishedItem`: the same fields and GSI. Deploy 2.
- **Listing keys carry the language.** `typeStatus`, `sectionStatus` and `headStageKey` gain the language for every row (`{tenant}#{language}#article#published`), so English listings, feeds, the board and the home page never pick up translations and Spanish listings list only Spanish Stories. No new index; the same keys, rewritten by the backfill.
- **Localization ids are derived, not slug-based**: `{primaryLineageId}--{languageTag}`. Creating the same localization twice yields the same id, which makes JIT generation idempotent and avoids the slug collision in `item_id_for`.
- **Slug lookups filter by language.** Every `itemBySlug` call site takes a language; uniqueness is per language. No new slug index.
- Every existing `Item` and `PublishedItem` gets `language` and the language part of its listing keys written explicitly by one bounded, resumable backfill before any code reads them. No "missing means primary" default.
- Group facts (section, concepts, references, stars, Cyclotron prediction) are read from the primary through `languageGroupId`, never copied.
- The localized body and its alignment are `ModelAttachment`s in S3.

## Hard problem 2: sync policies and protecting human wording

### Blocks, alignment and ownership (spike PPY-1e2f29 result below)

- Split the body into blocks by Markus structure (paragraphs, headings, list items, quotes, containers). A block's identity is its normalised content hash **plus its occurrence number**, so identical blocks (rules, repeated lines) stay distinct.
- Each target block records its source block identity, owner and pinned flag.
- When a person saves a localization, diff old against new target text; changed or added blocks become `human` and pinned. A paragraph a person adds has no source block and rides after its preceding block.
- When the source changes, diff old against new source blocks:
  - unchanged or moved source block: keep the target block (moving it with its source);
  - changed or new source block with a machine target: re-translate that block only;
  - deleted source block with a machine target: drop it;
  - changed or deleted source block with a pinned human target: **conflict**; nothing is overwritten.

### Derive from primary (default)

Edits in a localization are local and pin their blocks; the localization is `diverged` while pins exist. Each primary publish (the trigger, decision 8) queues one job per enabled language.

### Propagate any edit

Saving a localization asks **Only this language** or **All languages**, with no default and a reason. "All languages" translates the changed blocks into the primary as a new primary version that goes through the primary's own process; once it is published, the derive flow updates the other languages. All propagation passes through the primary, so there are no language-to-language chains or loops.

### Terminology memory

A per-site, per-language glossary (term, approved translation, do-not-translate, note) is a guideline document kind `glossary`, layered publication then section. Translation receives the entries present in the blocks being translated; the rule checks verify them. A corrector's change to a recurring term can be offered as a glossary entry for a person to accept; nothing is learned silently.

### What is recorded

Each localization version records who (person or agent), when, why, edit scope (`local` or `all`), source version and hash, model and prompt version, glossary version, alignment and check results.

### Once per change, no O(N)

- There is no stream on `Item`. The trigger is a durable desired-state record written at the same point as `announce_published` (after a successful projection), keyed `languageGroupId#language`, holding the newest `sourceContentHash`. Unlike `announce_published`, a failure to write it fails the operation loudly.
- The group's members are read with one query on `languageGroupId + language` (as many rows as languages).
- A newer publish overwrites the desired state (coalescing); a worker drops a job whose source hash is older than the localization's current source, so out-of-order jobs cannot replace newer or human work.
- Translation writes never enqueue translation: only primary publishes do.
- The trigger point is the publication setting `translation.trigger` (`published` now; `approved` later for a bilingual newsroom). The desired-state record is the same either way.

## Hard problem 3: URLs and hreflang

### Two URL modes

- **Primary at root**: the primary keeps today's URLs exactly; other languages live under `/{prefix}/` with the same structure (`/es/articles/{slug}/`). The only mode for an existing site, because published URLs are never retired.
- **Language prefixed**: every language under its prefix, for new sites. `/` is a static redirect (the existing KeyValueStore) to the `x-default` language's home; the switching banner then works as on any page.

The URL prefix is configured separately from the BCP 47 tag. `<html lang>`, `hreflang`, `og:locale`, JSON-LD `inLanguage` and feeds use the tag; paths use the prefix.

### Chinese: `zh-Hans` at `/zh/` (decision 1)

Reasoning: `cn` is the ISO country code for China, not a language. Chinese is `zh`; what readers notice is the script. Simplified (`zh-Hans`) is read in mainland China, Singapore and Malaysia; Traditional (`zh-Hant`) in Taiwan, Hong Kong and Macau and much of the diaspora. `/zh/` says "Chinese" without naming a country, so it welcomes Chinese readers anywhere; `/cn/` reads as "for China" and can put off readers in Taiwan or Hong Kong. Browsers send `zh-CN`, `zh-SG` or `zh-Hans` for Simplified and `zh-TW`, `zh-HK` or `zh-Hant` for Traditional, so the banner maps those to the right script.

**Open item (later):** do we want Traditional readers? A Traditional edition is a separate localization (`zh-Hant`, `/zh-hant/`), not a character conversion, because vocabulary differs. Until then, visitors who prefer Traditional get no banner (there is no Traditional page) and can still choose 中文 (简体) in the switcher.

### Slugs (decision 7, tentative)

Translated slugs for Latin-script languages (Spanish), drafted in the language at first publish and then fixed (the existing slug lock). Chinese uses the primary's slug: Chinese characters in URLs become long percent-encoded strings when copied into chat or email, and pinyin slugs are hard to read. A later slug change uses retire with redirect for that language only. **Ask Ryan again before Slice 2.**

### hreflang, canonical, sitemap

- Every published page of a group lists `<link rel="alternate" hreflang>` for each published language in the group, including itself, plus `x-default` (the primary page, or `/` in prefixed mode). Only published languages appear.
- Each page is canonical to itself (canonicalising a translation to its source tells search engines to drop it).
- One sitemap per language in the sitemap index. hreflang lives in the page head only.
- Publishing or retiring a localization re-renders its siblings (their switcher and hreflang change): O(languages), coalesced by the publish queue.

### Missing localizations (no fallbacks)

No Spanish localization means no Spanish page. The switcher lists only languages that exist for that page; Spanish listings list only Spanish Stories (the listing keys carry the language). A language becomes `public` only when its interface strings are complete. English text never appears inside a Spanish page.

## Hard problem 4: welcoming language switching (decision 6, revised)

### What the visitor sees

On any page (home, section and listing pages, articles, wiki pages) that **also exists** in the language the visitor's browser prefers, a small banner appears at the top of the page, written in that language:

> 我们注意到您偏好中文。15 秒后切换到中文版… [立即切换] [留在此页] [暂停]

The number counts down from 15 with a thin progress bar, like a streaming service's next-episode countdown. **Switch now** switches immediately; **Stay here** closes the banner; **Pause** stops the clock. When the clock reaches zero the page switches to the same page in the preferred language. If that exact page does not exist in the preferred language there is no banner (no fallback to that language's home page).

### How it decides

1. The page already lists its translations in `<link rel="alternate" hreflang>`. The projection also inlines the banner's strings for each of those languages (a few short lines each, from the interface strings).
2. A small script matches `navigator.languages` against the page's own language and its translations (`zh-CN` and `zh-SG` match `zh-Hans`; any `es-*` matches `es`).
3. If the best match is the page's own language, nothing happens.
4. If the visitor has a remembered reading language (below), that wins over the browser preference.
5. Otherwise, if the best match is another language this page exists in, the banner appears.

### The remembered choice

- The choice is stored as a **reading language** in `localStorage` (`papyrus.readingLanguage`), set only by a visitor's action: Switch now, letting the countdown finish, Stay here, Undo, or picking a language in the switcher. Stay here stores the current page's language.
- On later pages:
  - Page is in the reading language: nothing happens.
  - Page exists in the reading language: switch at once, without a countdown, and show a quiet note on the arriving page: "Switched to 中文 · Undo" (fades after a few seconds, stays reachable by keyboard). Undo returns to the page the visitor came from and stores that page's language.
  - Page does not exist in the reading language: nothing happens (no banner, no fallback).
- A visitor who clicked **Stay here** on English pages is never asked again on any English page: their reading language is English, so English pages match it.
- The language switcher stores the language picked, so it is always the way to change one's mind.
- Why `localStorage`, not a cookie: no server or cache needs it (nothing at the edge reads it), it never travels with requests, and it is a preference the visitor asked for, which is "strictly necessary" under the EU ePrivacy rules and needs no consent banner. Private windows and cleared storage simply forget the choice; the banner then appears again, once.

### Never frustrating

- Never blocks reading: the banner sits above the content, pushes nothing off screen on phones beyond one short line, and has no overlay.
- Scrolling, typing or selecting text on the page pauses the countdown (the visitor has started reading); the banner stays with Switch now and Stay here.
- Switching uses `location.replace`, so the page left behind is not in the history. Back goes where the visitor came from (search results, the sharing app), never into a loop between two languages.
- Arriving from search or a shared link is treated the same way: the banner appears if this page exists in the preferred language.
- Never loops: the banner appears at most once per page view, and only until the visitor makes a choice; after that, the remembered choice decides silently with Undo.
- Off switch per site (`languages.switchBanner: false`), default on.

### Never toward the primary by countdown (the one concrete exception)

The countdown never switches **to the site's primary language** automatically. When an English-preferring visitor opens a Chinese or Spanish page, they see a quiet "Read in English" link at the top instead. Reason: search engine renderers execute JavaScript, run timers and report an English browser preference. Without this rule, Google's renderer would watch every Spanish and Chinese page count down and redirect itself to English, conclude the translated pages redirect, and drop them from the index. The rule needs no user-agent sniffing and costs English readers only one tap on a page someone deliberately shared with them in another language. Crawlers that render with a Chinese preference (Baidu) could follow a countdown from an English page to its Chinese twin; that only helps them index the Chinese page, which also has its own URL and hreflang.

### Accessibility

- Timing is adjustable (WCAG 2.2.1): Pause, Stay here and Switch now are all available, and scrolling pauses the clock.
- The banner is announced once by an `aria-live="polite"` region when it appears ("Chinese version available; switching in 15 seconds; press Pause to stop"), not on every tick.
- Focus is not moved into the banner (that would interrupt reading); the controls are the first items after the skip link, reachable by keyboard, with visible focus. The banner's text and buttons carry `lang` for their language so screen readers pronounce them correctly.
- `prefers-reduced-motion`: no animated progress bar and no fade; the number still counts down in text.
- Buttons are plain text with Lucide icons (`Languages`, `Pause`, `X`), flat fills, no borders.

### Trade-offs

SEO: pages stay one language per URL with self-canonical and hreflang, so indexing is unaffected; the "never toward the primary by countdown" rule keeps renderers from following translated pages to English, and a Chinese-preferring renderer at most finds a page that is already in hreflang. Caching: nothing changes at the edge; no `Vary`, no cookie, no cache key change; the CloudFront function redirect and `?lang=` handling in the first draft are **removed from the design**. Sharing: a URL always means the same language; the recipient may be offered their own language, and the sender's link is never rewritten. Back button: `location.replace` keeps history clean, at the cost that a visitor cannot use Back to return to the language they were auto-switched from (Undo and the switcher cover that). Analytics: an auto-switch produces two page views (a short one on the first page); a GA4 event `language_switch {from, to, method: countdown|button|remembered|undo|switcher}` and the `page_language` custom dimension keep reporting honest. The costs of being client-side: the banner needs JavaScript (without it, the switcher still works), and a visitor briefly sees the first page before switching (a choice Ryan made in favour of a visible, welcoming switch over a silent redirect).

## Hard problem 5: JIT generation, checks and corrections

### The translation procedure (per language, as data)

A localization's checklist comes from a **translation procedure** stored as data (a guideline document kind `translation-procedure`, publication scope with an optional per-language overlay). It is the first consumer of guidelines as data (PPY-2a2a8a P1), which must land first or be built in this work. Each step becomes a sub-task on the localization lineage, run by the worker, never by hand. Costs below are estimates for a 1,000-word Story at the GPT-6 Luna list price ($0.10 per million input tokens, $0.50 per million output tokens) and must be replaced by measured numbers from spike PPY-3f3aac.

| Step | What it does | Model cost (est.) |
| --- | --- | --- |
| 1. Collect | Source version, changed blocks (or all blocks the first time), glossary hits, language guidelines, the previous alignment | none |
| 2. Translate | Changed blocks with neighbouring blocks as context, Markus protected, quotations marked | about $0.001 |
| 3. Rule checks | Numbers, dates, units, URLs, citation keys, quotation count and markers, Markus structure, glossary and do-not-translate names | none |
| 4. Bilingual judge | Block by block against the exact source version: meaning, certainty, omissions, additions, fluency | about $0.0006 |
| 5. Target-language copy-edit | Humanus with the language's policies (rule lane free; judgment lane as configured) | about $0.0005 |
| 6. Repair | If steps 3 to 5 found high-severity problems, one re-translation of those blocks with the findings; if they persist, **hold**: the localization is not published and subscribers are told it needs a person | about $0.0003 when needed |
| 7. Render and publish | Projection of the localization and its siblings (hreflang, switcher), targeted invalidation | none |
| 8. Notify | Translation notification to the language's subscribers with the correction link | none |

Estimated total: about $0.002 to $0.003 per Story per language, before reasoning tokens. Step 6's hold is the fact-checking gate: a page whose numbers or claims differ from the source is never published automatically.

### Labels for readers and agents

- Readers: one plain line under the byline in the page's language: "Traducido por IA del original en inglés" with a link to the original, becoming "Traducido por IA y revisado por una persona" once a corrector has reviewed the current version.
- Agents: JSON-LD `inLanguage`, `translationOfWork` and `translator`; Markdown twin front matter `language`, `translatedFrom`, `translation: machine`, `reviewed`; `llms.txt` and the agent guide explain it.

### Correctors and the translation notification (decision 2)

- **Notification kind** `translation.published` (class `admin`), with facts title, language, page URL and correction link, grouped by site. Subscriptions are per site and language. Caducus 0.2.0 delivers only to the operator list, so this needs Caducus subscriptions with a scope (`language:es`) from its "preferences" milestone. That Caducus work is a dependency, filed on this board.
- **Corrector role**: a managed role `translator` with a list of languages, granted through the existing `manage-user-role` operations (Administration and CLI). The Cognito group `translator` lets the person open the correction view only; the correction mutation (a Lambda operation, because group rules cannot express "Spanish only") checks the person's languages. Editors and admins can correct every language.
- **Correction flow**: the email link opens `/newsroom/translations/{localizationLineage}` (with `?block=` when the notice is about one block). Google sign-in returns to that link (the existing return path). The view shows source and translation side by side, block by block, with the check findings beside the blocks they concern. The corrector edits a block in place and saves, or presses **Looks right** to record a review without edits.
- **What a correction records**: a new localization version by that person, the changed blocks pinned as human, an optional reason, the rule checks re-run on the changed blocks, and immediate JIT publish. A reviewed-without-edits press records the review on the current version and updates the label.

### Corrections of the original (decision 4)

When a new primary version is published, each localization keeps its page and gets a one-line notice in its language, styled as quiet secondary text (no warning colour, no icon of alarm): "Actualizando según la última versión del original." It disappears when the re-translated version publishes, which normally takes minutes because generation is JIT.

### Quotations (decision 9)

Journalism practice is that a quotation is the speaker's words; translating them is acceptable when the reader is told. So:

- The quotation is translated and marked "(traducción)" / "（译文）" right after it.
- The original wording is one tap away: an expandable note on touch screens and a tooltip on hover, both keyboard reachable, with `lang` set on the original text.
- Markus keeps the original in the quotation's source-language field, which the Markdown twin and JSON-LD expose to agents.
- Never: a machine translation presented as a verbatim quote without the mark.
- A Story can be marked **do not localize** (legal sensitivity, satire, wordplay).

## Hard problem 6: cost (decision 11)

- Each job's cost is estimated before it runs and recorded after, under the spend category **translations** per site (`model_cost.py`, price table, and the cost-allocation tag `papyrus:spend=translations`).
- Each site has a translations budget per rolling week, set from its measured spend and publishing rate. When it is reached, new jobs wait, the console shows "Translations paused: weekly budget reached" with the backlog and amount, and the operators get a notification. An operator can raise it. Never silent and no fixed cap in code.
- Changed blocks only, coalescing, and the publish trigger keep spend proportional to real change.

## Ratings, Cyclotron and the English-only audit (decision 10)

- Stars belong to the language group: rated once, on the primary; the localized page shows the group's rating and voting on it records the vote against the group. Cyclotron predictions are per group; votes on localized pages train the same site Cyclotron through the group.
- **Audit result (read-only, 2026-11-12)**: no English-only sources rule was found in:
  - Papyrus code: the rejection reason codes have no language code (`reference_policy.py:8-18`) and no relevance or curation prompt mentions language;
  - Cyclotron main (`04ae377`): no factor, rubric or label about language;
  - site repositories;
  - the live writing guidelines and editorial context of MoM, Anth.us, Threat Intelligence, Shipped and Pilobolus (read with `papyrus guidelines show` and `papyrus editorial context`);
  - the titles of the 72 rejected References on those five sites (none rejected for language).
- **English bias that does exist** and must change for non-English sources:
  - the topic model's English stop words (`knowledge_snapshot/topic_config.py:28`);
  - Cyclotron lexical retrieval's English stop words `en-v1` and the `ascii-v1` tokenizer option (`decision_flywheel/lexical_retrieval.py:56-65`);
  - the search tokenizer (`papyrus-search.js`);
  - the YouTube transcript preference for English (`references_transcripts.py:127`);
  - the English-only fact checker.
- **Not readable from the editor lane**, so still to check with an operator sign-in:
  - the free-text rejection notes (`curationStatusReason`), which the priming export copies into Cyclotron explanations (`priming_export.py:127`);
  - each site Cyclotron's learned rubric in its runtime store;
  - Data Parade and p.apyr.us, which had no CLI session.
- **Change plan:** (1) operator read of rejection notes matching language words, and language detection on rejected References' titles; (2) read each Cyclotron's learned rubric for language criteria; (3) for each hit, `papyrus references approve --reference ID --dry-run`, then a person confirms the relabel; (4) retrain through the existing retrain trigger; (5) switch the stop-word and tokenizer settings above to language-aware ones. No live Cyclotron data is changed until the list is confirmed.
- **Change list today: empty.** No confirmed English-only label exists yet.

## In scope for the MVP that follows (decision 12)

- **Concepts Wiki**: wiki pages are `wiki_page` Items, so they localize with the same JIT procedure once the primary page is published (the primary's review stamp remains the gate). Concept names and aliases get localized names on the shared concept (short catalog fields), so a Spanish hashtag or link resolves to the same concept.
- **Reader messages, original first**: a thread page always shows each message exactly as posted, in its own language, first. Beneath it, when its language differs from the page's, a secondary "Traducción automática" line, expanded on demand. Translations are generated once when the message is exported (compute once on change), stored in S3 by message id, content hash and language, and only for the site's public languages.
- **Console language**: a per-person setting, separate from content language, with interface strings in a catalog per language (plural rules through `Intl.PluralRules`). Sequenced after Spanish is public.
- **Later**: localized Caducus emails; Alexa per language; share images with text.
- **Not now (YAGNI)**: right-to-left languages.

### Is right-to-left relevant for Chinese?

No. Modern Chinese on the web is written left to right, horizontally; vertical writing is not needed. What Chinese does need:
- CJK fonts (system fonts first);
- line breaking between characters (`line-break: strict`, no hyphenation);
- full-width punctuation (，。「」), with no stray spaces around it;
- no synthetic italics (emphasis by weight instead);
- reading-time estimates by characters, not words;
- a search tokenizer that indexes characters or pairs of characters (today's drops them);
- careful typography where Latin words and numbers sit inside Chinese text.

## Everything else that must be sorted out

### Language and locale

- BCP 47 tags in config (`en`, `es`, `zh-Hans`). One neutral Spanish (`es`) for readers in Latin America and Spain.
- Dates, numbers, currencies and plurals per language: the projection is Python, so dates and numbers use CLDR data (Babel); interface strings carry plural forms.
- The projection's CSS should use logical properties as it is touched, so right-to-left stays cheap later; no right-to-left work now.

### What is translated and what is not

| Translated | Not translated |
| --- | --- |
| Title, dek, blurb, body, captions, image alt text, pull quotes, section names, navigation, interface strings, labels, `<title>`, meta description, Open Graph and JSON-LD text, wiki pages and concept names, reader messages (secondary to the original), figure text as a localized variant (Slice 1 avoids figures with text) | Names of people, organisations and products; code, commands, equations; citations and bibliography entries; Reference records; source URLs |

Feeds per language (`/es/feed.xml`) and a search index per language belong to M4.

### Editorial process

- Retirement: retiring a primary retires every localization; each language redirects to the target Story's localization in the same language, or to the target's primary page when it has none (an explicit, recorded redirect per URL).
- References and ideas: localized Stories cite the group's References; dedupe groups are unaffected.

### Surfaces and operations

- **Console**: a Languages panel on each Story (each language: generating, published, held, updating, diverged, conflict), the correction view, conflict resolution (keep mine, take the new translation, edit), the "Only this language / All languages" choice on save, and the translations budget and backlog.
- **CLI, MCP, skill parity** (one operation table): `papyrus stories localize`, `papyrus stories localizations`, `papyrus translations status|correct|review`, `papyrus glossary ...`. Writes by default, `--dry-run` to preview.
- **Analytics**: GA4 `page_language` custom dimension and the `language_switch` event.
- **Consent and ads**: the consent banner's legal text per language must be reviewed by a person before a language goes public; ad network language support checked per language.
- **Render and edge cost**: each publish touches the localization, its siblings and per-language listings; it must stay under `maxInvalidationPaths` (measured in Slice 1). No new cache behaviours, no bulk invalidation.
- **Multi-tenant (Humorus)**: languages are per site and every key is tenant-prefixed; satire stays single-language until decided otherwise.
- **SEO**: search engines accept machine translation that adds value; scaled unhelpful translation is penalised. Mitigations: the fact-checking hold, correctors, self-canonical pages, hreflang only for published languages, and the countdown rule above.

### Test strategy

Narrative Gherkin for: the version model, listing keys and ids; alignment and pinning; sync policies and conflicts; the JIT procedure, hold and notification; correction and corrector permission; URL modes and hreflang (golden HTML); the switching banner (browser tests with fake timers, reduced motion, keyboard, Back, remembered choice); missing-language behaviour; labels and quotations; the budget pause. Fixtures in Spanish and Simplified Chinese, and the alignment fixtures from the spike.

## How could we screw this up? (inversion)

| Failure | Prevention |
| --- | --- |
| Break existing English URLs | Primary at root keeps every URL; prefixed mode only for new sites |
| Spanish Stories appear in English listings and feeds | Listing keys carry the language, written for every row by the backfill |
| A Chinese localization overwrites the English record | Localization ids derived from the primary lineage and language, not from the slug |
| Search engines see translated pages redirect to English | The countdown never switches toward the primary; static pages, self-canonical, hreflang |
| A Back-button loop between languages | `location.replace`, choice remembered |
| A visitor is asked on every page | A remembered reading language, set only by the visitor's actions |
| A machine silently overwrites a corrector's wording | Pinned human blocks, conflicts, stale jobs dropped (spike: 0 lost edits in 100 runs) |
| A translation publishes a changed number or claim | Rule checks and judge before publish; hold on persistent high-severity findings |
| Nobody ever corrects Chinese | The label says "translated by AI" until a corrector reviews; the translation notification makes subscribing one step |
| Translation spend runs away | Translations budget per site from measured spend, visible pause |
| A Spanish page keeps an error the English page corrected | Quiet "updating" notice and prompt JIT re-translation |
| Chinese search returns nothing | Per-language search with CJK tokenizing before Chinese is public |
| Quotes from real people change meaning | Marked as translated, original one tap away, "do not localize" per Story |

## Spike results (2026-11-12)

### PPY-063c71: published Stories per site (read-only, `papyrus stories list --stage published`)

| Site | Published | Articles | Posts | Words |
| --- | --- | --- | --- | --- |
| Machines on Machines | 138 | 66 | 71 | 85,302 |
| Anth.us | 120 | 119 | 0 | 145,877 |
| Shipped | 74 | 73 | 0 | 14,679 |
| Threat Intelligence | 19 | 18 | 0 | 7,790 |
| Pilobolus | 11 | 10 | 0 | 15,023 |
| Data Parade, p.apyr.us | not read (no CLI session) | | | |

At the estimated $0.002 to $0.003 per 1,000 words per language, backfilling all of MoM into Spanish and Chinese is well under one dollar before reasoning tokens. Budgets will matter for the ongoing judge and repair loops and for reasoning tokens, not for the backfill itself.

### PPY-1e2f29: alignment and pinning without Markus block identifiers

Prototype at `spikes/multilingual/align_spike.py` (pure Python, no model). Ten real MoM Stories (195 blocks), ten scenarios each:
- a person tweaks blocks while the source edits others;
- the source rewrites or deletes a tweaked block;
- the source adds, reorders, splits or merges paragraphs;
- a person adds a local-only paragraph;
- duplicate identical blocks;
- no change.

Result: **0 human edits silently lost in 100 runs**. Rewrites and deletions under a pinned block became conflicts, moved blocks kept their wording, and only changed blocks were re-translated. One defect found and fixed: identical blocks (two `---` rules) shared a hash and were duplicated; identity is now the hash plus the occurrence number. Remaining weakness: inserting a new copy of a repeated block before others renumbers later copies (a re-translation of a separator, harmless). Conclusion: Markus block identifiers are not needed.

### PPY-d50d27: publish path review (no writes)

Option B fits `publish_item` and the projection unchanged per lineage, with three required changes found by reading the code:
- language in the listing keys;
- derived localization ids instead of `item_id_for(section, slug)`;
- a language filter on the seven `itemBySlug` call sites.

Also, the translation trigger must be a durable record written where `announce_published` runs, because there is no stream on `Item` and `announce_published` swallows errors. Invalidation paths per publish still need measuring on a sandbox (part of Slice 1).

### PPY-3f3aac: translation quality and cost (measured 2026-11-12)

Script: `spikes/multilingual/translate_spike.py`. GPT-6 Luna translated each Story block by block, with a glossary, protected Markus and quotation markers; then the rule checks and a bilingual GPT-6 Luna judge ran. Inputs were ten MoM Stories (six articles, four posts) read from the public Markdown twins, because the editor lane has no command that reads a body. Translated into Spanish and Simplified Chinese. Nothing was written to any backend.

**Cost**:
- Total: **$0.047** for 20 translations, translation plus judge.
- Per Story per language: $0.0008 to $0.0063, average **$0.0024**, about $0.0027 per 1,000 words.
- Output tokens (74k against 101k input) include the model's reasoning.
- Translating all of MoM (85k words) into both languages: about **$0.46**.
- Budgets matter only for repair loops and runaway retries, not for volume.

**Quality**:
- Judge scores: fluency 4/5 and fidelity 4 to 5/5 for nearly every Story; one Chinese post scored fluency 3.
- Judge findings: 0 high, 25 medium, 51 low.
- No changed facts. The medium findings are meaning nuances and formatting.

**Defects the spike found, and their fixes (prompt and checks, not workarounds):**
1. **Number formats.** The prompt said "convert nothing", so Spanish kept English separators (`1,250 entrevistas` reads as 1.25 in Spain) and Chinese left English unit words (`低 68 percent`, `约 50 million`). Fix: localize number and unit formatting per language (CLDR); the rule check compares the normalised values.
2. **Rule-check false positives in Chinese.** Nine of the ten Chinese "number" findings were dates rendered with digits (`December 2025` became `2025年12月`). Fix: date-aware, language-aware number comparison.
3. **Gender and number of neutral words.** `parent` became `padre`/`madre` in Spanish and `父母` ("both parents") in Chinese. `one professor's classroom` became the masculine `un profesor` for a woman named earlier. `credential` became plural. Fix: a glossary and guideline note on neutral terms, and the judge already catches these.
4. **Quotation marker placement.** In Chinese, the marker landed inside the quote and duplicated the attribution (`“我还没看过 UI 代码，”[译文] 他写道。`). Fix: the marker becomes Markus markup added by the renderer, not text the model writes.
5. **Markup.** One Chinese citation gained a space (`[ @floorplan; …]`), which the rule check caught. Repair or hold handles it.
6. **Term choice.** `abliteration` became `消融` (that is "ablation"); `disclosure` became `泄露` ("leak", more negative than the original); `soundtrack` became `配乐` ("music score"). These are glossary candidates for correctors.

**Samples for Ryan to judge** (source → translation; ✓ = judge and I find no problem):

| Language | Source | Translation | Note |
| --- | --- | --- | --- |
| es | The sound that can give away where you live | El sonido que puede revelar dónde vives | ✓ |
| es | An anonymous leak, a plane overhead and a company employee list show how the boundary between sharing and disclosure is moving. | Una filtración anónima, un avión que pasa por encima y la lista de empleados de una empresa muestran cómo se está desplazando el límite entre compartir y revelar. | ✓ |
| es | She checks the screen for her reflection. She checks the frame for a window. | Mira la pantalla para comprobar si se refleja. Revisa el encuadre para ver si aparece una ventana. | ✓ natural |
| es | The original Transformer was built to translate sentences | El Transformer original se diseñó para traducir oraciones | ✓ |
| es | …involved in police-reportable crashes… | …tuvieron choques que debían reportarse a la policía… | ✗ implies a legal duty ("had to be reported") |
| es | Anthropic released 1,250 interviews | Anthropic publicó 1,250 entrevistas | ✗ number format (should be 1250 or 1.250) |
| es | Tom is Ann's parent, that Ann is Joe's parent… | Tom es el padre de Ann, que Ann es la madre de Joe… | ✗ invented genders |
| es | The open question is how much a refusal edit changes either one. | La pregunta pendiente es cuánto cambia cada uno una edición para eliminar rechazos. | ✗ garbled subject |
| zh-Hans | The sound that can give away where you live | 能泄露你住在哪里的声音 | ✓ |
| zh-Hans | Waymo's driverless cars crashed 68% less often than human drivers in four cities | Waymo 无人驾驶汽车在四座城市的碰撞率比人类驾驶员低 68% | ✓ |
| zh-Hans | She checks the screen for her reflection… Then she films the demonstration… | 她检查屏幕，看看能不能映出自己的倒影……然后，她拍下工作笔记本电脑上播放的演示视频，并用一个新账号发布了视频。 | ✓ natural |
| zh-Hans | The original Transformer puts an encoder on the left and a decoder on the right. (alt text) | 最初的 Transformer 左侧是编码器，右侧是解码器。 | ✓ |
| zh-Hans | …at a rate 68 percent lower per mile… about 50 million miles | …比人类驾驶员低 68 percent……约 50 million m… | ✗ English unit words left in |
| zh-Hans | the boundary between sharing and disclosure | 分享与泄露之间的界限 | ✗ "leak" instead of "disclosure" (披露) |
| zh-Hans | The edits are often called abliteration. | 这类改动通常称为消融（abliteration）。 | ✗ 消融 means "ablation" |
| zh-Hans | “I still haven't looked at the UI code,” he wrote. | 他写道：“我还没看过 UI 代码，”[译文] 他写道。 | ✗ marker inside the quote, attribution duplicated |

**Conclusions:**
- GPT-6 Luna is good enough to publish JIT behind the layered checks once fixes 1, 2 and 4 are made.
- Its remaining errors are the kind a corrector fixes in seconds and a glossary prevents next time.
- The judge is worth its cost: it found every defect above, except the separator errors it rated medium.
- Humanus target-language checks were not run in this spike. The English packs need Spanish and Chinese policies first.

## First slice

**Slice 1: one Story on MoM, Spanish, JIT, preview only.**
- One editor-chosen published MoM Story without text-bearing figures.
- Derive from primary; Spanish only; the full translation procedure (steps 1 to 8, with notify going to the operator list until Caducus subscriptions exist).
- Version model B with listing keys, derived ids and the alignment attachment, on a sandbox backend.
- `/es/articles/{slug}/` with lang, AI label, hreflang pair and self-canonical, rendered by `tools/preview_production.py` only.
- The countdown banner on the English page in preview.
- A correction by one of the two Spanish reviewers through the correction view, recorded and pinned.
- Gherkin written first (PPY-9753e6) and seen to fail. No live publish.

Slice 2 (after Ryan sees Slice 1 and reconfirms slugs): Spanish public on MoM for new Stories at publish, with Spanish home, section pages, interface strings, feed and sitemap, and the banner live. Slice 3: backfill MoM Spanish by traffic and stars within budget; wiki pages; reader messages. Then Chinese (after CJK search and typography), propagate-any-edit, console language.

## Order of work

1. Fold the PPY-3f3aac fixes into the procedure design: localized number formats, date-aware rule checks, renderer-added quotation markers, a neutral-terms note in the glossary.
2. M1 deploy 1: `language`, listing-key language, derived ids, group index on `Item`, backfill; deploy 2: `PublishedItem`.
3. Guidelines as data P1 (or its minimal part) for the glossary and translation procedure documents.
4. Slice 1 in preview on MoM.
5. Caducus scoped subscriptions; translation notification; corrector role and correction view.
6. M4 for Spanish (Slice 2): URLs, hreflang, banner, interface strings, listings, feeds, sitemaps, labels.
7. M2: desired-state trigger, worker, coalescing, translations budget.
8. Slice 3: MoM Spanish backfill, wiki pages, reader messages.
9. Chinese: CJK search and typography, then `zh-Hans` at `/zh/`.
10. Propagate-any-edit and the conflict view; console language; Cyclotron English-bias settings and any relabels confirmed by the audit.

## Open items

1. Slugs (tentative): confirm translated Latin-script slugs and the primary's slug for Chinese before Slice 2.
2. Traditional Chinese audience: is a `zh-Hant` edition wanted, and when?
3. Ryan's verdict on the translation samples in the PPY-3f3aac results.
4. An operator read of rejection notes and each Cyclotron's learned rubric to finish the English-only audit.
5. Who reviews Chinese (nobody yet; pages will appear labelled as AI-translated).
