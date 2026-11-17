Feature: Resuming an agent in the agent policy
  An admin who lifts a pause expects the agent to run again. Resuming an agent the policy document does not name would change
  nothing and say nothing, so the person would believe it was done. It is refused instead, with the agent's name, and nothing is
  written. Resuming a paused agent clears the pause and the change is stored as a new version with its reason.

  Scenario: Resuming an agent the policy does not name is refused
    Given a site where "rate" is at "draft"
    When an admin tries to resume "ghost" because "Back on"
    Then the change is refused as invalid
    And the refusal says "ghost" is not named
    And the policy is still version 1

  Scenario: Resuming on a site that never saved a policy is refused as well
    Given a site that has never saved an agent policy
    When an admin tries to resume "rate" because "Back on"
    Then the change is refused as invalid
    And the refusal says "rate" is not named
    And the policy is still version 0

  Scenario: Resuming a paused agent clears the pause
    Given a site where "rate" is at "draft"
    And an admin paused "rate" because "Checking the rating rules"
    When an admin resumes "rate" because "Rules checked"
    Then the policy is version 3
    And a wake for "rate" starts at the rung "draft"
    And version 3 records the admin, a time and the reason "Rules checked"
