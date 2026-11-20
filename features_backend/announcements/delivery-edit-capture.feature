Feature: What a person changed in an announcement is recorded, with how far it should reach
  When an announcement went out with a person's words in it, or a person saved how it should have read, the Delivery can record, once, which version was the machine's and which
  was the person's, and the person's choice of how far the change reaches: just this one, this channel, this kind on this channel, or the whole publication. With no choice the
  edit is kept as a candidate, and a candidate changes nothing about any later draft. A choice of "just this one" changes nothing either. Nothing is learned unless a person
  says so, and only a person says it. The one-line reason a person gives is stored with the words in S3 and never in the catalog row. The difference between the two versions is
  worked out from the two stored versions when it is needed, so it is not stored a second time.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And one worker serves the channel "x" account "handle-1"

  Scenario: An edit sent with the scope "this channel" is recorded as an example for that channel
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "channel"
    Then the Delivery "x" "handle-1" is an "active" example with the scope "channel"
    And the Delivery "x" "handle-1" records version 1 as the machine's and version 2 as the final one
    And the active example of the Delivery "x" "handle-1" is read from the partition "channel:x"

  Scenario: An edit with the scope "this kind on this channel" is read from that kind's partition
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "kind"
    Then the Delivery "x" "handle-1" is an "active" example with the scope "kind"
    And the active example of the Delivery "x" "handle-1" is read from the partition "kind:x:story_published"

  Scenario: An edit with the scope "the whole publication" is read from the publication's partition
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "publication"
    Then the active example of the Delivery "x" "handle-1" is read from the partition "publication"

  Scenario: An edit with no scope is a candidate and changes nothing about later drafts
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with no scope
    Then the Delivery "x" "handle-1" is a "candidate" example with no scope
    And the Delivery "x" "handle-1" records version 1 as the machine's and version 2 as the final one
    And the Delivery "x" "handle-1" is in no partition of active examples

  Scenario: Choosing "just this one" is a decision that changes nothing later
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "this_one"
    Then the Delivery "x" "handle-1" is a "declined" example with the scope "this_one"
    And the Delivery "x" "handle-1" is in no partition of active examples

  Scenario: A candidate is given its scope later and becomes an example then
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    And the person "ellie" records the edit of the Delivery "x" "handle-1" with no scope
    When the person "ada" records the edit of the Delivery "x" "handle-1" with the scope "channel"
    Then the Delivery "x" "handle-1" is an "active" example with the scope "channel"
    And the history of the Delivery "x" "handle-1" shows "ada" recorded it

  Scenario: Recording the same choice twice changes nothing
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    And the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "channel"
    And the writes so far are remembered
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "channel"
    Then nothing more was written

  Scenario: An example that is already active is not recorded again with another scope
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    And the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "channel"
    And the writes so far are remembered
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "publication"
    Then the call is refused saying "turn it off before it is recorded again"
    And nothing more was written

  Scenario: A send nobody edited records nothing
    Given the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    And the writes so far are remembered
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "channel"
    Then the record said "has no words a person changed"
    And nothing more was written
    And the Delivery "x" "handle-1" is in no partition of active examples

  Scenario: A Delivery that has not gone out has nothing to record yet
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the writes so far are remembered
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "channel"
    Then the call is refused saying "has not gone out"
    And nothing more was written

  Scenario: The reason is kept in S3 and never in the catalog row
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with the scope "channel" and the reason "Open with the verb, not the title."
    Then the reason of the Delivery "x" "handle-1" in S3 is "Open with the verb, not the title."
    And the Delivery row "x" "handle-1" holds none of "Open with the verb"

  Scenario: A reason is one line and goes with a scope
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    When the person "ellie" records the edit of the Delivery "x" "handle-1" with no scope and the reason "Because."
    Then the call is refused saying "goes with the choice"

  Scenario: Only a person says how far a change reaches
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    And an announce agent working at the rung "publish_auto" on the channel "x" for the kind "story_published"
    And the writes so far are remembered
    When the announce agent asks the door to record the edit of the Delivery "x" "handle-1" with the scope "channel"
    Then the door answers "human_required"
    And nothing more was written

  Scenario: A person says it through the one door
    Given the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    When the person "ellie" asks the door to record the edit of the Delivery "x" "handle-1" with the scope "channel"
    Then the door answers "allowed"
    And the Delivery "x" "handle-1" is an "active" example with the scope "channel"
