Feature: A large backend release is never killed by the build timeout
  Amplify stops a build job after 30 minutes unless the app's _BUILD_TIMEOUT environment variable says otherwise
  (minimum 5, maximum 120 minutes). A backend release that creates many indexes needs more than 30 minutes: Machines on
  Machines job 107 was stopped at 30 minutes while its CloudFormation update, which took 54 minutes, was still running.
  The app shell sets _BUILD_TIMEOUT on the Amplify app, so every branch gets it, from the site setting
  cms.buildTimeoutMinutes (a whole number from 5 to 120, default 120). Nothing is set by hand. Changing the value on an
  existing site is a CloudFormation Modify of the Amplify app's EnvironmentVariables: no replacement, no new resource.
  The backend deploy command and the deploy workflow read the same limit. The second half, the release budget that keeps a
  release inside the timeout, is in features_backend/platform/gsi-ledger.feature.
  Executable by scripts/test-build-timeout.ts (and scripts/test-backend-deploy.mjs for the deploy time).

  Scenario: The app shell sets the build timeout in infrastructure as code
    Given a site config with cms.buildTimeoutMinutes 90
    When the app shell template is synthesized
    Then the Amplify app has an environment variable _BUILD_TIMEOUT with value "90"
    And the Amplify branches set no _BUILD_TIMEOUT of their own

  Scenario: The timeout defaults to the maximum for a site that deploys its backend in the build
    Given a site config that does not set cms.buildTimeoutMinutes
    When the app shell template is synthesized
    Then the Amplify app has _BUILD_TIMEOUT "120"

  Scenario: A value outside Amplify's range is refused
    Given a site config with cms.buildTimeoutMinutes 121, 4, 90.5 or "90"
    When the site config is validated
    Then validation fails saying the range is 5 to 120 minutes

  Scenario: The deploy passes use the configured timeout
    Given _BUILD_TIMEOUT is "120" in the build environment
    When papyrus-infra backend-deploy computes its time
    Then it has 110 minutes for deploying

  Scenario: The deploy workflow waits longer than the build can run
    Given a build timeout of 120 minutes
    When amplify-deploy starts the job
    Then its wait and its own job timeout are more than 120 minutes

  Scenario: A real deploy longer than 30 minutes completes
    Given the app shell deployed with the timeout set
    When an Amplify job on a site runs a backend update that takes 35 minutes
    Then the job ends SUCCEED and is not stopped at 30 minutes
    # Verified on the first real job after the app shell is deployed; not executable in CI.
