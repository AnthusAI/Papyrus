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
  emailReceipt: {
    paths: ["features/newsroom-email-receipt.feature"],
    require: ["features/step_definitions/email-receipt.steps.js"],
    format: ["summary"],
  },
  // Editorial findings in the article editor (demo mode: no server or credentials). Needs `next dev` on PAPYRUS_BASE_URL.
  editorialPreview: {
    paths: ["features/newsroom-editorial-preview.feature"],
    require: ["features/support/**/*.js", "features/step_definitions/articles.steps.js", "features/step_definitions/editorial-preview.steps.js"],
    tags: "",
    format: ["progress", "summary"],
  },
  adminEditorRights: {
    paths: ["features/newsroom-admin-editor-rights.feature"],
    require: ["features/step_definitions/admin-editor-rights.steps.js"],
    format: ["summary"],
  },
  referenceEditor: {
    paths: ["features/newsroom-reference-editor-review.feature"],
    require: ["features/step_definitions/reference-editor.steps.js"],
    format: ["summary"],
  },
  newsroomUxReview: {
    paths: ["features/newsroom-board-and-ideas.feature"],
    require: ["features/step_definitions/newsroom-ux-review.steps.js"],
    format: ["summary"],
  },
  decisionControl: {
    paths: ["features/newsroom-decision-control.feature"],
    require: ["features/step_definitions/decision-control.steps.js"],
    format: ["summary"],
  },
  notificationCenter: {
    paths: ["features/newsroom-notification-center.feature"],
    require: ["features/step_definitions/notification-center.steps.js"],
    format: ["summary"],
  },
  referenceFeed: {
    paths: ["features/newsroom-reference-feed.feature"],
    require: ["features/step_definitions/reference-feed.steps.js"],
    format: ["summary"],
  },
  conversations: {
    paths: ["features/newsroom-conversations.feature"],
    require: ["features/step_definitions/conversations.steps.js"],
    format: ["summary"],
  },
  referenceVoteSaved: {
    paths: ["features/newsroom-reference-vote-saved.feature"],
    require: ["features/step_definitions/reference-vote-saved.steps.js"],
    format: ["summary"],
  },
  messageHashtags: {
    paths: ["features/message-hashtags.feature"],
    require: ["features/step_definitions/message-hashtags.steps.js"],
    format: ["summary"],
  },
  messageAuthorEnforced: {
    paths: ["features/message-author-enforced.feature"],
    require: ["features/step_definitions/message-author-enforced.steps.js"],
    format: ["summary"],
  },
  // The alexa plugin and the tasks that extend it: every features/alexa-*.feature with its features/step_definitions/alexa-*.steps.js.
  alexa: {
    paths: ["features/alexa-*.feature"],
    require: ["features/step_definitions/alexa-*.steps.js"],
    format: ["summary"],
  },
  messagesPage: {
    paths: ["features/newsroom-messages-page.feature"],
    require: ["features/step_definitions/messages-page.steps.js"],
    format: ["summary"],
  },
  cliLoginDiscovery: {
    paths: ["features/cli-login-discovery.feature"],
    require: ["features/step_definitions/cli-login-discovery.steps.js"],
    format: ["summary"],
  },
  cliRemoteLoginSite: {
    paths: ["features/cli-remote-login-site.feature"],
    require: ["features/step_definitions/cli-remote-login-site.steps.js"],
    format: ["summary"],
  },
  cliEnrollRoute: {
    paths: ["features/cli-enroll-route.feature"],
    require: ["features/step_definitions/cli-enroll-route.steps.js"],
    format: ["summary"],
  },
  referenceEditorLayout: {
    paths: ["features/newsroom-reference-editor-layout.feature"],
    require: ["features/step_definitions/reference-editor.steps.js"],
    format: ["summary"],
  },
};
