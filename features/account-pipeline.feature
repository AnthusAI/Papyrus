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

  Scenario: The account keeps a management-events audit trail
    Given the cloudtrail account stack
    Then it creates one multi-region trail that records management events only, with no data events and no Insights
    And log file validation is on and global service events are included
    And its log bucket blocks all public access, is encrypted, refuses plain HTTP and is retained if the stack is deleted
    And log files expire after the retention days, 400 by default and never fewer than 30
    And the first copy of management events is free, so only S3 storage is billed

  Scenario: Mail events are captured before any mail is sent
    Given the ses account stack
    Then it creates a configuration set and an SNS topic that only SES in this account may publish to
    And the event destination carries bounce, complaint, delivery-delay and reject events and nothing else
    And no send, open or click events are recorded

  Scenario: The mail event names cannot be forgotten
    Given the ses account stack
    Then the configuration set name and the event topic name are required parameters with no default
    And the service role can manage configuration sets, topics, the trail and the trail bucket only when they are named with the deployment prefix
