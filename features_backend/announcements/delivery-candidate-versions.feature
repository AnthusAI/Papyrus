Feature: A Delivery may hold several candidate texts or pictures, one chosen and the others kept
  Beside the draft a person or the machine may keep another text or another picture. A candidate changes nothing that goes out: it is a file in S3 and a line on the
  Delivery, so it can be added even after the lock. Choosing one is a save like any other, a new version that names the version it replaces, and the candidates that were
  not chosen are kept. This is also what makes a later comparison of two wordings possible.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text                   |
      | x       | handle-1 | soft     | Slow water is on shelves. |

  Scenario: A text kept as a candidate changes no version
    When "the machine" keeps the text "Slow water: the harbour reads it first." beside the Delivery "x" "handle-1" as a candidate
    Then the Delivery "x" "handle-1" is at version 1
    And the Delivery "x" "handle-1" holds candidate "c1" in the state "open"
    And candidate "c1" of the Delivery "x" "handle-1" has the words "Slow water: the harbour reads it first." in S3
    And the Delivery "x" "handle-1" keeps 1 versions, each its own file in S3

  Scenario: Choosing one candidate saves a new version and the others are kept
    Given "the machine" keeps the text "Slow water: the harbour reads it first." beside the Delivery "x" "handle-1" as a candidate
    And "ellie" keeps the text "Slow water has landed." beside the Delivery "x" "handle-1" as a candidate
    When the person "ellie" chooses candidate "c2" of the Delivery "x" "handle-1" from version 1
    Then the Delivery "x" "handle-1" is at version 2
    And version 2 of the Delivery "x" "handle-1" has the words "Slow water has landed."
    And version 2 of the Delivery "x" "handle-1" was chosen from candidate "c2"
    And version 2 of the Delivery "x" "handle-1" was saved by "ellie" as human and replaced version 1
    And the Delivery "x" "handle-1" holds candidate "c2" in the state "chosen"
    And the Delivery "x" "handle-1" holds candidate "c1" in the state "kept"
    And candidate "c1" of the Delivery "x" "handle-1" has the words "Slow water: the harbour reads it first." in S3
    And version 1 of the Delivery "x" "handle-1" has the words "Slow water is on shelves."

  Scenario: A different choice later keeps the earlier choice too
    Given "the machine" keeps the text "Slow water: the harbour reads it first." beside the Delivery "x" "handle-1" as a candidate
    And "ellie" keeps the text "Slow water has landed." beside the Delivery "x" "handle-1" as a candidate
    And the person "ellie" chooses candidate "c2" of the Delivery "x" "handle-1" from version 1
    When the person "ellie" chooses candidate "c1" of the Delivery "x" "handle-1" from version 2
    Then version 3 of the Delivery "x" "handle-1" has the words "Slow water: the harbour reads it first."
    And the Delivery "x" "handle-1" holds candidate "c1" in the state "chosen"
    And the Delivery "x" "handle-1" holds candidate "c2" in the state "kept"
    And version 2 of the Delivery "x" "handle-1" has the words "Slow water has landed."

  Scenario: A picture can be a candidate and the chosen one goes out with the words
    Given "ellie" keeps the picture "newsroom/images/harbour.png" beside the Delivery "x" "handle-1" as a candidate
    And "ellie" keeps the picture "newsroom/images/shelves.png" beside the Delivery "x" "handle-1" as a candidate
    When the person "ellie" chooses candidate "c2" of the Delivery "x" "handle-1" from version 1
    Then candidate "c1" of the Delivery "x" "handle-1" has the picture "newsroom/images/harbour.png"
    And version 2 of the Delivery "x" "handle-1" has the words "Slow water is on shelves."
    And the Delivery "x" "handle-1" goes out with the picture "newsroom/images/shelves.png"
    And the Delivery "x" "handle-1" holds candidate "c1" in the state "kept"

  Scenario: Choosing a candidate names the version it replaces, like any save
    Given "the machine" keeps the text "Another wording." beside the Delivery "x" "handle-1" as a candidate
    And the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "Sierra got there first."
    When the person "ellie" chooses candidate "c1" of the Delivery "x" "handle-1" from version 1
    Then the Delivery save is refused as stale
    And the refusal names version 2 saved by "sierra" as the one that replaced version 1
    And the Delivery "x" "handle-1" holds candidate "c1" in the state "open"

  Scenario: Candidates are never in the catalog row as words
    Given "the machine" keeps the text "Candidate words nobody should find in the row." beside the Delivery "x" "handle-1" as a candidate
    Then the Delivery row "x" "handle-1" contains none of "Candidate words nobody" anywhere

  Scenario: A candidate that is not there is not found
    When the person "ellie" chooses candidate "c7" of the Delivery "x" "handle-1" from version 1
    Then the call is refused saying "has no candidate c7"

  Scenario: A candidate of nothing is refused
    When "ellie" keeps the text "   " beside the Delivery "x" "handle-1" as a candidate
    Then the call is refused saying "A candidate is a text or a picture"

  Scenario: A machine's choice keeps the blocks a person pinned
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Ellie's own line."
    And "the machine" keeps the text "A machine line." beside the Delivery "x" "handle-1" as a candidate
    When the machine chooses candidate "c1" of the Delivery "x" "handle-1" from version 2
    Then version 3 of the Delivery "x" "handle-1" has the words "Ellie's own line."

  Scenario: A candidate can be added after the lock, because it changes nothing that goes out
    Given the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:00:00Z"
    When "the machine" keeps the text "A wording for the next time." beside the Delivery "x" "handle-1" as a candidate
    Then the call went through
    And the Delivery "x" "handle-1" holds candidate "c1" in the state "open"
    And the Delivery "x" "handle-1" still sends version 1
    When the person "ellie" chooses candidate "c1" of the Delivery "x" "handle-1" from version 1
    Then the call is refused saying "locked"
