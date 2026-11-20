Feature: The shared stacks start empty, inside the existing production account, with five isolation layers (PPY-daf673)
  The shared tier is the same Papyrus backend deployed once with tenancy mode "shared". It lives in the Papyrus
  production account next to every dedicated site and Prospectus, because no new AWS account is available (Ryan,
  2026-11-13). Two stacks exist, shared production and shared staging, and every release lands on staging first.
  Nothing here is created by hand: the stacks come from templates in Git, and only the release pipeline creates or
  changes them, through a change set it checks. The five layers keep the shared tier apart from the dedicated sites:
  distinct name prefixes and a pipeline-only deploy path, one customer-managed KMS key per stack, a permissions
  boundary on every shared role together with a deny on every dedicated role, reserved concurrency on every shared
  function, and alarms and a budget per stack. There is no sandbox account (D9), so every scenario here is a synth-level
  or template-level check; the first real create of the staging stack is the first live test.

  Scenario: The shared stack starts empty and serves no site
    Given a fresh shared stack
    When any host is requested
    Then the edge answers 404 and the API holds no tenant rows

  Scenario: The shared backend is the same artefact in tenancy mode shared
    Given the shared staging backend is synthesised
    Then every function carries the tenancy mode "shared"
    And the content-actions function bundles no site files
    And the backend configures no site host and no distribution alias

  Scenario: The first create fits CloudFormation's per-operation resource limit
    Given the shared staging backend is synthesised with the bootstrap stage on
    Then the root and nested templates together hold fewer than 2,500 resources
    And the models of the optional groups are left for the second deploy

  Scenario: Shared production and shared staging are separate stacks with prefixes that do not overlap
    Given the shared stack plans for production and staging
    Then the production names start with "papyrus-shared-prod"
    And the staging names start with "papyrus-shared-staging"
    And no production name is a prefix of a staging name or the other way round
    And no dedicated site id can take a shared deployment tag value

  Scenario: Only the release pipeline creates the shared stacks
    Given the pipeline's stack list and its roles
    Then both shared foundation stacks are listed in the "shared" group with their own deploy role and service role
    And a pull request that touches a shared template prints a read-only dry run
    And the shared deploy role may create change sets only on stacks that start with "papyrus-shared-"
    And the existing per-site and monitoring deploy roles name no shared stack

  Scenario: Each shared stack has its own customer-managed key
    Given the shared foundation template
    Then it creates one key with rotation on and the longest deletion window, retained when the stack is deleted
    And its key policy allows use only to roles on the stack's own role path and the platform operator role
    And its key policy allows administration only to the pipeline's shared CloudFormation role
    And no statement of the key policy trusts the account root

  Scenario: The key encrypts what the backend lets it encrypt
    Given the shared staging backend is synthesised
    Then every Amplify data table, every other DynamoDB table, every S3 bucket, every queue and every function log group is encrypted with the shared key
    And no resource of the backend names a key other than the shared one
    And the backend names exactly which resources could not take the key

  Scenario: Every shared role carries the permissions boundary and the stack's role path
    Given the shared staging backend is synthesised
    Then every role has the staging boundary policy and a path that starts with "/papyrus-shared-staging/"
    And the boundary allows actions only on resources tagged with the staging deployment or named with the staging prefix
    And the few actions with no resource-level permission are listed one by one in the boundary

  Scenario: Dedicated sites change only by the added deny
    Given the dedicated backend is synthesised with and without the shared-stack deny
    Then the only difference is one inline policy named "papyrus-deny-shared-stack" on each role outside the per-model data stacks
    And the policy denies every action on resources tagged with a shared deployment or named with the shared prefix
    And no resource is added to or removed from any template

  Scenario: The app shell's roles carry the same deny and nothing else changes
    Given a dedicated site's app shell is synthesised with and without the shared-stack deny
    Then the only difference is the inline policy on each role
    And the deny is identical to the one the site backend adds

  Scenario: Reserved concurrency comes from configuration
    Given the shared staging backend is synthesised
    Then every function of the stack has reserved concurrency taken from the settings file
    And the reserved total does not pass the tier's limit in the settings file

  Scenario: Shared production refuses to synthesise before its concurrency is measured
    Given the settings file has no measured reserved concurrency for production
    When the shared production backend is synthesised
    Then synthesis fails naming the production reserved concurrency and the staging traffic it must come from

  Scenario: Each shared stack has its own alarms
    Given the shared staging backend is synthesised
    Then it has alarms on function errors, function throttles and function concurrency against the reserved share
    And it has alarms on AppSync errors, DynamoDB throttles and the projection dead-letter queue
    And the edge purge-count alarm is created as soon as the stack has a distribution
    And every alarm name starts with the staging prefix

  Scenario: Each shared stack has a budget filtered on its cost tags
    Given the shared foundation template
    Then it creates one monthly budget filtered on the tag "anthus:deployment" with the stack's own deployment value
    And the budget alerts the operator's alarm mailbox read from SSM, never an address in Git
