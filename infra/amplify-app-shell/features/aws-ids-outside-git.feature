Feature: A site repository does not have to store AWS account and resource ids
  LeftBlock blocks AWS account ids and resource ids in commits. Papyrus tooling used to read them from
  literals in a site's repository: infra/site.json, papyrus.config.ts, amplify.yml, a postinstall script and
  the deploy workflow. Each of those now also reads its value from somewhere that is not Git, and a literal is
  only a fallback, so a site that still has literals deploys exactly as before until it is migrated.
  The pattern is the same everywhere: GitHub repository variables for workflows, Amplify branch environment
  variables for builds and backend synthesis, and the deploy environment (or the caller's credentials) for
  operator tooling. These scenarios are verified by scripts/test-infra-site-config.ts,
  scripts/test-infra-app-shell-account.mjs, scripts/test-infra-cdk-environment.mjs,
  scripts/test-infra-deploy-edge.mjs, scripts/test-infra-deploy-workflow.mjs,
  scripts/test-s3-projection-publication.ts, scripts/test-reader-steering-plugin.ts,
  scripts/test-newsletter-plugin.ts, scripts/test-scheduled-job-synth.ts and
  procedures/newsroom/tests/test_site_google_secrets.py. Account ids in the examples are AWS's documentation
  account 111122223333.

  Scenario: The deploy account comes from PAPYRUS_AWS_ACCOUNT_ID
    Given a site.json with an aws.region and no aws.accountId
    And PAPYRUS_AWS_ACCOUNT_ID is set to a 12-digit account id
    When the app-shell stack is synthesized
    Then the stack targets that account and the site repository holds no account id

  Scenario: The environment wins over a literal that is still in site.json
    Given a site.json whose aws.accountId is one account
    And PAPYRUS_AWS_ACCOUNT_ID names another
    When the deploy environment is resolved
    Then the account from PAPYRUS_AWS_ACCOUNT_ID is used
    And with the variable unset or blank, the literal in site.json is used exactly as before

  Scenario: No account is guessed
    Given a site.json without aws.accountId and no PAPYRUS_AWS_ACCOUNT_ID
    When the deploy environment is resolved
    Then it fails saying the site does not say where it deploys and naming PAPYRUS_AWS_ACCOUNT_ID
    And a PAPYRUS_AWS_ACCOUNT_ID that is not 12 digits is an error, not something to work around

  Scenario: A pinned deploy cannot land in another account
    Given PAPYRUS_AWS_ACCOUNT_ID pins a deploy to one account
    When papyrus-infra deploy runs with credentials for a different account
    Then it stops before synthesizing, says the credentials are for another account, and deploys nothing
    And if the caller's account cannot be determined it also stops

  Scenario: Operator commands assert the pinned account
    Given papyrus site google-secrets runs with PAPYRUS_AWS_ACCOUNT_ID set and no --account flag
    When the credentials belong to a different account
    Then it refuses before any read or write, as it does for aws.accountId
    And the --account flag still wins over both

  Scenario: The Prospectus accounts ARN may come from the environment
    Given a site with reader features and PAPYRUS_PROSPECTUS_ACCOUNTS_API_STAGE_ARN set
    When the site config is parsed
    Then the environment value is used, whether or not site.json still carries cms.prospectusAccountsApiStageArn
    And a malformed value is rejected naming the variable

  Scenario: The app-shell stack hands its own identifiers to the branches it creates
    Given the app-shell stack creates the CMS app, its compute role and the main and staging branches
    When the stack is synthesized
    Then both branches carry PAPYRUS_AMPLIFY_APP_ID and PAPYRUS_COMPUTE_ROLE_ARN, derived from the stack
    And a site's cms.environment may not set those two names itself

  Scenario: The compute role ARN comes from the branch environment
    Given a site backend uses the reader-steering or newsletter plugin
    When PAPYRUS_COMPUTE_ROLE_ARN is set on the Amplify branch
    Then the plugin uses it, whether or not computeRoleArn is written in papyrus.config.ts
    And with the variable unset the written computeRoleArn is used as before
    And with neither, the error names both places

  Scenario: The edge distribution ARN comes from the branch environment
    Given a site backend publishes through an existing CloudFront distribution
    When PAPYRUS_EDGE_DISTRIBUTION_ARN is set on the Amplify branch
    Then the publication uses it in place of any written edgeDistributionArn
    And with the variable unset the written edgeDistributionArn is used as before
    And publication: false still turns publication off

  Scenario: The owning-app guard names its app in the branch environment
    Given a build runs inside Amplify and PAPYRUS_AMPLIFY_APP_ID names the owning app
    When papyrus-infra deploy or deploy-edge runs in a different app
    Then it skips, saying the app does not own the stack
    And PAPYRUS_AMPLIFY_APP_ID wins over a literal --only-app-id

  Scenario: A site that opted in to the guard fails closed when the expected app is missing
    Given a postinstall passes --only-app-id with a value that expands to nothing
    And the build runs inside Amplify and PAPYRUS_AMPLIFY_APP_ID is not set
    When papyrus-infra deploy runs
    Then it fails and deploys nothing, instead of lifting the guard
    And outside an Amplify build it still skips quietly, so a local install keeps working

  Scenario: A site that never opted in is unchanged
    Given a postinstall without --only-app-id and without PAPYRUS_AMPLIFY_APP_ID
    When papyrus-infra deploy runs in an Amplify build on the owning branch
    Then it deploys as it always has

  Scenario: The reusable deploy workflow takes repository variables
    Given a caller passes app-id from vars.AMPLIFY_APP_ID, aws-account-id from vars.AWS_ACCOUNT_ID and a role-name
    When the deploy job starts
    Then the role ARN is built from the account and role name, and the Amplify job starts for the commit
    And a caller that still passes a literal role-to-assume and app-id works unchanged
    And a missing variable stops the job at its first step naming the variable

  Scenario: The deploy example carries no ids
    Given infra/amplify-app-shell/examples/deploy-on-merge.workflow.yml
    Then it contains no account id and no app id, only vars.AMPLIFY_APP_ID and vars.AWS_ACCOUNT_ID
