# Brand pack

A site on the shared tier is data, never code. Its look is one **brand pack**: a small JSON document that a validator checks before the site uses it. The format is `src/papyrus_content/brand_pack/schema.json` (JSON Schema 2020-12, `schemaVersion` 1, `additionalProperties: false` everywhere). The platform policy is `src/papyrus_content/brand_pack/policy.json`. The validator is `papyrus_content.brand_pack.validate_brand_pack`, which returns a list of problems (empty means valid). Planned in PPY-88a883; first slice PPY-7bc5b7.

## What an owner can set

| Field | What it is |
| --- | --- |
| `name` | The brand's name. |
| `logo` | Optional. `asset` (an uploaded `.svg`, `.png` or `.webp` file name) and `alt` text. |
| `wordmark` | `text`, shown in the heading font beside or instead of the logo. |
| `colors.light`, `colors.dark` | One `#rrggbb` colour for each role, in both themes. |
| `fonts` | `heading` and `body` family, each from the allow-list in `policy.json`. |
| `imageStyle` | Optional. `treatment: "pictogram"` (still pictograms only) and a short `summary`. Links the image style profile work (PPY-1f68bf). |

The colour roles are named for the standard front end's `--papyrus-*` custom properties: `bg`, `ink`, `bandBg`, `bandCardBg`, `bandMutedBg`, `buttonBg`, `buttonInk`, `rule` and `focus`. A brand change writes one small stylesheet of custom properties; the core stylesheet stays shared.

Custom CSS, sizes, spacing, borders, hooks and plugins are not part of the pack. They are refused, and the refusal says why.

## What the validator checks

- **Text contrast.** Each text and fill pair in `textPairs` (ink on the page and on each band tone, button label on the button fill) must reach 4.5:1 in both light and dark. Source: WCAG 2.2 Success Criterion 1.4.3, Contrast (Minimum), level AA, normal text. Button labels are normal-size text, so they use 4.5:1 rather than the 3:1 allowed for large text.
- **Colour-safe pairs.** Each pair in `lightnessPairs` (button fill, rule and focus ring against the page) must be told apart by lightness and not only by hue, so that people who cannot tell certain hues apart can still see it. The measure is the WCAG contrast ratio, which is computed from relative luminance and so ignores hue; the minimum is 3:1. Source: WCAG 2.2 Success Criterion 1.4.11, Non-text Contrast, level AA, with SC 1.4.1, Use of Color.
- **Fonts.** Each family must be in the `fonts` list in `policy.json`, the one place the allow-list is defined. Adding a font is a data change reviewed in Git.

A refusal names the setting, the roles, the theme and the measured ratio, for example `colors.dark: ink on bg (#5A6672 on #12171D) has contrast 3.06:1, needs 4.5:1`. Ratios are truncated to two decimals so a pair just under a minimum is never shown as meeting it.

## Tests and shared vectors

`scripts/fixtures/brand-pack-vectors.json` holds valid and refused packs (invented brand, `Lantern Quay`) with the messages each must produce. The Python tests (`src/papyrus_content/brand_pack/brand_pack_test.py`) and the behave feature (`features_backend/brand-pack-validator.feature`) read it, and the newsroom's TypeScript validator will reuse it.

```
poetry run pytest src/papyrus_content/brand_pack -q
poetry run behave features_backend/brand-pack-validator.feature
```
