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

  Scenario: After the debounced run the public files show the numbers
    Given "bob" is also on the staff
    When "bob" rates "item-one" "real" 5
    And "alice" rates "item-one" "real" 3
    And "alice" upvotes "item-one"
    And the snapshot runs
    Then the public file "_data/reader/items.json" shows 1 upvote on "item-one"
    And it shows readers rating "item-one" "real" at 3.0 from 1 rating and editors at 5.0
    And the public file "_data/reader/board.json" ranks "item-one" first on the front
    And the public file "_data/reader/board.json" lists "item-one" as rising with 1 upvote

  Scenario: The hype gap appears only when five readers have rated every dimension involved
    Given "bob" is also on the staff
    When "bob" rates "item-one" "real" 5
    And 4 more readers rate "item-one" "real" 3
    And the snapshot runs
    Then the public file "_data/reader/items.json" shows no hype gap on "item-one"
    When 1 more readers rate "item-one" "real" 3
    And the snapshot runs
    Then the public file "_data/reader/items.json" shows a hype gap of 2.0 on "item-one"

  Scenario: The scheduled run drops a deleted account's votes and frees its handle
    When "alice" picks the handle "quiet-fox"
    And "alice" upvotes "item-one"
    And "bob" upvotes "item-one"
    And Prospectus reports "alice" deleted
    And the scheduled snapshot runs
    Then the public file "_data/reader/items.json" shows 1 upvote on "item-one"
    And the handle "quiet-fox" is free
    And "alice" has no profile

  Scenario: A merged account's votes move to the surviving subject, and a debounced run does not poll
    When "alice" upvotes "item-one"
    And Prospectus reports "alice" merged into "bob"
    And the snapshot runs
    Then Prospectus was not asked
    When the scheduled snapshot runs
    Then "bob" sees "up" on "item-one" in the reader state
    And "alice" has no profile

  Scenario: Until submissions exist nobody has karma
    When "alice" picks the handle "quiet-fox"
    And "bob" upvotes "item-one"
    And the snapshot runs
    Then nobody is on the karma list

  Scenario: The files follow the site's base path and the edge is purged for exactly those files
    When "alice" upvotes "item-one"
    And the snapshot runs under the base path "posts"
    Then the site store holds "posts/_data/reader/items.json", "posts/_data/reader/board.json" and "posts/_data/reader/readers.json"
    And the edge was asked to purge those three files and nothing else

  Scenario: The public files never identify a reader
    When "alice" picks the handle "quiet-fox"
    And "alice" upvotes "item-one"
    And the snapshot runs
    Then the public files hold no site subject, person id or email address
