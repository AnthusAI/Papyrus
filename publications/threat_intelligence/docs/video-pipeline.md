# Video pipeline (Threat Intelligence seed edition)

Papyrus can generate narrated summary videos for Threat Intelligence seed articles using [VideoML](https://github.com/AnthusAI/videoml-toolchain) (`vml` CLI). The Python CLI orchestrates DSL generation and invokes `vml pipeline` as a subprocess; VideoML handles TTS, timing, and MP4 rendering.

**Branding, pictogram policy, and content rules:** [skills/produce-video/SKILL.md](../skills/produce-video/SKILL.md)

## Prerequisites

1. **VideoML via Babulus** (preferred, one-time setup):

   Babulus ships a working `videoml-cli` pipeline. Ensure `~/Projects/Babulus` exists with dependencies installed:

   ```bash
   cd ~/Projects/Babulus
   npm install
   npx playwright install chromium
   ```

   Override with `BABULUS_ROOT=/path/to/Babulus` if needed.

   Build the Threat Intelligence pictogram browser bundle (required for animated React pictograms in videos):

   ```bash
   npm run videoml:bundle
   ```

   Output: `public/videoml/ti-browser-bundle.js` (gitignored). The video pipeline builds this automatically before render if missing.

   Legacy static SVG pictograms under `public/seed-art/threat-intelligence/*.svg` have been removed; videos use the same React pictogram components as the blog.

2. **OpenAI key** in `.papyrus/config.yaml` (gitignored):

   ```yaml
   schemaVersion: 1
   openai:
     api_key: "sk-..."
     model: gpt-4o-mini-tts
     voice: alloy
   ```

   Copy [papyrus-config.example.yaml](../papyrus-config.example.yaml) into `.papyrus/config.yaml` and set `openai.api_key`.

   Resolution order: `OPENAI_API_KEY` env var, then `.papyrus/config.yaml` `openai.api_key` (via [src/papyrus_content/papyrus_config.py](../src/papyrus_content/papyrus_config.py)).

3. **Worktree note:** `.papyrus/` is per-checkout and gitignored. When running from a git worktree that does not have its own `.papyrus/config.yaml`, either copy the file from the main clone or set:

   ```bash
   export PAPYRUS_CONFIG=/Users/ryan/Projects/Threat-Intelligence/.papyrus/config.yaml
   ```

## Commands

Probe the OpenAI key (no render):

```bash
poetry run papyrus videos seed --probe-only
```

Render all six lead-pictogram articles plus the edition overview teaser:

```bash
poetry run papyrus videos seed
```

Render only the edition overview (~1 minute teaser):

```bash
poetry run papyrus videos render --edition-overview
```

Render one article:

```bash
poetry run papyrus videos render --article the-balance-of-power-is-shifting
```

Output MP4s are written to:

```text
publications/threat_intelligence/seed-art/videos/edition-overview.mp4
publications/threat_intelligence/seed-art/videos/<slug>.mp4
```

Reader URLs use `/seed-art/threat-intelligence/videos/...` via the `public/seed-art/threat-intelligence` symlink.

## Seeding videos to Amplify

After rendering MP4s locally, upload them during sandbox seed:

```bash
PAPYRUS_SEED_VIDEOS=1 npm run seed:amplify
```

Without `PAPYRUS_SEED_VIDEOS=1`, seed still creates `MediaAsset(type="video")` rows with `externalUrl` pointing at `/seed-art/...` for local Next.js serving, but skips S3 upload.

Alternatively, refresh GraphQL seed records from Python (requires JWT authoring lane):

```bash
poetry run papyrus videos attach --article the-balance-of-power-is-shifting
```

## Content model

- Edition overview: top-level `video` block in seed JSON → `Edition.metadata.editionVideo`
- Article videos: `video` blocks on the six lead-pictogram articles → `MediaAsset(type="video")`

## Web embedding (reader pages)

Videos are **pre-rendered MP4s**, not live VideoML playback. The reader uses native HTML5 `<video>` via [`components/article-video.tsx`](../components/article-video.tsx) (`ArticleVideoFigure`).

| Surface | Placement |
|---------|-----------|
| Blog index | Edition overview `<video>` just above the first section header |
| Blog index cards | Article `<video>` below the excerpt and pictogram (full card width) |
| Article pages | Article `<video>` above the title and deck; pictogram remains in the body |

URL resolution: article videos use `MediaAsset.storagePath` (signed S3 when seeded with `PAPYRUS_SEED_VIDEOS=1`) or `externalUrl` (`/seed-art/threat-intelligence/videos/<slug>.mp4` for local dev). Edition overview reads `Edition.metadata.editionVideo.src` (and optional `storagePath` after upload).

The VideoML browser bundle (`public/videoml/ti-browser-bundle.js`) is for **offline render only** — do not embed it on reader pages.

## Pipeline shape

```text
seed article (excerpt + pullQuotes)
  → Python DSL (.babulus.xml in videoml-work/<slug>/) with <ti-title-slide pictogramSlug=...>
  → npm run videoml:bundle (if needed) → public/videoml/ti-browser-bundle.js
  → vml pipeline (OPENAI_API_KEY + BABULUS_BROWSER_BUNDLE)
  → public/seed-art/threat-intelligence/videos/<slug>.mp4
  → seed upload (optional, PAPYRUS_SEED_VIDEOS=1)
  → MediaAsset(type=video) → blog article page
```

### Scene order

- **Article briefings:** cold-open quote → pictogram title → excerpt → second quote → dated CTA (`THREAT INTELLIGENCE` in tomato red + edition date + tagline).
- **Edition overview:** cold-open quote (first lead article) → edition title + first lead pictogram → edition teaser (date + headline list) → six spotlights → dated CTA.

Backgrounds are flat solid `#191918` paper — no gradients. See the produce-video skill for full policy.

## Light and dark variants

Threat Intelligence videos support both dark and light reader themes via dual-rendered MP4s.

### Filename convention

- Dark (default): `<slug>.mp4`, `edition-overview.mp4`
- Light: `<slug>-light.mp4`, `edition-overview-light.mp4`

### Render

```bash
# Render all 14 MP4s (7 dark + 7 light) — default, 3 parallel jobs
poetry run papyrus videos seed

# Render with more parallelism (each job spawns a headless Chromium)
poetry run papyrus videos seed --jobs 4

# Render only dark or light
poetry run papyrus videos seed --theme dark
poetry run papyrus videos seed --theme light

# Render one article in both themes
poetry run papyrus videos render --article <slug> --theme both
```

The `--theme` flag accepts `dark`, `light`, or `both` (default: `both`).
The `--jobs` flag controls parallel renders (default: `3`). Each job renders one video's themes sequentially (dark before light) so the light variant reuses the dark variant's TTS cache. Different videos run in parallel since each has its own work directory.

### Palettes

Two palette constants live in [`src/papyrus_content/video_pipeline.py`](../src/papyrus_content/video_pipeline.py):

| Token | Dark | Light |
|-------|------|-------|
| `background` | `#191918` (sand-2 dark) | `#f9f9f8` (sand-2 light) |
| `--ti-alarm-red` | `#e54d2e` (tomato-9) | `#c54028` (tomato-11, WCAG-compliant on light paper) |
| `--ti-headline-color` | `#eeeeec` | `#44403c` (sand-12) |
| `--ti-pictogram-edge` | `#363a3f` (slate-6 dark) | `#889096` (slate-8 light) |

Light tomato uses `tomato-11` (`#c54028`) for WCAG contrast on `#f9f9f8` paper, not the dark-mode `tomato-9` (`#e54d2e`).

### Data model

- `ArticleVideoAsset.themeVariants.light.src` — light variant URL (TypeScript)
- `MediaAsset.metadata.themeVariants.light.sourceUrl` — GraphQL storage
- `Edition.metadata.editionVideo.themeVariants.light.src` — edition overview

### Reader resolution

[`components/article-video.tsx`](../components/article-video.tsx) uses `useResolvedPapyrusTheme()` + `resolveThemedVideoSrc()` to pick the matching `<video>` src at runtime. The `<video>` element is keyed by src so React re-mounts it on theme switch.

### TTS cache sharing

Each video uses a single shared work directory (`videoml-work/<slug>/`) for both dark and light renders. Babulus caches TTS segments under `.videoml/out/<compId>/env/<env>/segments/`, keyed by text content hash — not visual styles. Since the voiceover text is identical across themes, the light render finds and reuses the dark render's cached TTS segments with zero OpenAI API calls. The script, timeline, and frame PNGs are overwritten per render, but the final MP4s are written to theme-suffixed output paths.

Override VideoML CLI location with `VIDEOML_CLI_DIR=/path/to/VideoML/cli` if needed.
