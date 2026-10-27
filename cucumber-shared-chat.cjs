module.exports = { default: {
  paths: ["features/newsroom-shared-chat.feature", "features/newsroom-chat-identity.feature", "features/newsroom-mobile-chat.feature"],
  require: ["features/step_definitions/shared-chat.steps.js"],
  format: ["summary"],
} };
