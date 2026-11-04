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
