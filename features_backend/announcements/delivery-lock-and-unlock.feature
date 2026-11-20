Feature: A Delivery locks for the send job at its lock time, and a late edit needs an explicit unlock
  At a set time before its release the Delivery locks, and the version that is locked is the version that is sent. A lock is a fact on the Delivery, lockedAt and
  lockedVersion, and not something held: nothing expires, nothing waits holding a lease, and a person who never answers blocks only that Delivery. An edit after the lock is
  refused until a person unlocks the Delivery, which is an event of their own. The attempt log records which version was sent, and an edit made while an attempt is open does
  not change that attempt: it is saved as a newer version flagged as preferred, for later.

  The lock time is a follow-up timer. When it comes the timer only raises a wake, and the run reads the Delivery again and checks everything before it locks anything. An edit
  and a lock at the same moment are two conditional writes on one row, so exactly one wins.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: The lock writes the time and the version it locked, as a fact on the row
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:15:00Z"
    Then the lock answered "locked"
    And the Delivery "x" "handle-1" is locked at "2026-11-16T14:15:00Z" with version 1
    And the Delivery "x" "handle-1" was approved by "ellie"
    And the Delivery "x" "handle-1" is due at "2026-11-16T14:20:00Z"

  Scenario: Before its lock time nothing is locked
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:10:00Z"
    Then the lock answered "not_yet"
    And the Delivery "x" "handle-1" is not locked

  Scenario: Locking twice leaves the first lock as it was
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | none     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:17:00Z"
    Then the lock answered "already_locked"
    And the Delivery "x" "handle-1" is locked at "2026-11-16T14:15:00Z" with version 1

  Scenario: The version that was locked is the version that is sent, and the attempt log says which
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Slow water has landed."
    And the person "ellie" approves version 2 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And one worker serves the channel "x" account "handle-1"
    When the Delivery "x" "handle-1" is sent by the worker at "2026-11-16T14:20:00Z"
    Then attempt 1 of the Delivery "x" "handle-1" records version 2
    And the channel was handed the words "Slow water has landed." for attempt 1 of the Delivery "x" "handle-1"

  Scenario: A late edit after the lock is refused and nothing is saved
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the writes so far are remembered
    When the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "A late idea."
    Then the call is refused saying "needs an explicit unlock by a person"
    And the call is refused saying "locked at 2026-11-16T14:15:00Z with version 1"
    And nothing more was written
    And the Delivery "x" "handle-1" is at version 1

  Scenario: A person unlocks, edits and the Delivery locks again at the time they named
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:16:00Z"
    When the person "ellie" unlocks the Delivery "x" "handle-1" to lock again at "2026-11-16T14:18:00Z"
    Then the call went through
    And the Delivery "x" "handle-1" is not locked
    And the Delivery "x" "handle-1" is due at "2026-11-16T14:18:00Z" for the lock
    And the history of the Delivery "x" "handle-1" shows who unlocked it
    When the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "A late idea, worth it."
    Then the call went through
    And the Delivery "x" "handle-1" is at version 2
    And the Delivery "x" "handle-1" still sends version 2
    When the lock time of the Delivery "x" "handle-1" is reached at "2026-11-16T14:18:00Z"
    Then the lock answered "approved_and_locked"
    And the Delivery "x" "handle-1" is locked at "2026-11-16T14:18:00Z" with version 2

  Scenario: Unlocking does not take back an approval, and an edit is what makes a version unapproved
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | hard     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:16:00Z"
    When the person "ellie" unlocks the Delivery "x" "handle-1" to lock again at "2026-11-16T14:18:00Z"
    Then the Delivery "x" "handle-1" was approved by "ellie"
    When the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "A better line."
    Then the Delivery "x" "handle-1" is not approved

  Scenario: An unlock names times that are still ahead
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | none     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:25:00Z"
    When the person "ellie" unlocks the Delivery "x" "handle-1"
    Then the call is refused saying "The release time 2026-11-16T14:20:00Z has passed"
    When the person "ellie" unlocks the Delivery "x" "handle-1" to lock again at "2026-11-16T14:40:00Z" and release at "2026-11-16T14:30:00Z"
    Then the call is refused saying "is between now and the release time"
    When the person "ellie" unlocks the Delivery "x" "handle-1" to lock again at "2026-11-16T14:28:00Z" and release at "2026-11-16T14:35:00Z"
    Then the call went through
    And the Delivery row "x" "handle-1" holds
      | field     | value                |
      | lockAt    | 2026-11-16T14:28:00Z |
      | releaseAt | 2026-11-16T14:35:00Z |

  Scenario: A Delivery that is not locked is not unlocked
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    When the person "ellie" unlocks the Delivery "x" "handle-1" to lock again at "2026-11-16T14:18:00Z"
    Then the call is refused saying "is not locked"

  Scenario: Nobody who never answers blocks anything but their own Delivery
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel  | account  | approval | text                      | lock at              |
      | x        | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
      | linkedin | page-1   | soft     | Slow water, for LinkedIn. | 2026-11-16T14:15:00Z |
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    When the person "ellie" saves version 1 of the Delivery "linkedin" "page-1" with the words "Slow water, rewritten."
    Then the call went through
    And the Delivery "linkedin" "page-1" is at version 2

  Scenario: An agent is told a person must unlock, and a person who unlocks through the one door is allowed
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:16:00Z"
    And an announce agent working at the rung "publish_auto" on the channel "x" for the kind "story_published"
    And the writes so far are remembered
    When the announce agent asks the door to unlock the Delivery "x" "handle-1"
    Then the door answers "human_required"
    And nothing more was written
    When the person "ellie" asks the door to unlock the Delivery "x" "handle-1" to lock again at "2026-11-16T14:18:00Z"
    Then the door answers "allowed"
    And the Delivery "x" "handle-1" is not locked

  Scenario: An agent's save after the lock is refused through the one door
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And an announce agent working at the rung "draft" on the channel "x" for the kind "story_published"
    When the announce agent asks the door to save the words "A redraft." over version 1 of the Delivery "x" "handle-1"
    Then the door says the Delivery was dropped
    And the Delivery "x" "handle-1" is at version 1

  Scenario: A person's edit while an attempt is open does not change that attempt and is saved as a preferred version
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:20:00Z"
    And an attempt is open on the Delivery "x" "handle-1"
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "How it should have read."
    Then the call went through
    And the save was a preferred version
    And the Delivery "x" "handle-1" has the preferred version 2
    And the Delivery "x" "handle-1" is at version 2
    And the Delivery "x" "handle-1" is still locked with version 1
    And the Delivery "x" "handle-1" still sends version 1
    And the review of the Delivery "x" "handle-1" reads "Released by a person (ellie)" with the mark "user-check"
    And version 2 of the Delivery "x" "handle-1" has the words "How it should have read."
    And version 1 of the Delivery "x" "handle-1" has the words "Slow water is on shelves."

  Scenario: The attempt that was open goes out as it was, whatever was saved while it was open
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:20:00Z"
    And an attempt is open on the Delivery "x" "handle-1"
    And the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "How it should have read."
    And one worker serves the channel "x" account "handle-1"
    When the worker settles the Delivery "x" "handle-1"
    Then the channel was handed the words "Slow water is on shelves." for attempt 1 of the Delivery "x" "handle-1"
    And attempt 1 of the Delivery "x" "handle-1" records version 1
    And the Delivery "x" "handle-1" has the preferred version 2

  Scenario: A machine's redraft while an attempt is open is dropped
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:20:00Z"
    And an attempt is open on the Delivery "x" "handle-1"
    When the machine redrafts version 1 of the Delivery "x" "handle-1" with the words "A machine's new idea."
    Then the redraft was dropped and nothing was written
    And the Delivery "x" "handle-1" has no preferred version

  Scenario: An edit that lands before the lock is locked with the version it made, and one that lands after is refused
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the clock reads "2026-11-16T14:15:00Z"
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" at the moment the lock time is reached
    Then the lock answered "approved_and_locked"
    And the Delivery "x" "handle-1" is locked at "2026-11-16T14:15:00Z" with version 2
    And version 2 of the Delivery "x" "handle-1" has the words "Edited at the last moment"
    And the Delivery "x" "handle-1" was approved by the policy at the lock time "2026-11-16T14:15:00Z"

  Scenario: A lock that lands first refuses the edit that was about to be saved
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the clock reads "2026-11-16T14:15:00Z"
    When the person "ellie" reads version 1 of the Delivery "x" "handle-1" and the lock time is reached before they save
    Then exactly one of the edit and the lock won: the Delivery is locked with version 1 and the edit was refused as late
    And the Delivery "x" "handle-1" is locked at "2026-11-16T14:15:00Z" with version 1
    And the Delivery "x" "handle-1" is at version 1
    And the Delivery "x" "handle-1" has these words in S3 "Slow water is on shelves."

  Scenario: A change to the Story lifts a lock on words it has outgrown
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    When the Story "slow-water" changes to version 4
    Then the Delivery "x" "handle-1" is not locked
    And the Delivery "x" "handle-1" is at version 2 and is a draft
    And version 2 of the Delivery "x" "handle-1" has the words "Slow water is on shelves."
    And the Delivery "x" "handle-1" is not approved

  Scenario: The lock time is a timer that only raises a wake, and the run checks the Delivery again
    Given the site "papyrus-test" holds its Deliveries with follow-up timers
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | soft     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    Then the site's timers hold exactly 1 entry
    And the one timer fires at "2026-11-16T14:15:00Z"
    When the time "2026-11-16T14:15:00Z" arrives for the site's timers
    Then the wake queue holds 1 message
    And the wake says the Delivery "x" "handle-1" was waiting for the "lock"
    And the Delivery "x" "handle-1" is not locked
    When the run for the last wake on the queue reads the Delivery again at "2026-11-16T14:15:00Z"
    Then the run locked the Delivery "x" "handle-1" and says it may go at "2026-11-16T14:20:00Z"
    And the Delivery "x" "handle-1" was approved by the policy at the lock time "2026-11-16T14:15:00Z"
    And the site's timers hold exactly 1 entry
    And the one timer fires at "2026-11-16T14:20:00Z"

  Scenario: A wake for a time the Delivery no longer waits for does nothing
    Given the site "papyrus-test" holds its Deliveries with follow-up timers
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | none     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the time "2026-11-16T14:15:00Z" arrives for the site's timers
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    When the run for the last wake on the queue reads the Delivery again at "2026-11-16T14:15:00Z"
    Then the deliver run did nothing and says "now waits until 2026-11-16T14:20:00Z"

  Scenario: Unlocking moves the Delivery's timer to the lock time the person named
    Given the site "papyrus-test" holds its Deliveries with follow-up timers
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:20:00Z" and these Deliveries
      | channel | account  | approval | text                      | lock at              |
      | x       | handle-1 | none     | Slow water is on shelves. | 2026-11-16T14:15:00Z |
    And the Delivery "x" "handle-1" is locked by the engine at "2026-11-16T14:15:00Z"
    And the clock reads "2026-11-16T14:16:00Z"
    When the person "ellie" unlocks the Delivery "x" "handle-1" to lock again at "2026-11-16T14:18:00Z"
    Then the site's timers hold exactly 1 entry
    And the one timer fires at "2026-11-16T14:18:00Z"
