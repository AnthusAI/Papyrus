# Shared publication front end

Umbrella: PPY-6702e2 (Papyrus ships a neutral public theme and two example themes). Pulls forward PPY-31efef (core cards, publication layout, brand pack), PPY-2a44b2 (tokens at final sizes), PPY-e572de (brand pack storage), PPY-88a883 (brand pack format and validator), PPY-3aa10f (starter template) and later PPY-f30ad5 (`papyrus site init`).
Requested by Humorus (HUM-1be843, HUM-dc9f71). Facts verified 2026-11-15 against Papyrus `origin/develop` bd11f4d34, Machines on Machines (MoM) `origin/develop` a65d112 and Humorus `origin/develop`.

Status: design for review. Nothing here is released. Decisions it is bound by are in "Bound by" below; open questions with defaults are the last section.

## Goal

Machines on Machines (machines-on-machines.anth.us) and TheHallucinator.ai (Humorus) both render on one Papyrus front end: the same cards, the same page layout, the same language handling, the same tokens and checks. They look different because each has its own brand pack (and MoM keeps a few ornaments in code), not because each has its own front end. A site with only a name looks finished; a brand pack restyles it; a brand pack cannot carry code.

## Bound by

- Canon (Ryan, 11-12): the ideal design first, never compromised for immediate pressure; no interim systems. So there is no interim copy of MoM's hooks into Humorus.
- No workarounds, fallbacks or shims (standing order). Where this plan moves behaviour from MoM into core, MoM's copy is deleted in the same slice that releases core's.
- Gherkin for every behaviour change; flat tones, no borders, Lucide icons only; colour is never the only signal (Ryan is colourblind).
- MoM must look the same afterwards (umbrella text, HUM decision 7). "The same" is defined by a measured visual diff, below.
- Humorus rule 2: a site folder holds settings, not code. No hooks, no CSS beyond tokens. Rule 7: satire is labelled on every page.
- Brand pack is validated data (`docs/brand-pack.md`, `src/papyrus_content/brand_pack/`); this plan extends it, it does not replace it.

## What exists today (the starting point)

Papyrus core already has the pieces, in two unrelated vocabularies:

- Core front end (`src/papyrus_content/projection/standard/`): `components.py` (`markus-*` markup: breadcrumbs, card, tags, byline), `home_page_components.py` and `assets/papyrus-home-page.css` (`home-page-*` tiles, rows, threads, stars, meter), `assets/markus-components.css`, `papyrus-section-fronts.css`, hooks (`masthead`, `footer`, `card`, `main`, `page_body`, `page_finish`, `block`, ...). Sizes are written in `rem`. Colour is `--papyrus-*` custom properties with fallbacks. Some rules still draw 1px borders (`.markus-logo a`, `.markus-column[data-panel="card"]`, the nav group panel).
- Brand pack v1: nine colour roles in light and dark, two fonts from a ten-family allow-list, logo, wordmark, image-style slot; validator checks contrast (4.5:1 text) and lightness separation (3:1 non-text). Not yet applied to any page: PPY-e572de stores and serves it.
- MoM (its own repository): `web/hooks.py` (2243 lines), `web/mom_components.py` (743), `web/css-src/site-theme.src.css` (~2000), `design/system/components/bundle.css` and `tokens.css`, `mom.js`, `mom-language.js`, `languages.py` (179). The PPY-31efef text says "about 940 lines"; it has grown to about 3,000 lines of Python plus the CSS. Roughly half of `hooks.py` is regular-expression surgery on core's stock home-page output (`_home_groups`, `_home_columns`, `_home_reserve_stories`, `_rail_conversations`, `_tile_to_reference_card`, ...). That is a signal that core's home and listing output lacks options MoM needs, not that those belong in a site.
- Wide-screen sizing: `tools/scale_css.py` multiplies every px by 0.75 from 600 px up, sets `html { font-size: 75% }` (which also scales core's rem stylesheets), then raises text to floors of 18, 14 and 13 px. Three generated stylesheets (`mom-tokens.css`, `mom-components.css`, `site-theme.css`, 240 KB together) are produced from sources by `tools/sync_design_assets.py`.
- Humorus (TheHallucinator.ai) today is not on this front end at all: `renderer: pretext` (the Next.js reader), no `publication` block, no `web/` directory, a 24-line `publication/theme.css` of four tokens. Its "super-basic" layout is the built-in reader. Moving it onto the standard front end (`publication.kind: s3-projection`) is part of this plan (slice 4); that is why it needs a brand pack and no hooks.

## Layers: what is core, what is brand pack, what is ornament

| Layer | Holds | Who edits | Carries code? |
| --- | --- | --- | --- |
| Core | The token vocabulary and its final-size values, the base stylesheet, the card set, the publication layout preset (page kinds, regions, navigation, menu, footer, home groups), language switcher, banner and strings handling, accessibility behaviour, platform checks | Papyrus | Yes (Python, CSS, small JS) |
| Brand pack | Name, logo, wordmark, colours for light and dark (the nine roles plus optional named role colours), two fonts, shape (corner scale), ornament level (an enumerated choice), image style | A site owner, in the newsroom or as JSON in the site repository | No. Validated data only |
| Ornament hooks | Decoration and site-only features: MoM's sticker, spine, loop band, halftone panel, wordmark seal, placeholder-art compositions, ads, its forum and findings pages | A publication repository, in Python, behind the existing named hooks | Yes, and only into named ornament slots (below) |

Rule for deciding where something goes: if a second publication would want it unchanged, it is core. If a site only wants it restyled, it is a token. If it is a drawing or a feature no one else asked for, it stays an ornament hook in that site's repository (PPY-31efef already says "promote only what a second consumer also needs"). Humorus is the second consumer for cards, layout, languages and tokens; nothing in MoM's ornament set has a second consumer, so nothing in it moves.

### Ornament slots

The preset exposes fixed, named places where a hook may add markup; with no hook, or with the brand pack's ornament level set to `none`, the slot is empty and the layout holds together without it:

- `masthead-mark` (in the masthead: MoM's sticker and wordmark seal),
- `page-top-art` (above a page title: MoM's halftone panel),
- `section-band` (between home groups: MoM's loop bands),
- `rail-end` (end of the article rail: MoM's spine, ads),
- `card-art` (the picture slot of a card with no picture: MoM's placeholder-art compositions; core's default is a flat tone block with the site's wordmark initial).

Slots are called through the existing hook mechanism (`block`, `masthead`, `page_finish`); this plan adds the slot names to the preset so a hook no longer has to find its insertion point by pattern-matching core's HTML. The brand pack's `ornaments` field is an enumeration (`none`, `quiet`, `expressive`) that core's own stylesheet reads; it never names a file or a rule.

## The card set

One card component with variants replaces core's two overlapping systems (`markus-card` and `home-page-tile`/`home-page-row`/`home-page-thread`) and MoM's `mom-*` set. Correction after reading the consumers (2026-11-15): the class family is not renamed. `markus-card`, `home-page-tile`, `home-page-row` and `home-page-thread` appear in about a dozen core test files, the golden `expected/` HTML of four fixture sites and the stylesheets of every Papyrus publication, so a rename is a breaking change across all seven sites that buys readers nothing. Slice 1b therefore keeps the existing class names as the canonical vocabulary, folds MoM's variants into them as `data-variant` and `data-size` attributes on one card builder (`components.card(entry, variant=..., size=...)` plus `reference_card`, `thread_card`, `term_card` sharing one set of parts: image, kicker, title, blurb, meta, chips), moves their sizes onto the tokens, and removes only the duplicated rules. MoM's `mom-*` classes are then deleted from MoM when it adopts them (slice 1c). A rename, if ever wanted, is a separate breaking step after the isolation suite and a security review, like the other breaking steps.

Inventory from MoM (`web/mom_components.py`, `design/system/components/`):

| MoM component | Becomes in core | Fed by | Notes |
| --- | --- | --- | --- |
| `story_card` (large, medium, brief, with kicker, meta, blurb, image) | `card(variant="story", size=...)` | Story entry, `card_image` | Every card has an image and a one-sentence blurb (house rule). No image: `card-art` slot, default flat tone block |
| `reference_card` with `confidence_meter`, `star_rating`, `reference_status`, optional click-to-play `player` | `card(variant="reference")` | Reference tile data | Overlaps core `home-page-tile`; the meter and stars already exist in core and are kept. The click-to-play video card is core (any publication with videos wants it, no JS until pressed) |
| `thread_card` | `card(variant="thread")` | Conversation thread | Overlaps core `home-page-thread` |
| `wiki_card` (term, associations, definition) | `card(variant="term")` | Concept / wiki page | Counts in the site's words from strings |
| `provenance_chip(s)`, `star_rating`, `confidence_meter` | `chip`, `stars`, `meter` | | Always text plus a mark; colour only supports it |
| `button`, `nav_pill`, `menu_button`, `menu_panel` | `button`, `nav-pill`, `menu` | `site.nav` | Lucide icons (`lucide_icon` table is replaced by core's icon set) |
| `language_switcher`, `language_menu_section`, `language_banner` | `language-switcher`, `language-banner` | `page.alternates`, `page.strings` | See "Languages" |
| `pull_quote` | `pull-quote` | Markus quote block | |
| `article_actions` (share, copy Markdown) | existing core page actions | | Core already ships this; MoM's copy is deleted |
| `forum_row`, `forum_board`, `proposal_row`, `wire_card` | stay in MoM (ornament / site feature) | | Conversations forum belongs to a different feature epic; revisit when a second site wants it |
| `sticker`, `spine`, `loop_band`, `wordmark` seal, `placeholder_art` compositions, halftone, ads | stay in MoM as ornaments | | Filled into ornament slots |

Cards carry no border and no hairline; separation is fill and space. Cards are links with one primary target; a card's text size obeys the floors below.

## The publication layout preset

`layout: "publication"` in `projection.json`. It owns the regions MoM currently builds by hand:

- Page frame: skip link, masthead (name or logo, optional tagline, nav pills, menu button, theme and language controls), `main`, footer. Masthead and footer text come from site settings and strings; hooks replace them only if a site truly needs to (MoM keeps its masthead as an ornament-filled variant of the preset's).
- Page kinds and their regions: home (lead, section groups in a column count, a trailing findings grid, a conversations rail), section and type listings (page header with count and dek, a lead row, a card stream, paging), article (header, optional hero, body column at the measure, a right rail with sources, concepts and related, end matter), concept/wiki term page, authored page, reference list, conversations page.
- The home page options MoM currently simulates by rewriting HTML move into the preset as options: columns per breakpoint, stories per group, a reserve of stories to fill short rows, a "more" link per group that names its object. These land together with the index-page work now in flight (see "Collisions").

The preset consumes data core already produces (`page.entries`, `page.alternates`, `page.strings`, `page.related_*`, `page.concept_links`) and calls named hooks only for ornament slots.

## Tokens at final sizes

Retire `tools/scale_css.py`, the phone stylesheet plus scaled stylesheet pair, and `html { font-size: 75% }`. Core ships one set of custom properties in the sizes people see, at two named layouts (compact: under 600 px, as MoM's phone sizes; wide: 600 px up, as MoM renders today). The wide values are authored numbers, not products of a multiplier. For the migration they are taken from the generated output once, so the migration changes no pixel; after that the numbers are edited like any other design token.

Format (one stylesheet, `papyrus-tokens.css`, `:root`, with `@media (min-width: 600px)` overriding only tokens whose wide value differs):

- Colour roles (already in the validator): `--papyrus-bg`, `-ink`, `-muted`, `-band-bg`, `-band-card-bg`, `-band-muted-bg`, `-button-bg`, `-button-ink`, `-rule` (used as a fill step, never a border), `-focus`, plus optional named role colours `--papyrus-role-<name>` and `--papyrus-on-role-<name>`.
- Type: `--papyrus-font-heading`, `--papyrus-font-body`; sizes `--papyrus-text-display`, `-headline`, `-title`, `-lede`, `-body`, `-interface`, `-label` and a line height for each, in px, final values.
- Floors as tokens: `--papyrus-floor-reading: 18px`, `--papyrus-floor-interface: 14px`, `--papyrus-floor-label: 13px`. The linter (below) fails any text-size token below its floor, in both layouts. MoM's rule "text has a floor in rendered pixels" is thereby enforced on the tokens instead of by rewriting every rule.
- Space and shape: `--papyrus-space-1..12` (4 px rhythm), `--papyrus-radius-sm..xl`, `--papyrus-measure`, `--papyrus-rail-width`, `--papyrus-nav-height`, `--papyrus-ratio-media` (16:9), `--papyrus-rhythm`.
- Core's rules are written only in these tokens; no literal px or rem for text in core CSS. The root font size is left to the reader's browser, which is better for accessibility than a fixed 75% root (the reader's chosen default text size scales every token written in `rem`; tokens are therefore authored in `rem` at final size, with px shown in the brand-pack documentation, so the browser's default size and zoom still apply).

Tooling: one token source file (`tokens.json`) generates `papyrus-tokens.css` and the documentation table; a linter checks floors, rhythm multiples, and that every token a core rule uses is defined. The linter runs for every brand pack together with the contrast validator (PPY-2a44b2: "platform policy checks run for every brand pack").

The brand pack v2 schema (versioned, `schemaVersion: 2`) adds only what a second site proves it needs: `shape.corners` (`square`, `soft`, `round`: selects a registered radius set), `ornaments` (`none`, `quiet`, `expressive`), and optional named `roles` (MoM's `brand`, `machine`, `human`; each pair is contrast-checked). Sizes, spacing and borders stay out of the pack (already refused today); a site that wants a different type scale picks a registered scale name, not numbers.

Fonts. The allow-list (`policy.json`, ten families, self-hosted, known metrics) is the rule on the shared tier. A dedicated deployment such as MoM may extend the list for its own repository with self-hosted fonts reviewed in Git (MoM: Anton and Archivo), because the allow-list exists to protect other tenants and readers from third-party font requests, not to ban a font the site ships itself. The extension is a data file the validator reads (`policy.extra-fonts.json`), not code.

## Where the stylesheet comes from

Per PPY-e572de: pages link the core stylesheet (shared, versioned per release, cached) and one small per-site file of custom properties written from the validated brand pack (`brand-<hash>.css`). The standard projection writes both into the site's output; a site repository with a `publication/brand.json` gets the same result at build time with no per-tenant storage. This plan does not change PPY-e572de's storage design; slice 3 delivers the rendering half in the standard projection, and PPY-e572de delivers storage and serving on the shared tier.

## How MoM keeps its hooks, reduced to ornaments

After the migration MoM's repository holds: `publication/brand.json` (palette, fonts, shape, roles), `projection.json` (`layout: "publication"`, options), `web/hooks.py` with only ornament hooks (sticker, spine, loop bands, halftone, wordmark seal, placeholder art, ads) and the site features that are not shared (conversations forum, findings and videos pages, ad slots), `web/strings/*.json`, and its illustration and figure system. Target: `hooks.py` plus components under 900 lines and one stylesheet of ornament rules of about 400 lines (from about 3,000 lines of Python and about 5,000 lines of CSS across sources and generated files). The reference documents in `design/system/` stay MoM's brand book; `bundle.css` is deleted because the components are core's.

## TheHallucinator.ai: a satire brand pack on the same base

It must not look like MoM. MoM is a navy and cool-grey digital publication: Anton display type, sticker and spine ornaments, a cool tint for machines and warm tint for humans. The Hallucinator is a deadpan wire-service newspaper with every word invented, so it dresses as old print news and lets the content be the joke.

Proposed identity (a proposal for Ryan; the numbers below already pass the validator):

- Type: headings in Playfair Display (high-contrast serif, newspaper nameplate and headlines), body in Source Serif 4. Both are on the existing allow-list, so nothing extra to ship.
- Palette, light ("newsprint"): bg `#F5EFE0`, ink `#1C1A17`, bandBg `#EAE1CB`, bandCardBg `#FFFBF0`, bandMutedBg `#DDD2B6`, buttonBg `#8E1B16` (stamp red) with buttonInk `#FFF8EC`, rule `#6B6150`, focus `#0B5C8A`.
- Palette, dark ("press room at night"): bg `#17140F`, ink `#F1E9D6`, bandBg `#221E16`, bandCardBg `#2B261C`, bandMutedBg `#352F23`, buttonBg `#F0A59C`, buttonInk `#2A0907`, rule `#9A8F78`, focus `#8CC8EE`.
- Colour is not the signal. Red is the brand and the satire label, and the label is always the words "Satire" or "Invented" plus a mark; the focus ring is blue so red-green colour blindness does not hide it, and every state is text or a shape.
- Ornament level `quiet`: a nameplate-style masthead (a filled band with the wordmark centred, never rules), a dateline above every headline ("Satire. Everything here is invented."), and a flat tone block with the wordmark initial for cards without a picture. No stickers, no animation. `shape.corners`: `square` (newsprint has no rounded corners, and square corners against MoM's rounded cards are the quickest way to tell the sites apart at a glance).
- The satire label is not decoration: Humorus rule 7 requires it on every page, Markdown twin, feed entry, structured-data block and share preview. Core's base gets one generic feature for it (`site.notice`, a short labelled strip under the masthead and a field in the Markdown twin and JSON-LD), because the label is a publication concern that Threat Intelligence ("AI-drafted") and MoM ("drafted by AI") also have. This is slice 4's only addition that is not tokens.

The pack is saved as `publication/brand.json` in the Humorus repository (settings, not code) and reaches the shared-tier storage later through PPY-e572de. Screens: 375 and 1440 px, light and dark, home, section, article, concept, with Spanish and Chinese editions, produced before the slice is merged.

## Languages (es-419, zh-Hans) and the switcher

Which languages a page exists in is already core's (`page.alternates`, `page.language`, `page.strings`, `link_in_language`). The base takes over MoM's drawing of them:

- `language-switcher` (in the bar and the menu) and `language-banner` (the welcome banner for a visitor whose browser prefers another language the page exists in, with countdown, pause and switch-now; its script `mom-language.js` becomes core's `papyrus-language.js`) are core components fed only from `page.alternates` and `page.strings`. A language the page does not exist in is never offered.
- The keys the switcher and banner need (`switcherLabel`, `noticed`, `countdown`, `switchNow`, `stay`, `pause`, `resume`, `paused`, `announce`, `language.name`, `home.label`, ...) are core's required interface strings with an English default, so a new site is complete in English and a language is complete when its file has the keys (core already refuses a public language that lacks them).
- `translate_chrome` (MoM's exact-text replacement of the English the engine writes) is a stopgap that disappears when the engine takes the languages' strings (PPY-bb4001). It is not moved into the base; MoM keeps it until PPY-bb4001 lands, and no new site depends on it.
- CJK: the preset sets `font-family` fallbacks per `:lang()` (system Hei/Songti stacks after the brand font), `line-height` and no letter-spacing on `:lang(zh)`, and the text floors apply to the same token names, so Chinese pages are checked by the same linter and by screenshots in the diff set.
- Spanish and Chinese editions of MoM are part of the visual diff (below). Humorus's editions follow when it publishes in another language.

This work touches the same area as the in-flight localize, language alternates and index-page changes (PR #1548 and #1551 landed in 5.115.4). Slice 2, which moves the switcher, starts after those branches have merged; the switcher moves as a pure move, with the existing `features/language-*.feature` scenarios as the safety net.

## Accessibility

- Contrast: validator enforces 4.5:1 for text and 3:1 by luminance for button, rule and focus pairs, light and dark, per brand pack (already built).
- Colour never alone: chips, status, confidence and stars always carry words and a shape; the linter greps core CSS for rules that change only `color`/`background` between states without a non-colour change (selected, current, visited) and fails them.
- Text floors in rendered pixels (18, 14, 13) as tokens, per layout; layouts tested at 375 and 1440 px, and at 200% browser zoom (nothing clipped, no horizontal scroll).
- Focus: a 3 px outline from `--papyrus-focus` on every interactive element, kept in forced-colours mode (where the "no borders" canon yields to the system: `@media (forced-colors: active)` restores outlines on cards, buttons and chips so they remain perceivable).
- Touch targets at least 44 by 44 px for nav pills, menu button, switcher options and card links on compact layout.
- Landmarks and language: `<html lang>`, `lang` and `hreflang` on cross-language links, skip link, one `h1`, breadcrumb navigation, a labelled switcher; reduced motion respected (the banner countdown and loop bands stop when `prefers-reduced-motion`; the banner has pause).
- Video cards load no player until pressed; every picture has alt text or is marked decorative.
- Checked by existing browser policy checks (PPY-a78dfd, PPY-a526ee) against MoM and the two brand packs; axe-core run on the diff page set.

## Migration with zero regression: the visual diff plan

MoM must look the same, so the diff is the acceptance test, not an afterthought.

1. Fixed input. `tools/preview_production.py` renders the whole site from this checkout's `web/` over the production content read through the signed-in session (read-only), and accepts `--papyrus-src` to try a Papyrus branch. Capture the content snapshot once (stories, stars, ads, strings) and render "before" and "after" from the same snapshot, so a difference is never the news.
2. Before. MoM `develop` at its pinned Papyrus: render, screenshot, save as the baseline for the slice.
3. After. MoM branch on the new core (from the Papyrus slice branch): same snapshot, same pages.
4. Page set (about 40 pages, each at 375 px and 1440 px, light and dark, so about 160 shots): home; each of a representative three sections' index; articles listing page 1 and 2; posts listing; one article with a hero, one without, one with pull quote and figure, one with an in-content ad; a post; a concept index; a concept term page; findings list; videos list; conversations page and a thread; about; corrections; 404; and for es-419 and zh-Hans: home, an index, a story, a concept, with the switcher open and the banner showing. Plus a states page: focus rings, menu open, language menu open, cookie banner.
5. Comparison. A Playwright script (Chromium from the Papyrus `node_modules`) loads each page with animations disabled and fonts waited for, takes a full-page screenshot, and compares before and after with pixelmatch at zero tolerance on layout (any changed pixel is reported with the bounding box) and writes a side-by-side and a highlighted diff image per page. Also dumps computed font-size, line-height, padding and margin of a list of selectors per page and compares them as numbers, so a one-pixel shift that a threshold hides is still caught.
6. Allowed differences, listed in advance and each justified in the report: only class names in markup (the diff is on rendered output, so none are visible); nothing else. If a page differs, the slice does not release; the difference is fixed or the baseline decision is taken explicitly by Ryan.
7. Report: pass/fail per page and viewport, the counts, the diff images of every page that failed, the numeric comparison, and the sets of screenshots for Ryan at 375 and 1440.
8. Release order for a slice that changes how MoM renders: Papyrus slice merged to develop and released as a Papyrus version; MoM pins it on a branch; preview (the diff report, plus the preview server on the LAN for the iPad); Ryan's approval; MoM release. Papyrus can release without MoM adopting it (a new core option is inert until a site uses it); MoM's adoption is the visual change and is the step that waits for approval.

## Slices

| # | Slice | Papyrus | MoM | Humorus | Size | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Design doc, board plan, diff harness | doc; harness script in `tools/` | harness page list | none | S | none |
| 1a | Token source, generated stylesheet and size linter (done: `src/papyrus_content/front_end_tokens/`, `assets/papyrus-tokens.css`, `features_backend/guidelines/front-end-tokens.feature`) | token source, generator, linter, inert until a site links it | none | none | S | none |
| 1b | Core card set on tokens: one card builder with variants on the existing `markus-card` / `home-page-*` classes (no rename); the projector links `papyrus-tokens.css` | cards, chips, buttons, stars, meter, pull quote, click-to-play video card | none yet (diff harness baseline taken) | none | M | 1a; listing and index-page branches merged |
| 1c | MoM runs on tokens and core cards; scaler retired | a registered `poster` scale holding MoM's display sizes (Anton) | MoM CSS rewritten onto `--papyrus-*` tokens, `scale_css.py`, `sync_design_assets.py` generated pair, `bundle.css` and card code in `hooks.py` deleted; visual diff zero | none | L | 1b |
| 2 | Layout preset and the language base | `layout: "publication"` regions, ornament slots, language switcher, banner, strings, `papyrus-language.js`, home options | `_home_*`, `_listing_main`, `_article_*`, `masthead`, `footer` hooks deleted; the preset's options set in `projection.json` | none | L | slice 1; localize branches merged |
| 3 | Brand pack v2 applied by the projection | schema v2 (`shape`, `ornaments`, `roles`, extra fonts), `brand-<hash>.css` writer, validator extended, p.apyr.us reference page | `publication/brand.json` replaces the palette in `tokens.json`; hooks are ornaments only | none | M | slice 1 (tokens); PPY-e572de for shared-tier storage is separate |
| 4 | TheHallucinator.ai on the base | `site.notice` (satire/AI label), example theme pack "newsprint" shipped as a documented example | none | `publication` block, `projection.json`, brand pack, strings, move off pretext | M | slices 2 and 3 |
| 5 | Neutral default and starter | neutral theme as the default pack, starter template (PPY-3aa10f), example themes page on p.apyr.us | none | none | M | slices 3 and 4 |
| 6 | `papyrus site init` (PPY-f30ad5), profiles news and satire | scaffold | none | uses it | M | later; Humorus comment on Amplify branch reset applies |

Order matters in one respect: slices 1 and 2 change shared rendering files (listing, home, cards, localize), so each starts only after the agents working on those have merged (see Collisions), and each rebases on `develop` before the first commit and again before opening the pull request.

## Collisions and coordination

- Index pages and listings: agent a024e2e1adb4a90ed. Concept and section labels: agent a656a046a6a651072. Slice 1 adds new files (`tokens`, `cards`) and replaces card markup call sites; it does not touch `localize/`, listing selection, language alternates or guidelines. If a card call site changes in their branches, ask them first.
- MoM's switcher and strings (another session) are slice 2's domain; slice 1 does not touch them.
- Board-only changes go straight to `develop`; code goes through a fresh worktree and a pull request to `develop`.

## Open questions, with defaults

1. Should wide-screen sizes stay at MoM's current 75% look, or does Ryan want to take the chance to resize? Default: keep exactly (zero regression); resizing is a later token edit, which is now one file.
2. The rem or px authoring of tokens: default rem (honours the reader's browser text size), documented with px.
3. May dedicated deployments extend the font allow-list with fonts self-hosted in their repository? Default yes (MoM needs Anton and Archivo); the shared tier keeps the ten-family list.
4. TheHallucinator.ai identity (newsprint cream, stamp red, Playfair Display over Source Serif 4, square corners, quiet ornaments). Default: proceed as proposed; palette values may change freely as long as the validator passes.
5. Satire label as a core `site.notice` feature versus Humorus-only. Default: core, because three publications need a labelled-AI or satire notice.
6. MoM's forum, findings and proposal components: stay ornaments until a second site asks. Default: stay.
7. The `ornaments` enumeration names (`none`, `quiet`, `expressive`). Default: as written.
8. MoM release while Ryan is away. Default: no release of a slice that changes how MoM renders until Ryan has seen the 375 and 1440 px preview, even when the diff is clean.
