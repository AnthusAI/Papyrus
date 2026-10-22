@brand-agnostic
Feature: Voting and flagging on any subject type from the page
  The Vote and Flag islands of the reader plugin work on any subject type a publication has turned on. These scenarios
  are verified in a real browser against a fake reader API by scripts/test-reader-islands.ts (the "typed Vote" and "Flag"
  tests), which run in test:ci:ts.

  Scenario: Up and down are shown in words and shapes
    Given a signed-in reader on a page with a Vote island for the proposal "prop-1"
    Then the island offers "Vote up" and "Vote down" buttons, each with a triangle shape
    And it reads "4 votes up, 2 votes down" from the snapshot

  Scenario: Choosing a vote changes the words, the shape and the count at once
    Given a signed-in reader on a page with a Vote island for the proposal "prop-1"
    When the reader chooses "Vote up"
    Then the button reads "Voted up", is pressed, and the count reads "5 votes up, 2 votes down"
    And the reader's vote is sent as type "proposal", id "prop-1", value 1
    When the reader chooses "Vote down"
    Then the vote is switched to down and sent with value -1
    When the reader chooses "Voted down" again
    Then the vote is removed and sent with value null

  Scenario: A refused vote is rolled back and explained
    Given a signed-in reader who already voted down
    When the server refuses an up vote
    Then the earlier down vote and the earlier counts are shown again
    And the reason is shown in words

  Scenario: Signed-out readers see the controls switched off and why
    Given a signed-out reader on a page with Vote and Flag islands
    Then every button is disabled and the status says "Sign in to vote and rate"
    And nothing is sent

  Scenario: Flagging needs a kind and a reason
    Given a signed-in reader on a page with a Flag island for the proposal "prop-1"
    When the reader opens the flag form
    Then it offers "This is wrong", "This belongs under…" and "Suggest a better name"
    And sending without a reason sends nothing
    When the reader flags it as wrong with a reason
    Then the flag is sent and the page says "Flag sent. Thank you."
    When the reader flags it as belonging under the concept "hardware" with a reason
    Then the flag is sent with that target
    When the reader suggests the name "Edge inference" with a reason
    Then the flag is sent with that name

  Scenario: A refused flag keeps the form
    Given a signed-in reader who opened the flag form
    When the server refuses the reason
    Then the form stays open and the refusal is shown in words

  Scenario: The page can tell which vote subject types are enabled
    Given a page whose reader config lists the vote subject types "item" and "proposal"
    Then window.papyrusReader.voteSubjects is "item" and "proposal"
    And window.papyrusReader.proposalVoting is true
    When the config lists no vote subject types
    Then voteSubjects defaults to "item" and "submission" and proposalVoting is false

  Scenario: A subject type that is not enabled is switched off in words
    Given a page whose reader config lists only "item"
    Then a Vote island and a Flag island for the proposal "prop-1" are disabled
    And they say "Voting on this is not open yet"
