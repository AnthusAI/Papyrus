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
  bootstrapFirstDeploy: {
    paths: ["features/bootstrap-first-deploy.feature"],
    require: ["features/step_definitions/bootstrap-first-deploy.steps.js"],
    format: ["summary"],
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
  boardRefresh: {
    paths: ["features/newsroom-board-refresh.feature"],
    require: ["features/step_definitions/board-refresh.steps.js"],
    format: ["summary"],
  },
  boardStoryTypes: {
    paths: ["features/newsroom-board-story-types.feature"],
    require: ["features/step_definitions/board-story-types.steps.js"],
    format: ["summary"],
  },
  notificationCenter: {
    paths: ["features/newsroom-notification-center.feature"],
    require: ["features/step_definitions/notification-center.steps.js"],
    format: ["summary"],
  },
  homeCyclotron: {
    paths: ["features/newsroom-home-cyclotron.feature"],
    require: ["features/step_definitions/home-cyclotron.steps.js"],
    format: ["summary"],
  },
  needsMeLinks: {
    paths: ["features/needs-me-link-suggestions.feature", "features/needs-me-phone-detail.feature"],
    require: ["features/step_definitions/needs-me-links.steps.js"],
    format: ["summary"],
  },
  connectCli: {
    paths: ["features/newsroom-connect-cli.feature"],
    require: ["features/step_definitions/connect-cli.steps.js"],
    format: ["summary"],
  },
  referenceFeed: {
    paths: ["features/newsroom-reference-feed.feature"],
    require: ["features/step_definitions/reference-feed.steps.js"],
    format: ["summary"],
  },
  referenceSearch: {
    paths: ["features/newsroom-reference-search.feature"],
    require: ["features/step_definitions/reference-search.steps.js"],
    format: ["summary"],
  },
  searchResults: {
    paths: ["features/newsroom-search-results.feature"],
    require: ["features/step_definitions/search-results.steps.js"],
    format: ["summary"],
  },
  referenceQuality: {
    paths: ["features/newsroom-reference-quality.feature"],
    require: ["features/step_definitions/reference-quality.steps.js"],
    format: ["summary"],
  },
  addReference: {
    paths: ["features/newsroom-add-reference.feature"],
    require: ["features/step_definitions/add-reference.steps.js"],
    format: ["summary"],
  },
  referenceMedium: {
    paths: ["features/newsroom-reference-medium.feature"],
    require: ["features/step_definitions/reference-medium.steps.js"],
    format: ["summary"],
  },
  referenceMediumFilter: {
    paths: ["features/newsroom-reference-medium-filter.feature"],
    require: ["features/step_definitions/reference-medium-filter.steps.js"],
    format: ["summary"],
  },
  referenceCaptureNeeded: {
    paths: ["features/newsroom-reference-capture-needed.feature"],
    require: ["features/step_definitions/reference-capture-needed.steps.js"],
    format: ["summary"],
  },
  conversations: {
    paths: ["features/newsroom-conversations.feature"],
    require: ["features/step_definitions/conversations.steps.js"],
    format: ["summary"],
  },
  sectionCoreConcepts: {
    paths: ["features/section-core-concepts.feature"],
    require: ["features/step_definitions/section-core-concepts.steps.js"],
    format: ["summary"],
  },
  referenceRelatedUi: {
    paths: ["features/reference-related-ui.feature"],
    require: ["features/step_definitions/reference-related-ui.steps.js"],
    format: ["summary"],
  },
  referenceVoteSaved: {
    paths: ["features/newsroom-reference-vote-saved.feature"],
    require: ["features/step_definitions/reference-vote-saved.steps.js"],
    format: ["summary"],
  },
  dataTableRecovery: {
    paths: ["features/data-table-point-in-time-recovery.feature"],
    require: ["features/step_definitions/data-table-point-in-time-recovery.steps.js"],
    format: ["summary"],
  },
  coverImagePicker: {
    paths: ["features/cover-image-picker.feature"],
    require: ["features/step_definitions/cover-image-picker.steps.js"],
    format: ["summary"],
  },
  storyDetailHeadlineImage: {
    paths: ["features/story-detail-headline-image.feature"],
    require: ["features/step_definitions/story-detail-headline-image.steps.js"],
    format: ["summary"],
  },
  messageHashtags: {
    paths: ["features/message-hashtags.feature"],
    require: ["features/step_definitions/message-hashtags.steps.js"],
    format: ["summary"],
  },
  referenceLinkResolvers: {
    paths: ["features/reference-link-resolvers.feature"],
    require: ["features/step_definitions/reference-link-resolvers.steps.js"],
    format: ["summary"],
  },
  markdownTwinDisplay: {
    paths: ["features/markdown-twin-display.feature"],
    require: ["features/step_definitions/markdown-twin-display.steps.js"],
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
  storyTypeEditor: {
    paths: ["features/newsroom-story-type-editor.feature"],
    require: ["features/step_definitions/story-type-editor.steps.js"],
    format: ["summary"],
  },
  // The research assignment box and the Work section's packets (demo mode). Needs `next dev` on PAPYRUS_BASE_URL.
  assignResearch: {
    paths: ["features/newsroom-assign-research.feature"],
    require: ["features/support/**/*.js", "features/step_definitions/story-references.steps.js", "features/step_definitions/assign-research.steps.js"],
    tags: "",
    format: ["summary"],
  },
  // AI agent notes in a story's Messages view (demo mode). Needs `next dev` on PAPYRUS_BASE_URL.
  storyAgentNotes: {
    paths: ["features/newsroom-story-agent-notes.feature"],
    require: ["features/support/**/*.js", "features/step_definitions/story-references.steps.js", "features/step_definitions/assign-research.steps.js", "features/step_definitions/story-agent-notes.steps.js"],
    tags: "",
    format: ["summary"],
  },
  createStory: {
    paths: ["features/newsroom-create-story.feature"],
    require: ["features/step_definitions/create-story.steps.js"],
    format: ["summary"],
  },
  cardSuggestions: {
    paths: ["features/newsroom-card-suggestions.feature"],
    require: ["features/step_definitions/card-suggestions.steps.js"],
    format: ["summary"],
  },
  referenceStars: {
    paths: ["features/newsroom-reference-stars.feature"],
    require: ["features/step_definitions/reference-stars.steps.js"],
    format: ["summary"],
  },
  storyStars: {
    paths: ["features/newsroom-story-stars.feature"],
    require: ["features/step_definitions/story-stars.steps.js"],
    format: ["summary"],
  },
  autoAcceptedList: {
    paths: ["features/newsroom-auto-accepted-list.feature"],
    require: ["features/step_definitions/auto-accepted-list.steps.js"],
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
