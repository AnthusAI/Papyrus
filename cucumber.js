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

module.exports = { default: defaultProfile };
