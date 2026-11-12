# Multilingual publishing: one publication in every supported language

Status: plan for agreement, nothing built. Initiative: PPY-82f150. Epics: PPY-5deff0 (M1 model), PPY-251157 (M2 background sync), PPY-376e85 (M3 copy-edit and verify), PPY-756495 (M4 publish and navigate), PPY-6f91de (M5 backfill, operate, evaluate), plus the new epics filed with this plan: spikes before the design is frozen, and Slice 1 (one Spanish Story on Machines on Machines, preview only). Related: guidelines as data (`docs/plans/guidelines-as-data.md`, PPY-2a2a8a), fact-checking (`docs/fact-checking.md`), content item lifecycle (`docs/content-item-lifecycle.md`), how a publish flows (`docs/how-a-publish-flows.md`), multi-tenancy (`docs/multi-tenancy.md`).

Note on the board: PPY-4748b6 "Write executable Slice 1 behavior specifications" belongs to the newsroom-pod Slice 1 (PPY-d0931707), not to this initiative. The multilingual specifications task is filed separately (see "Board changes").

## What Ryan asked for

1. **Primary language at the root.** A site can name a primary language. On Machines on Machines the primary is English, and `https://machines-on-machines.anth.us/` is the English root, not `/en/`. Spanish and Chinese go under a prefix (`/es/`, and Ryan wrote `/cn/`; see the Chinese decision below).
2. **Language-prefixed mode.** Other sites may put every language under its code (`/en/`, `/es/`), and the bare base URL sends the visitor to the language their browser prefers (`Accept-Language`). Primary-at-root sites can also offer that redirect, from the primary base URL. The redirect must be right for search engines and caches: a language the visitor chose sticks, crawlers are never pushed away from the primary root, the CDN cache key is correct, there is no flash of the wrong language.
3. **Two synchronization policies** per site, with an override for a Story (a section override is considered below):
   - **Derive from primary.** Every localization is always derived from the primary-language copy. Edits happen in the primary and are re-translated.
   - **Propagate any edit.** An edit to any localization updates all the others, except edits that are only a local readability tweak, which must not propagate. The editor says which kind an edit is; human-tuned local wording is protected from the next machine re-derivation; conflicts are shown and resolved; who, when and why is recorded; re-translation happens once per change without whole-table or O(N) reads.

Standing rules that shape the design: fix causes, no workarounds, no fallbacks, no compatibility shims; simplest thing that meets the need; narrative Gherkin for every behaviour; no arbitrary fixed limits; DynamoDB is the catalog and text lives in S3; no whole-table reads or O(N) work per change, compute once on change and coalesce; no AppSync subscriptions; nothing made by hand in the cloud; plain UI text, Lucide icons, flat fills, no borders; everything a model writes gets a layered check and human review before publish; an AI-translated page says so to readers and agents; model spend is bounded by data-driven budgets and never silent.

## What exists today

Short version: Papyrus has **no language dimension** anywhere except one site-wide setting. Everything below that says "absent" is plan-only (it lives in the five epic descriptions and nowhere in code).

| Area | In code today | Where |
| --- | --- | --- |
| Site language | `site.language` (default `"en"`) in `projection.json`. Used for `<html lang>`, RSS `<language>` and Atom `xml:lang`, nothing else | `src/papyrus_content/projection/standard/config.py:108,647`, `projector.py:1687`, `feeds.py:86,136` |
| Story versions | Every version is an `Item` row on a lineage: `lineageId`, `versionNumber`, `previousVersionId`, `versionState`, `versionCreatedBy`, `changeReason`, `contentHash`, `stage`, `slug`, `section`. Body text in S3 through `ModelAttachment` (`item_body`) | `amplify/data/schema.ts:2345-2407,2234`, `src/papyrus_content/model_attachments.py` |
| Published copy | `PublishedItem`, id = prefix + `lineageId`: exactly one published row per lineage | `schema.ts:2534`, `src/papyrus_content/publishing.py:80` |
| Publish gate | Checklist closed, per-site publish approval keyed by record id + content hash, images present | `publishing.py:342-430`, `publish_gate.py:104` |
| Checklists | Sub-task Items on `parentLineageId`, template `STEPS` (choose ... fact_check, copy_edit, editor_review ...), stale per Story version | `story_checklist.py`, `newsroom_process.py:60` |
| Guidelines as data | `doctrine` Items with S3 attachments; resolver layers section over publication | `guidelines/store.py`, `docs/plans/guidelines-as-data.md` |
| Language fields in the schema | **Absent** (no `language`, `locale`, `originalLanguage` on any model) | `amplify/data/schema.ts` |
| Language in URLs | **Absent**. Only `urls.basePath`, `urls.style` (html, directory, clean), `urls.sections`, `urls.types` | `projection/standard/urls.py:20-75`, `config.py:36,660-673` |
| hreflang, `x-default`, `og:locale` | **Absent**. Canonical exists (`head.py:105-112`); the only `rel=alternate` links are feeds and the Markdown twin | `projection/standard/head.py` |
| Sitemap | One file or an index, `<loc>` and `<lastmod>` only | `projection/standard/sitemap.py` |
| Search index | One flat `_data/search-index.json`. The client tokenizer splits on `[^a-z0-9]+` after NFD, so Chinese, Arabic and other non-Latin text is dropped | `projection/public_data.py`, `public_assets/papyrus-search.js:27-35` |
| Edge | One CloudFront Function (viewer request): KeyValueStore redirects, pattern redirects, Markdown negotiation by `Accept`, directory index. No `Accept-Language`, no Lambda@Edge | `amplify/publication/redirect-and-index.js`, `amplify/publication/s3-projection.ts:91-143` |
| Invalidation | Targeted only, capped by `publication.cache.maxInvalidationPaths` (default 25), over the cap raises | `src/papyrus_content/edge_invalidation.py`, `page_refresh/budget.py` |
| Markus | No `lang` on spans or blocks, no stable block identifiers; citations format with en-US punctuation | `docs/markus-content-markup.md`, `markus_renderer/citations.py:208` |
| Editorial checks | Humanus packs carry a `language` field that nothing selects on. `fact_check.py` is English-specific (number words, possessives, capitalised names) | `editorial_checks.py:381`, `fact_check.py:88-270` |
| Model cost | Per-run estimates from a price table, `--max-cost-usd` in idea synthesis; no central spend budget | `model_cost.py`, `data/model_prices.json`, `ideas/synthesis.py:33` |
| Email, newsletter, Messages, Cyclotron | No language dimension; email hard-codes `lang="en"` | `email_render/render.py:218` |
| Alexa | `locales` setting, English variants only, one model for all | `amplify/plugins/alexa/config.ts:24-26,76-77` |
| Console UI | No i18n library, `lang="en"` hard-coded; projection chrome strings are English literals (a few labels are configurable) | `app/layout.tsx:57`, `config.py:456` |
| Gherkin | 427 feature files; none about languages | `features/`, `features_backend/` |
| Site scaffold | No scaffold command; public-site config is `projection.json` in the site's static directory | `projector.py:226-231` |

## The model in one picture

- A **language group** is one Story told in several languages. Its key is the primary Story's `lineageId`.
- Each language is its own **localization**: an ordinary Story lineage with its own versions, slug, checklist, approval and published row, plus `language`, `languageGroupId` and, on each version, the exact source it came from (`sourceLineageId`, `sourceVersionNumber`, `sourceContentHash`).
- Each localization version carries an **alignment** in S3: for every block of the localized body, which source block it came from (by block hash), who owns it (`machine` or `human`), and whether it is pinned.
- The site config declares its languages: BCP 47 tag, URL prefix (empty for the primary in primary-at-root mode), direction, display name, enabled state (`preview` or `public`), sync policy.

## Hard problem 1: what a localization is (the version model)

Options considered:

| Option | What it means | For | Against |
| --- | --- | --- | --- |
| A. A version on the same lineage | Spanish is version N+1 of the English Story, with a `language` field | No new linkage | Breaks the version sequence (versions are a linear history of one text), `versionState: current` is per lineage, `PublishedItem` is one row per lineage so two languages cannot be published at once, checklists go stale per Story version so a Spanish edit would reopen English steps. Every one of these needs a special case: shims everywhere |
| B. A sibling Story linked by a language group (**recommended**) | Each language is its own lineage; `languageGroupId` joins them; each localization version records its source version | Reuses everything that already works per lineage: versions, slugs, checklists, publish approval by content hash, `PublishedItem`, retire with redirect, projection per item. Approval of one language can never be mistaken for approval of another, because approvals are keyed by record and hash already | Group-level facts (section, rating, concepts, references, Cyclotron prediction) must be read from the primary, not copied; one new index to find a group's members |
| C. A rendition table under the lineage | New `Rendition` model with its own versions | Clean separation | Rebuilds versions, approval, publish and projection for a second kind of record; two code paths forever |

**Recommendation: B.** The primary stays exactly as it is today. A localization is a Story whose `language` differs from the primary's and whose `languageGroupId` is the primary lineage. Group-level data is never duplicated: section, concept tags, references, stars and Cyclotron predictions are read from the primary through the group key, so they cannot drift.

Data changes (one new index per table per deploy):

- `Item`: `language` (BCP 47 tag, required), `languageGroupId` (tenant-prefixed like the other keys in `tenancy.py`), and on localization versions `sourceLineageId`, `sourceVersionNumber`, `sourceContentHash`, `syncState`. New GSI `languageGroupId + language`. Deploy 1.
- `PublishedItem`: the same fields and GSI. Deploy 2.
- Every existing `Item` and `PublishedItem` gets `language` set explicitly to its site's primary by a bounded, resumable backfill before any code reads the field. No "missing means primary" default: that would be a hidden fallback.
- `languageGroupId` is written on the primary when its first localization is created (compute once on change).
- Slugs: no new slug index. `itemBySlug` already returns a handful of rows; the slug lookup filters by `language`, and uniqueness is checked per language.
- Text stays in S3: the localized body and its alignment JSON are `ModelAttachment`s on the localization version.

## Hard problem 2: the two sync policies and protecting human wording

### Blocks, alignment and ownership

Markus has no stable block identifiers, and adding them to every body is a large change to the markup that readers and agents see. The plan does not need them. Alignment is computed once when a localization version is saved and stored beside it:

- Split the source body into blocks by Markus structure (paragraphs, headings, list items, quotes, captions, figure text). A block's identity is its normalised hash plus its position.
- Each target block records the source block hash it was derived from, its owner (`machine` or `human`) and `pinned` (true for human-owned blocks).
- When a person saves a localization version, diff the previous target text against the new one; changed or added blocks become `human`-owned and pinned. This is the rule "a human edit pins the machine block".
- When the source changes, diff old source blocks against new ones. Only source blocks that changed produce work. For each affected target block:
  - `machine`-owned: re-translate that block only.
  - `human`-owned and its source block unchanged: keep it as is.
  - `human`-owned and its source block changed: **conflict**. Nothing is overwritten. The localization goes to `needs review` with the old source, new source, current human wording and a machine proposal side by side.

Translating changed blocks only (with neighbouring blocks as context) also keeps cost proportional to the change, not to the Story.

### Derive from primary (default)

- Edits in a localization are always local. They pin the blocks they touch, and the localization is marked `diverged` until an editor clears the pin or the source block changes and the conflict is resolved.
- A primary version that reaches the translation trigger (see question 8) queues one job per enabled language.

### Propagate any edit

- Saving a localization asks one plain question with two answers: **Only this language** or **All languages**. There is no default when the policy is propagate; the editor must choose, and must give a reason (`changeReason` already exists).
- **Only this language**: same as derive mode, the blocks are pinned locally.
- **All languages**: the changed blocks are translated into the primary language, a new primary version is created and goes through the primary's own review, and once that version is accepted the normal derive flow updates every other language. Propagation always passes through the primary, so there is one source of truth per block and no language-to-language chains that can loop.
- Conflicts arise when another language has a pinned human block on the same source block; they are shown exactly as in derive mode.

### Terminology memory

- A per-site, per-language **glossary** (term, approved translation, do-not-translate flag, note) lives with the writing guidelines as data (`guideline document`, a new kind `glossary`, layered publication then section). It is the one place for rules such as "never translate *desk*" or product and person names.
- Every translation job sends the glossary entries that occur in the blocks being translated, and the fidelity check verifies them.
- A human change to a recurring term can be offered as a glossary entry (the person accepts or rejects it); it is never learned silently.

### What is recorded

Every localization version records who made it (person or agent), when, why (`changeReason`), its edit scope (`local` or `all`), its source version and hash, the model and prompt version for machine text, the glossary version, the alignment, and the checks that ran on it. Approval is keyed by the localization's own content hash, so approving English never approves Spanish.

### Once per change, no O(N)

- The trigger is the save of a primary version (a DynamoDB stream event or the existing post-save hook, whichever the slice spike shows is already in place). It reads the group's members with one query on `languageGroupId + language` (as many rows as languages) and writes one desired-state record per target language, keyed by `languageGroupId#language#sourceContentHash`.
- A later save of the same primary replaces the desired state for that language (coalescing). A worker only translates the newest desired state, and a job whose source hash is older than the localization's current source is dropped, so out-of-order jobs cannot replace newer or human work.
- Writes made by the translation worker never enqueue translation (the worker writes localizations, and only primary saves trigger).

### Section override

A Story override is enough for the cases Ryan named (a feature that is hand-written in each language). A section-level override adds a third layer to resolve for little gain. Recommendation: site setting plus Story override now; a section override only if a real section asks for it.

## Hard problem 3: URLs, hreflang and the language redirect

### Two URL modes

- **Primary at root** (`urls.languages.mode: primaryAtRoot`): the primary language keeps today's URLs exactly. Other languages live under `/{prefix}/` with the same section structure: `/es/{section}/{slug}`. Existing indexed URLs never change. This is the only mode for an existing site, because moving existing pages under `/en/` would retire every published URL.
- **Language prefixed** (`urls.languages.mode: prefixed`): every language under its prefix; `/` is only a redirector. For new sites.

The URL prefix is a configured string separate from the BCP 47 tag. `<html lang>`, `hreflang`, `og:locale`, JSON-LD `inLanguage` and the feeds use the tag; paths use the prefix.

### Chinese: `zh`, not `cn`

`cn` is the country code for China, not a language. Chinese is `zh`, and what matters for readers is the script: `zh-Hans` (Simplified, mainland China and Singapore) or `zh-Hant` (Traditional, Taiwan and Hong Kong). Recommendation: tag `zh-Hans`, prefix `/zh/`; if Traditional is ever added it becomes `zh-Hant` at `/zh-hant/`. `/cn/` remains possible because the prefix is configurable, but it reads as "for China" and can put off readers in Taiwan, Hong Kong and elsewhere.

### Slugs

Recommendation: each localization has its own slug, drafted in its language when it is first published and then frozen (titles can change, slugs do not). A later slug change uses the existing retire-with-redirect path for that language only. Shared English slugs are simpler but give Spanish readers English URLs and leak the source language into search results.

### hreflang, canonical, sitemap

- Every published page of a group carries `<link rel="alternate" hreflang>` for each published language in the group, including itself, plus `x-default` pointing at the primary page (primary at root) or at `/` (prefixed mode). Only languages that are actually published appear.
- Each page is canonical to itself, never to the primary (canonicalising a translation to its source tells search engines to drop it).
- Per-language sitemaps listed in the sitemap index. hreflang is in the page head only (not duplicated in sitemaps) so there is one place to keep correct.
- Publishing or retiring a localization re-renders its siblings, because their language switcher and hreflang change. That is O(languages) per change and coalesced by the existing publish queue.

### Missing localizations (no fallbacks)

A Story without a Spanish localization has no Spanish page. The language switcher lists only languages that exist for that page. Spanish listings (`/es/`, `/es/{section}/`) list only Spanish Stories. A language is shown publicly only when the site sets it `public`, which requires its interface strings to be complete and reviewed. Nothing ever shows English text inside a Spanish page.

### The language redirect

Design, for both modes:

1. Only the bare root `/` is ever redirected. Deep pages are never redirected, so a shared link always opens what was shared, and crawlers that follow links see what was linked.
2. The decision runs in the existing CloudFront viewer-request function, before the cache. The function reads, in order: an explicit choice in the query (`/?lang=es`, which the language switcher uses), the `papyrus_lang` cookie, then `Accept-Language`, matched against the site's public languages.
3. `/?lang=xx` sets `papyrus_lang=xx` (one year, `SameSite=Lax`) and redirects to the clean URL for that language. This makes a choice stick with or without JavaScript.
4. No `Accept-Language` header, or no public language that matches, means no redirect: the visitor gets the primary root (primary at root) or the `x-default` language (prefixed). Search engine crawlers generally send no `Accept-Language`, so they are never pushed off the primary root. No user-agent sniffing (that would be cloaking).
5. The redirect is a `302` with `Cache-Control: private, no-store` and `Vary: Accept-Language, Cookie`. It is generated by the function and never stored in CloudFront, and the `no-store` keeps browsers and shared proxies from caching it. Pages themselves are unchanged: the CloudFront cache key does not include `Accept-Language` or the cookie, and page responses need no `Vary`, because each URL always returns the same language.
6. Primary-at-root sites: the redirect from the English root is a site setting, off by default. The English root stays a real, indexable English page; a visitor who prefers Spanish and has made no choice is sent to `/es/`.
7. No client-side redirect at all, so there is no flash of the wrong language.

The function grows by one small branch on `/`; the public languages are spliced in at deploy time like the pattern rules already are.

## Hard problem 4: quality, review and labelling

- **Translation engine**: GPT-6 Luna (the LLM default) through the existing OpenAI path, one call per changed block set, with the publication voice, the language's writing guidelines, the glossary hits and protected Markus (links, citations, code, equations, entity names) as placeholders the model cannot alter. Background backfill uses the Batch API.
- **Layered check on every localization version** (the fact-checking standard applied to translation):
  1. Deterministic fidelity: numbers, dates, units, URLs, citation anchors, quotation count, Markus structure, glossary terms and do-not-translate names preserved. This needs language-aware rules; `fact_check.py` is English-only today.
  2. Model judge, bilingual: changed meaning, certainty or qualifiers ("may" becoming "will"), omissions, additions, block by block against the exact source version.
  3. Humanus editorial checks in the target language with that language's policies. English detectors are not assumed to transfer; the spike measures them.
  4. Human review by a person who reads that language, recorded on the checklist. The publish gate already refuses without approval for the exact content hash.
- **Per-language checklist**: a localization's checklist is drawn from a translation procedure template: translate, glossary check, fidelity check, copy-edit, language review, editor approval. Steps with no person who reads the language cannot be closed, so a language without a reviewer stays in preview.
- **Labelling for readers**: a plain line under the byline: "Traducido por IA del original en inglés. Revisado por [name/role]." with a link to the original page. The wording per language lives in the interface strings and is reviewed like them.
- **Labelling for agents**: JSON-LD `translationOfWork` (the original page) and `inLanguage`, `translator` as the software agent; the Markdown twin's front matter gains `language`, `translatedFrom` (URL), `translation: machine` and `reviewed: true|false`; `llms.txt` and the agent-readable guide state that localized pages are AI translations of the linked original.
- **Quotations**: translated, marked as translated in the rendering, with the original wording available beside it (Markus attribute rendered as a note). A Story can be marked "do not localize" (legal sensitivity, satire, wordplay).

## Hard problem 5: cost

- Each job's cost is estimated before it runs from token counts and `data/model_prices.json` (`model_cost.py`), and recorded after it runs.
- Each site gets a translation spend budget per rolling week, set from measured spend (the spike gives the first numbers; afterwards it follows the site's actual publishing rate). When the budget is reached, new jobs wait, the console shows "Translation paused: budget reached" with the backlog and the amount, and the operator can raise it. Never silent, never a fixed cap in code.
- Translating changed blocks only, coalescing rapid edits, and starting translation at the agreed trigger (not on every draft) keep spend proportional to real change.

## Everything else that must be sorted out

### Language and locale

- **Tags**: BCP 47 tags in config (`en`, `es`, `zh-Hans`). Regional variants (`es-ES` versus `es-419`) only when a site really writes two; recommendation: one neutral Spanish (`es`), written for a Latin American and Spanish readership.
- **Right-to-left**: `dir` comes from the language config. The projection's CSS must use logical properties (`margin-inline-start`, not `margin-left`) before any right-to-left language is enabled; mixed-direction runs (English names inside Arabic) need `<bdi>`. Fixture tests with Arabic text from the start, enablement later.
- **Fonts and Chinese**: a CJK font stack (system fonts first, Noto Sans SC as a web font only if the spike shows system fonts are poor), no synthetic italics for CJK, `line-break: strict`, reading-time by characters not words, line-length settings per script.
- **Formats**: dates, numbers, currencies and plurals per language. The projection is Python, so dates and numbers need CLDR data (Babel); interface strings need plural forms (ICU message format) in the string catalog.

### What is translated and what is not

| Translated | Not translated |
| --- | --- |
| Title, dek, blurb, body, captions, image alt text, pull quotes, section names and descriptions, navigation, interface strings, AI labels, `<title>` and meta description, Open Graph text, JSON-LD text, figure text (SVG text nodes, as a localized figure variant; Slice 1 avoids figures with text) | Names of people, organisations and products; code, commands, equations; citations and bibliography entries (stay in the source's language, with the title translated in brackets later if wanted); Reference records and their titles in Slice 1; URLs of sources; user-written Messages and forum posts (original wording is kept; reader-side translation is a later, explicit feature) |

Later, each as its own epic: Concepts Wiki pages and concept names (shared concept identity, localized names and aliases); newsletters and notifications per subscriber language (the living issue Story gets localizations like any Story); RSS and Atom per language (`/es/feed.xml`, simple, in M4); search index per language with a tokenizer that handles CJK (bigrams) and accents; Alexa per language (Spanish locales need their own interaction model); share images with text; email templates.

### Editorial process

- A localization is published when its own checklist closes and its own approval exists; it can go out later than the primary.
- Corrections: a correction to the primary marks localizations stale. A stale localization stays published with an automatic notice ("The original was corrected on [date]; this translation is being updated" with a link to the original) and its re-translation jumps the queue. Taking pages down would break URLs; silently leaving them would leave readers with a wrong fact.
- Retirement: retiring a primary retires every localization; each language redirects to the target Story's localization in the same language, and where the target has none, to the target's primary page (an explicit redirect rule, recorded per URL).
- Ratings and the three-star floor: stars belong to the language group (rated once, on the primary); translation quality is judged by the per-language review, not by stars. One Cyclotron per site, as today; localized Stories show the group's prediction. Votes on localized pages train the same model through the group.
- References and ideas: localized Stories cite the same References (the group's). Reference dedupe groups are unaffected, because References are not localized in Slice 1.

### Surfaces and operations

- **Console**: a Languages panel on each Story (each language with state: missing, translating, needs review, conflict, approved, published, stale, diverged), a side-by-side source and translation view by block, conflict resolution (keep mine, take the new translation, edit), the "Only this language / All languages" choice on save, and a translation budget and backlog view. Console UI language stays English (separate from content language; YAGNI).
- **CLI, MCP, skill parity** (one operation table): `papyrus stories localize`, `papyrus stories localizations`, `papyrus stories localization-review`, `papyrus translations status`, `papyrus glossary ...`. Writes by default, `--dry-run` to preview, as all mutation commands.
- **Analytics**: a GA4 `page_language` custom dimension (GA4's built-in `language` is the browser's, not the page's).
- **Ads and consent**: the consent banner and its legal text per language need reviewed translations before a language goes public; ad networks' language support checked per language.
- **Accessibility**: `lang` on the page and on any foreign-language span inside it; the language switcher names each language in its own language ("Español", "中文") with the `lang` attribute set.
- **Render and edge cost**: each publish now touches the localized page, its siblings and per-language listings. This must stay under `maxInvalidationPaths`; the slice measures it. No new cache behaviours: languages are path prefixes in the same bucket. No bulk invalidation.
- **Multi-tenant (Humorus)**: languages are per site config and every new key is tenant-prefixed. Satire is adaptation, not translation: Humorus stays single-language until someone decides otherwise.
- **Site defaults**: Machines on Machines first (primary-at-root, English, Spanish then Chinese); Anth.us and the other sites unchanged until they opt in. When a scaffold command exists it writes a single-language config with the language block present and one language listed.
- **SEO risks**: search engines accept machine translation that people have reviewed and that adds value; unreviewed bulk translation is treated as scaled low-value content. Human review before publish (already required) and self-canonical pages with correct hreflang are the protection.

### Test strategy

- Narrative Gherkin for every behaviour: version model and alignment (backend), sync policies and conflicts, URL modes and hreflang (projection golden HTML), the edge redirect (CloudFront Function unit tests against `cloudfront-js` semantics), missing-language behaviour, labelling, budget pause.
- Fixtures with Spanish, Simplified Chinese and Arabic text (accents, CJK line breaking, right-to-left), and golden HTML for one localized Story, its English twin and a localized section page.

## How could we screw this up? (inversion)

| Failure | Prevention in this plan |
| --- | --- |
| Break existing English URLs or indexed pages | Primary-at-root keeps every existing URL; prefixed mode only for new sites |
| Redirect Googlebot off the English root, or serve the wrong language from cache | Only `/` redirects; no `Accept-Language` means no redirect; redirects are `no-store`; page cache keys unchanged |
| A machine re-translation silently overwrites a human's careful wording | Pinned human blocks; conflicts instead of overwrites; jobs drop when their source is older |
| Approving English is taken as approving Spanish | Approval keyed by each localization's own content hash (already how the gate works) |
| A Spanish page keeps an error the English page corrected | Stale notice plus priority re-translation |
| Translation spend runs away during backfill | Per-site weekly budget from measured data, visible pause, changed blocks only |
| English-only checks wave through bad Spanish | Language-aware deterministic checks, bilingual judge, target-language Humanus measured in the spike, human reader of the language |
| Half-translated site chrome (English buttons on a Spanish page) | A language goes public only when its strings are complete and reviewed |
| Language-to-language propagation loops | All propagation passes through the primary |
| Per-change cost multiplies with languages | Group query is O(languages); coalesced desired state; incremental projection |
| Chinese search silently returns nothing | Search per language with CJK tokenizing before Chinese goes public |
| Quotes from real people change meaning in translation | Quotes marked as translated with the original beside them; "do not localize" per Story |

## First slice

**Slice 1: one Spanish Story on Machines on Machines, preview only.**

- One existing published MoM Story without text-bearing figures, chosen by an editor.
- Derive-from-primary only. Spanish only. Started by a command (`papyrus stories localize --story X --language es`), no background trigger yet.
- Version model B with the alignment attachment; human edits pin blocks.
- Layered check (deterministic fidelity, bilingual judge, Spanish copy-edit) and human review recorded on the localization's checklist.
- Projection renders `/es/{section}/{slug}` with Spanish `<html lang>`, the AI label, hreflang pair and self-canonical, on the preview tool (`tools/preview_production.py`) only. The English page gains the switcher and hreflang only in preview. No live publish, no edge redirect, no Spanish home or section pages yet.
- Gherkin specs written first and seen to fail.

Slice 2 (after Ryan sees Slice 1): Spanish public on MoM for a handful of reviewed Stories, with `/es/` home and section pages, interface strings, per-language feed and sitemap. Slice 3: background sync (M2) and budget. Then propagate-any-edit, the edge redirect, Chinese.

## Spikes before the design is frozen

1. **Translation quality and cost**: 10 real MoM Stories into Spanish and Simplified Chinese with GPT-6 Luna, block by block with glossary; measure tokens, cost per Story, judge and Humanus findings, and a human reviewer's time and corrections. Output: the first budget numbers and whether English Humanus checks are useful on Spanish. No publishing.
2. **Alignment and pinning**: pure Python on fixtures: split, align, pin, re-derive after source edits (paragraph added, removed, reordered, rewritten), show conflicts. Output: whether hash-plus-position alignment is stable enough without Markus block identifiers.
3. **Edge redirect and hreflang**: the CloudFront Function branch tested with CloudFront's function test tooling and a deployed preview stack (through the pipeline, nothing by hand): cookie, query choice, `Accept-Language` matching, no-header case, cache headers.
4. **Version model**: the `language` and `languageGroupId` fields and the group index in a sandbox backend, with one localization published beside its primary through the real publish path; measure invalidation paths per publish.
5. **Story counts**: how many published Stories each site has, and read counts, to size backfill and its budget (read from indexes, not scans).

## Order of work

1. Ryan agrees this plan and answers the questions below.
2. Spikes 1, 2 and 5 (no deploy), then 3 and 4.
3. M1: `language` field and backfill (deploy 1), group index on `Item` (deploy 1), on `PublishedItem` (deploy 2), alignment, localization versions, provenance.
4. Slice 1 in preview on MoM.
5. M4 for Spanish on MoM (Slice 2): URLs, hreflang, switcher, interface strings, labels, listings, feeds, sitemaps.
6. M3 in full: language-aware checks, translation checklist template, glossary as data.
7. M2: background trigger, desired state, coalescing, budget, Batch for backfill.
8. Propagate-any-edit policy and conflicts UI.
9. Edge redirect (opt-in on MoM; default for new prefixed sites).
10. M5: backfill MoM Spanish by traffic and stars within budget; then Chinese after CJK search and typography.
11. Later epics: wiki and concepts, newsletters, Alexa, right-to-left languages, reader Messages.

## Questions for Ryan

1. Chinese: use the language tag `zh-Hans` (Simplified) with the URL prefix `/zh/` rather than `/cn/`? Recommended: yes.
2. Who reads and approves Spanish, and who reads and approves Chinese? Recommended: a named reviewer per language; a language without one stays preview-only.
3. When a Story has no translation, show no page in that language and list only existing languages in the switcher? Recommended: yes, no English stand-in.
4. When the English original is corrected, keep the translation up with a "being updated" notice and re-translate first? Recommended: yes.
5. Default sync policy "derive from primary", "propagate any edit" as a site setting with a per-Story override, and no section override for now? Recommended: yes.
6. Language redirect: only from the home page, off by default on MoM, never on article pages? Recommended: yes.
7. Article addresses: translated slugs, fixed once published? Recommended: yes.
8. When should translation start: when the English Story is published, or when an editor approves it (so both can launch together)? Recommended: on publish for now.
9. Quotations: translate them, marked as translated, with the original wording shown beside them? Recommended: yes.
10. Stars and Cyclotron: one rating and one prediction per Story across all its languages? Recommended: yes.
11. Budget: a weekly translation budget per site set from the spike's measured costs, pausing visibly when reached? Recommended: yes.
12. Out of the first rounds: Concepts Wiki, newsletters, Alexa, reader messages, the console's own language, right-to-left languages? Recommended: yes, each later as its own epic.

## Board changes filed with this plan

- Initiative PPY-82f150: comment linking this plan and the questions.
- New epic: spikes before freezing the multilingual design (five tasks above).
- New epic: Slice 1, one Spanish Story on MoM in preview, with narrative Gherkin stories, and a task to write its executable specifications first.
- New stories under M1, M3 and M4 for the language group model, block ownership and pinning, sync policies, the translation fidelity check and checklist, URL modes and hreflang, the language redirect, and labelling.
- Dependencies: M2, M3 and M4 blocked by M1; M5 blocked by M2, M3 and M4; M1 blocked by the spikes; Slice 1 blocked by the spikes.
