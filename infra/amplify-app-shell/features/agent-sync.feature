Feature: The Amplify build applies the site's agent definitions after it registers the procedures
  The agent definitions are in Git: the core ones in the Papyrus wheel and the site's own in its repository. The generated production build spec
  runs `papyrus agents apply` right after `papyrus procedures seed-required`, so a deploy applies every definition with no step done by hand, and
  after the procedures a definition names are registered. The step runs as the Amplify build role on the operator lane, from the site's checkout,
  with the Papyrus version the site pins. It is not allowed to fail quietly: an invalid definition, a definition naming a procedure that is not
  registered, or a failed write fails the build, so a site is never deployed with definitions that disagree with Git. The step needs no new
  permission beyond the procedure step's: it reads and writes the site's Automation records through the site's GraphQL API as that step does.
  Behaviour of the command: features_backend/agent-definitions-on-release.feature. Executable by scripts/test-infra-agent-sync.ts.

  Scenario: The production build applies the agent definitions after the procedures are registered
    Given the generated production build spec of a site
    Then the backend phase runs "papyrus agents apply" after "papyrus procedures seed-required"
    And it runs as the build role on the operator lane from the site's checkout
    And the step is not followed by a fallback that lets the build continue
    And the step applies and does not only preview or check

  Scenario: The agent step comes before the Alexa sync, which may fail quietly
    Given the generated production build spec of a site
    Then the Alexa sync stays the last backend command

  Scenario: The staging build does not apply agent definitions
    Given the generated staging build spec of a site
    Then it does not run "papyrus agents apply"
