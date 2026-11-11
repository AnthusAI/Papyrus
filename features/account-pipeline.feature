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
    Then the roles job waits in the protected environment for a person to approve it
    And the ordinary deploy role is denied on that stack

  Scenario: A stack that waits for DNS delegation is disabled with a reason
    Given the certificate stack is disabled in the config
    Then no job deploys, plans or scopes it until it is enabled

  Scenario: Nothing changes for the running Anthus deployments
    Given the existing stacks.json and the papyrus-pipeline-approver stack
    Then stack_deploy.py behaves exactly as before for monitoring and the operators stack
