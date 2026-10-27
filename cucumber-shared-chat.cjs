module.exports = { default: {
  paths: ["features/newsroom-shared-chat.feature", "features/newsroom-chat-identity.feature", "features/newsroom-mobile-chat.feature", "features/newsroom-chat-transaction-permissions.feature"],
  require: ["features/step_definitions/shared-chat.steps.js", "features/step_definitions/chat-transaction-permissions.steps.js"],
  format: ["summary"],
} };
