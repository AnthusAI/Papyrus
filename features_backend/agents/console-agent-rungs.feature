Feature: An admin sets an agent's rung in the newsroom, with no command line
  Raising an agent one step is a person's decision, and until now only `papyrus agents set-rung` made it, so a person needed the command line and the
  right credentials to let the rating agent write suggestions. The newsroom's Automation page shows every agent's rung and lets an admin change it. The
  console sends the request to the site's agent-policy function, behind the same checks as pause and resume: an admin whose token the console's own
  app client issued. The change runs the same checks as the command line: the rung is one the agent's definition uses, never above it, never
  publish_auto while its floor stands, and a reason is kept with the new version. The agents are the ones the deploy registered on the site.

  Background:
    Given a site whose agent policy holds "rate" at the rung "observe" and a budget of 5 dollars a week, changed only through the policy function
    And the site's registered agents are "announce" and "rate", and a retired "old-digest"

  Scenario: The board shows each registered agent's rung and the rungs a person may choose
    When ada, an admin signed in on the console's app client, opens the rung board
    Then the board lists the agents "announce" and "rate"
    And the board shows "rate" at the rung "observe", going no higher than "propose", with the choices "off, observe, propose"
    And the board shows "announce" at the rung "off"

  Scenario: An admin raises the rating agent to propose from the console, and the version records who and why
    When ada, an admin signed in on the console's app client, sets "rate" to "propose" on the rung board because "Let it write suggestions"
    Then the rung board change succeeded and saved version 2 with "rate" at the rung "propose"
    And version 2 of the agent policy records "ada@example.test", the time "2026-11-22T09:00:00Z" and the reason "Let it write suggestions"

  Scenario: A rung above what the agent's definition uses is refused, and nothing is saved
    When ada, an admin signed in on the console's app client, sets "rate" to "draft" on the rung board because "More"
    Then the rung board refused the change as "constraint_conflict", saying "Set it to propose or lower"
    And the agent policy is still version 1 with "rate" at the rung "observe"

  Scenario: A token from another app client cannot set a rung on the board
    When an agent holding an admin token from another app client sets "rate" to "propose" on the rung board because "Raise myself"
    Then the rung board refused the change as "human_required", saying "Only a person signed in to the console"
    And the agent policy is still version 1 with "rate" at the rung "observe"

  Scenario: A caller that says it is an agent is blocked, even on the console's client
    When an agent on the console's app client declares itself and sets "rate" to "propose" on the rung board because "Raise myself"
    Then the rung board refused the change as "blocked", saying "An agent never sets a rung here"
    And the agent policy is still version 1 with "rate" at the rung "observe"

  Scenario: A change without a reason is refused
    When ada, an admin signed in on the console's app client, sets "rate" to "propose" on the rung board because ""
    Then the rung board refused the change as "invalid_input", saying "needs a reason"
