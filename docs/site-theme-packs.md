# Site theme packs and ops chrome

Papyrus newsroom (`/newsroom`) is a **platform** surface. It is not a
Pilobolus app. Every publication reuses the same Shadcn ops chrome and
customizes appearance through a **theme pack** on `SiteBrand`.

Kanbus: PPY-3e26b7 (PM: PPY-5a5570). Acceptance client: Pilobol.us.

## Independent axes (do not collapse them)

Configured on `SiteBrand` in `lib/site-brand.ts` / `lib/site-stack.ts`:

| Axis | Type | What it changes | What it must not change |
| --- | --- | --- | --- |
| **Theme pack** | `themePack` + `themeTokens` | Shadcn CSS variables (paper / moss / ochre / ink, plus optional card, line, …) | Renderer, hosting, GraphQL |
| **Ops chrome** | `opsChrome`: `app` \| `newsprint` | Newsroom shell vocabulary | Reader page layout |
| **Renderer** | `renderer.kind`: `pretext` \| `markus` | Publication / reader output | Ops chrome or theme tokens |
| **Hosting** | `hosting.kind` | Where the built site is served | Theme or renderer |

A Markus reader (Pilobol.us) can use Shadcn ops. A Pretext reader (Papyr.us,
Threat Intelligence) uses the **same** ops chrome with a different pack.
Adopting Shadcn ops does not force Markus on the reader.

Pluggable-stack contract (ops vs renderer): [site-stacks.md](site-stacks.md).
See [site-hosting.md](site-hosting.md) for hosting/renderer pairings.

## How a pack is selected

1. Set `PAPYRUS_SITE_BRAND` / `NEXT_PUBLIC_PAPYRUS_SITE_BRAND`.
2. `resolveSiteBrandId` maps aliases (`pilobolus`, `pilobol.us`, `threat-intel`, …).
3. `getSiteBrand()` supplies `themePack`, `themeTokens`, `opsChrome`, `renderer`, `hosting`.
4. `app/layout.tsx` writes `data-theme-pack` and `data-ops-chrome` on `<html>`.
5. Publication CSS keyed on those attributes maps tokens onto Shadcn variables.

Default brand is **papyrus** (slate Shadcn tokens). Pilobolus is the first
extra themed client: `PAPYRUS_SITE_BRAND=pilobol-us` for acceptance against
pilobol-us. It is not the platform default.

## Packs shipping now

| `themePack` | Brand env | CSS | Notes |
| --- | --- | --- | --- |
| `papyrus` | `papyrus` (default) | `publications/papyrus/theme.css` | Identity pack: aliases `--theme-*` to existing Shadcn `:root` tokens |
| `threat-intelligence` | `threat-intelligence` | `publications/threat_intelligence/theme.css` | Reader + ops sand/tomato tokens |
| `pilobol-us` | `pilobol-us` | `publications/pilobol_us/theme.css` | Official Markus fungus-among-us colors, copied in; **no** font stack |

## Shared UI contract

`components/newsroom-app-shell.tsx` and `.newsroom-app-shell` rules in
`app/globals.css` may use Shadcn / `--theme-*` variables only.

Forbidden in shared ops primitives:

- Publication names (`pilobol`, `threat-intelligence`, `papyrus` class names)
- One-off Pilobolus hexes (`#f1ead9`, `#3f5d43`, `#a35a2a`, …)
- Site poem / masthead font stacks

Add a new pack by copying `publications/papyrus/` or `publications/pilobol_us/`,
registering the brand in `lib/site-brand.ts`, and adding a `ThemePackId`. Do
not fork the Next.js app.
