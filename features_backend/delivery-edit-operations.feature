Feature: Editing a Delivery is one set of operations that the newsroom, the command line and an agent all call the same way
  Reading the versions, saving the words, keeping and choosing candidates, changing a pinned block and unlocking are rows of the one operation table, so the newsroom and the
  command line get them from the same place and one gate decides what an agent may do. A person's save is the person's and is pinned; an agent's is a redraft that keeps what a
  person pinned and is dropped, not refused, when the person's version is newer. A save names the version it replaces, so a stale one is refused with the version that replaced it
  in the answer, ready for the caller to read again.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |

  Scenario: A person reads the versions and then saves the next one
    When the person "ellie" asks the door for the versions of the Delivery "x" "handle-1"
    Then the door answers "allowed"
    And the door's listing shows 1 versions and 0 candidates
    And the door's listing carries no words and no S3 keys
    When the person "ellie" asks the door to save the words "Slow water has landed." over version 1 of the Delivery "x" "handle-1"
    Then the door says the Delivery was saved
    When the person "ellie" asks the door for version 2 of the Delivery "x" "handle-1"
    Then the door gives the words "Slow water has landed."

  Scenario: A stale save through the door says which version replaced the one that was read
    Given the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "Sierra's words."
    When the person "ellie" asks the door to save the words "Ellie's words." over version 1 of the Delivery "x" "handle-1"
    Then the door answers "stale_version"
    And the door names version 2 as the one that replaced the version read
    And the Delivery "x" "handle-1" is at version 2

  Scenario: An agent's redraft that the person's newer version outranks is dropped, not refused
    Given the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "Sierra's words."
    And an announce agent working at the rung "draft" on the channel "x" for the kind "story_published"
    And the writes so far are remembered
    When the announce agent asks the door to save the words "A machine redraft." over version 1 of the Delivery "x" "handle-1"
    Then the door says the Delivery was dropped
    And nothing more was written
    And version 2 of the Delivery "x" "handle-1" has the words "Sierra's words."

  Scenario: An agent below the draft rung is told a person must do it
    Given an announce agent working at the rung "propose" on the channel "x" for the kind "story_published"
    And the writes so far are remembered
    When the announce agent asks the door to save the words "A machine redraft." over version 1 of the Delivery "x" "handle-1"
    Then the door answers "human_required"
    And nothing more was written

  Scenario: A save has to name the version it replaces
    When the person "ellie" asks the door to save the words without naming a version for the Delivery "x" "handle-1"
    Then the door answers "invalid_input"
    And the Delivery "x" "handle-1" is at version 1

  Scenario: An edit while an attempt is open is a preferred version, through the door too
    Given the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:20:00Z"
    And an attempt is open on the Delivery "x" "handle-1"
    When the person "ellie" asks the door to save the words "How it should have read." over version 1 of the Delivery "x" "handle-1"
    Then the door says the Delivery was preferred
    And the Delivery "x" "handle-1" has the preferred version 2
    And the Delivery "x" "handle-1" still sends version 1

  Scenario: A late edit through the door is refused as locked
    Given the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    When the person "ellie" asks the door to save the words "Too late." over version 1 of the Delivery "x" "handle-1"
    Then the door answers "locked"
    And the Delivery "x" "handle-1" is at version 1

  Scenario: Keeping and choosing a candidate through the door
    When the person "ellie" asks the door to keep the text "Another wording." for the Delivery "x" "handle-1"
    Then the door says the Delivery was candidate
    And the door's listing of candidates shows "c1" kept open
    When the person "ellie" asks the door to choose candidate "c1" over version 1 of the Delivery "x" "handle-1"
    Then the door says the Delivery was saved
    And version 2 of the Delivery "x" "handle-1" has the words "Another wording."
    And version 2 of the Delivery "x" "handle-1" was chosen from candidate "c1"

  Scenario: A Delivery that is not there is not found
    When the person "ellie" asks the door for the versions of a Delivery that is not there
    Then the door answers "not_found"
