export type ThemePackId = "papyrus" | "threat-intelligence" | "pilobol-us";

export type RendererConfig = {
  kind: "pretext" | "markus";
};

export type HostingConfig =
  | { kind: "amplify-ssr" }
  | { kind: "amplify-static" };

export type OpsChrome = "newsprint" | "app";

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
