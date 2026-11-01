Feature: Amplify builds only deploy
  CI (type-check, lint, tests) runs in GitHub Actions for public repos and locally
  for private repos, never in Amplify, because Amplify build minutes cost money and
  the type-check ran out of memory there. withPapyrus skips Next's build-time checks
  inside Amplify. These scenarios are verified by
  scripts/test-with-papyrus-build-checks.mjs (npm run test:with-papyrus-build-checks).

  Scenario: In Amplify the build-time checks are skipped
    Given the build environment sets AWS_APP_ID and AWS_BRANCH
    When a site's Next config is wrapped with withPapyrus
    Then typescript.ignoreBuildErrors is true and eslint.ignoreDuringBuilds is true

  Scenario: Outside Amplify the checks run
    Given the build environment sets neither AWS_APP_ID nor AWS_BRANCH
    When a site's Next config is wrapped with withPapyrus
    Then it sets no typescript or eslint skip options

  Scenario: A site's own config wins
    Given the build runs in Amplify
    And the site config sets typescript.ignoreBuildErrors to false
    When the config is wrapped with withPapyrus
    Then the site's value is kept

  Scenario: The override restores the checks in Amplify
    Given the build runs in Amplify
    And PAPYRUS_NEXT_BUILD_CHECKS is 1
    When a site's Next config is wrapped with withPapyrus
    Then it sets no typescript or eslint skip options
