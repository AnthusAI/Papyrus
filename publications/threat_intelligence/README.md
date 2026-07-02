# Threat Intelligence publication

All publication-specific code, assets, and configuration for Anthus Threat Intelligence live here. The Papyrus framework imports from this directory; it does not embed TI branding or content in generic framework modules.

## Layout

| Path | Purpose |
|------|---------|
| `brand.ts` | Site brand definition (masthead, fonts, footer, section nav) |
| `theme.css` | TI CSS tokens and blog presentation styles |
| `seed/seed-edition-content.json` | Fixture edition content (articles, videos, layout metadata) |
| `seed-art/videos/` | Rendered MP4 briefings (gitignored) |
| `pictograms/` | React pictogram registry, art, and article figure component |
| `blog-defense/` | Animated blog hero background graph |
| `videoml/` | Video pipeline Python modules and browser bundle entry |
| `docs/` | Bootstrap and video pipeline runbooks |
| `skills/produce-video/` | Agent skill for video production |
| `tests/` | TI pictogram, blog-defense, and video pipeline tests |

## Public URLs

Static assets are web-served through symlinks under `public/`:

- `public/seed-art/threat-intelligence` → `publications/threat_intelligence/seed-art`
- Seed JSON video `src` values use `/seed-art/threat-intelligence/videos/...` paths.

## Environment

```bash
export PAPYRUS_SITE_BRAND=threat-intelligence
export PAPYRUS_SEED_PROFILE=threat-intelligence
```

## Commands

```bash
# Render all 14 MP4s (7 dark + 7 light), 3 parallel jobs
poetry run papyrus videos seed

# Seed sandbox GraphQL from TI fixture edition
PAPYRUS_SEED_PROFILE=threat-intelligence npm run seed:amplify
```

See [docs/video-pipeline.md](docs/video-pipeline.md) and [docs/bootstrap.md](docs/bootstrap.md).
