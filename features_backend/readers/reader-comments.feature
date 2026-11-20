Feature: Public comments as a steering signal
  A signed-in reader with a handle comments on a published item. Comments are plain text, threaded one level deep, editable
  for ten minutes and deleted into a stub. A comment written when rating can carry the rating it explains, and that text
  rationale is exported next to the vote for the Cyclotron loop. Everything public goes through the snapshot.

  Background:
    Given a publication whose readers rate "real" and "useful"
    And the published items "item-one" and "item-two"
    And the signed-in readers "alice" and "bob"

  Scenario: A comment is public after the next snapshot, with the reader's handle and a count
    When "alice" picks the handle "quiet-fox"
    And "alice" comments "Worth reading." on "item-one"
    Then "alice" is answered with status 201
    When the snapshot runs
    Then the comment file of "item-one" lists "Worth reading." by "quiet-fox"
    And the public file "_data/reader/items.json" shows 1 comment on "item-one"

  Scenario: Replies go one level deep
    When "alice" picks the handle "quiet-fox"
    And "bob" picks the handle "loud-owl"
    And "alice" comments "Top level." on "item-one"
    And "bob" replies "Agreed." to the last comment of "alice"
    Then "bob" is answered with status 201
    When "alice" replies "Thanks." to the last comment of "bob"
    Then "alice" is answered with status 422 "invalid_parent"
    When the snapshot runs
    Then the comment file of "item-one" nests "Agreed." under "Top level."

  Scenario: The author can edit for ten minutes
    When "alice" picks the handle "quiet-fox"
    And "alice" comments "First draft." on "item-one"
    And 9 minutes pass
    And "alice" edits the last comment to "Second draft."
    Then "alice" is answered with status 200
    When 2 minutes pass
    And "alice" edits the last comment to "Too late."
    Then "alice" is answered with status 403 "edit_window_closed"
    When the snapshot runs
    Then the comment file of "item-one" lists "Second draft." by "quiet-fox"
    And the comment file of "item-one" marks "Second draft." as edited

  Scenario: Deleting leaves a stub only while there are replies
    When "alice" picks the handle "quiet-fox"
    And "bob" picks the handle "loud-owl"
    And "alice" comments "Top level." on "item-one"
    And "bob" replies "Agreed." to the last comment of "alice"
    And "alice" deletes her last comment
    And "alice" comments "Alone." on "item-two"
    And "alice" deletes her last comment
    And the snapshot runs
    Then the comment file of "item-one" shows a removed comment with the reply "Agreed." under it
    And the comment file of "item-two" is empty

  Scenario: A rationale is exported next to the rating it explains
    When "alice" picks the handle "quiet-fox"
    And "alice" rates "item-one" "real" 4
    And "alice" comments "The benchmarks held up." on "item-one" explaining "real" 4
    Then "alice" is answered with status 201
    When "alice" comments "I never gave this." on "item-one" explaining "useful" 5
    Then "alice" is answered with status 422 "rating_context_mismatch"
    And the reader feedback export holds a rationale "The benchmarks held up." for "real" 4 by "alice"

  Scenario: Hidden and deleted comments are retracted in the export
    When "alice" picks the handle "quiet-fox"
    And "alice" comments "Soon gone." on "item-one"
    And "alice" deletes her last comment
    Then the reader feedback export retracts the last comment of "alice"

  Scenario: Thirty comments an hour, a third of that for a new account
    When "alice" picks the handle "quiet-fox"
    And "alice" posts 12 comments on "item-one"
    Then "alice" was refused 2 times with status 429

  Scenario: The comment files never identify a reader
    When "alice" picks the handle "quiet-fox"
    And "alice" comments "Fine." on "item-one"
    And the snapshot runs
    Then the public files hold no site subject, person id or email address
