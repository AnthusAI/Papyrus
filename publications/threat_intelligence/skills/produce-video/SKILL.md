# Produce Video (Threat Intelligence / Papyrus seed editions)

Use this skill when generating or updating narrated MP4 briefings for Threat Intelligence seed
editions, article summary videos, or edition overview teasers.

## Purpose

Threat Intelligence videos are **teaser briefings**, not generic motion graphics:

- **Edition overview** (`edition-overview.mp4`): ~1 minute teaser for the latest issue.
  Cold-opens with the first lead article's strongest pull quote, then edition title + first lead
  pictogram, then "In this edition" headline list, spotlights each lead article with its pictogram,
  and closes with a dated CTA.
- **Article briefings** (`<slug>.mp4`): ~60–90 second summaries for lead-pictogram articles.
  Cold-opens with the strongest pull quote, then headline/deck, excerpt, optional second quote,
  and a dated CTA.

Voice tone: practical, calm, editorial — “mission briefing” not marketing hype.

## Branding (Threat Intelligence blog dark mode)

Videos must match the **Threat Intelligence blog dark-mode reader theme** in `app/globals.css`
(`:root[data-site-brand="threat-intelligence"]` with dark color scheme), not generic blue SaaS
gradients.

Canonical video palette (approximate hex from Radix sand-dark + tomato accent):

| Token | Hex | Use |
|-------|-----|-----|
| `--color-bg` / paper | `#191918` | Flat scene background (no gradients) |
| surface | `#21201c` | Cards / quote panels |
| text | `#eeeeec` | Headlines |
| text muted | `#b5b3ad` | Decks, excerpts |
| `--ti-alarm-red` / `--ti-section-rule` | `#e54d2e` (Radix tomato-9 dark) | Masthead wordmark, CTA title, quote accent, section rule bars |
| `--ti-pictogram-throb` | `#ac4d39` (Radix tomato-8 dark) | Pictogram pulse accent |
| pictogram edge / node | `#363a3f` / `#2e3135` (Radix slate-6 / slate-5 dark) | Pictogram strokes and fills |

Backgrounds are **flat solid `#191918` paper** — no gradient bands. This matches the TI blog brand language.

Typography intent: Helvetica Neue / system sans stack, weight **900** on headlines and section eyebrows (same as TI blog display type).

Section eyebrows on title slides mimic the blog **section header** (`.presentation-section-header`): two red bars as tall as the eyebrow text, flanking the label on both sides, with the label centered on a page-background chip. Use `var(--ti-alarm-red)` (Radix tomato-9) for all brand reds — do not substitute lighter or legacy accent hex values.

Implementation lives in `src/papyrus_content/video_pipeline.py` as `TI_SCENE_STYLES_DARK` and
`TI_BACKGROUND_PROPS_DARK`. Update those constants when the blog theme changes — do not hard-code
alternate palettes in one-off DSL files.

## Light and dark dual-render

Threat Intelligence videos support both dark and light reader themes. The render pipeline
produces two MP4s per video: a dark default (`<slug>.mp4`) and a light variant
(`<slug>-light.mp4`).

### Light palette

| Token | Hex | Use |
|-------|-----|-----|
| `--color-bg` / paper | `#f9f9f8` (sand-2 light) | Flat scene background |
| surface | `#fcfcfc` (sand-1) | Cards / quote panels |
| text | `#44403c` (sand-12) | Headlines |
| text muted | `#696964` (sand-11) | Decks, excerpts |
| `--ti-alarm-red` / `--ti-section-rule` | `#c54028` (Radix tomato-11) | WCAG-compliant on light paper |
| `--ti-pictogram-throb` | `#d9542e` (tomato-8 light) | Pictogram pulse accent |
| pictogram edge / node | `#889096` (slate-8 light) | Pictogram strokes and fills |

Light tomato uses `tomato-11` (`#c54028`) for WCAG contrast on `#f9f9f8` paper — do not use
the dark-mode `tomato-9` (`#e54d2e`) on light backgrounds.

Implementation: `TI_SCENE_STYLES_LIGHT` and `TI_BACKGROUND_PROPS_LIGHT` in
`src/papyrus_content/video_pipeline.py`. Theme selection via `scene_styles_for_theme(theme)`
and `background_props_for_theme(theme)`.

### Render command

```bash
# Render all 14 MP4s (7 dark + 7 light) — default, 3 parallel jobs
poetry run papyrus videos seed

# Render with more parallelism (each job spawns a headless Chromium)
poetry run papyrus videos seed --jobs 4

# Render only one theme
poetry run papyrus videos seed --theme dark
poetry run papyrus videos seed --theme light

# Render one article in both themes
poetry run papyrus videos render --article <slug> --theme both
```

The `--jobs` flag controls parallel renders (default: `3`). Each job renders one video's themes sequentially (dark before light) so the light variant reuses the dark variant's TTS cache. Different videos run in parallel since each has its own work directory (`videoml-work/<slug>/`).

Babulus caches TTS segments by text content hash, not visual styles. Since the voiceover text is identical across themes, the light render reuses the dark render's cached TTS with zero OpenAI API calls.

### Data flow

- Seed JSON `video.themeVariants.light.src` → `MediaAsset.metadata.themeVariants.light.sourceUrl` (GraphQL)
- Reader: `ArticleVideoFigure` uses `useResolvedPapyrusTheme()` + `resolveThemedVideoSrc()` to pick the matching `<video>` src at runtime
- The `<video>` element is keyed by src so React re-mounts on theme switch

## Pictograms (required)

Every article video scene should show the article **React pictogram** (same components as the blog):

- Source of truth: article **slug** → registry in [`lib/threat-intelligence-pictograms.ts`](../../lib/threat-intelligence-pictograms.ts) and SVG art in [`components/pictograms/pictogram-art.tsx`](../../components/pictograms/pictogram-art.tsx)
- Legacy `public/seed-art/threat-intelligence/*.svg` pictogram files are **removed** — do not reintroduce them
- VideoML DSL uses `<ti-title-slide>` with `pictogramSlug` and `pictogramSize` props (not `title-slide` + embedded SVG data URIs)
- Rendering uses a Papyrus browser bundle built by `npm run videoml:bundle` → `public/videoml/ti-browser-bundle.js`, wired via `BABULUS_BROWSER_BUNDLE` during `vml pipeline`
- Pictogram motion is **frame-driven** ([`lib/pictogram-video-motion.ts`](../../lib/pictogram-video-motion.ts)) so animation syncs with video frames

Edition overview spotlights use the same slug-based pictogram per featured article.

Build the browser bundle before rendering (automatic when using `poetry run papyrus videos seed`):

```bash
npm run videoml:bundle
```

## VideoML components

Always include visual `<layer>` elements. Voice-only DSL produces blank frames.

Preferred components:

- `video-background` — flat TI paper backdrop (`variant: solid`, dark `#191918` or light `#f9f9f8`)
- `ti-title-slide` — animated React pictogram + eyebrow / title / subtitle header (lead articles)
- `title-slide` — text-only scenes (e.g. closing)
- `quote-card` — pull-quote scenes

Do not ship scenes with `<voice>` cues only.

## Content policy

### Scene order

**Article briefings:** hook (cold-open pull quote, if present) → title (pictogram + section eyebrow + headline + deck) → briefing excerpt → second pull quote (if present) → closing CTA.

**Edition overview:** hook (first lead article's `pullQuotes[0]`) → title (edition title + first lead pictogram + tagline) → edition teaser (date + "In this edition" + headline list) → six spotlights → closing CTA.

**Reader placement:** edition overview video on the blog index just above the first section header; article videos on index cards below excerpt/pictogram; article pages show video above title/deck with pictogram in body.

No separate brand-only intro scene on edition overview.

### Writing for narration (seed copy contract)

Every narrated word comes from seed JSON fields. Scene → source:

| Scene | Voice source |
|-------|--------------|
| Hook (cold open) | `pullQuotes[0]` |
| Title | `headline` + pause + `deck` |
| Briefing (article videos) | full `excerpt` |
| Overview spotlight | `headline` + **first sentence** of `excerpt` (fallback: `deck`) |
| Overview teaser | edition `description` + fixed "This edition features…" line |
| Closing | fixed CTA (see below) |

Rules that follow from this:

- **First-sentence contract.** The pipeline's sentence splitter breaks on `.` `!` `?` — but NOT on em dashes or semicolons. A lead article's excerpt must land a complete thought (setup *and* payoff) before its first period, or the spotlight tease dangles and the scene cuts mid-idea. Join two-beat hooks with an em dash or semicolon:
  - ✗ `"The engineer left in January. The workspace invite … are all still live."` → spotlight speaks only *"The engineer left in January."*
  - ✓ `"The engineer left in January — but the workspace invite … are all still live."`
- **Spotlight subtitle limit.** That first sentence also renders on screen, truncated at 180 characters — keep it under.
- **Excerpts do triple duty**: edition-index hook, full briefing narration, and spotlight tease. Write them for the ear as well as the eye — read them aloud.
- **Adjacent-scene echo rule.** The hook quote and the deck are spoken ~10 seconds apart; do not let them share distinctive phrasing (a hook of "tireless automation / tireless analysis" followed by a deck opening "Attackers bring tireless automation" reads fine on the page and grates when spoken). Likewise the overview opens tagline → `description` → fixed "practical checks" line back-to-back: keep "practical" (and other tagline words) out of `description`.
- **Deck = claim, excerpt = hook** — same division of labor as the edition index. The deck states the thesis in one or two tight sentences; the excerpt carries stakes, a question, or a scenario, and must not restate the deck (the title scene and briefing scene would then say the same thing twice in a row).
- **Pull quotes are verbatim body sentences.** `pullQuotes` are narrated cold opens and must occur verbatim in the article body; video-lead articles require `pullQuotes[0]`. Not every article needs a pull quote — drop a weak one rather than keeping a paraphrase. When weaving, never leave the quote adjacent to the sentence that used to paraphrase it.

### Pre-render script check

Before rendering, proofread what will be *spoken*, not just what the JSON says:

1. Simulate the full voice script for the overview and all six briefings (replicate `first_sentence()` / `truncate_display()` from `video_pipeline.py` in a scratch script) and read it end-to-end. Check: no dangling spotlight teases, no word pile-ups across adjacent scenes, spotlight subtitles ≤ 180 chars.
2. The edition's topic and vocabulary constraints apply to narrated words too — narration is public content. Run the same vocabulary checks used for article copy against every field the videos read (`headline`, `deck`, `excerpt`, `pullQuotes`, `description`).
3. Confirm the worktree's seed JSON narration fields match the canonical main-repo copy. The render reads the worktree file and will happily speak stale copy.

### Closing CTA (every video)

Slide: eyebrow `Learn more — {edition date} edition`, title `THREAT INTELLIGENCE` in tomato red (`--ti-alarm-red`), subtitle = tagline.

Voice: `To learn more, check out the {edition date} edition of Anthus Threat Intelligence. {tagline}`

Edition date comes from seed `publishDate` (formatted as `July 4, 2026` on slides and in voice).

### Other rules

- **Article voice** uses excerpt + pull quotes only; do not read the full article body.
- Do not invent facts, incidents, or vendor claims not present in seed article copy.
- Keep OpenAI keys in `.papyrus/config.yaml` (`openai.api_key`) or `OPENAI_API_KEY`; never commit keys.

## Commands

```bash
# Worktree without local .papyrus/
export PAPYRUS_CONFIG=/path/to/.papyrus/config.yaml

# Render edition overview + all six lead article videos
poetry run papyrus videos seed

# Render only edition overview
poetry run papyrus videos render --edition-overview

# Render one article
poetry run papyrus videos render --article the-balance-of-power-is-shifting
```

Outputs (gitignored):

```text
publications/threat_intelligence/seed-art/videos/edition-overview.mp4
publications/threat_intelligence/seed-art/videos/<slug>.mp4
```

Reader URLs: `/seed-art/threat-intelligence/videos/...` (symlinked from `public/`).

Upload during Amplify seed: `PAPYRUS_SEED_VIDEOS=1 npm run seed:amplify`

## Seed fixture contract

- Edition video: top-level `video` block in
  `publications/threat_intelligence/seed/seed-edition-content.json`
- Article videos: per-article `video` blocks on the six lead-pictogram articles
- Edition video is copied into `Edition.metadata.editionVideo` during seed
- Blog reader shows edition video below the masthead via `EditionContent.editionVideo`

## When changing this pipeline

1. Read this skill and `publications/threat_intelligence/docs/video-pipeline.md`.
2. Update `publications/threat_intelligence/videoml/video_pipeline.py` (single source for theme + DSL).
3. Re-render with `poetry run papyrus videos seed`.
4. Verify a extracted frame is not solid black and pictograms are visible.
5. Update tests in `publications/threat_intelligence/tests/test_video_pipeline.py` if DSL shape changes.

## Improvement ideas (not yet implemented)

Future pipeline options — listed so nobody mistakes them for current behavior:

- **`--script-only` dry run**: a mode that prints the assembled voice script for all videos without TTS or render cost, making the pre-render script check a one-command step instead of a scratch script.
- **`video.voiceHook` override**: an optional per-article seed field to override the spotlight tease when the ideal index excerpt and the ideal spoken tease diverge, instead of bending one surface to fit the other. Until it exists, the first-sentence contract above is the compromise.
- **Overview spotlight cadence**: six identical headline+tease title-slide scenes in a row is the video version of index-page monotony. If the overview starts to feel flat, consider varying the scene type partway through (e.g., a quote-card for one spotlight) rather than adding more words.
