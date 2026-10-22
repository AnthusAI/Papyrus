Feature: Moderation of reader submissions and comments
  Content is public at once. A moderator (an editor or admin) decides after the fact: approve, hide, show again, promote a
  submission into a draft item, limit or ban a reader, and undo. Every decision is one logged action written with the change
  it records. Hidden content leaves the next snapshot, and a banned reader's writes are refused. A publication can hold new
  content until approved, or turn the review queue off.

  Background:
    Given a publication whose readers rate "real" and "useful"
    And the published items "item-one" and "item-two"
    And the signed-in readers "alice" and "bob"
    And "alice" is the submitter of the first link

  Scenario: New content waits in the queue while it is already public
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    Then the first submission is in the review queue
    And the public file "_data/reader/submissions.json" lists 1 submission by "quiet-fox" as pending

  Scenario: A moderator approves and the item leaves the queue
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And a moderator approves the first submission
    Then the moderator is told it is done
    And the first submission is not in the review queue
    And the moderation log holds 1 entries, the last marked by a human

  Scenario: A reported comment goes back to the queue and hiding it removes it from the next snapshot
    When "alice" picks the handle "quiet-fox"
    And "bob" picks the handle "loud-owl"
    And "alice" comments "Buy my thing" on "item-one"
    And a moderator approves the last comment of "alice"
    And "bob" reports the last comment of "alice" saying "An advert"
    Then the last comment of "alice" is in the review queue with 1 report
    When a moderator hides the last comment of "alice"
    And the snapshot runs
    Then the comment file of "item-one" is empty

  Scenario: Hiding a submission removes it and undo brings it back
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And a moderator hides the first submission
    And the snapshot runs
    Then the first submission has state "hidden"
    And the public file "_data/reader/submissions.json" lists no submissions
    When a moderator undoes the last action
    And the snapshot runs
    Then the first submission has state "pending"
    And the public file "_data/reader/submissions.json" lists 1 submission by "quiet-fox" as pending

  Scenario: A banned reader's writes are refused
    When "bob" picks the handle "loud-owl"
    And "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And a moderator bans "bob"
    Then "bob" cannot vote
    And "bob" cannot comment
    And "bob" cannot submit
    And "bob" cannot report
    When a moderator unbans "bob"
    And "bob" upvotes "item-one"
    Then "bob" is answered with status 200

  Scenario: A moderator promotes a submission into a draft item
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And a moderator promotes the first submission
    Then a draft item was created from the first submission
    And the first submission has state "promoted"

  Scenario: Only editors and admins can moderate
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And someone who is not an editor tries to hide the first submission
    Then the moderator is refused with "not_staff"
    And the first submission has state "pending"

  Scenario: A publication can hold new content until a moderator approves it
    Given pre-moderation is on
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    Then the public file "_data/reader/submissions.json" lists no submissions
    When a moderator approves the first submission
    And the snapshot runs
    Then the public file "_data/reader/submissions.json" lists 1 submission by "quiet-fox" as pending

  Scenario: With moderation off nothing waits in a queue
    Given moderation is off
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    Then the first submission is not in the review queue
