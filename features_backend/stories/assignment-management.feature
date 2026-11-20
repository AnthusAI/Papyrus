@backend @assignments
Feature: Assignment Management REST Semantics
  As a newsroom operator
  I need deterministic Assignment resource behavior
  So create/list/get/update/filter flows stay stable.

  Scenario: Create and fetch a research assignment
    Given an empty assignment resource
    When I create a research assignment titled "CV research last 90 days"
    Then the assignment is created with status "open"
    And fetching the assignment by id returns the same title

  Scenario: List assignments with filters and pagination
    Given an empty assignment resource
    And the assignment resource has seeded assignments
    When I list assignments with status "open"
    Then I receive only assignments with status "open"
    When I list assignments with type "research" and limit 2 offset 1
    Then I receive 2 assignments in deterministic order

  Scenario: Update assignment status and validate error shape
    Given an empty assignment resource
    And the assignment resource has seeded assignments
    When I update assignment "assignment-001" status to "claimed"
    Then assignment "assignment-001" has status "claimed"
    When I update assignment "missing-assignment" status to "claimed"
    Then I receive an error with code "not_found"
