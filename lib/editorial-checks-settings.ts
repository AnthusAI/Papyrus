/** Runtime settings for editorial checks, stored in EditorialCheckSettings (id "settings"). */
export type EditorialSettings = {
  /** Core to every site and on by default; a publication turns its checks off here. */
  enabled: boolean;
  lanes: { rules: boolean; classifier: boolean };
  classifierModel: string;
  rewriteModel: string;
  deadlineSeconds: number;
  maxInputTokens: number;
  maxExamplesPerQuestion: number;
  guidance: string;
  publishWarning: boolean;
  /** Checks run on their own after the body changes and after each save. On unless an admin sets this to false (absent or null counts as on). */
  checkWhileTyping: boolean;
};

export const DEFAULT_EDITORIAL_SETTINGS: EditorialSettings = {
  enabled: true,
  lanes: { rules: true, classifier: true },
  classifierModel: "jev-latest",
  rewriteModel: "gpt-6-luna",
  deadlineSeconds: 20,
  maxInputTokens: 500000,
  maxExamplesPerQuestion: 4,
  guidance: "",
  publishWarning: true,
  checkWhileTyping: true,
};

/**
 * Stored settings over the defaults. A stored `null` (or a missing key) never overrides a default, so a record that
 * predates a setting, or holds null for it, behaves like the default: checks run automatically.
 */
export function mergeEditorialSettings(stored: Partial<{ [K in keyof EditorialSettings]: EditorialSettings[K] | null }> | null | undefined): EditorialSettings {
  const merged: Record<string, unknown> = { ...DEFAULT_EDITORIAL_SETTINGS };
  for (const [name, value] of Object.entries(stored ?? {})) if (value !== null && value !== undefined) merged[name] = value;
  merged.lanes = { ...DEFAULT_EDITORIAL_SETTINGS.lanes, ...(stored?.lanes ?? {}) };
  return merged as EditorialSettings;
}
