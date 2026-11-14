Feature: The skill sync starts wherever it is run
  A site's Amplify build runs `papyrus-app alexa-sync` after the backend deploy; an operator can run the same sync by hand with
  `scripts/alexa/ask-deploy.ts`. Both entry points once failed before doing anything (top-level await under tsx's CJS transform),
  so the Pilobolus skill had to be created by hand. These scenarios run the real entry points with outputs that do not enable the
  plugin, so they skip without touching AWS or Amazon.

  Scenario: The build's entry point starts
    When the sync's command-line entry point runs for a site without the alexa plugin
    Then it says it skipped and exits successfully

  Scenario: The by-hand script starts
    When the by-hand sync script runs for a site without the alexa plugin
    Then it says it skipped and exits successfully
