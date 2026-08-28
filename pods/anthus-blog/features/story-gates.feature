Feature: Gate newsroom story transitions
  As a newsroom operator
  I want each transition to explain and enforce its editorial prerequisite
  So that agents learn the process and cannot silently skip required work

  Scenario: Coach before a transition is attempted
    Given a story is in the idea stage
    And the idea artifact is not ready for assignment
    When an agent inspects the story through Kanbus
    Then Kanbus emits guidance naming the missing work
    And the guidance explains why the work belongs before the next stage

  Scenario: Refuse an incomplete transition
    Given a story is in the idea stage
    And the idea artifact is missing or empty
    When the agent requests advancement to assignment through Kanbus
    Then the transition fails closed
    And the story remains in the idea stage
    And the response identifies a concrete recovery action

  Scenario: Refuse skip-ahead transitions
    Given a story is in the idea stage
    When the agent requests advancement to copywriting through Kanbus
    Then the transition fails closed
    And the story remains in the idea stage
    And the response explains the required stage ladder

  Scenario: Allow a complete transition
    Given a story is in the idea stage
    And the idea artifact is complete
    When the agent requests advancement to assignment through Kanbus
    Then the transition succeeds
    And the story is in the assignment stage
