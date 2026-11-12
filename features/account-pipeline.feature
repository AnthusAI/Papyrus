Feature: A deployment's account is seeded once and then changed only from Git
  Ryan's rule (2026-11-11): nobody creates a cloud resource by hand. A deployment repository seeds its AWS account with the account baseline
  stack (infra/account/baseline.yaml) in one documented apply, and from then on the reusable workflow account-stacks.yml deploys the account's
  own stacks (DNS, budget, certificate, SES) from Git. Resources that were made by hand are adopted by CloudFormation import, never replaced.
  These scenarios are checked by procedures/newsroom/tests/test_account_stacks.py and, for the templates, by cfn-lint in CI.

  Scenario: A new deployment is seeded with one apply
    Given a new AWS account and a deployment repository
    When a person applies infra/account/baseline.yaml once with the prefix, the repository and the budget name
    Then the account has the GitHub OIDC provider and the plan, deploy, roles-apply and two service roles
    And nothing in the template names AnthusAI, anth.us or any other deployment's account

  Scenario: The deploy role is trusted only for the release branch
    Given the seeded deploy role
    Then its trust names only the repository's main branch
    And a pull request or any other branch is refused by AWS

  Scenario: A merge deploys changed stacks through the service role
    Given a stack template changed in a commit merged to main
    When the account-stacks workflow runs
    Then each enabled stack of the default group gets a change set created through the service role
    And a change set that would Remove or Replace anything not in allowed-changes.json is deleted unexecuted

  Scenario: A hand-made zone is imported, not replaced
    Given the Route 53 zone exists and has no stack
    When the stack is first deployed
    Then the change set type is IMPORT and every change in it is an Import
    And a change set holding any other action is deleted unexecuted
    And afterwards the zone's name servers equal the expected list, or the deploy fails

  Scenario: Changing the account baseline waits for a person
    Given a merged change to the baseline stack
    When the workflow finds the live stack differs from Git
    Then the roles job applies it in the main-only environment, with no person's approval, and the app stacks deploy after it
    And the ordinary deploy role is denied on that stack

  Scenario: A stack that waits for DNS delegation is disabled with a reason
    Given the certificate stack is disabled in the config
    Then no job deploys, plans or scopes it until it is enabled

  Scenario: Nothing changes for the running Anthus deployments
    Given the existing stacks.json and the papyrus-pipeline-approver stack
    Then stack_deploy.py behaves exactly as before for monitoring and the operators stack

  Scenario: The app shell is synthesized without AWS and a second stack is refused
    Given a deployment repository that calls app-shell-deploy.yml with the expected stack name
    When the synth job runs on a pull request
    Then papyrus-infra synth runs with no AWS credentials
    And check_cdk_manifest.py fails the job unless the manifest holds exactly one CloudFormation stack with that name
    And a synth that also names another stack, such as the account baseline, never reaches the deploy job

  Scenario: The app shell deploys only from main
    Given the synth job passed
    When the run is a pull request or any ref other than main
    Then the deploy and build jobs are skipped
    And on a push to main the deploy job assumes the github-deploy role, runs one at a time per repository and is never cancelled

  Scenario: The first build waits for the two person-only steps
    Given the app-shell stack deployed and the first-build-watch workflow runs on the default branch
    When the Amplify app has no repository connected, or the Google client parameters are missing from SSM
    Then the watcher prints which step is missing, without the app id, and reads only parameter names, never a value
    And it dispatches no build and stays enabled

  Scenario: The first build starts by itself and the watcher turns itself off
    Given the repository is connected and the Google client parameters exist
    When the watcher runs as the read-only github-watch role, which trusts the default branch only
    Then it dispatches first-build.yml on main and disables its own workflow so it never runs again

  Scenario: The first build runs the two-pass bootstrap and can be resumed
    Given the first-build workflow runs on main as the github-deploy role
    Then it sets PAPYRUS_BOOTSTRAP_STAGE=1 keeping every other branch variable, starts pass 1 and waits
    And on success it removes the variable, starts pass 2 and waits, then disables the watcher
    And a run that finds pass 1 succeeded starts only pass 2, a run that finds a running job waits for it, and a run that finds pass 2 succeeded does nothing

  Scenario: A failed first-build pass stops and waits for a person
    Given a first-build job failed or was cancelled
    When the workflow runs again
    Then it starts nothing and exits with an error telling a person to read the Amplify job log
    And only a manual dispatch with retry-failed starts the pass again
