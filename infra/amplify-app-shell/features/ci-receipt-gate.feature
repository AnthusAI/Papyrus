Feature: Private site builds verify the LeftBlock CI receipt before deploying
  Amplify builds only deploy. A private repository gets no GitHub Actions minutes and no branch protection, so
  its tests run locally and `leftblock ci` posts a `leftblock/ci` commit status for the exact commit it tested.
  A site that opts in with `ci.gate: leftblock-receipt` makes the first commands of its production build read
  that status for $AWS_COMMIT_ID from GitHub, so a commit without a successful receipt stops in well under a
  minute, before `npm ci`, instead of failing a twelve minute build. A site without `ci` is not changed at all.
  The GitHub token is a SecureString at /papyrus/<siteId>/github-status-token created by the app-shell stack.
  Executable by scripts/test-infra-ci-gate.ts.

  Scenario: a site without a ci section keeps today's build spec and synthesizes nothing new
    Given a site config without a "ci" section
    When the app shell stack is synthesized
    Then no build spec contains the receipt gate
    And no github-status-token parameter or read grant exists

  Scenario: private site build without a receipt stops before npm ci
    Given a private site config with ci gate "leftblock-receipt"
    And GitHub reports no "leftblock/ci" status for the build's commit
    When the generated gate commands run
    Then the build exits with status 1
    And it prints "No LeftBlock CI receipt for" the commit id with the instruction to run `leftblock ci` and push again
    And the gate is the first backend command, ahead of "npm ci"

  Scenario: a failure receipt, an unreadable response and a missing commit id also stop the build
    Given a private site config with ci gate "leftblock-receipt"
    When the status is "failure", or GitHub cannot be read, or AWS_COMMIT_ID is empty
    Then the build exits with status 1

  Scenario: private site build with a success receipt deploys
    Given a private site config with ci gate "leftblock-receipt"
    And GitHub reports a "success" "leftblock/ci" status for the build's commit
    When the generated gate commands run
    Then the gate passes and the build continues to "npm ci"
    And this holds with jq and with the grep and awk fallback

  Scenario: the stack grants the build role one parameter and nothing else
    Given a private site config with ci gate "leftblock-receipt"
    When the app shell stack is synthesized
    Then one SecureString parameter "/papyrus/<siteId>/github-status-token" is created by the stack
    And the build service role may only ssm:GetParameter that parameter for the gate
    And the reader app of the same site shares the same parameter

  Scenario: the gate must match how the site deploys
    Given a site config
    When autoDeploy is true and the gate is "leftblock-receipt", or autoDeploy is false and the gate is "actions"
    Then the config is rejected
    And requireSignature true is rejected until signature verification exists
