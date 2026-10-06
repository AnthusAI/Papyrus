# Video pipeline (`papyrus videos`)

Papyrus renders narrated MP4 videos from CMS items with [VideoML](https://github.com/AnthusAI/videoml-toolchain) (`vml`, npm `@videoml/cli`). The Python CLI (`src/papyrus_content/videoml/`) builds the VideoML script (DSL), then runs `vml pipeline <dsl> --project-dir <dir> --out <mp4>` as a subprocess; VideoML handles TTS, timing and MP4 rendering. Everything publication-specific (palette, components, output paths, post-roll branding) comes from the publication's video config. Production guidance (stages, narration rules, post-roll contract) is in [skills/produce-video/SKILL.md](../skills/produce-video/SKILL.md).

## Prerequisites in the publication repo

1. `@videoml/cli` as a devDependency, installed with `npm install`. `@videoml/cli` 1.0.0 imports `gsap`, `framer-motion`, `d3` and `three` without declaring them, so list those as devDependencies too, and run `npx playwright install chromium` once for rendering.
2. A browser bundle (the custom elements named in the config, built by the publication) at the configured `browserBundle` path. The pipeline passes it to VideoML as `BABULUS_BROWSER_BUNDLE`; it does not build it.
3. An OpenAI key: `OPENAI_API_KEY`, or `openai.api_key` in `.papyrus/config.yaml` (use `PAPYRUS_CONFIG` from a worktree). Keys never go in the video config or in git. Voice and model come from `openai.voice` / `openai.model` (defaults `alloy` / `gpt-4o-mini-tts`) and are written into every script's `<voiceover>` element.
4. `video/video.yml` (or the path in `PAPYRUS_VIDEO_CONFIG`).

## Locating the VideoML CLI

1. `VIDEOML_CLI`: path to a `vml` executable (or a `.js` entry run with `node`). It must exist.
2. Otherwise `npx --no-install vml`, run in the publication root, when `node_modules/.bin/vml` exists there.
3. Otherwise the command fails and says what to install. There are no home-directory defaults.

## Video config (`video/video.yml`)

```yaml
schemaVersion: 1
outputDir: video/out            # rendered MP4s (gitignored)
workDir: video/work             # optional, default video/work: scripts and TTS cache
browserBundle: public/videoml/browser-bundle.js
leadSlugs: []                   # slugs rendered by `videos seed` without --slug
scene:
  dark:  { background: "#191918", color: "#eeeeec", vars: { "--color-accent": "#e54d2e" } }
  light: { background: "#ffffff", color: "#111111", vars: {} }
components: { titleSlide: "brand-title-slide", quoteCard: "brand-quote-card" }
slideProps: {}                  # optional: extra props merged into every slide
quoteAccentColor: "var(--color-accent)"   # optional
postRoll:                       # optional: omit for no post-roll
  eyebrow: "Publisher name"
  title: "PUBLICATION"
  tagline: "One line."
  voice: "To learn more, check out the {date} edition of Publication. One line."
  props: {}                     # optional extra title-slide props for the end screen
tts: { provider: openai }
```

Paths are relative to the publication root (the working directory). Unknown keys and invalid values fail with the key named. `scene.<theme>.vars` are CSS variables the brand components read.

## Content model

- Articles are CMS `Item` rows. A script is generated from the article: `headline`, `deck`, `section`, `pullQuotes`, `editorial.excerpt` (or `editorial.newsroom.excerpt`) and `editorial.video`.
- `editorial.video.scenes` is the authored script: `{kind: "quote", quote, attribution?, voice}` or `{kind: "slide", eyebrow?, title?, subtitle?, pictogram?, voice}` scenes in order; `editorial.video.postRollVoice` overrides the spoken post-roll line. Without scenes a fallback structure is generated (hook quote, title, briefing, second quote).
- A stored script is an `Item` with slug `<slug>--videoml` and `editorial.videoScript.dsl`. `videos render` uses it when present (re-themed to the requested theme from the config palettes), unless `--from-article` is passed. A stored script authored against a different `scene.dark` palette is rejected: regenerate it.

## Commands

```bash
papyrus videos render --article <slug> [--theme dark|light|both] [--from-article] [--provider openai] [--probe-only]
papyrus videos seed [--slug <slug>] [--theme ...] [--jobs 3] [--from-article] [--dry-run] [--probe-only]
papyrus videos attach --article <slug>
```

- `--probe-only` makes one tiny TTS request to check the key; `--dry-run` (seed) resolves every script and prints the planned outputs without probing or rendering.
- Output: `<outputDir>/<slug>.mp4` (dark) and `<outputDir>/<slug>-light.mp4`. Both themes of one video render in sequence so the light render reuses the dark render's TTS cache; different videos run in parallel (`--jobs`).
- `attach` uploads the MP4s to `media/videos/<slug>.mp4` (and `-light`) and writes a `MediaAsset` (`type: video`, `role: lead`, `metadata.themeVariants.light.storagePath`) on the article's `Item`. Publish the item afterward so `PublishedMediaAsset` is projected.

## Pipeline shape

```text
CMS Item (+ editorial.video)  or  stored <slug>--videoml script
  -> VideoML DSL in <workDir>/<slug>/<slug>-<theme>.babulus.xml
  -> vml pipeline (OPENAI_API_KEY, BABULUS_BROWSER_BUNDLE)
  -> <outputDir>/<slug>[-light].mp4
  -> videos attach -> S3 media/videos/ + MediaAsset
```

## Brand video components

Papyrus ships the VideoML mechanics; a publication supplies its own scene components.

- `@videoml` already registers generic `TitleSlide` and `QuoteCard` components, so the default config (`titleSlide: "title-slide"`, `quoteCard: "quote-card"`) needs no bundle entry of its own. Add one when the brand wants its own scene components.
- Register the brand's components in a TSX module and point the brand at it in `papyrus.config.ts`:

```ts
brand: { ..., video: { bundleEntry: "publication/video/browser-bundle.tsx", sceneComponents: { "quote-card": "acme-quote-card" } } }
```

The module registers components through `window.Babulus.registerComponent("AcmeQuoteCard", AcmeQuoteCard)`. A DSL element `<acme-quote-card>` renders the component registered as `AcmeQuoteCard`. The standard entry (`window.Babulus`, `window.renderFrame`) is bundled in front of the brand's module, so the module does not import anything for registration. React is read from `window.React` (the render shell loads React 18).

- `sceneComponents` maps generic DSL element names to the brand's (used by the browser preview to rewrite stored scripts such as `<quote-card>`). The Python `components` config must name the same elements.
- `video.rhythm` is reserved for brand layout tokens that scene components read; Papyrus does not interpret it.
- The module can call `window.PapyrusVideo?.registerPreviewRetheme((xml, theme) => xml)` to swap a stored dark script to a light palette in the preview bundle.

Build the bundles from the publication root (the brand is `PAPYRUS_SITE_BRAND`, else `defaultBrand`):

```bash
npx papyrus-app videoml-bundle              # public/videoml/browser-bundle.js (render)
npx papyrus-app videoml-bundle --preview    # public/videoml/preview-bundle.js, preview.html, vendor/ (reader preview)
```

Inside the Papyrus repo the same builders are `npm run videoml:bundle` and `npm run videoml:preview-bundle`. The publication installs `@videoml/cli`, `@videoml/toolchain`, `@videoml/player`, `gsap`, `framer-motion`, `d3`, `three` and `esbuild` as devDependencies. Point the Python `VideoConfig.browserBundle` at `public/videoml/browser-bundle.js`. A missing `brand.video.bundleEntry` fails with a message naming the brand.
