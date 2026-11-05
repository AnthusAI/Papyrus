Feature: Shared stacks deploy from the release, never by hand
  Ryan asked why anyone was creating change sets by hand when a commit through DevOps would do. The shared stacks papyrus-monitoring and the
  operator sending stack now deploy from a release to main with GitHub OIDC. A pull request shows a read-only dry run first. The run stops, and
  executes nothing, when a stack is in a failed state or a change would Remove or Replace something nobody listed. These scenarios are checked by
  procedures/newsroom/tests/test_stack_deploy.py.

  Scenario: A docs-only release deploys nothing
    Given a release whose only changes are documentation and the Kanbus board
    When the stack-deploy workflow decides which stacks are in scope
    Then no stack is in scope
    And the tests and the deploy job are skipped

  Scenario: A release that changes monitoring code deploys the monitoring stack
    Given a release that changes a module the router zip is built from
    When the stack-deploy workflow decides which stacks are in scope
    Then papyrus-monitoring is in scope
    And the operator sending stack is not

  Scenario: A release that failed is retried by the next one
    Given the last successful stack-deploy run was on an older commit
    When a later release contains only documentation
    Then the scope is measured from the last successful run, so the earlier stack changes are in scope again

  Scenario: The release deploys the changed stack through a change set it reads first
    Given the tests passed on the release commit
    And the stack is in UPDATE_COMPLETE
    When the deploy builds and uploads the zips and creates a change set through the service role
    And the change set holds no Remove and no Replace
    Then the change set is executed once
    And the run polls the stack until it reports UPDATE_COMPLETE
    And a stale UPDATE_COMPLETE left from an earlier deploy is never read as success

  Scenario: An unexpected removal or replacement stops the release
    Given the change set would Remove or Replace a resource that infra/pipeline/allowed-changes.json does not list for that stack
    When the deploy reads the change set
    Then the change set is deleted without being executed
    And the run fails and names the resource
    And adding a reviewed entry with a reason to allowed-changes.json lets the next release go ahead

  Scenario: A stack in a failed state stops the release
    Given the stack is in UPDATE_ROLLBACK_FAILED
    When the deploy starts
    Then no change set is created and nothing is uploaded
    And the run fails and says a person must repair the stack

  Scenario: A malformed key never reaches CloudFormation
    Given a code key that spans two lines
    When the deploy validates its parameters
    Then the run stops before creating a change set

  Scenario: A failed update alerts
    Given the change set is executing
    When the stack rolls back
    Then the run fails with the first failed resource event as the cause
    And nothing is retried

  Scenario: The first create of the operator stack
    Given the stack is in REVIEW_IN_PROGRESS with an unexecuted change set the pipeline did not make
    When the deploy runs
    Then it creates its own CREATE change set and leaves the other one alone
    And it looks the hosted zone up and never stores its id

  Scenario: A first create whose change set disappears while it runs
    Given the release executed the change set that creates a new stack
    And CloudFormation no longer finds that change set
    When the stack finishes creating
    Then the deploy succeeds, because it judged the stack and not the change set
    And a stack that rolls back still fails the release

  Scenario: A pull request shows a dry run and changes nothing
    Given a pull request that edits infra/monitoring
    When the dry-run job runs with the read-only role
    Then the job summary lists resources added, removed and modified against the live stack
    And a removal that is not on the allowed list is marked as one that would stop the release
    And no change set, upload or execution is made

  Scenario: The roles trust only this repository
    Given the pipeline bootstrap template
    Then the deploy role trusts only this repository's main branch
    And the dry-run role trusts only this repository's pull requests and holds only read permissions
    And no account id and no stored key appears in the repository

  # The role bootstrap (PPY-9d1b3e). Ryan, 2026-11-05: a command that sets up a role the deployment needs must be repeatable as code and
  # written down for people and agents, because a release failed on an out-of-date role and only a person running a command from chat fixed it.
  # Checked by the same test file.

  Scenario: One command sets up or updates the pipeline roles
    Given a person with administrator credentials for an AWS account
    When they run infra/pipeline/bootstrap.sh and name the account
    Then it refuses if the credentials belong to another account, before changing anything
    And it shows a change set and applies it only after the person types yes
    And it sets the AWS_ACCOUNT_ID repository variable and verifies the roles and the deployed template
    And running it again with nothing to change says so and touches nothing

  Scenario: An account with no GitHub OIDC provider gets one only when asked
    Given an account whose GitHub OIDC provider does not exist
    When the person runs the bootstrap without asking for the provider
    Then it stops and tells them to pass --create-oidc-provider
    And an account that already has a provider is never given a second one, and the default template change leaves it untouched

  Scenario: The first papyrus-monitoring on a new account has a bucket to upload to
    Given the papyrus-monitoring stack does not exist yet
    When the release deploys it
    Then the templates and zips go to the CDK bootstrap bucket named from the account and region
    And that bucket name is passed as the stack's CodeBucket, which later releases read back from the live stack

  Scenario: The release says when the deployed roles are older than the template
    Given the template in the repository differs from the deployed papyrus-stack-pipeline stack
    When a pull request dry run or a release deploy starts
    Then the job summary says the pipeline roles are out of date and names the bootstrap command
    And the release carries on, because this is a notice and not a failure
    And a deployed role that cannot read the pipeline stack yet gets the same notice

  Scenario: A permission refusal names the fix
    Given a deploy fails because the service role is not authorized to perform an action
    When the job summary is written
    Then it says roles are changed only by a person and names infra/pipeline/bootstrap.sh

  Scenario: The requirement is written down where people and agents look
    Given the top-level README, AGENTS.md, the pipeline README and the account-setup docs
    Then each names infra/pipeline/bootstrap.sh
    And the README, AGENTS.md and the pipeline README say it is required, that a person runs it, and that any change to the role template needs it again
    And AGENTS.md tells an agent never to run it unless told to, and what to say to ask for it

  Scenario: The role template cannot repeat a statement id
    Given the role template
    Then no policy in it has two statements with the same Sid
    And every AWS service a shared stack template creates resources in is granted to the service role

  Scenario: Only a merged template is applied
    Given the template in the checkout differs from origin/develop and from origin/main
    When a person runs the bootstrap to apply it
    Then it refuses before any AWS call and says to merge the change to develop first
    And there is no flag to override that
    But with --plan-only it warns and shows the change set, so a pull request can be previewed
    And a template equal to origin/develop or origin/main is applied, and the output says which it matched
