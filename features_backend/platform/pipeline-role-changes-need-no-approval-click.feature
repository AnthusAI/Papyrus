Feature: A change to the deploy roles is checked by machine instead of waiting for someone to click approve
  The IAM roles that release deploys run as can be changed only by merging a change to their template. No person is asked to approve it. An
  automatic check runs on the pull request and again against the live roles before anything is applied: it refuses a change that would make a
  role administrator-sized or trust everyone, and it refuses any changed permission that the change did not also list by fingerprint. A refused
  change applies nothing and says exactly what to fix.

  Scenario: A permission that nobody listed is refused with the fingerprint to list
    Given the deploy roles template with one extra permission on the deploy role
    And an empty list of allowed role changes
    When the automatic check runs on the pull request
    Then the automatic check fails
    And the output names the extra permission and its fingerprint

  Scenario: Listing the fingerprint in the same change lets it through
    Given the deploy roles template with one extra permission on the deploy role
    And the extra permission listed by its fingerprint
    When the automatic check runs on the pull request
    Then the automatic check passes

  Scenario: An administrator-sized policy is refused even when its fingerprint is listed
    Given the deploy roles template with the AdministratorAccess policy attached to the deploy role
    And every changed statement listed by its fingerprint
    When the automatic check runs on the pull request
    Then the automatic check fails
    And the output says a hard rule is broken

  Scenario: The deploy roles in the repository break no hard rule
    Given the deploy roles template in the repository
    When the hard rules are read
    Then no rule is broken

  Scenario: The apply job waits for no reviewer
    Given the role deploy workflow
    When its apply job is read
    Then the apply job needs the plan job
    And the workflow says no person approves a change
