Feature: Votes and flags on any subject type
  A signed-in reader can vote up or down on any kind of subject a publication has turned on: items, submissions,
  stories, proposals and concepts. A subject is named by its type and its id, so a proposal and a concept may share
  an id without sharing votes. A reader has one vote per subject, can switch it or take it back, and can flag a
  subject as wrong, as belonging under another subject, or as needing a better name, always with a reason. Flags are
  kept apart from votes. Nothing is stored under the reader's pairwise site subject being shown or the Person ID:
  rows hold only the opaque reader id.

  Background:
    Given a publication whose readers rate "real" and "useful"
    And the published items "item-one" and "item-two"
    And the signed-in readers "alice" and "bob"
    And the publication lets readers vote on items, stories, proposals and concepts

  Scenario: A reader upvotes a proposal and downvotes a story
    When "alice" votes up on the proposal "prop-1"
    And "alice" votes down on the story "weekly-42"
    Then "alice" is answered with status 200
    And there are 2 stored votes
    And "alice" sees the vote 1 on "proposal:prop-1" in the reader state
    And "alice" sees the vote -1 on "story:weekly-42" in the reader state

  Scenario: A reader has one vote per subject and may switch or remove it
    When "alice" votes up on the proposal "prop-1"
    And "alice" votes up on the proposal "prop-1"
    And "alice" votes down on the proposal "prop-1"
    Then there is 1 stored vote
    And "alice" sees the vote -1 on "proposal:prop-1" in the reader state
    When "alice" removes the vote on the proposal "prop-1"
    Then there are 0 stored votes

  Scenario: The same id under two types is two subjects
    When "alice" votes up on the proposal "shared-id"
    And "alice" votes up on the concept "shared-id"
    Then there are 2 stored votes

  Scenario: A subject type the publication has not turned on is refused
    Given the publication lets readers vote on items only
    When "alice" votes up on the proposal "prop-1"
    Then "alice" is answered with status 422 "unknown_subject_type"
    And there are 0 stored votes

  Scenario: A subject type that does not exist is refused
    When "alice" votes up on the person "someone"
    Then "alice" is answered with status 422 "unknown_subject_type"
    And there are 0 stored votes

  Scenario: Votes on items written before subject types still count as item votes
    When "alice" upvotes "item-one"
    And "bob" votes down on the item "item-one"
    Then there are 2 stored votes
    And every stored vote on "item-one" has the subject type "item"

  Scenario: An item vote still needs a published item
    When "alice" votes up on the item "not-published"
    Then "alice" is answered with status 404 "unknown_subject"

  Scenario: A vote must be up, down or removed
    When "alice" sends a vote of 5 on the proposal "prop-1"
    Then "alice" is answered with status 422 "invalid_vote"
    And there are 0 stored votes

  Scenario: Any signed-in reader may vote, with no karma needed
    When "alice" votes up on the proposal "prop-1"
    Then "alice" is answered with status 200
    And "alice" has karma 0

  Scenario: A reader flags a subject as wrong with a reason
    When "alice" flags the proposal "prop-1" as "wrong" because "The figures do not match the source."
    Then "alice" is answered with status 200
    And there is 1 stored flag of kind "wrong" on "proposal:prop-1"
    And there are 0 stored votes

  Scenario: A flag that a subject belongs under another subject names the other subject
    When "alice" flags the proposal "prop-1" as belonging under the concept "hardware" because "It is about chips."
    Then "alice" is answered with status 200
    And the stored flag points at "concept:hardware"
    When "bob" flags the proposal "prop-1" as belonging under nothing because "No idea."
    Then "bob" is answered with status 422 "invalid_target"

  Scenario: A flag that a subject needs a better name carries the suggested name
    When "alice" suggests the name "Edge inference" for the proposal "prop-1" because "It is clearer."
    Then "alice" is answered with status 200
    And the stored flag suggests the name "Edge inference"
    When "bob" suggests no name for the proposal "prop-1" because "Just wrong."
    Then "bob" is answered with status 422 "invalid_name"

  Scenario: A flag without a reason, or with a reason that is too long, is refused
    When "alice" flags the proposal "prop-1" as "wrong" without a reason
    Then "alice" is answered with status 422 "invalid_reason"
    When "alice" flags the proposal "prop-1" as "wrong" because a reason of 501 characters
    Then "alice" is answered with status 422 "invalid_reason"
    And there are 0 stored flags

  Scenario: A flag of an unknown kind is refused
    When "alice" flags the proposal "prop-1" as "spam" because "Not welcome."
    Then "alice" is answered with status 422 "invalid_flag_kind"

  Scenario: Flagging the same way again replaces the reason
    When "alice" flags the proposal "prop-1" as "wrong" because "First thought."
    And "alice" flags the proposal "prop-1" as "wrong" because "Second thought."
    Then there is 1 stored flag of kind "wrong" on "proposal:prop-1"
    And the stored flag reason is "Second thought."

  Scenario: Stored votes and flags never hold the site subject
    When "alice" votes up on the proposal "prop-1"
    And "alice" flags the proposal "prop-1" as "wrong" because "Checked it."
    Then no stored vote or flag contains the site subject of "alice"

  Scenario: The snapshot publishes up, down and net per subject type
    Given the publication has adopted the shrinkage combination
    When "alice" votes up on the proposal "prop-1"
    And "bob" votes down on the proposal "prop-1"
    And "alice" votes down on the story "weekly-42"
    And the account of "alice" is more than a day old
    And the snapshot runs
    Then the proposal "prop-1" has 1 up and 1 down in its public votes file
    And the story "weekly-42" has 0 up and 1 down in its public votes file
    And the public file "_data/reader/subjects.json" lists the subject types "item", "story", "proposal" and "concept"

  Scenario: A new account's vote counts for a third in the net score
    Given the publication has adopted the shrinkage combination
    When "alice" votes up on the proposal "prop-1"
    And "bob" votes up on the proposal "prop-1"
    And the account of "alice" is more than a day old
    And the snapshot runs
    Then the proposal "prop-1" has 2 up and 0 down in its public votes file
    And the proposal "prop-1" has a net of 1.3333 in its public votes file

  Scenario: The score shrinks toward zero until many readers agree
    Given the publication has adopted the shrinkage combination
    When "alice" votes up on the proposal "prop-1"
    And the account of "alice" is more than a day old
    And the snapshot runs
    Then the proposal "prop-1" has a score of 0.0476 in its public votes file

  Scenario: Flags reach the snapshot as counts with no reader and no reason
    When "alice" flags the proposal "prop-1" as "wrong" because of the secret reason
    And "bob" suggests the name "Edge inference" for the proposal "prop-1" because "Clearer."
    And the snapshot runs
    Then the proposal "prop-1" has 1 "wrong" flag in its public votes file
    And the proposal "prop-1" has 1 "better_name" flag in its public votes file
    And the proposal "prop-1" has 0 "belongs_under" flag in its public votes file
    And the public file "_data/reader/votes/proposal.json" holds no reason text
    And the public files hold no site subject, person id or email address

  Scenario: A downvote is not an upvote for Rising and the item keeps its old fields
    When "bob" votes down on the item "item-one"
    And the snapshot runs
    Then the public file "_data/reader/items.json" shows 0 upvote on "item-one"
    And "bob" is not counted as rising on "item-one"
    And the item "item-one" has 0 up and 1 down in its public votes file

  Scenario: Subjects of other types are also in items.json under their subject key
    When "alice" votes up on the proposal "prop-1"
    And "bob" votes down on the proposal "prop-1"
    And the snapshot runs
    Then the public file "_data/reader/items.json" shows 1 up and 1 down on "proposal:prop-1"
