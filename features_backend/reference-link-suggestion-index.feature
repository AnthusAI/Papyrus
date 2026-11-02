@backend @reference-link-suggestion-index
Feature: Open link suggestions are served most likely first from one index, and a decided suggestion leaves it at once
  The Needs me queue shows the links the vector index suggests, and an editor works through them from the top, so the ones most likely to
  be right have to come first out of all of them, not out of whichever few were read last. Each suggestion therefore sits in its own sparse
  index while it is open: one shared partition value, "reference-links#suggested", and a sort value that is the close match the vector
  index recorded, so reading the index from the high end returns the most likely suggestion first and the cursor continues from there. A
  suggestion with no close match is given a sort value below every real similarity, so it still comes out of the index, last. Writing a
  suggestion puts the row in the index. An editor's accept or reject, or a link an editor writes over it, takes the row out again in the
  same write, so a decided suggestion never reappears in the queue. A later suggestion for the same pair never overwrites a decision and
  never puts the row back. A suggestion written before the index existed has neither field, so the operator backfill sets them: it
  writes only those two fields, writes nothing for a row that is already right, undoes no decision, and a second run changes nothing.
  Nothing here touches production: the backend is in memory.

  Background:
    Given the References "reference-a", "reference-b", "reference-c" and the concept "node-voice" for the suggestion index

  Scenario: Suggestions come out of the index most likely first and one with no close match comes last
    When the newsroom suggests three links with close matches 0.7, none and 0.9
    Then reading the suggestion index returns the close matches 0.9, 0.7 and none, in that order
    And every row in the index has the one shared partition value "reference-links#suggested"

  Scenario: Suggesting the same pair again moves it to its new place
    Given the newsroom suggested two links with close matches 0.5 and 0.6
    When the newsroom suggests the first pair again with a close match of 0.95
    Then reading the suggestion index returns the close matches 0.95 and 0.6, in that order

  Scenario: An editor's decision takes the suggestion out of the index in the same write
    Given the newsroom suggested a link with a close match of 0.8
    When an editor rejects it
    Then the suggestion index is empty
    And the decided link is rejected

  Scenario: Accepting takes the suggestion out of the index too
    Given the newsroom suggested a link with a close match of 0.8
    When an editor accepts it
    Then the suggestion index is empty
    And the decided link is current

  Scenario: A link an editor writes over a suggestion takes it out of the index
    Given the newsroom suggested a link with a close match of 0.8
    When an editor links the same two References as related
    Then the suggestion index is empty

  Scenario: A later suggestion never overwrites a decision or puts the row back
    Given the newsroom suggested a link with a close match of 0.8
    And an editor rejected it
    When the newsroom suggests the same pair again with a close match of 0.99
    Then the suggestion index is empty
    And the decided link is rejected and keeps its close match of 0.8

  Scenario: A link an editor makes from scratch was never a suggestion and is not in the index
    When an editor links "reference-a" and "reference-b" as related for the first time
    Then the suggestion index is empty

  Scenario: The backfill puts suggestions written before the index into it
    Given suggestions with close matches 0.8, none and 0.6 were written before the index existed, beside a rejected one and a link an editor made
    When the operator backfills the suggestion index
    Then reading the suggestion index returns the close matches 0.8, 0.6 and none, in that order
    And the rejected link and the editor's link are not in the index and nothing but the two index fields changed on any row

  Scenario: A dry run says what it would do and writes nothing
    Given suggestions with close matches 0.8, none and 0.6 were written before the index existed, beside a rejected one and a link an editor made
    When the operator previews the backfill of the suggestion index
    Then it reports 3 suggestions to key and writes 0
    And the suggestion index is empty

  Scenario: Running the backfill twice changes nothing the second time
    Given suggestions with close matches 0.8, none and 0.6 were written before the index existed, beside a rejected one and a link an editor made
    And the operator backfilled the suggestion index
    When the operator backfills the suggestion index
    Then it writes 0 rows

  Scenario: The backfill takes a stray key off a decided row and never undoes the decision
    Given suggestions with close matches 0.8, none and 0.6 were written before the index existed, beside a rejected one and a link an editor made
    And the rejected link carries a stray suggestion key
    When the operator backfills the suggestion index
    Then the rejected link has no key and is still rejected
