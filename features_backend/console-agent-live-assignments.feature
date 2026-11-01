@live-agent @agent-assignments
Feature: Live console agent Assignment behavior
  Live AppSync and LLM Assignment behavior specs for the Papyrus console responder.

  Background:
    Given live console agent tests are enabled

  Scenario: The console agent creates a research Assignment
    When I run the live console agent smoke scenario "create-research-assignment"
    Then the live console agent smoke result should include tool call "papyrus.Assignment.create"
    And the live console agent smoke result should include exactly 1 assignment
    And the live console agent response should match regex "^assignment[-_][A-Za-z0-9_-]+$"
    And the live console agent smoke result should include no structured errors
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can list prefixed Assignments
    When I run the live console agent smoke scenario "list-research-assignments"
    Then the live console agent smoke result should include tool call "papyrus.Assignment.create"
    And the live console agent smoke result should include tool call "papyrus.Assignment.list"
    And the live console agent smoke result should include tool calls in order "papyrus.Assignment.create" then "papyrus.Assignment.list"
    And the live console agent smoke result should include exactly 1 assignment
    And the live console agent response should match regex "^assignment[-_][A-Za-z0-9_-]+$"
    And the live console agent smoke result should include no structured errors
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can fetch Assignment info
    When I run the live console agent smoke scenario "get-research-assignment"
    Then the live console agent smoke result should include tool call "papyrus.Assignment.create"
    And the live console agent smoke result should include tool call "papyrus.Assignment.get"
    And the live console agent smoke result should include tool calls in order "papyrus.Assignment.create" then "papyrus.Assignment.get"
    And the live console agent smoke result should include exactly 1 assignment
    And the live console agent response should match regex "^assignment[-_][A-Za-z0-9_-]+$"
    And the live console agent smoke result should include no structured errors
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can update Assignment status
    When I run the live console agent smoke scenario "update-research-assignment"
    Then the live console agent smoke result should include tool call "papyrus.Assignment.update"
    And the live console agent smoke result should include exactly 1 assignment
    And the live console agent smoke result should include no structured errors
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent returns structured error shape for invalid Assignment input
    When I run the live console agent smoke scenario "invalid-assignment-input"
    Then the live console agent smoke result should include tool call "papyrus.Assignment.create"
    And the live console agent smoke result should include a structured error
    And the live console agent response should equal "invalid-input-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"
