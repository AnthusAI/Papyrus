export type ThemePackId = "papyrus" | "threat-intelligence" | "pilobol-us";

export type RendererConfig = {
  kind: "pretext" | "markus";
};

export type HostingConfig =
  | { kind: "amplify-ssr" }
  | { kind: "amplify-static" };

export type OpsChrome = "newsprint" | "app";

export type ThemePackTokens = {
  paper: string;
  moss: string;
  ochre: string;
  ink: string;
};

export const DEFAULT_THEME_PACK_TOKENS: ThemePackTokens = {
  paper: "#f4f4f5",
  moss: "#18181b",
  ochre: "#a1a1aa",
  ink: "#3f3f46",
};

export const PILOBOL_US_THEME_PACK_TOKENS: ThemePackTokens = {
  paper: "#f4efe4",
  moss: "#3f5d4a",
  ochre: "#c4843a",
  ink: "#2c2a24",
};
