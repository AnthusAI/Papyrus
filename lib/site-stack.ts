/**
 * Independent site-stack axes. Do not collapse these into one "brand mode".
 * - themePack / themeTokens: ops + shared Shadcn colors
 * - opsChrome: newsroom shell (app vs newsprint)
 * - renderer: publication / reader output (pretext vs markus)
 * - hosting: where the built site is served
 *
 * Shared ops components consume CSS variables only. Pilobolus is the first
 * extra pack, not the platform default (that remains `papyrus`).
 */
/** Open string: publications register their own pack id (see lib/define-site.ts). */
export type ThemePackId = string;

export type RendererConfig = {
  kind: "pretext" | "markus";
};

export type HostingConfig =
  | { kind: "amplify-ssr" }
  | { kind: "amplify-static" };

/**
 * What the root route (`/`) of a Papyrus app does. Independent of hosting and
 * of where the public reader lives — a site configures this explicitly.
 *
 * - `reader`: render the publication home page here (the single-app reader+Cms
 *   model used by p.apyr.us and Threat Intelligence). Default when omitted.
 * - `redirect`: redirect `/` to `destination` (a path or absolute URL). Use
 *   this for CMS-only deployments whose public reader lives on another app.
 * - `newsroom`: render the newsroom desk at `/` (for a CMS-only subdomain).
 */
export type RootRouteConfig =
  | { kind: "reader" }
  | { kind: "redirect"; destination: string; permanent?: boolean }
  | { kind: "newsroom" };

/**
 * Optional reader deployment when CMS and public reader ship separately
 * (Pilobolus, Anth.us).
 *
 * `domain` and `amplifyAppId` are optional because a reader can legitimately
 * exist before either is known: a staging port runs on the Amplify-provided
 * hostname with no custom domain attached, and the app id does not exist until
 * someone creates the app. Leave them unset rather than writing down a
 * hostname that is not actually serving this build — a wrong canonical host is
 * worse than an absent one.
 */
export type ReaderDeployment = {
  kind: "amplify-static";
  repository: string;
  domain?: string;
  amplifyAppId?: string;
};

export type OpsChrome = "newsprint" | "app";

export type SiteOpsStack = {
  chrome: OpsChrome;
  themePack: ThemePackId;
  themeTokens: ThemePackTokens;
};

export type SitePublicationStack = {
  renderer: RendererConfig;
};

/** Ops UI and publication/reader are independently pluggable. */
export type SiteStack = {
  ops: SiteOpsStack;
  publication: SitePublicationStack;
  hosting: HostingConfig;
};

export type SiteStackSource = {
  themePack: ThemePackId;
  themeTokens: ThemePackTokens;
  opsChrome: OpsChrome;
  renderer: RendererConfig;
  hosting: HostingConfig;
};

export function getSiteStack(source: SiteStackSource): SiteStack {
  return {
    ops: {
      chrome: source.opsChrome,
      themePack: source.themePack,
      themeTokens: source.themeTokens,
    },
    publication: { renderer: source.renderer },
    hosting: source.hosting,
  };
}

export type ThemePackPalette = {
  paper: string;
  moss: string;
  ochre: string;
  ink: string;
  muted?: string;
  card?: string;
  line?: string;
  quote?: string;
  tip?: string;
  caution?: string;
  stage?: string;
};

export type ThemePackTokens = ThemePackPalette & {
  dark?: ThemePackPalette;
};

export const DEFAULT_THEME_PACK_TOKENS: ThemePackTokens = {
  paper: "#f4f4f5",
  moss: "#18181b",
  ochre: "#a1a1aa",
  ink: "#3f3f46",
};

/**
 * Pilobolus / fungus-among-us palette copied from AnthusAI/Pilobol.us
 * `web/css/pilobil-theme-v10.css` (`:root` / `@media (prefers-color-scheme: dark)`).
 * Colors only — Shadcn owns typography. Do not load that file at runtime.
 */
export const PILOBOL_US_THEME_PACK_TOKENS: ThemePackTokens = {
  ink: "#211d17",
  muted: "#6b6153",
  paper: "#f1ead9",
  card: "#fbf6ea",
  line: "#d7cbb2",
  moss: "#3f5d43",
  ochre: "#a35a2a",
  quote: "#4a3548",
  tip: "#4f6b3a",
  caution: "#8a3324",
  stage: "#ddd4bf",
  dark: {
    ink: "#dfded0",
    muted: "#8b9184",
    paper: "#14170f",
    card: "#1c2117",
    line: "#333b2a",
    moss: "#b7d18a",
    ochre: "#d0895a",
    quote: "#b7a3c4",
    tip: "#9fce7a",
    caution: "#d17e6e",
    stage: "#0d0f0a",
  },
};

/**
 * Anthus palette, read off the live Gatsby site at `AnthusAI/Anth.us`
 * (`src/styles/variables.scss` `:root`). Colors only — Shadcn owns typography.
 * Mapping from that file's names to the pack's slots:
 *
 * | pack slot | Anth.us variable          | value     |
 * | --------- | ------------------------- | --------- |
 * | `paper`   | `--color-layout-bg`       | `#f1f9fe` |
 * | `card`    | `--color-wrapper-bg`      | `#ffffff` |
 * | `ink`     | `--color-text`            | `#333333` |
 * | `moss`    | `--color-primary`         | `#dc5497` |
 * | `ochre`   | `--color-active`          | `#ff57b4` |
 * | `quote`   | `--color-gradient-mid`    | `#9b165d` |
 * | `tip`     | `--color-gradient-end`    | `#0389d7` |
 * | `stage`   | `--color-hamburger`       | `#fedded` |
 *
 * Two slots have no counterpart on the Gatsby site and are **derived**, which
 * is called out here so nobody mistakes them for copied brand values:
 *
 * - `line`: the site's only rule color is `hr { background: hsla(0,0%,0%,0.2) }`
 *   over white, flattened to `#cccccc`.
 * - `muted`: the site has no muted-text token at all — it dims with
 *   `opacity: 0.5` instead (and references an undefined `--color-text-light`).
 *   `#5f6b73` is `--color-text` desaturated toward `paper`'s blue.
 * - `caution`: `#e95800`, which the site uses for one of its `::marker`
 *   colors; it has no dedicated danger color.
 *
 * There is deliberately **no `dark` palette**: the Gatsby site has no dark
 * mode. Its only `prefers-color-scheme: dark` block overrides two
 * code-highlight tints. Inventing a dark Anthus palette here would be making
 * up a look rather than porting one, so `theme.css` pins `color-scheme: light`.
 */
export const ANTH_US_THEME_PACK_TOKENS: ThemePackTokens = {
  ink: "#333333",
  muted: "#5f6b73",
  paper: "#f1f9fe",
  card: "#ffffff",
  line: "#cccccc",
  moss: "#dc5497",
  ochre: "#ff57b4",
  quote: "#9b165d",
  tip: "#0389d7",
  caution: "#e95800",
  stage: "#fedded",
};
