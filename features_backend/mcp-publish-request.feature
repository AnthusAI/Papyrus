Feature: Request human approval to publish a Story
  An agent can ask for a person's decision without publishing or approving its own work.

  Scenario: A current draft needs a person's approval
    Given a site requires human publication approval
    When an agent requests publication of its current draft
    Then the version-bound review is opened or reused and the Story stays unpublished

  Scenario: A changed draft cannot receive an outdated request
    Given a site requires human publication approval
    When the Story changes before the request is recorded
    Then the request is refused and nothing is published

  Scenario: Approval is never publication
    Given a site requires human publication approval
    When a person approves the version
    Then the agent is directed to the staff console and nothing is published

  Scenario: A site without a gate hands publishing to staff
    Given a site does not require publication approval
    When an agent requests publication of its current draft
    Then it receives a staff console handoff and no record is written

  Scenario: An agent cannot satisfy the person's gate
    Given a site requires human publication approval
    When an agent answers a previous approval request
    Then another person must still approve the version

  Scenario: A Story failing publish preflight is not sent for approval
    Given a site requires human publication approval
    When the current draft cannot be published at its placeholder address
    Then no approval request is created

  Scenario: Bootstrap sites can omit the review models
    Given a site excludes its review and editorial model groups
    When the site configures Story publication requests
    Then it omits the operation from discovery and direct requests fail closed
