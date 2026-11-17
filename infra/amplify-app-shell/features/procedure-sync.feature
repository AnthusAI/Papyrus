Feature: The Amplify build registers the site's procedures after it deploys the backend
  A site's procedures are in Git: the core ones in the Papyrus wheel and the site's own in its repository. The generated production
  build spec runs `papyrus procedures seed-required` right after `papyrus-infra backend-deploy`, so a deploy registers every
  procedure with no step done by hand. The step runs as the Amplify build role on the operator lane, from the site's checkout, with
  the Papyrus version the site pins. It is not allowed to fail quietly: a registration that fails fails the build, so a site is never
  deployed with procedures that disagree with Git. Behaviour of the command: features_backend/procedures-registered-on-deploy.feature.
  Executable by scripts/test-infra-procedure-sync.ts.

  Scenario: The production build registers the procedures after the backend deploy
    Given the generated production build spec of a site
    Then the backend phase runs "papyrus procedures seed-required" after "npx papyrus-infra backend-deploy"
    And it installs the pinned Papyrus engine before it runs the command
    And it runs as the build role on the operator lane from the site's checkout
    And the step is not followed by a fallback that lets the build continue

  Scenario: The CI receipt gate still comes first and the staging build is unchanged
    Given the generated production build spec of a private site
    Then the receipt gate is still the first backend command
    And the staging build spec does not register procedures
