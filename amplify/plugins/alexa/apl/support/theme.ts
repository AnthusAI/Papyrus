import type { AlexaConfig, AlexaTheme } from "../../config";

/** The colours the APL documents use. Same shape as the optional `theme` setting of the plugin. */
export type AplTheme = AlexaTheme;

/** The brand palette fields a site's `themeTokens` carry (`lib/site-stack.ts` `ThemePackTokens`); only what the mapping reads. */
export type BrandPalette = { ink: string; paper: string; card?: string; muted?: string; moss?: string; ochre?: string };
export type BrandTokens = BrandPalette & { dark?: BrandPalette };

/**
 * Pilobolus (`PILOBOL_US_THEME_PACK_TOKENS`, dark variant): Echo Shows are usually dark, so this is the fallback when a site sets
 * no theme. paper -> background, card -> surface, ink -> text, muted -> mutedText, moss -> accent.
 */
export const DEFAULT_APL_THEME: AplTheme = {
  background: "#14170f",
  surface: "#1c2117",
  text: "#dfded0",
  mutedText: "#8b9184",
  accent: "#b7d18a",
};

/**
 * The same mapping from a site's brand tokens, for a site that wants its theme derived rather than typed. `mode: "dark"` reads the
 * dark variant when the tokens have one. Missing optional tokens fall back to the default theme's value.
 */
export function themeFromTokens(tokens: BrandTokens, mode: "light" | "dark" = "dark"): AplTheme {
  const palette = mode === "dark" && tokens.dark !== undefined ? tokens.dark : tokens;
  return {
    background: palette.paper,
    surface: palette.card ?? palette.paper,
    text: palette.ink,
    mutedText: palette.muted ?? DEFAULT_APL_THEME.mutedText,
    accent: palette.moss ?? palette.ochre ?? DEFAULT_APL_THEME.accent,
  };
}

/** The site's `theme` setting, or the built-in dark theme when it sets none. */
export function themeFromConfig(config: Pick<AlexaConfig, "theme">): AplTheme {
  return config.theme ?? DEFAULT_APL_THEME;
}
