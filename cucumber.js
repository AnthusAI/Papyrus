function resolveTags() {
  const siteEnv = process.env.SITE_ENV;
  if (siteEnv === "staging") return "@staging";
  if (siteEnv === "production") return "not @live-agent and not @staging";
  return "not @live-agent and not @staging and not @production-guards";
}

const tags = resolveTags();

const defaultProfile = {
  paths: ["features/**/*.feature"],
  require: ["features/support/**/*.js", "features/step_definitions/**/*.js"],
  tags,
  format: ["progress", "summary"],
  publishQuiet: true,
};

module.exports = {
  default: defaultProfile,
  // Hermetic component/browser acceptance: no server, credentials or production reads.
  referenceEditor: {
    paths: ["features/newsroom-reference-editor-review.feature"],
    require: ["features/step_definitions/reference-editor.steps.js"],
    format: ["summary"],
  },
  cliLoginDiscovery: {
    paths: ["features/cli-login-discovery.feature"],
    require: ["features/step_definitions/cli-login-discovery.steps.js"],
    format: ["summary"],
  },
  referenceEditorLayout: {
    paths: ["features/newsroom-reference-editor-layout.feature"],
    require: ["features/step_definitions/reference-editor.steps.js"],
    format: ["summary"],
  },
};
