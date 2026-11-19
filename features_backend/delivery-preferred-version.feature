Feature: Teach without sending again: a preferred version of a Delivery that already went out
  When an announcement is already out, a LinkedIn post or an email cannot be recalled and a new post costs money and attention. A person can still save how it should have read, as a preferred
  version that is never sent. Saving one sends nothing and changes no public text. It can teach the drafter exactly as an edit made before sending does, once a person says how
  far it reaches, in the same step or later. Correcting the public post is a different choice, made separately: a superseding Delivery, where the channel can delete.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text                                  |
      | linkedin | page-1  | none     | A look at how slow water shapes stone |
      | x       | handle-1 | none     | A look at how slow water shapes stone |
    And one worker serves the channel "linkedin" account "page-1"
    And the Delivery "linkedin" "page-1" is sent by the worker at "2026-11-17T09:00:00Z"

  Scenario: A preferred version on a sent post sends nothing and changes no public text
    When the person "ellie" saves a preferred version over version 1 of the Delivery "linkedin" "page-1" with the words "How slow water carves the harbour."
    Then the door answers "allowed"
    And the door says the Delivery was preferred
    And the Delivery "linkedin" "page-1" has the preferred version 2
    And the Delivery "linkedin" "page-1" is "sent"
    And the Delivery "linkedin" "page-1" still sends version 1
    And the Delivery "linkedin" "page-1" has 1 attempt
    And version 1 of the Delivery "linkedin" "page-1" has the words "A look at how slow water shapes stone"
    And version 2 of the Delivery "linkedin" "page-1" has the words "How slow water carves the harbour."

  Scenario: A preferred version given a scope in the same step becomes an example
    When the person "ellie" saves a preferred version over version 1 of the Delivery "linkedin" "page-1" with the words "How slow water carves the harbour." and the scope "channel"
    Then the Delivery "linkedin" "page-1" has the preferred version 2
    And the Delivery "linkedin" "page-1" is an "active" example with the scope "channel"
    And the Delivery "linkedin" "page-1" records version 1 as the machine's and version 2 as the final one
    And the active example of the Delivery "linkedin" "page-1" is read from the partition "channel:linkedin"

  Scenario: A preferred version with no scope is a candidate until a person gives it one
    Given the person "ellie" saves a preferred version over version 1 of the Delivery "linkedin" "page-1" with the words "How slow water carves the harbour."
    And the person "ellie" records the edit of the Delivery "linkedin" "page-1" with no scope
    Then the Delivery "linkedin" "page-1" is a "candidate" example with no scope
    When the person "ada" records the edit of the Delivery "linkedin" "page-1" with the scope "kind"
    Then the Delivery "linkedin" "page-1" is an "active" example with the scope "kind"
    And the active example of the Delivery "linkedin" "page-1" is read from the partition "kind:linkedin:story_published"

  Scenario: Teaching does not correct the public post
    Given one worker serves the channel "x" account "handle-1"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-17T09:00:00Z"
    When the person "ellie" saves a preferred version over version 1 of the Delivery "x" "handle-1" with the words "Slow water shapes stone, corrected" and the scope "channel"
    Then the live Delivery of "x" "handle-1" is generation 1
    And exactly 2 posts were made

  Scenario: Correcting is a separate choice that makes a superseding Delivery from the preferred words
    Given one worker serves the channel "x" account "handle-1"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-17T09:00:00Z"
    And the fact check supports what the Story titled "A look at how slow water shapes stone" says
    And the person "ellie" saves a preferred version over version 1 of the Delivery "x" "handle-1" with the words "Slow water shapes stone, corrected" and the scope "channel"
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, corrected"
    Then the command succeeds
    And the command's result names generation 2 which supersedes generation 1 of "x" "handle-1"
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2
    And generation 1 of "x" "handle-1" is still an "active" example with the scope "channel"

  Scenario: A preferred version names the version it replaces
    Given the person "ellie" saves a preferred version over version 1 of the Delivery "linkedin" "page-1" with the words "How slow water carves the harbour."
    And the writes so far are remembered
    When the person "sierra" saves a preferred version over version 1 of the Delivery "linkedin" "page-1" with the words "Another idea."
    Then the door answers "stale_version"
    And nothing more was written

  Scenario: A Delivery that has not gone out has no preferred version
    When the person "ellie" saves a preferred version over version 1 of the Delivery "x" "handle-1" with the words "Too early."
    Then the door answers "constraint_conflict"
    And the Delivery "x" "handle-1" has no preferred version

  Scenario: An agent does not teach
    Given an announce agent working at the rung "publish_auto" on the channel "linkedin" for the kind "story_published"
    And the writes so far are remembered
    When the announce agent asks the door to save a preferred version over version 1 of the Delivery "linkedin" "page-1" with the words "A machine's idea."
    Then the door answers "human_required"
    And nothing more was written

  Scenario: A machine's redraft of a sent Delivery is refused
    When the machine redrafts version 1 of the Delivery "linkedin" "page-1" with the words "A machine's new idea."
    Then the redraft was dropped and nothing was written
    And the dropped redraft says "was sent"

  # An email cannot be recalled at all, so teaching from one is the only way to learn from it. The email is sent through Caducus with its mailer replaced by a recorder.
  Scenario: A preferred version on a sent email sends no second email
    Given a site "alpha" with the lists "stories" (every story) and "security" (the security section)
    And "reader1@example.test" confirmed "stories"
    And the decision "story-published:slow-water-mail" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account    | approval | text             | lists   |
      | email   | alpha-send | none     | Slow water rises | stories |
    When the worker sends the email Delivery of "story-published:slow-water-mail" and Caducus works through its queue
    And the person "ellie" saves a preferred version over version 1 of the Delivery "email" "alpha-send" with the words "Slow water rises over the harbour." and the scope "channel"
    Then the Delivery "email" "alpha-send" has the preferred version 2
    And the Delivery "email" "alpha-send" is "sent"
    And the Delivery "email" "alpha-send" has 1 attempt
    And the Delivery of "story-published:slow-water-mail" counts "1 sent"
    And the Delivery "email" "alpha-send" is an "active" example with the scope "channel"
