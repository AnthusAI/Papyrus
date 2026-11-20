Feature: Nothing is sent that no person had the chance to look at, whatever the review setting says
  A Delivery's review decides what the lock time means. Under hard review nothing is sent until a person approves the version, and a Delivery that reaches its lock time with
  no approval is not locked, not sent and flagged, once. Under soft review a person may edit or stop the Delivery before its lock time and silence lets it go: with nobody
  acting, the engine approves the current version as the publication's policy at the lock time, then locks it, in one conditional write, and the record says so. Under none the
  machine's draft goes at its release time, because the policy approved it when it was made. The sender reads only the locked version, so a Delivery whose lock time has come
  is locked, by the same write that opens its attempt if nothing locked it earlier, and nothing goes out before its release time under any review.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: Under soft review with nobody acting, the current version is approved by the policy and locked at the lock time
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | policy                                      | text                      | lock at              |
      | x       | handle-1 | soft     | publication policy (agent policy version 4) | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "approved_and_locked"
    And the Delivery row "x" "handle-1" holds
      | field           | value                                       |
      | approvedVersion | 1                                           |
      | approvedBy      | system                                      |
      | approvedAt      | 2026-11-16T14:15:00Z                        |
      | lockedVersion   | 1                                           |
      | lockedAt        | 2026-11-16T14:15:00Z                        |
      | approvalPolicy  | publication policy (agent policy version 4) |
    And the Delivery "x" "handle-1" was approved by the policy at the lock time "2026-11-16T14:15:00Z"
    And the history of the Delivery "x" "handle-1" says "approved version 1 by publication policy at the lock time (soft review: nobody acted) and locked it"
    And the review of the Delivery "x" "handle-1" reads "Released automatically by publication policy" with the mark "bot"
    And the Delivery "x" "handle-1" may go at "2026-11-16T14:20:00Z"

  Scenario: Under soft review a person's approval is what is locked, and the policy approves nothing over it
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "locked"
    And the Delivery "x" "handle-1" was approved by "ellie"
    And the Delivery "x" "handle-1" is locked at "2026-11-16T14:15:00Z" with version 1

  Scenario: Under soft review the policy approves the version a person edited, because that is the one that was there to look at
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "approved_and_locked"
    And the Delivery "x" "handle-1" is locked at "2026-11-16T14:15:00Z" with version 2
    And the Delivery "x" "handle-1" was approved by the policy at the lock time "2026-11-16T14:15:00Z"

  Scenario: A soft Delivery the lock time never reached is still locked, by policy, in the write that opens its attempt
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And one worker serves the channel "x" account "handle-1"
    When the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    Then the Delivery "x" "handle-1" is locked at "2026-11-16T14:20:00Z" with version 1
    And the Delivery "x" "handle-1" was approved by the policy at the lock time "2026-11-16T14:20:00Z"
    And attempt 1 of the Delivery "x" "handle-1" records version 1
    And the channel posted exactly once

  Scenario: Under hard review a Delivery with no approval at its lock time is not locked, not sent and flagged once
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | hard     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "waiting_for_person"
    And the lock said "with no approved version, and hard review needs a person to approve it"
    And the lock raised one flag
    And the Delivery "x" "handle-1" is not locked
    And the Delivery "x" "handle-1" is not approved
    And the Delivery "x" "handle-1" is due at "2026-11-16T14:15:00Z" for the lock
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:16:00Z"
    Then exactly 1 review request has been raised for the Deliveries

  Scenario: Under hard review nothing is sent at the release time until a person approves
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | hard     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And one worker serves the channel "x" account "handle-1"
    When the worker tries to send the Delivery "x" "handle-1" at "2026-11-16T14:20:00Z"
    Then the call is refused saying "waiting for approval"
    And the Delivery "x" "handle-1" is not locked
    And nothing was posted to the channel

  Scenario: Under hard review the version a person approves is the version that is locked and sent
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | hard     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And one worker serves the channel "x" account "handle-1"
    When the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    Then the Delivery "x" "handle-1" is locked at "2026-11-16T14:20:00Z" with version 2
    And the Delivery "x" "handle-1" was approved by "ellie"
    And attempt 1 of the Delivery "x" "handle-1" records version 2
    And the channel was handed the words "Slow water has landed." for attempt 1 of the Delivery "x" "handle-1"

  Scenario: Under hard review an edit after the approval takes the approval away
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | hard     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "Sierra changed it after."
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "waiting_for_person"
    And the Delivery "x" "handle-1" is not locked

  Scenario: Under none the machine's draft goes at its release time and nobody had to look
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | none     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And one worker serves the channel "x" account "handle-1"
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "locked"
    And the Delivery "x" "handle-1" was approved by "system"
    And the Delivery "x" "handle-1" is locked at "2026-11-16T14:15:00Z" with version 1
    When the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    Then the channel posted exactly once
    And attempt 1 of the Delivery "x" "handle-1" records version 1

  Scenario: Nothing goes before its release time, whatever its review
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | none     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And one worker serves the channel "x" account "handle-1"
    When the worker tries to send the Delivery "x" "handle-1" at "2026-11-16T14:17:00Z"
    Then the call is refused saying "waiting for its release time"
    And nothing was posted to the channel

  Scenario: A Delivery whose words are not ready is not locked, even under soft review
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | state   | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | drafted | 2026-11-16T14:15:00Z |
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "not_ready"
    And the lock said "its words are not ready"
    And the Delivery "x" "handle-1" is not locked

  Scenario: A Delivery a person posts by hand is never locked for sending
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel  | account | approval | text                      | mode   | lock at              |
      | linkedin | page-1  | soft     | Slow water is on shelves. | manual | 2026-11-16T14:15:00Z |
    When the lock time of the Delivery "linkedin" "page-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "by_hand"
    And the Delivery "linkedin" "page-1" is not locked
    And the Delivery "linkedin" "page-1" is not approved

  Scenario: A person who stops it before the lock time keeps it from going
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    When the person "ellie" cancels the Announcement "story-published:slow-water"
    And the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "nothing"
    And the Delivery "x" "handle-1" is not locked
    And the Delivery "x" "handle-1" is withdrawn
