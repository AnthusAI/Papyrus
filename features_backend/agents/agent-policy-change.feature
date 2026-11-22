Feature: Only a person signed in to the console changes the agent policy
  The agent policy says how far each always-on agent may go and how much paid agent work may spend. A rung or a budget is a person's decision, never
  an agent's, and an agent working in a person's session holds that person's credentials. So a signed-in admin does not write the policy with their own
  credentials: every change, a rung, a pause, a loop limit or the budget, goes to the site's agent-policy function. The function checks that the token
  belongs to an admin and was issued to a person-only app client (the console's), and only then saves the version with its own role, recording who,
  when and why. A token issued to any other client is refused and nothing is saved, whichever command sent it. The admin group may read the policy
  objects but not write them, so the function is the only way in. Releasing the wakes that wait for the budget still needs the operator's
  credentials for the site's wake queue, as before.

  Background:
    Given a site whose agent policy holds "rate" at the rung "propose" and a budget of 5 dollars a week, changed only through the policy function

  Scenario: A person on the console's client raises a rung, and the version records who and when
    When ada, an admin signed in on the console's app client, sets "rate" to the rung "observe" because "Watch it for a week"
    Then the policy function saved version 2 with "rate" at the rung "observe"
    And version 2 of the agent policy records "ada@example.test", the time "2026-11-22T09:00:00Z" and the reason "Watch it for a week"

  Scenario: A credential issued to another app client cannot change a rung
    When an agent holding an admin token from another app client sets "rate" to the rung "observe" because "Raise myself"
    Then the policy function refused the change as "human_required"
    And the agent policy is still version 1 with "rate" at the rung "propose"

  Scenario: A person on the console's client raises the budget with set-budget, and the version records who and when
    When ada, an admin signed in on the console's app client, runs set-budget for 20 dollars a week because "Launch week" and applies it
    Then the budget command succeeded and saved version 2
    And the agent policy holds a budget of 20 dollars a week at version 2
    And version 2 of the agent policy records "ada@example.test", the time "2026-11-22T09:00:00Z" and the reason "Launch week"

  Scenario: A credential issued to another app client cannot change the budget
    When an agent holding an admin token from another app client runs set-budget for 500 dollars a week because "More room" and applies it
    Then the budget command was refused as "human_required"
    And the agent policy holds a budget of 5 dollars a week at version 1

  Scenario: The signed-in commands write nothing to the policy objects themselves
    When ada, an admin signed in on the console's app client, runs set-budget for 20 dollars a week because "Launch week" and applies it
    Then the signed-in command's own credentials wrote no policy object and no catalogue row
    And every policy object was written by the policy function

  Scenario: With no person-only client configured, nobody changes the policy
    Given the site's stack names no person-only app client
    When ada, an admin signed in on the console's app client, sets "rate" to the rung "observe" because "Watch it for a week"
    Then the policy function refused the change as "human_required"
    And the agent policy is still version 1 with "rate" at the rung "propose"
