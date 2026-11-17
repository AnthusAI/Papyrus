@brand-agnostic
Feature: A brand-new site can create its backend in two deploys
  CloudFormation creates at most 2,500 resources in one stack operation,
  nested stacks included, and the full Papyrus backend is more than that. Sites
  that already exist reached their size one release at a time, but a new site
  creates everything at once and the first deploy rolls back. Setting the
  branch variable PAPYRUS_BOOTSTRAP_STAGE to 1 makes the first deploy leave out
  the models that nothing else depends on. The second deploy, with the
  variable removed, is an ordinary update that adds them. Without the variable
  nothing changes, because every release reaches every live site.

  Scenario: The variable is off unless it is exactly 1
    Given the branch variable PAPYRUS_BOOTSTRAP_STAGE is not set
    Then no model groups are left out of the data API
    And a site that configures the editions group still leaves out only editions

  Scenario: Setting the variable defers every optional model group
    Given the branch variable PAPYRUS_BOOTSTRAP_STAGE is "1"
    Then every optional model group is left out of the data API
    And the models the newsroom needs to start are still created

  Scenario: The first deploy of a new site fits in one CloudFormation operation
    Given the site backend is synthesized in the bootstrap stage
    Then the whole backend has fewer than 2000 resources
    And no deferred model has a stack
    And the first deploy creates no post-deploy render, because the render reads models the second deploy adds

  Scenario: The first deploy leaves out the agents stack
    Given the site backend is synthesized in the bootstrap stage
    Then it has no agents stack
    And the first-stage resource count does not include any agent resource

  Scenario: The second deploy adds the agents stack as an ordinary update
    Given an agent piece exists
    When the backend is synthesized without the bootstrap variable
    Then it has one stack named agents holding the piece
    And that stack is not created when the variable is 1
    And a site with no agent piece has no agents stack, because CloudFormation accepts no empty stack

  Scenario: Every agent piece's resource count is printed before it merges
    Given the agent pieces of the site backend
    When the agents stack is priced
    Then each piece's resource count is printed
    And the total is printed against the first-deploy headroom
    And two pieces with the same id are refused
