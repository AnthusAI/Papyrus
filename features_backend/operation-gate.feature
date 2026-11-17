Feature: One gate answers every call an agent makes
  Each operation in the one operation table, the table behind the command line, the tool server and the newsroom, names the lowest rung of the
  site's agent policy at which an agent may call it. One gate on the server receives the operation, the agent and its run, reads the site's policy
  once, and answers one of three words. Allowed means it happens. Blocked means no agent may do it at any rung: it changes policy, budget or
  accounts, or the agent is off or paused, or the operation is unknown. Human required means a person must do it or approve it: the agent's rung
  is lower than the operation needs. When a call gets human required the call does not happen, the engine raises one review request for the run,
  and the run ends as asked. Raising the rung in the site's policy document allows the very same call with no change to any code. A person's own
  action is never limited by an agent's rung. Every answer the gate gives is written on the run record, with the version of the policy it was
  given under.

  Scenario: The same call is refused at a low rung and allowed at a higher one
    Given a site where "illustrate" is at "propose"
    And an agent run of "illustrate"
    When the agent calls "image_apply"
    Then the gate answers "human_required"
    And the write did not happen
    When an admin raises "illustrate" to "draft" because "The pictures have earned it"
    And an agent run of "illustrate"
    And the agent calls "image_apply"
    Then the gate answers "allowed"
    And the write happened once

  Scenario: A read is allowed from observe
    Given a site where "illustrate" is at "observe"
    And an agent run of "illustrate"
    When the agent calls "image_search"
    Then the gate answers "allowed"

  Scenario Outline: A blocked operation is blocked at every rung
    Given a site where "illustrate" is at "<rung>"
    And an agent run of "illustrate"
    When the agent calls "announcements_settings_set"
    Then the gate answers "blocked"
    And the write did not happen

    Examples:
      | rung         |
      | observe      |
      | propose      |
      | draft        |
      | prepare      |
      | publish_soft |
      | publish_auto |

  Scenario: A person-only operation is human required at the top rung
    Given a site where "illustrate" is at "publish_auto"
    And an agent run of "illustrate"
    When the agent calls "image_review"
    Then the gate answers "human_required"
    And the write did not happen

  Scenario: An agent that is off or paused is blocked
    Given a site where "illustrate" is at "off"
    And an agent run of "illustrate"
    When the agent calls "image_search"
    Then the gate answers "blocked"
    And the gate says "illustrate is off"

  Scenario: A narrower override decides the rung of a call
    Given a site where "illustrate" is at "draft"
    And the section "opinion" narrows "illustrate" to "propose"
    And an agent run of "illustrate"
    When for the section "opinion" the agent calls "image_apply"
    Then the gate answers "human_required"
    When for the section "news" the agent calls "image_apply"
    Then the gate answers "allowed"

  Scenario: A call the table does not know is blocked
    Given a site where "illustrate" is at "publish_auto"
    And an agent run of "illustrate"
    When the agent asks the gate about "image_teleport"
    Then the gate answers "blocked"

  Scenario: Human required raises one review request and ends the run as asked
    Given a site where "illustrate" is at "propose"
    And an agent run of "illustrate"
    When the agent calls "image_apply"
    And the agent calls "image_discard"
    Then the run raises 1 review request naming "image_apply" and "image_discard"
    And the run ends as "asked" with the reason "human_required"

  Scenario: A run that was only allowed raises no review request
    Given a site where "illustrate" is at "draft"
    And an agent run of "illustrate"
    When the agent calls "image_apply"
    Then the run raises 0 review requests
    And the run declares no outcome of its own

  Scenario: A person's action is not gated
    Given a site where "illustrate" is at "off"
    When a person calls "image_apply"
    Then the gate answers "allowed"
    And the write happened once

  Scenario: Every gate answer is on the run record with the policy version
    Given a site where "illustrate" is at "propose"
    And an agent run of "illustrate"
    When the agent calls "image_search"
    And the agent calls "image_apply"
    Then the run record names policy version 1 and holds 2 answers in order
    And answer 1 is "allowed" for "image_search" and answer 2 is "human_required" for "image_apply" at the rung "propose" needing "draft"

  Scenario: Every operation names its rung in the table
    Then every operation in the table names the lowest rung an agent may call it at, or says only a person may
