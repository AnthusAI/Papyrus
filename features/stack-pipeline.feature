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

  # The pipeline roles are changed by an approval-gated workflow (PPY-9d1b3e). Ryan, 2026-11-05: a role the deployment needs must be code,
  # written down for people and agents, and he will not deploy a stack by hand: he approves in GitHub. Checked by the same test file.

  Scenario: A merged role change is planned without anyone asking for it
    Given a change to infra/pipeline/papyrus-stack-pipeline.yaml is merged to develop or main
    When the role-stack-deploy workflow runs
    Then its plan job creates a change set and prints every change, with an IAM view of the statements added and removed, in the job summary
    And it stops on anything failed
    And a plan with nothing to change ends quietly and no approval is requested

  Scenario: Only a reviewer's approval applies the change
    Given a plan with changes
    When the apply job starts in the protected pipeline-roles environment
    Then it waits for the required reviewer to approve
    And it runs as a role that trusts exactly that environment's OIDC subject with the audience checked
    And it refuses to execute if the template or the stack changed since the plan, or the change set is not the one planned
    And it executes that change set by name, polls it, and verifies the deployed template equals the repository

  Scenario: A failed apply says what failed and leaves the stack clean
    Given an approved apply that fails
    Then the summary names the first failed resource
    And an update is rolled back by CloudFormation
    And a first create that rolled back is deleted so the next run starts fresh

  Scenario: The approval roles cannot raise their own permissions
    Given the separate approver stack
    Then no policy in it can change the approver stack or its roles
    And its service role can write only the three pipeline roles and the stack's own managed policies
    And it cannot create any other role or attach an AWS-managed policy
    And the apply role has no IAM rights at all

  Scenario: The one-time setup for a new account is a person's step, written down
    Given a new AWS account
    When a person runs bootstrap.sh with --approver-only and then create-environment.sh with a reviewer
    Then the approver stack, the repository variable and the GitHub environment exist
    And the GitHub OIDC provider is created only when asked, and never a second one
    And the reviewer is a parameter, so no login is committed

  Scenario: Only a merged template is applied by hand
    Given the template in the checkout differs from origin/develop and from origin/main
    When a person runs the bootstrap to apply it
    Then it refuses before any AWS call and says to merge the change to develop first
    And there is no flag to override that
    But with --plan-only it warns and shows the change set, so a pull request can be previewed

  Scenario: The release says when the deployed roles are older than the template
    Given the template in the repository differs from the deployed papyrus-stack-pipeline stack
    When a pull request dry run or a release deploy starts
    Then the job summary says the pipeline roles are out of date and links the role-stack-deploy workflow
    And the release carries on, because this is a notice and not a failure
    And a deployed role that cannot read the pipeline stack yet gets the same notice

  Scenario: A permission refusal names the fix
    Given a deploy fails because the service role is not authorized to perform an action
    When the job summary is written
    Then it says roles change only through the role-stack-deploy workflow after a person approves, and links it

  Scenario: The first papyrus-monitoring on a new account has a bucket to upload to
    Given the papyrus-monitoring stack does not exist yet
    When the release deploys it
    Then the templates and zips go to the CDK bootstrap bucket named from the account and region
    And that bucket name is passed as the stack's CodeBucket, which later releases read back from the live stack

  Scenario: The requirement is written down where people and agents look
    Given the top-level README, AGENTS.md, the pipeline README and the account-setup docs
    Then each names the role-stack-deploy workflow and the one-time setup command
    And AGENTS.md tells an agent to link the reviewer to the approval and never to approve, apply by hand or work around a refusal

  Scenario: The role templates cannot repeat a statement id
    Given the pipeline and approver templates
    Then no policy in either has two statements with the same Sid
    And every AWS service a shared stack template creates resources in is granted to the service role

  Scenario: No managed policy in a shared stack can reach IAM's size limit unnoticed
    Given the first full deploy of papyrus-monitoring failed because RouterIdeaPolicy was over IAM's 6,144-character limit and the stack rolled back
    When the tests compute the size of every managed policy in both stack templates and in the pipeline roles
    Then each substitution is counted at its longest, a policy at ninety percent of the limit fails the pull request, and so does a role whose inline policies approach their own limit
    And the vector pass's statements sit in RouterEnrichmentStoragePolicy, a policy attached to the same role, so the router's access is the same and no new managed policy is attached

  Scenario: The service role can make every call CloudFormation makes, including while it rolls back
    Given the service role lacked lambda:GetEventSourceMapping and lambda:DeleteEventSourceMapping, which Lambda checks against resource "*" when a cancelled create has no mapping id yet
    When the tests list, for each resource type the two templates use, the calls its create, update and delete handlers make
    Then the service role is allowed every one of them, and a custom resource's function can be started by the role
    And creating a mapping stays tied to this account's own functions, and only Get and Delete are allowed on resource "*"

  Scenario: A failed first create does not leave a table that blocks the next one
    Given OperatorTable keeps its data when the stack is deleted
    When the create that makes it rolls back
    Then the empty table is deleted with the rollback, because its deletion policy retains it except on create
    And a later create is not refused by the early existence check

  Scenario: A refused change set names the resource that refused it
    Given a change set fails early validation, for example because a table with a fixed name already exists outside the stack
    When the release reads the change set's events before deleting the change set
    Then the job summary and the error annotation name the resource, the check and the reason
    And say that a person deletes an empty leftover or imports one that holds data, because the pipeline never deletes data
    And if the events cannot be read the original reason is still shown

  Scenario: A change set with no changes asks nobody for approval
    Given the pipeline role template differs from the deployed text only in a comment or a blank line
    When role-stack-deploy plans it
    Then CloudFormation reports a change set with no changes, which is not the "no changes" failure
    And the plan deletes it, says nothing needs approval, and the apply job does not start

  Scenario: The dead-man alarm stays quiet until the first heartbeat could have arrived
    Given the dead-man alarm treats missing data as breaching, which fired it and emailed the moment it was first created
    When the stack is created, a custom resource writes one HeartbeatDelivered datapoint before the alarm exists
    Then the alarm does not fire during its first thirty to forty-five minutes
    And if heartbeats never start, the datapoint ages out of the three-period window and the alarm fires, which is the check working
