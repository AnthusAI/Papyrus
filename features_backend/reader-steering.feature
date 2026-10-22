Feature: Reader steering for a signed-in reader
  A reader signed in to a publication has a per-site pairwise identity, a public handle, and can vote and rate
  published items. Everything fails closed, every action is rate limited per reader, and a vote asks for one
  debounced snapshot run.

  Background:
    Given a publication whose readers rate "real" and "useful"
    And the published items "item-one" and "item-two"
    And the signed-in readers "alice" and "bob"

  Scenario: A reader picks a handle once and nobody else can take it
    When "alice" picks the handle "Quiet-Fox"
    Then "alice" is answered with status 200
    When "bob" picks the handle "quiet-fox"
    Then "bob" is answered with status 409 "handle_taken"
    When "alice" picks the handle "another-name"
    Then "alice" is answered with status 409 "handle_already_set"
    And "alice" sees the handle "quiet-fox" in the reader state

  Scenario: Reserved and malformed handles are refused
    When "alice" picks the handle "admin"
    Then "alice" is answered with status 422 "reserved_handle"
    When "alice" picks the handle "no spaces"
    Then "alice" is answered with status 422 "invalid_handle"

  Scenario: Voting twice is the same as voting once, and unvoting removes the vote
    When "alice" upvotes "item-one" 3 times
    Then there is 1 stored vote
    And "alice" sees "up" on "item-one" in the reader state
    When "alice" removes the upvote on "item-one"
    Then there are 0 stored votes

  Scenario: A new rating replaces the old one
    When "alice" rates "item-one" "real" 2
    And "alice" rates "item-one" "real" 5
    Then there is 1 stored vote
    And "alice" sees "real" at 5 on "item-one" in the reader state

  Scenario: Only published items can be voted on
    When "alice" upvotes "not-published"
    Then "alice" is answered with status 404 "unknown_subject"
    And there are 0 stored votes

  Scenario: An editor's rating is recorded as an editor's
    Given "bob" is also on the staff
    When "bob" rates "item-one" "useful" 4
    And "alice" rates "item-one" "useful" 3
    Then the stored voter roles are "editor" and "reader"

  Scenario: A new account is limited to a third of the hourly allowance
    Given the allowance is 30 actions an hour
    When "alice" upvotes "item-one" 12 times
    Then "alice" was refused 2 times with status 429
    And the refusal says when to retry

  Scenario: The next vote after a snapshot run asks for a new one only after a minute
    When "alice" upvotes "item-one" 3 times
    Then 1 snapshot run was requested
    When a minute passes
    And "bob" upvotes "item-one"
    Then 2 snapshot runs were requested

  Scenario: The reader state never exposes the reader's identity
    When "alice" upvotes "item-one"
    Then the reader state of "alice" contains neither her site subject nor her person id
