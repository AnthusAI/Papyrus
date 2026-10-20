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
