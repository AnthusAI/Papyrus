@checklist-gate
Feature: A publish refused by the checklist says so in a way a script can read
  A story publishes only when every required checklist step is closed. When one
  is open the publish is refused, and a script that publishes many stories must
  be able to tell that apart from every other outcome: the command exits with its
  own non-zero code, and its machine-readable result lists the open steps by key
  and label. Which steps are required is the owner's policy and is not changed
  here.

  Scenario: The machine-readable result lists the open steps
    Given a story whose review steps are open
    When the operator runs the publish command asking for a machine-readable result
    Then the command exits with code 3
    And the result names the code "checklist-open"
    And the result lists the open step "review_people" labelled "Reviewed for readers"
    And no published record exists for the story

  Scenario: The text result lists the open steps too
    Given a story whose review steps are open
    When the operator runs the publish command
    Then the command exits with code 3
    And the output lists the open step "review_people"

  Scenario: Another refusal keeps its own code
    Given a story that does not exist
    When the operator runs the publish command asking for a machine-readable result
    Then the command exits with code 1
    And the result names the code "not-found"
