module.exports = {
  default: {
    paths: ["features/**/*.feature"],
    require: ["features/support/**/*.js", "features/step_definitions/**/*.js"],
    tags: "not @live-agent",
    format: ["progress", "summary"],
    publishQuiet: true,
  },
  canonical: {
    paths: ["features/**/*.feature"],
    require: ["features/support/**/*.js", "features/step_definitions/**/*.js"],
    tags: "not @live-agent",
    format: ["progress", "summary"],
    publishQuiet: true,
  },
  fork: {
    paths: ["features/**/*.feature"],
    require: ["features/support/**/*.js", "features/step_definitions/**/*.js"],
    tags: "not @live-agent",
    format: ["progress", "summary"],
    publishQuiet: true,
  },
  marketing: {
    paths: ["features/marketing-site.feature"],
    require: ["features/support/**/*.js", "features/step_definitions/**/*.js"],
    format: ["progress", "summary"],
    publishQuiet: true,
  },
};
